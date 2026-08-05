#!/usr/bin/env python
"""Evaluate the real expanded NHL history without synthetic or market features."""

from __future__ import annotations

import csv
import json
import math
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from honest_real_only_benchmark import select_weighted_calibrator
from run_walk_forward_experiments import (
    BASE_FEATURE_CANDIDATES,
    ROSTER_FEATURE_CANDIDATES,
    V3_INTERACTION_FEATURE_NAMES,
    V4_INTERACTION_FEATURE_NAMES,
    WEIGHTED_MODEL_WEIGHTS,
    CalibrationConfig,
    EloState,
    RecencyConfig,
    apply_isotonic,
    apply_platt,
    build_robust_scaler,
    compute_metrics_from_arrays,
    compute_recency_weights,
    fit_isotonic_calibrator,
    fit_platt_scaler,
    load_feature_rows,
    load_historical_games,
    tune_elo_params,
    weighted_score,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "processed" / "nhl_research.db"
FEATURE_TABLE = "backtest_features_real_expanded_roster"
OUT_DIR = REPO_ROOT / "data" / "processed" / "execution_plan" / "real_expanded_retrain"
REPORT_PATH = REPO_ROOT / "data" / "reports" / "real_expanded_retrain_results.md"
BENCHMARK_ACCURACY = 0.5682
BENCHMARK_GAMES = 5248
BENCHMARK_TEST_SEASONS = [20222023, 20232024, 20242025, 20252026]


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def wilson_ci(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    margin = z * math.sqrt((p * (1.0 - p) / n) + (z * z / (4.0 * n * n))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def feature_lists(feature_names: Sequence[str]) -> tuple[List[str], List[str]]:
    allowlist = set(
        BASE_FEATURE_CANDIDATES
        + ROSTER_FEATURE_CANDIDATES
        + V3_INTERACTION_FEATURE_NAMES
        + V4_INTERACTION_FEATURE_NAMES
    )
    usable = sorted({name for name in feature_names if name in allowlist and not name.startswith("market_")})
    weighted = sorted([name for name in usable if name in WEIGHTED_MODEL_WEIGHTS and not name.startswith("market_")])
    return usable, weighted


def train_seasons_for_policy(prior_seasons: Sequence[int], policy: str) -> List[int]:
    if policy == "all_prior_real":
        return list(prior_seasons)
    if policy == "recent_2021_forward":
        return [s for s in prior_seasons if s >= 20212022]
    if policy == "all_prior_real_recency_weighted":
        return list(prior_seasons)
    raise ValueError(f"unknown policy: {policy}")


def recency_for_policy(policy: str) -> RecencyConfig:
    if policy == "all_prior_real_recency_weighted":
        return RecencyConfig(
            mode="season_exponential",
            season_half_life=2.0,
            game_half_life=800.0,
            min_weight=0.15,
            normalize_mean_one=True,
        )
    return RecencyConfig(mode="none", season_half_life=1.5, game_half_life=800.0, min_weight=0.2, normalize_mean_one=True)


def run_policy(
    rows,
    historical_games,
    weighted_features: Sequence[str],
    *,
    policy: str,
    test_seasons: Sequence[int] | None,
) -> tuple[List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
    seasons = sorted({r.season for r in rows})
    historical_map = {(g.season, g.game_id): g for g in historical_games}
    test_scope = "benchmark_window" if test_seasons is not None else "all_walk_forward"
    calibration = CalibrationConfig(
        selector_mode="season_aware",
        validation_seasons=2,
        season_half_life=1.0,
        selection_objective="joint",
        objective_margin=0.0005,
    )
    recency = recency_for_policy(policy)
    wanted_tests = set(test_seasons) if test_seasons is not None else set(seasons[1:])

    predictions: List[Dict[str, object]] = []
    folds: List[Dict[str, object]] = []
    for test_season in seasons:
        if test_season not in wanted_tests:
            continue
        prior = [s for s in seasons if s < test_season]
        train_seasons = train_seasons_for_policy(prior, policy)
        if not train_seasons:
            continue
        train_rows = [r for r in rows if r.season in set(train_seasons)]
        test_rows = [r for r in rows if r.season == test_season]
        if not train_rows or not test_rows:
            continue

        train_weights = compute_recency_weights(train_rows, train_seasons, recency)
        train_games = [historical_map[(r.season, r.game_id)] for r in train_rows]
        test_games = [historical_map[(r.season, r.game_id)] for r in test_rows]

        elo_params = tune_elo_params(train_games)
        elo_state = EloState(elo_params)
        for game in train_games:
            elo_state.predict_update(game, do_update=True)

        selected_method = select_weighted_calibrator(train_rows, train_weights, weighted_features, calibration)
        med, sc = build_robust_scaler(train_rows, weighted_features)
        train_scores = [weighted_score(r, weighted_features, med, sc) for r in train_rows]
        train_targets = [r.home_win for r in train_rows]
        platt_a, platt_b = fit_platt_scaler(train_scores, train_targets, sample_weights=train_weights)
        iso = fit_isotonic_calibrator(train_scores, train_targets, sample_weights=train_weights)

        y_fold: List[int] = []
        p_fold: List[float] = []
        for row, game in zip(test_rows, test_games):
            elo_prob = elo_state.predict_update(game, do_update=True)
            score = weighted_score(row, weighted_features, med, sc)
            weighted_prob = (
                apply_platt(score, platt_a, platt_b)
                if selected_method == "platt"
                else apply_isotonic(score, iso["breakpoints"], iso["values"])
            )
            prob = 0.5 * weighted_prob + 0.5 * elo_prob
            pick = 1 if prob >= 0.5 else 0
            y_fold.append(row.home_win)
            p_fold.append(prob)
            predictions.append(
                {
                    "policy": policy,
                    "test_scope": test_scope,
                    "train_start_season": train_seasons[0],
                    "train_end_season": train_seasons[-1],
                    "train_seasons": " ".join(str(s) for s in train_seasons),
                    "season": row.season,
                    "game_id": row.game_id,
                    "game_date": row.game_date,
                    "home_team_abbrev": row.home_team,
                    "away_team_abbrev": row.away_team,
                    "actual_home_win": row.home_win,
                    "home_win_probability": round(prob, 6),
                    "confidence": round(max(prob, 1.0 - prob), 6),
                    "is_correct_pick": 1 if pick == row.home_win else 0,
                }
            )
        metrics = compute_metrics_from_arrays(y_fold, p_fold)
        folds.append(
            {
                "policy": policy,
                "test_scope": test_scope,
                "season": test_season,
                "train_start_season": train_seasons[0],
                "train_end_season": train_seasons[-1],
                "train_games": len(train_rows),
                "games": int(metrics["games"]),
                "accuracy": round(float(metrics["accuracy"]), 6),
                "log_loss": round(float(metrics["log_loss"]), 6),
                "brier_score": round(float(metrics["brier_score"]), 6),
                "weighted_calibrator": selected_method,
            }
        )

    overall_metrics = compute_metrics_from_arrays(
        [int(r["actual_home_win"]) for r in predictions],
        [float(r["home_win_probability"]) for r in predictions],
    )
    overall = {
        "policy": policy,
        "test_scope": test_scope,
        "test_seasons": " ".join(str(s) for s in sorted({int(r["season"]) for r in predictions})),
        "games": int(overall_metrics["games"]),
        "accuracy": round(float(overall_metrics["accuracy"]), 6),
        "log_loss": round(float(overall_metrics["log_loss"]), 6),
        "brier_score": round(float(overall_metrics["brier_score"]), 6),
    }
    return predictions, folds, overall


def confidence_table(predictions: Sequence[Dict[str, object]], thresholds: Iterable[float]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    total = len(predictions)
    for threshold in thresholds:
        subset = [p for p in predictions if float(p["confidence"]) >= threshold]
        n = len(subset)
        correct = sum(int(p["is_correct_pick"]) for p in subset)
        acc = correct / n if n else 0.0
        lo, hi = wilson_ci(correct, n)
        rows.append(
            {
                "threshold": f">={threshold:.2f}",
                "games": n,
                "coverage_pct": round(100.0 * n / total, 2) if total else 0.0,
                "accuracy": round(acc, 6),
                "ci95_low": round(lo, 6),
                "ci95_high": round(hi, 6),
            }
        )
    return rows


def db_diagnostics(con: sqlite3.Connection) -> Dict[str, object]:
    by_season = [
        {
            "season": int(season),
            "games": int(games),
            "synthetic_rows": int(synth or 0),
            "sources": sources or "",
        }
        for season, games, synth, sources in con.execute(
            f"""
            SELECT season, COUNT(*), SUM(COALESCE(is_synthetic,0)), GROUP_CONCAT(DISTINCT data_source)
            FROM {FEATURE_TABLE}
            GROUP BY season
            ORDER BY season
            """
        ).fetchall()
    ]
    roster_coverage = [
        {
            "season": int(season),
            "games": int(games),
            "both_roster_source_games": int(both_sources),
            "avg_home_roster_coverage_pct": round(float(home_cov or 0.0), 2),
            "avg_away_roster_coverage_pct": round(float(away_cov or 0.0), 2),
        }
        for season, games, both_sources, home_cov, away_cov in con.execute(
            f"""
            SELECT season, COUNT(*),
                   SUM(CASE
                       WHEN COALESCE(home_roster_source_tag, '') != 'missing_roster_rows'
                        AND COALESCE(away_roster_source_tag, '') != 'missing_roster_rows'
                        AND home_roster_source_tag IS NOT NULL
                        AND away_roster_source_tag IS NOT NULL
                       THEN 1 ELSE 0 END),
                   AVG(home_pregame_roster_data_coverage_pct),
                   AVG(away_pregame_roster_data_coverage_pct)
            FROM {FEATURE_TABLE}
            GROUP BY season
            ORDER BY season
            """
        ).fetchall()
    ]
    market_cols = [
        row[1]
        for row in con.execute(f'PRAGMA table_info("{FEATURE_TABLE}")').fetchall()
        if str(row[1]).startswith("market_")
    ]
    return {"by_season": by_season, "roster_coverage": roster_coverage, "market_columns": market_cols}


def pct(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def md_table(rows: Sequence[Dict[str, object]], columns: Sequence[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in columns) + " |")
    return "\n".join(lines)


def write_report(
    diagnostics: Dict[str, object],
    overall_rows: Sequence[Dict[str, object]],
    fold_rows: Sequence[Dict[str, object]],
    confidence_rows: Sequence[Dict[str, object]],
) -> None:
    direct = {r["policy"]: r for r in overall_rows if r["test_scope"] == "benchmark_window"}
    all_hist = direct["all_prior_real"]
    recent = direct["recent_2021_forward"]
    recency = direct["all_prior_real_recency_weighted"]
    diff = float(all_hist["accuracy"]) - BENCHMARK_ACCURACY
    z = diff / 0.006
    meaningful = abs(diff) >= 1.96 * 0.006
    lines = [
        "# Real expanded retrain results",
        "",
        "## Executive result",
        (
            f"Against the fixed honest benchmark window ({BENCHMARK_GAMES} games, "
            f"{' '.join(str(s) for s in BENCHMARK_TEST_SEASONS)}), all prior real history scored "
            f"**{pct(float(all_hist['accuracy']))}** vs the prior **{pct(BENCHMARK_ACCURACY)}** benchmark "
            f"({diff*100:+.2f} pp; z≈{z:.2f} using the requested ~0.6 pp SE)."
        ),
        (
            "**Statistically meaningful:** "
            + ("yes" if meaningful else "no")
            + "."
        ),
        "",
        "## Data integrity checks",
        "- The expanded feature table has no `market_*` columns.",
        "- `exclude_synthetic_data=True` was used when loading features.",
        "- 2015-2019 rows are real NHL API rows (`data_source='real_nhl_api_web'`); no fabricated 2015-2018 feature rows were used.",
        "",
        md_table(diagnostics["by_season"], ["season", "games", "synthetic_rows", "sources"]),
        "",
        "## Roster/player-stat coverage",
        "Roster/player boxscore features exist for 2015-2018 and 2021-2026. They are intentionally absent for 2018-2019 and 2019-2020, so roster features degrade to null/default-safe values rather than imputed outcomes.",
        "",
        md_table(
            diagnostics["roster_coverage"],
            ["season", "games", "both_roster_source_games", "avg_home_roster_coverage_pct", "avg_away_roster_coverage_pct"],
        ),
        "",
        "## Benchmark-window model comparison",
        md_table(
            [
                {
                    **r,
                    "accuracy": pct(float(r["accuracy"])),
                    "log_loss": f"{float(r['log_loss']):.4f}",
                    "brier_score": f"{float(r['brier_score']):.4f}",
                }
                for r in overall_rows
                if r["test_scope"] == "benchmark_window"
            ],
            ["policy", "test_scope", "test_seasons", "games", "accuracy", "log_loss", "brier_score"],
        ),
        "",
        "Policy definitions: `all_prior_real` trains on every earlier real season; `recent_2021_forward` trains only on earlier seasons from 2021-2022 onward; `all_prior_real_recency_weighted` uses all earlier real seasons with a predeclared 2-season half-life.",
        "",
        "## Benchmark-window folds",
        md_table(
            [
                {
                    **r,
                    "accuracy": pct(float(r["accuracy"])),
                    "log_loss": f"{float(r['log_loss']):.4f}",
                    "brier_score": f"{float(r['brier_score']):.4f}",
                }
                for r in fold_rows
                if r["season"] in BENCHMARK_TEST_SEASONS
                and r["test_scope"] == "benchmark_window"
            ],
            ["policy", "season", "train_start_season", "train_end_season", "train_games", "games", "accuracy", "log_loss", "brier_score", "weighted_calibrator"],
        ),
        "",
        "## Larger-sample confidence tiers",
        "Computed on the full expanded walk-forward `all_prior_real` run (first season training-only).",
        "",
        md_table(
            [
                {
                    **r,
                    "accuracy": pct(float(r["accuracy"])),
                    "ci95_low": pct(float(r["ci95_low"])),
                    "ci95_high": pct(float(r["ci95_high"])),
                }
                for r in confidence_rows
            ],
            ["threshold", "games", "coverage_pct", "accuracy", "ci95_low", "ci95_high"],
        ),
        "",
        "## Interpretation",
        (
            f"More genuine history {'improved' if diff > 0 else 'did not improve'} the fixed benchmark by {diff*100:+.2f} pp. "
            f"The recent-only policy scored {pct(float(recent['accuracy']))}; the recency-weighted all-history diagnostic scored {pct(float(recency['accuracy']))}. "
            "Because these variants were compared on the same fixed test window, treat the variant comparison as diagnostic rather than a newly selected production model."
        ),
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    with sqlite3.connect(DB_PATH) as con:
        diagnostics = db_diagnostics(con)
        rows, feature_names = load_feature_rows(
            con,
            FEATURE_TABLE,
            exclude_synthetic_data=True,
            exclude_market_features=True,
        )
        historical = load_historical_games(con)

    if diagnostics["market_columns"]:
        raise RuntimeError(f"market columns present in {FEATURE_TABLE}: {diagnostics['market_columns']}")
    if any(int(r["synthetic_rows"]) for r in diagnostics["by_season"]):
        raise RuntimeError("synthetic rows are present in the expanded real feature table")

    _, weighted_features = feature_lists(feature_names)
    if not weighted_features:
        raise RuntimeError("No weighted features available for evaluation.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_predictions: List[Dict[str, object]] = []
    all_folds: List[Dict[str, object]] = []
    all_overall: List[Dict[str, object]] = []

    for policy in ["all_prior_real", "recent_2021_forward", "all_prior_real_recency_weighted"]:
        predictions, folds, overall = run_policy(
            rows,
            historical,
            weighted_features,
            policy=policy,
            test_seasons=BENCHMARK_TEST_SEASONS,
        )
        all_predictions.extend(predictions)
        all_folds.extend(folds)
        all_overall.append(overall)

    expanded_predictions, expanded_folds, expanded_overall = run_policy(
        rows,
        historical,
        weighted_features,
        policy="all_prior_real",
        test_seasons=None,
    )
    expanded_overall["test_scope"] = "all_walk_forward"
    all_predictions.extend(expanded_predictions)
    all_folds.extend(expanded_folds)
    all_overall.append(expanded_overall)
    conf = confidence_table(expanded_predictions, [0.55, 0.60, 0.65, 0.70, 0.75])

    write_csv(OUT_DIR / "predictions.csv", all_predictions)
    write_csv(OUT_DIR / "fold_metrics.csv", all_folds)
    write_csv(OUT_DIR / "overall_metrics.csv", all_overall)
    write_csv(OUT_DIR / "confidence_tiers.csv", conf)
    (OUT_DIR / "summary.json").write_text(
        json.dumps(
            {
                "feature_table": FEATURE_TABLE,
                "weighted_feature_count": len(weighted_features),
                "diagnostics": diagnostics,
                "overall": all_overall,
                "confidence_tiers": conf,
                "benchmark_accuracy": BENCHMARK_ACCURACY,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    write_report(diagnostics, all_overall, all_folds, conf)
    print(json.dumps({"overall": all_overall, "confidence_tiers": conf, "report": str(REPORT_PATH)}, indent=2))


if __name__ == "__main__":
    main()
