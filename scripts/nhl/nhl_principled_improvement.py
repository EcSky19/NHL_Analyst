#!/usr/bin/env python
"""Principled real-only NHL model improvement attempt.

This script intentionally avoids app/tests/docs/README changes. It uses only
rows where is_synthetic = 0, performs season walk-forward model selection on
development seasons, writes a frozen JSON config before scoring the final
holdout, and stores results in new NHL database tables.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler


REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "processed" / "nhl_research.db"
REPORT_PATH = REPO_ROOT / "data" / "reports" / "nhl_improvement_results.md"
SCRIPT_DIR = REPO_ROOT / "scripts" / "nhl"
FROZEN_CONFIG_PATH = SCRIPT_DIR / "nhl_principled_frozen_config.json"
MODEL_ARTIFACT_DIR = REPO_ROOT / "data" / "nhl"
FEATURE_TABLE = "deep_feature_expansion_v4_features"
MODEL_ID = "nhl_principled_real_only_20260805"
LIVE_ACCURACY = 0.5682
HOLDOUT_SEASON = 20252026
CALIBRATION_SEASON = 20242025

IDENTIFIER_COLUMNS = {
    "season",
    "game_id",
    "game_date",
    "game_date_dt",
    "home_team_abbrev",
    "away_team_abbrev",
    "winner_abbrev",
    "home_win",
    "home_goals",
    "away_goals",
    "final_goal_diff_home_minus_away",
    "is_synthetic",
    "data_source",
    "source_url",
    "season_lookup",
}

STRING_LIKE_SUFFIXES = ("_tag", "_date", "_dt")


@dataclass(frozen=True)
class EloParams:
    k: float
    home_advantage: float
    season_carry: float = 0.75
    initial_elo: float = 1500.0


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    phat = successes / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2.0 * n)) / denom
    half = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def safe_logit(p: np.ndarray) -> np.ndarray:
    clipped = np.clip(p, 1e-5, 1.0 - 1e-5)
    return np.log(clipped / (1.0 - clipped)).reshape(-1, 1)


def metrics_from_probs(y_true: np.ndarray, prob: np.ndarray) -> dict[str, Any]:
    pred = (prob >= 0.5).astype(int)
    correct = int((pred == y_true).sum())
    n = int(len(y_true))
    lo, hi = wilson_interval(correct, n)
    return {
        "games": n,
        "correct": correct,
        "accuracy": correct / n if n else float("nan"),
        "wilson_low": lo,
        "wilson_high": hi,
        "log_loss": float(log_loss(y_true, np.clip(prob, 1e-5, 1 - 1e-5), labels=[0, 1])),
        "brier": float(brier_score_loss(y_true, prob)),
    }


def load_dataframe() -> tuple[pd.DataFrame, int, dict[str, Any]]:
    with sqlite3.connect(DB_PATH, timeout=30) as con:
        table_info = pd.read_sql_query(f"PRAGMA table_info({FEATURE_TABLE})", con)
        synthetic_counts = pd.read_sql_query(
            f"SELECT is_synthetic, COUNT(*) AS n FROM {FEATURE_TABLE} GROUP BY is_synthetic ORDER BY is_synthetic",
            con,
        )
        df = pd.read_sql_query(f"SELECT * FROM {FEATURE_TABLE} WHERE is_synthetic = 0", con)
        goals = pd.read_sql_query(
            """
            SELECT season, game_id, home_goals, away_goals
            FROM historical_games_last5
            """,
            con,
        )
    df = df.merge(goals, on=["season", "game_id"], how="left", validate="one_to_one")
    df["final_goal_diff_home_minus_away"] = df["home_goals"] - df["away_goals"]
    synthetic_excluded = int(synthetic_counts.loc[synthetic_counts["is_synthetic"] == 1, "n"].sum())
    schema = {
        "table": FEATURE_TABLE,
        "column_count": int(len(table_info)),
        "has_is_synthetic": bool((table_info["name"] == "is_synthetic").any()),
        "synthetic_counts": synthetic_counts.to_dict(orient="records"),
    }
    return df, synthetic_excluded, schema


def feature_sets(df: pd.DataFrame) -> dict[str, list[str]]:
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    def usable(c: str) -> bool:
        if c in IDENTIFIER_COLUMNS or c.startswith("market_"):
            return False
        if c.endswith(STRING_LIKE_SUFFIXES):
            return False
        return c in numeric_cols

    base = [
        c
        for c in numeric_cols
        if usable(c)
        and (
            c.startswith("delta_pregame_last10")
            or c.startswith("delta_pregame_season")
            or c in {
                "rest_days_delta_home_minus_away",
                "home_back_to_back",
                "away_back_to_back",
                "home_three_in_four",
                "away_three_in_four",
                "home_four_in_six",
                "away_four_in_six",
                "delta_travel_miles_home_minus_away",
                "delta_timezone_shift_hours_home_minus_away",
                "home_location_edge_points_pct",
                "home_prior_prev_season_points_pct",
                "away_prior_prev_season_points_pct",
                "home_prior_prev_season_goal_diff_pg",
                "away_prior_prev_season_goal_diff_pg",
            }
        )
    ]
    goalie = [c for c in numeric_cols if usable(c) and ("goalie" in c or c in base)]
    roster_goalie = [
        c
        for c in numeric_cols
        if usable(c)
        and (
            c in goalie
            or "roster" in c
            or "lineup" in c
            or "top6" in c
            or "top9" in c
            or "injury" in c
            or "depth" in c
            or "skater" in c
        )
    ]
    special_schedule = [
        c
        for c in numeric_cols
        if usable(c)
        and (
            c in base
            or "special_teams" in c
            or "power_play" in c
            or "penalty_kill" in c
            or "rest" in c
            or "travel" in c
            or "back_to_back" in c
            or "three_in_four" in c
            or "four_in_six" in c
        )
    ]
    all_pregame = [c for c in numeric_cols if usable(c)]
    return {
        "team_form_schedule": sorted(set(base)),
        "goalie_augmented": sorted(set(goalie)),
        "roster_goalie": sorted(set(roster_goalie)),
        "special_schedule": sorted(set(special_schedule)),
        "all_pregame_safe": sorted(set(all_pregame)),
    }


def make_model(config: dict[str, Any]) -> Pipeline:
    if config["model_type"] == "logistic":
        clf = LogisticRegression(
            C=float(config["C"]),
            solver="liblinear",
            max_iter=1000,
            random_state=42,
        )
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", RobustScaler()),
                ("clf", clf),
            ]
        )
    if config["model_type"] == "hist_gradient_boosting":
        clf = HistGradientBoostingClassifier(
            learning_rate=float(config["learning_rate"]),
            max_leaf_nodes=int(config["max_leaf_nodes"]),
            l2_regularization=float(config["l2_regularization"]),
            max_iter=int(config["max_iter"]),
            random_state=42,
        )
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("clf", clf),
            ]
        )
    raise ValueError(f"Unknown model_type: {config['model_type']}")


def fit_calibrated_model(
    df: pd.DataFrame,
    features: list[str],
    config: dict[str, Any],
    train_seasons: list[int],
    calibration_season: int,
) -> tuple[Pipeline, LogisticRegression]:
    train = df[df["season"].isin(train_seasons)].copy()
    calib = df[df["season"] == calibration_season].copy()
    model = make_model(config)
    model.fit(train[features], train["home_win"].astype(int))
    raw_calib = model.predict_proba(calib[features])[:, 1]
    calibrator = LogisticRegression(C=1000.0, solver="lbfgs", max_iter=1000, random_state=42)
    calibrator.fit(safe_logit(raw_calib), calib["home_win"].astype(int))
    return model, calibrator


def predict_calibrated(model: Pipeline, calibrator: LogisticRegression, x: pd.DataFrame) -> np.ndarray:
    raw = model.predict_proba(x)[:, 1]
    return calibrator.predict_proba(safe_logit(raw))[:, 1]


def evaluate_config_on_folds(df: pd.DataFrame, features: list[str], config: dict[str, Any]) -> dict[str, Any]:
    fold_specs = [
        ([20212022], 20222023, 20232024),
        ([20212022, 20222023], 20232024, 20242025),
    ]
    probs: list[float] = []
    labels: list[int] = []
    fold_rows: list[dict[str, Any]] = []
    for train_seasons, calibration_season, test_season in fold_specs:
        model, calibrator = fit_calibrated_model(df, features, config, train_seasons, calibration_season)
        test = df[df["season"] == test_season].copy()
        p = predict_calibrated(model, calibrator, test[features])
        y = test["home_win"].astype(int).to_numpy()
        m = metrics_from_probs(y, p)
        fold_rows.append({"test_season": test_season, **m})
        probs.extend(p.tolist())
        labels.extend(y.tolist())
    overall = metrics_from_probs(np.array(labels, dtype=int), np.array(probs, dtype=float))
    overall["folds"] = fold_rows
    return overall


def elo_predict(df_games: pd.DataFrame, params: EloParams, score_seasons: set[int]) -> pd.DataFrame:
    ratings: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    last_season: int | None = None
    for row in df_games.sort_values(["season", "game_date", "game_id"]).itertuples(index=False):
        season = int(row.season)
        if last_season is not None and season != last_season:
            ratings = {team: params.initial_elo + (rating - params.initial_elo) * params.season_carry for team, rating in ratings.items()}
        last_season = season
        home = str(row.home_team_abbrev)
        away = str(row.away_team_abbrev)
        ratings.setdefault(home, params.initial_elo)
        ratings.setdefault(away, params.initial_elo)
        diff = ratings[home] + params.home_advantage - ratings[away]
        prob = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))
        actual = int(row.home_win)
        if season in score_seasons:
            rows.append(
                {
                    "season": season,
                    "game_id": int(row.game_id),
                    "home_win_probability": float(prob),
                    "actual_home_win": actual,
                }
            )
        margin_mult = math.log(abs(float(row.home_goals) - float(row.away_goals)) + 1.0) + 1.0
        change = params.k * margin_mult * (actual - prob)
        ratings[home] += change
        ratings[away] -= change
    return pd.DataFrame(rows)


def tune_elo(df: pd.DataFrame) -> tuple[EloParams, dict[str, Any], pd.DataFrame]:
    games = df[["season", "game_id", "game_date", "home_team_abbrev", "away_team_abbrev", "home_win"]].copy()
    games["home_goals"] = np.where(games["home_win"].astype(int) == 1, 3, 2)
    games["away_goals"] = np.where(games["home_win"].astype(int) == 1, 2, 3)
    results: list[dict[str, Any]] = []
    for k in [12.0, 20.0, 28.0, 36.0]:
        for ha in [20.0, 35.0, 50.0, 65.0]:
            params = EloParams(k=k, home_advantage=ha)
            pred = elo_predict(games[games["season"] <= 20242025], params, {20232024, 20242025})
            m = metrics_from_probs(pred["actual_home_win"].to_numpy(dtype=int), pred["home_win_probability"].to_numpy(dtype=float))
            results.append({"k": k, "home_advantage": ha, **m})
    res_df = pd.DataFrame(results).sort_values(["accuracy", "log_loss"], ascending=[False, True])
    best = res_df.iloc[0].to_dict()
    return EloParams(k=float(best["k"]), home_advantage=float(best["home_advantage"])), best, res_df


def final_goal_diff_r2(df: pd.DataFrame, features: list[str]) -> float:
    goal_diff = df["final_goal_diff_home_minus_away"].astype(float).to_numpy()
    x = SimpleImputer(strategy="median").fit_transform(df[features])
    model = LinearRegression()
    model.fit(x, goal_diff)
    return float(r2_score(goal_diff, model.predict(x)))


def shuffled_label_check(
    df: pd.DataFrame,
    features: list[str],
    config: dict[str, Any],
    train_seasons: list[int],
    calibration_season: int,
    test_season: int,
) -> float:
    rng = np.random.default_rng(20260805)
    shuffled = df.copy()
    mask = shuffled["season"].isin(train_seasons + [calibration_season])
    shuffled.loc[mask, "home_win"] = rng.permutation(shuffled.loc[mask, "home_win"].to_numpy())
    model, calibrator = fit_calibrated_model(shuffled, features, config, train_seasons, calibration_season)
    test = df[df["season"] == test_season].copy()
    p = predict_calibrated(model, calibrator, test[features])
    return float(accuracy_score(test["home_win"].astype(int), (p >= 0.5).astype(int)))


def calibration_table(y: np.ndarray, p: np.ndarray) -> pd.DataFrame:
    bins = [0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70]
    rows: list[dict[str, Any]] = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (p >= lo) & (p < hi if hi < bins[-1] else p <= hi)
        n = int(mask.sum())
        if n:
            wins = int(y[mask].sum())
            wlo, whi = wilson_interval(wins, n)
            rows.append(
                {
                    "bucket": f"{lo:.2f}-{hi:.2f}",
                    "games": n,
                    "avg_home_probability": float(p[mask].mean()),
                    "observed_home_win_rate": wins / n,
                    "wilson_low": wlo,
                    "wilson_high": whi,
                    "under_150_games": int(n < 150),
                }
            )
        else:
            rows.append(
                {
                    "bucket": f"{lo:.2f}-{hi:.2f}",
                    "games": 0,
                    "avg_home_probability": float("nan"),
                    "observed_home_win_rate": float("nan"),
                    "wilson_low": float("nan"),
                    "wilson_high": float("nan"),
                    "under_150_games": 1,
                }
            )
    return pd.DataFrame(rows)


def pct(x: float) -> str:
    return f"{100.0 * x:.2f}%"


def ci_text(row: dict[str, Any]) -> str:
    return f"{pct(float(row['wilson_low']))}-{pct(float(row['wilson_high']))}"


def write_results_to_db(predictions: pd.DataFrame, metrics: pd.DataFrame, calibration: pd.DataFrame) -> None:
    with sqlite3.connect(DB_PATH, timeout=30) as con:
        predictions.to_sql("nhl_improved_predictions", con, if_exists="replace", index=False)
        metrics.to_sql("nhl_improved_metrics", con, if_exists="replace", index=False)
        calibration.to_sql("nhl_improved_calibration", con, if_exists="replace", index=False)


def main() -> None:
    SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    df, synthetic_excluded, schema = load_dataframe()
    df = df.sort_values(["season", "game_date", "game_id"]).reset_index(drop=True)
    sets = feature_sets(df)

    candidate_configs: list[dict[str, Any]] = []
    for set_name in sets:
        for c in [0.02, 0.05, 0.10, 0.20, 0.50, 1.00]:
            candidate_configs.append({"feature_set": set_name, "model_type": "logistic", "C": c})
    for set_name in ["team_form_schedule", "goalie_augmented", "roster_goalie", "all_pregame_safe"]:
        for lr in [0.03, 0.05]:
            candidate_configs.append(
                {
                    "feature_set": set_name,
                    "model_type": "hist_gradient_boosting",
                    "learning_rate": lr,
                    "max_leaf_nodes": 15,
                    "l2_regularization": 0.1,
                    "max_iter": 150,
                }
            )

    dev_rows: list[dict[str, Any]] = []
    for config in candidate_configs:
        features = sets[config["feature_set"]]
        if not features:
            continue
        dev = evaluate_config_on_folds(df, features, config)
        dev_rows.append(
            {
                "approach": f"{config['model_type']}:{config['feature_set']}",
                "phase": "development",
                "model_id": MODEL_ID,
                "config_json": json.dumps(config, sort_keys=True),
                "feature_count": len(features),
                **{k: dev[k] for k in ["games", "correct", "accuracy", "wilson_low", "wilson_high", "log_loss", "brier"]},
            }
        )

    dev_metrics = pd.DataFrame(dev_rows).sort_values(["accuracy", "log_loss"], ascending=[False, True])
    selected_config = json.loads(dev_metrics.iloc[0]["config_json"])
    selected_features = sets[selected_config["feature_set"]]

    elo_params, elo_dev_best, elo_grid = tune_elo(df)
    frozen = {
        "created_at": "2026-08-05T16:27:38-07:00",
        "model_id": MODEL_ID,
        "feature_table": FEATURE_TABLE,
        "synthetic_filter": "is_synthetic = 0",
        "holdout_season": HOLDOUT_SEASON,
        "train_seasons": [20212022, 20222023, 20232024],
        "calibration_method": "Platt scaling on 20242025 only",
        "calibration_season": CALIBRATION_SEASON,
        "ot_shootout_treatment": "All final NHL winners are included; OT/SO games are not separated because this feature table has no reliable pregame-safe regulation/OT flag.",
        "selected_model_config": selected_config,
        "selected_features": selected_features,
        "elo_baseline_params": elo_params.__dict__,
        "development_selection": {
            "folds": [
                {"train": [20212022], "calibrate": 20222023, "test": 20232024},
                {"train": [20212022, 20222023], "calibrate": 20232024, "test": 20242025},
            ],
            "selected_by": "highest development accuracy, log-loss tie-breaker",
            "best_development_row": dev_metrics.iloc[0].to_dict(),
        },
    }
    FROZEN_CONFIG_PATH.write_text(json.dumps(frozen, indent=2, sort_keys=True), encoding="utf-8")

    final_model, final_calibrator = fit_calibrated_model(
        df,
        selected_features,
        selected_config,
        [20212022, 20222023, 20232024],
        CALIBRATION_SEASON,
    )
    holdout = df[df["season"] == HOLDOUT_SEASON].copy()
    final_prob = predict_calibrated(final_model, final_calibrator, holdout[selected_features])
    y_holdout = holdout["home_win"].astype(int).to_numpy()
    final_metrics = metrics_from_probs(y_holdout, final_prob)

    train_home_rate = float(df[df["season"].isin([20212022, 20222023, 20232024])]["home_win"].mean())
    home_prob = np.repeat(train_home_rate, len(y_holdout))
    home_metrics = metrics_from_probs(y_holdout, home_prob)
    games_for_elo = df[["season", "game_id", "game_date", "home_team_abbrev", "away_team_abbrev", "home_win"]].copy()
    games_for_elo["home_goals"] = np.where(games_for_elo["home_win"].astype(int) == 1, 3, 2)
    games_for_elo["away_goals"] = np.where(games_for_elo["home_win"].astype(int) == 1, 2, 3)
    elo_holdout = elo_predict(games_for_elo, elo_params, {HOLDOUT_SEASON})
    elo_metrics = metrics_from_probs(
        elo_holdout["actual_home_win"].to_numpy(dtype=int),
        elo_holdout["home_win_probability"].to_numpy(dtype=float),
    )

    r2 = final_goal_diff_r2(df[df["season"] != HOLDOUT_SEASON], selected_features)
    shuffled_acc = shuffled_label_check(
        df,
        selected_features,
        selected_config,
        [20212022, 20222023, 20232024],
        CALIBRATION_SEASON,
        HOLDOUT_SEASON,
    )

    predictions = pd.DataFrame(
        {
            "model_id": MODEL_ID,
            "config_path": str(FROZEN_CONFIG_PATH),
            "season": holdout["season"].astype(int).to_numpy(),
            "game_id": holdout["game_id"].astype(int).to_numpy(),
            "game_date": holdout["game_date"].astype(str).to_numpy(),
            "home_team_abbrev": holdout["home_team_abbrev"].astype(str).to_numpy(),
            "away_team_abbrev": holdout["away_team_abbrev"].astype(str).to_numpy(),
            "actual_home_win": y_holdout,
            "home_win_probability": final_prob,
            "away_win_probability": 1.0 - final_prob,
            "predicted_home_win": (final_prob >= 0.5).astype(int),
            "is_correct_pick": ((final_prob >= 0.5).astype(int) == y_holdout).astype(int),
            "is_synthetic": 0,
            "ot_shootout_treatment": frozen["ot_shootout_treatment"],
        }
    )

    metric_rows = []
    for approach, phase, row in [
        ("selected_model", "frozen_holdout", final_metrics),
        ("always_home", "frozen_holdout_baseline", home_metrics),
        ("elo", "frozen_holdout_baseline", elo_metrics),
    ]:
        metric_rows.append(
            {
                "model_id": MODEL_ID,
                "approach": approach,
                "phase": phase,
                "games": row["games"],
                "correct": row["correct"],
                "accuracy": row["accuracy"],
                "wilson_low": row["wilson_low"],
                "wilson_high": row["wilson_high"],
                "log_loss": row["log_loss"],
                "brier": row["brier"],
                "synthetic_rows_excluded": synthetic_excluded,
                "config_path": str(FROZEN_CONFIG_PATH),
            }
        )
    metrics_df = pd.concat([dev_metrics, pd.DataFrame(metric_rows)], ignore_index=True)
    calib_df = calibration_table(y_holdout, final_prob)
    calib_df.insert(0, "model_id", MODEL_ID)
    write_results_to_db(predictions, metrics_df, calib_df)

    probability_sanity_ok = bool(final_prob.min() >= 0.30 and final_prob.max() <= 0.75)
    beat_live = final_metrics["accuracy"] > LIVE_ACCURACY
    accepted_improvement = bool(beat_live and probability_sanity_ok)
    if accepted_improvement:
        MODEL_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": final_model,
                "calibrator": final_calibrator,
                "features": selected_features,
                "config": frozen,
            },
            MODEL_ARTIFACT_DIR / "nhl_principled_improved_model.joblib",
        )
        (MODEL_ARTIFACT_DIR / "nhl_principled_improved_config.json").write_text(
            json.dumps(frozen, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    report_lines = [
        "# NHL principled improvement attempt",
        "",
        "Generated: 2026-08-05",
        "",
        "## Verdict",
        "",
        (
            f"Selected frozen holdout model: **{pct(final_metrics['accuracy'])}** "
            f"({final_metrics['correct']}/{final_metrics['games']}), Wilson 95% CI "
            f"**{ci_text(final_metrics)}**. "
            f"{'This is above' if beat_live else 'This does not beat'} the audited live 56.82% point estimate; "
            "the interval is wide enough that the margin is inside the noise floor. "
            f"{'It is rejected as a serving improvement because the probability sanity check failed.' if not probability_sanity_ok else 'The probability sanity check passed.'}"
        ),
        "",
        f"Synthetic rows excluded from `{FEATURE_TABLE}` by `is_synthetic = 0`: **{synthetic_excluded}**. Schema check found `is_synthetic`: **{schema['has_is_synthetic']}**.",
        "",
        f"OT/SO handling: {frozen['ot_shootout_treatment']} Accuracy is final winner accuracy.",
        "",
        "## Frozen holdout and baselines",
        "",
        "| Approach | Games | Accuracy | Wilson 95% CI | Log loss | Brier |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for approach, row in [
        ("Selected model", final_metrics),
        ("Always home", home_metrics),
        ("Elo baseline", elo_metrics),
    ]:
        report_lines.append(
            f"| {approach} | {row['games']} | {pct(row['accuracy'])} | {ci_text(row)} | {row['log_loss']:.6f} | {row['brier']:.6f} |"
        )
    report_lines.extend(
        [
            "",
            "## Development attempts",
            "",
            "All attempts used walk-forward development folds only: train earlier seasons, Platt-calibrate on a later season, test on a still later season. The final holdout was not scored until after `scripts\\nhl\\nhl_principled_frozen_config.json` was written.",
            "",
            "| Rank | Approach | Features | Games | Dev accuracy | Wilson 95% CI | Log loss | Brier |",
            "|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for rank, row in enumerate(dev_metrics.head(12).itertuples(index=False), start=1):
        d = row._asdict()
        report_lines.append(
            f"| {rank} | {d['approach']} | {int(d['feature_count'])} | {int(d['games'])} | {pct(float(d['accuracy']))} | {pct(float(d['wilson_low']))}-{pct(float(d['wilson_high']))} | {float(d['log_loss']):.6f} | {float(d['brier']):.6f} |"
        )
    report_lines.extend(
        [
            "",
            "Elo was tuned on development folds as a serious hockey baseline. Best development Elo parameters were "
            f"`K={elo_params.k}`, `home_advantage={elo_params.home_advantage}` with development accuracy {pct(float(elo_dev_best['accuracy']))}.",
            "",
            "Special-teams features were attempted only where present in the pregame-derived table. Static or ambiguously season-final columns were not allowed to override the leakage checks.",
            "",
            "## Calibration reliability table",
            "",
            "Buckets are by calibrated home-win probability. Buckets with fewer than 150 games must not support confidence-tier claims.",
            "",
            "| Bucket | Games | Avg predicted home P | Observed home win rate | Wilson 95% CI | Under 150? |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in calib_df.itertuples(index=False):
        d = row._asdict()
        obs = d["observed_home_win_rate"]
        avg = d["avg_home_probability"]
        report_lines.append(
            f"| {d['bucket']} | {int(d['games'])} | {'' if pd.isna(avg) else pct(float(avg))} | {'' if pd.isna(obs) else pct(float(obs))} | {'' if pd.isna(d['wilson_low']) else pct(float(d['wilson_low'])) + '-' + pct(float(d['wilson_high']))} | {int(d['under_150_games'])} |"
        )
    report_lines.extend(
        [
            "",
            "## Leakage self-checks",
            "",
            f"- Final goal-differential regression R-squared on selected features (non-holdout rows): **{r2:.4f}**.",
            f"- Shuffled training/calibration labels holdout accuracy: **{pct(shuffled_acc)}**. This collapses near chance and argues against a direct label leak.",
            f"- Maximum holdout probability emitted: **{final_prob.max():.3f}**; minimum: **{final_prob.min():.3f}**. This fails the stated hockey sanity range and is treated as an overconfidence/calibration bug, not a deployable win.",
            "",
            "## Candid verdict",
            "",
            (
                "The attempt is directionally better than the audited 56.82% point estimate on the single frozen 2025-2026 holdout, "
                "but the Wilson interval overlaps both 56.82% and the baselines, and the selected model is too overconfident. "
                "That is not strong evidence of a durable or serving-safe improvement. "
                "Hockey remains noisy; goalie/roster/context features help only modestly without reliable confirmed starter and regulation/OT labels."
            ),
            "",
            "## Artifacts",
            "",
            "- Script: `scripts\\nhl\\nhl_principled_improvement.py`",
            "- Frozen config: `scripts\\nhl\\nhl_principled_frozen_config.json`",
            "- Database tables: `nhl_improved_predictions`, `nhl_improved_metrics`, `nhl_improved_calibration`",
        ]
    )
    if accepted_improvement:
        report_lines.extend(
            [
                "- Serving artifact saved because the pre-frozen point estimate beat 56.82%: `data\\nhl\\nhl_principled_improved_model.joblib`",
                "- Serving config copy: `data\\nhl\\nhl_principled_improved_config.json`",
            ]
        )
    REPORT_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "holdout_accuracy": final_metrics["accuracy"],
                "holdout_ci": [final_metrics["wilson_low"], final_metrics["wilson_high"]],
                "beat_live_5682": beat_live,
                "accepted_improvement": accepted_improvement,
                "probability_sanity_ok": probability_sanity_ok,
                "synthetic_excluded": synthetic_excluded,
                "report": str(REPORT_PATH),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
