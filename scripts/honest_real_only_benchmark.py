#!/usr/bin/env python
"""Run the quarantined honest NHL benchmark: real rows only, no market proxies."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple

from run_walk_forward_experiments import (
    BASE_FEATURE_CANDIDATES,
    ROSTER_FEATURE_CANDIDATES,
    V3_INTERACTION_FEATURE_NAMES,
    V4_INTERACTION_FEATURE_NAMES,
    WEIGHTED_MODEL_WEIGHTS,
    CalibrationConfig,
    EloState,
    RecencyConfig,
    aggregate_weighted_metrics,
    apply_isotonic,
    apply_platt,
    build_robust_scaler,
    calibration_validation_regime_label,
    choose_calibration_method,
    compute_metrics_from_arrays,
    compute_recency_weights,
    load_feature_rows,
    load_historical_games,
    parse_float,
    fit_isotonic_calibrator,
    fit_platt_scaler,
    tune_elo_params,
    weighted_score,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "processed" / "nhl_research.db"
OUT_DIR = REPO_ROOT / "data" / "processed" / "execution_plan" / "honest_real_only_no_market"
FEATURE_TABLE = "backtest_features_last5_roster"
MODEL_ID = "honest_blend_top2_fixed_50_50__weighted_calibrated__elo_form_tuned"


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def select_weighted_calibrator(train_rows, train_weights, weighted_features, config: CalibrationConfig) -> str:
    train_seasons = sorted({r.season for r in train_rows})
    requested_validation_seasons = max(1, int(config.validation_seasons))
    selected_validation_seasons = train_seasons[-requested_validation_seasons:]
    if len(train_seasons) > requested_validation_seasons:
        fit_season_set = set(train_seasons[:-requested_validation_seasons])
    else:
        fit_season_set = set(train_seasons)

    fit_rows = []
    fit_weights = []
    val_rows = []
    for row, weight in zip(train_rows, train_weights):
        if row.season in fit_season_set:
            fit_rows.append(row)
            fit_weights.append(weight)
        if row.season in set(selected_validation_seasons):
            val_rows.append(row)
    if not fit_rows or not val_rows:
        fit_rows = list(train_rows)
        fit_weights = list(train_weights)
        val_rows = list(train_rows)
        selected_validation_seasons = [train_seasons[-1]] if train_seasons else []

    med, sc = build_robust_scaler(fit_rows, weighted_features)
    fit_scores = [weighted_score(r, weighted_features, med, sc) for r in fit_rows]
    fit_targets = [r.home_win for r in fit_rows]
    val_scores = [weighted_score(r, weighted_features, med, sc) for r in val_rows]
    val_targets = [r.home_win for r in val_rows]

    platt_a, platt_b = fit_platt_scaler(fit_scores, fit_targets, sample_weights=fit_weights)
    iso = fit_isotonic_calibrator(fit_scores, fit_targets, sample_weights=fit_weights)
    probs_by_method = {
        "platt": [apply_platt(s, platt_a, platt_b) for s in val_scores],
        "isotonic": [apply_isotonic(s, iso["breakpoints"], iso["values"]) for s in val_scores],
    }
    metrics_by_method = {
        method: compute_metrics_from_arrays(val_targets, probs)
        for method, probs in probs_by_method.items()
    }
    selector_metrics = metrics_by_method

    if config.selector_mode == "season_aware":
        ordered_val_seasons = sorted({r.season for r in val_rows})
        latest_val_season = ordered_val_seasons[-1] if ordered_val_seasons else None
        weighted_method_metrics = {}
        for method_name in sorted(probs_by_method):
            weighted_rows = []
            for season in ordered_val_seasons:
                idxs = [i for i, row in enumerate(val_rows) if row.season == season]
                y_view = [val_targets[i] for i in idxs]
                p_view = [probs_by_method[method_name][i] for i in idxs]
                season_metrics = compute_metrics_from_arrays(y_view, p_view)
                age = 0 if latest_val_season is None else max(
                    0, ordered_val_seasons.index(latest_val_season) - ordered_val_seasons.index(season)
                )
                season_w = 0.5 ** (age / max(float(config.season_half_life), 1e-6))
                weighted_rows.append((season_w, season_metrics))
            weighted_method_metrics[method_name] = aggregate_weighted_metrics(weighted_rows)
        selector_metrics = weighted_method_metrics
    elif config.selector_mode == "season_regime":
        ordered_val_seasons = sorted({r.season for r in val_rows})
        regimes = [calibration_validation_regime_label(r.season, ordered_val_seasons) for r in val_rows]
        regime = regimes[-1] if regimes else "late"
        idxs = [i for i, value in enumerate(regimes) if value == regime]
        selector_metrics = {
            method: compute_metrics_from_arrays(
                [val_targets[i] for i in idxs],
                [probs_by_method[method][i] for i in idxs],
            )
            for method in probs_by_method
        }

    return choose_calibration_method(
        selector_metrics,
        objective=config.selection_objective,
        objective_margin=config.objective_margin,
    )


def main() -> None:
    with sqlite3.connect(DB_PATH) as con:
        rows, feature_names = load_feature_rows(
            con,
            FEATURE_TABLE,
            exclude_synthetic_data=True,
            exclude_market_features=True,
        )
        historical = load_historical_games(con)

    seasons = sorted({r.season for r in rows})
    historical_map = {(g.season, g.game_id): g for g in historical}
    feature_allowlist = set(BASE_FEATURE_CANDIDATES + ROSTER_FEATURE_CANDIDATES + V3_INTERACTION_FEATURE_NAMES + V4_INTERACTION_FEATURE_NAMES)
    usable_features = sorted({name for name in feature_names if name in feature_allowlist and not name.startswith("market_")})
    weighted_features = sorted([name for name in usable_features if name in WEIGHTED_MODEL_WEIGHTS and not name.startswith("market_")])
    recency = RecencyConfig(mode="none", season_half_life=1.5, game_half_life=800.0, min_weight=0.2, normalize_mean_one=True)
    calibration = CalibrationConfig(
        selector_mode="season_aware",
        validation_seasons=2,
        season_half_life=1.0,
        selection_objective="joint",
        objective_margin=0.0005,
    )

    predictions: List[Dict[str, object]] = []
    fold_rows: List[Dict[str, object]] = []
    for idx in range(1, len(seasons)):
        train_seasons = seasons[:idx]
        test_season = seasons[idx]
        train_rows = [r for r in rows if r.season in train_seasons]
        test_rows = [r for r in rows if r.season == test_season]
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
            pred_home = 1 if prob >= 0.5 else 0
            y_fold.append(row.home_win)
            p_fold.append(prob)
            predictions.append(
                {
                    "model_id": MODEL_ID,
                    "fold_train_end_season": train_seasons[-1],
                    "fold_test_season": test_season,
                    "season": row.season,
                    "game_id": row.game_id,
                    "game_date": row.game_date,
                    "home_team_abbrev": row.home_team,
                    "away_team_abbrev": row.away_team,
                    "actual_home_win": row.home_win,
                    "home_win_probability": round(prob, 6),
                    "away_win_probability": round(1.0 - prob, 6),
                    "predicted_winner_abbrev": row.home_team if pred_home else row.away_team,
                    "is_correct_pick": 1 if pred_home == row.home_win else 0,
                    "is_synthetic": 0,
                    "data_source": "REAL_NHL_API_OR_DERIVED_FROM_REAL",
                    "excluded_market_features": 1,
                }
            )
        metrics = compute_metrics_from_arrays(y_fold, p_fold)
        fold_rows.append(
            {
                "season": test_season,
                "games": int(metrics["games"]),
                "accuracy": round(float(metrics["accuracy"]), 6),
                "log_loss": round(float(metrics["log_loss"]), 6),
                "brier_score": round(float(metrics["brier_score"]), 6),
                "weighted_calibrator": selected_method,
            }
        )

    overall = compute_metrics_from_arrays(
        [int(r["actual_home_win"]) for r in predictions],
        [float(r["home_win_probability"]) for r in predictions],
    )
    overall_row = {
        "model_id": MODEL_ID,
        "games": int(overall["games"]),
        "accuracy": round(float(overall["accuracy"]), 6),
        "log_loss": round(float(overall["log_loss"]), 6),
        "brier_score": round(float(overall["brier_score"]), 6),
        "train_policy": "expanding walk-forward over real seasons only; first real season is training-only",
        "feature_table": FEATURE_TABLE,
        "excluded_market_features": True,
        "synthetic_rows_excluded": True,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_DIR / "predictions.csv", predictions)
    write_csv(OUT_DIR / "by_season_metrics.csv", fold_rows)
    write_csv(OUT_DIR / "overall_metrics.csv", [overall_row])
    (OUT_DIR / "summary.json").write_text(
        json.dumps(
            {
                "model_id": MODEL_ID,
                "overall_metrics": overall_row,
                "by_season_metrics": fold_rows,
                "seasons_available": seasons,
                "test_seasons": [r["season"] for r in fold_rows],
                "real_rows_loaded": len(rows),
                "weighted_feature_count": len(weighted_features),
                "excluded": {
                    "fabricated_seasons": [20152016, 20162017, 20172018],
                    "market_features": True,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(json.dumps(overall_row, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
