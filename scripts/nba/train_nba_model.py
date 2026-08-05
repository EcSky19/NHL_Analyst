"""Train frozen walk-forward NBA model and store predictions/metrics."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, mean_absolute_error, r2_score
from sklearn.pipeline import make_pipeline


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "nba" / "nba_research.db"
CONFIG_PATH = ROOT / "data" / "nba" / "nba_model_config.json"
MODEL_PATH = ROOT / "data" / "nba" / "nba_model_final.joblib"

MODEL_PARAMS = {
    "learning_rate": 0.045,
    "max_iter": 220,
    "max_leaf_nodes": 15,
    "l2_regularization": 0.08,
    "min_samples_leaf": 30,
    "random_state": 20260805,
}
FIRST_TEST_SEASON = 2007
FINAL_HOLDOUT_SEASONS = [2023]
CALIBRATION_METHOD = "platt_on_prior_season"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def wilson_ci(wins: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return centre - half, centre + half


def load_features() -> pd.DataFrame:
    with connect() as con:
        return pd.read_sql_query("SELECT * FROM nba_features_pregame ORDER BY game_date, game_id", con)


def replace_owned_table(con: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    cols = []
    for name, dtype in df.dtypes.items():
        sql_type = "INTEGER" if pd.api.types.is_integer_dtype(dtype) else "REAL" if pd.api.types.is_float_dtype(dtype) else "TEXT"
        cols.append(f'"{name}" {sql_type}')
    con.execute(f'CREATE TABLE IF NOT EXISTS {table} ({", ".join(cols)})')
    con.execute(f"DELETE FROM {table}")
    df.to_sql(table, con, if_exists="append", index=False)


def feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = {"game_id", "season", "game_date", "home_team", "away_team", "home_win", "home_score", "away_score", "final_margin"}
    return [c for c in df.columns if c not in excluded]


def make_base_model():
    return make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        HistGradientBoostingClassifier(**MODEL_PARAMS),
    )


def fit_fold(df: pd.DataFrame, features: list[str], test_season: int) -> tuple[np.ndarray, object, LogisticRegression]:
    calib_season = test_season - 1
    train = df[df["season"] < calib_season]
    calib = df[df["season"] == calib_season]
    test = df[df["season"] == test_season]
    if train.empty or calib.empty or test.empty:
        raise ValueError(f"Bad fold for season {test_season}")

    base = make_base_model()
    base.fit(train[features], train["home_win"])
    calib_raw = base.predict_proba(calib[features])[:, 1]
    platt = LogisticRegression(C=1.0, solver="lbfgs", random_state=20260805)
    platt.fit(np.log(np.clip(calib_raw, 1e-6, 1 - 1e-6) / np.clip(1 - calib_raw, 1e-6, 1)).reshape(-1, 1), calib["home_win"])
    raw = base.predict_proba(test[features])[:, 1]
    logits = np.log(np.clip(raw, 1e-6, 1 - 1e-6) / np.clip(1 - raw, 1e-6, 1))
    pred = platt.predict_proba(logits.reshape(-1, 1))[:, 1]
    return pred, base, platt


def metric_row(name: str, season: int | str, y: np.ndarray, p: np.ndarray) -> dict[str, float | int | str]:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    pred = (p >= 0.5).astype(int)
    wins = int((pred == y).sum())
    lo, hi = wilson_ci(wins, len(y))
    return {
        "model": name,
        "season": season,
        "games": int(len(y)),
        "correct": wins,
        "accuracy": wins / len(y),
        "wilson_low": lo,
        "wilson_high": hi,
        "log_loss": log_loss(y, p, labels=[0, 1]),
        "brier": brier_score_loss(y, p),
    }


def freeze_config(df: pd.DataFrame, features: list[str]) -> None:
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    config = {
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_table": "nba_features_pregame",
        "prediction_table": "nba_model_predictions",
        "metric_table": "nba_model_metrics",
        "data_scope": "NBA regular-season, completed, non-neutral games only",
        "per_game_data_window": f"{int(df['season'].min())}-{int(df['season'].max())}",
        "development_test_seasons": list(range(FIRST_TEST_SEASON, min(FINAL_HOLDOUT_SEASONS))),
        "final_holdout_seasons": FINAL_HOLDOUT_SEASONS,
        "model_type": "HistGradientBoostingClassifier + Platt scaling on immediately prior season",
        "model_params": MODEL_PARAMS,
        "feature_builder_params": {"rolling_windows": [3, 5, 10, 20], "elo_k_factor": 20.0, "elo_home_advantage_points": 65.0},
        "calibration_method": CALIBRATION_METHOD,
        "feature_columns": features,
        "script_sha256": script_hash,
        "synthetic_data_policy": "No fabricated or simulated rows; features come from prior real games only.",
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def leakage_check(df: pd.DataFrame, features: list[str]) -> dict[str, float]:
    train = df[df["season"] < min(FINAL_HOLDOUT_SEASONS)]
    holdout = df[df["season"].isin(FINAL_HOLDOUT_SEASONS)]
    reg = make_pipeline(
        SimpleImputer(strategy="median"),
        ExtraTreesRegressor(n_estimators=120, min_samples_leaf=20, random_state=20260805, n_jobs=-1),
    )
    reg.fit(train[features], train["final_margin"])
    pred = reg.predict(holdout[features])
    corr = []
    for col in features:
        if df[col].notna().sum() > 100 and df[col].nunique(dropna=True) > 2:
            corr.append(abs(np.corrcoef(df[col].fillna(df[col].median()), df["final_margin"])[0, 1]))
    return {
        "holdout_margin_r2": float(r2_score(holdout["final_margin"], pred)),
        "holdout_margin_mae": float(mean_absolute_error(holdout["final_margin"], pred)),
        "exact_margin_within_1_point_rate": float((np.abs(pred - holdout["final_margin"]) <= 1).mean()),
        "max_abs_single_feature_margin_corr": float(np.nanmax(corr)),
    }


def main() -> None:
    df = load_features()
    features = feature_columns(df)
    freeze_config(df, features)
    print(f"Frozen config written before holdout evaluation: {CONFIG_PATH}")

    predictions: list[pd.DataFrame] = []
    metrics: list[dict[str, float | int | str]] = []
    fold_lines: list[str] = []
    test_seasons = list(range(FIRST_TEST_SEASON, int(df["season"].max()) + 1))

    for season in test_seasons:
        calib_season = season - 1
        train_min = int(df[df["season"] < calib_season]["season"].min())
        train_max = int(df[df["season"] < calib_season]["season"].max())
        fold_type = "final_holdout" if season in FINAL_HOLDOUT_SEASONS else "development"
        fold_lines.append(f"{season}: train {train_min}-{train_max}, calibrate {calib_season}, test {season} ({fold_type})")
        print(fold_lines[-1])
        p_model, base, platt = fit_fold(df, features, season)
        test = df[df["season"] == season].copy()
        y = test["home_win"].to_numpy()
        elo = test["elo_prob_home"].clip(1e-6, 1 - 1e-6).to_numpy()
        home_rate = float(df[df["season"] < season]["home_win"].mean())
        home_prob = np.full(len(test), np.clip(home_rate, 1e-6, 1 - 1e-6))

        metrics.append(metric_row("nba_model", season, y, p_model))
        metrics.append(metric_row("always_home", season, y, home_prob))
        metrics.append(metric_row("pure_elo", season, y, elo))

        pred_df = test[["game_id", "season", "game_date", "home_team", "away_team", "home_win", "final_margin", "elo_prob_home"]].copy()
        pred_df["fold_type"] = fold_type
        pred_df["model_prob_home"] = p_model
        pred_df["model_pick_home"] = (pred_df["model_prob_home"] >= 0.5).astype(int)
        pred_df["elo_pick_home"] = (pred_df["elo_prob_home"] >= 0.5).astype(int)
        pred_df["always_home_pick"] = 1
        predictions.append(pred_df)

        if season == max(FINAL_HOLDOUT_SEASONS):
            joblib.dump({"base_model": base, "platt": platt, "features": features, "config_path": str(CONFIG_PATH)}, MODEL_PATH)

    preds = pd.concat(predictions, ignore_index=True)
    metric_df = pd.DataFrame(metrics)
    for model in ["nba_model", "always_home", "pure_elo"]:
        for label, subset in [("development_overall", preds[preds["fold_type"] == "development"]), ("final_holdout_overall", preds[preds["fold_type"] == "final_holdout"]), ("all_walk_forward", preds)]:
            if subset.empty:
                continue
            y = subset["home_win"].to_numpy()
            p = subset["model_prob_home"].to_numpy() if model == "nba_model" else subset["elo_prob_home"].to_numpy() if model == "pure_elo" else np.full(len(subset), df[df["season"] < subset["season"].min()]["home_win"].mean())
            metric_df = pd.concat([metric_df, pd.DataFrame([metric_row(model, label, y, p)])], ignore_index=True)

    leak = leakage_check(df, features)
    leak_df = pd.DataFrame([{"check_name": k, "value": v} for k, v in leak.items()])
    fold_df = pd.DataFrame({"fold": fold_lines})
    with connect() as con:
        replace_owned_table(con, "nba_model_predictions", preds)
        replace_owned_table(con, "nba_model_metrics", metric_df)
        replace_owned_table(con, "nba_model_leakage_checks", leak_df)
        replace_owned_table(con, "nba_model_fold_boundaries", fold_df)
        con.execute("CREATE INDEX IF NOT EXISTS idx_nba_model_predictions_season ON nba_model_predictions(season)")

    print(f"Stored {len(preds):,} walk-forward predictions and {len(metric_df):,} metric rows")
    print("Leakage check:", leak)


if __name__ == "__main__":
    main()
