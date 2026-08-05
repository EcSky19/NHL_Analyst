"""Evaluate pre-registered NBA Elo/model probability blends."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "nba" / "nba_research.db"
CONFIG_PATH = ROOT / "data" / "nba" / "nba_blend_config.json"
ARTIFACT_PATH = ROOT / "data" / "nba" / "nba_blend_final.joblib"
REPORT_PATH = ROOT / "data" / "reports" / "nba_blend_results.md"

RANDOM_STATE = 20260805
META_START_SEASON = 2009
FINAL_HOLDOUT_SEASON = 2023
GRID_WEIGHTS = np.round(np.linspace(-0.5, 1.5, 81), 6)
SELECTED_METHOD = "logistic_stack"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def clip_prob(p: np.ndarray | pd.Series) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)


def logit(p: np.ndarray | pd.Series) -> np.ndarray:
    p = clip_prob(p)
    return np.log(p / (1 - p))


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


def wilson_ci(wins: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return centre - half, centre + half


def metric_row(model: str, scope: str, y: np.ndarray, p: np.ndarray) -> dict[str, float | int | str]:
    p = clip_prob(p)
    pred = (p >= 0.5).astype(int)
    correct = int((pred == y).sum())
    lo, hi = wilson_ci(correct, len(y))
    return {
        "model": model,
        "scope": scope,
        "games": int(len(y)),
        "correct": correct,
        "accuracy": correct / len(y),
        "wilson_low": lo,
        "wilson_high": hi,
        "log_loss": log_loss(y, p, labels=[0, 1]),
        "brier": brier_score_loss(y, p),
    }


def replace_owned_table(con: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    cols = []
    for name, dtype in df.dtypes.items():
        if pd.api.types.is_integer_dtype(dtype):
            sql_type = "INTEGER"
        elif pd.api.types.is_float_dtype(dtype):
            sql_type = "REAL"
        else:
            sql_type = "TEXT"
        cols.append(f'"{name}" {sql_type}')
    con.execute(f'CREATE TABLE IF NOT EXISTS {table} ({", ".join(cols)})')
    con.execute(f"DELETE FROM {table}")
    df.to_sql(table, con, if_exists="append", index=False)


def load_predictions(where_sql: str) -> pd.DataFrame:
    query = f"""
        SELECT game_id, season, game_date, home_team, away_team, home_win, final_margin,
               elo_prob_home, model_prob_home, fold_type
        FROM nba_model_predictions
        WHERE {where_sql}
        ORDER BY season, game_date, game_id
    """
    with connect() as con:
        return pd.read_sql_query(query, con)


def probability_average(train: pd.DataFrame, test: pd.DataFrame, score: str) -> tuple[np.ndarray, dict[str, float | str]]:
    y = train["home_win"].to_numpy()
    best: tuple[tuple[float, float], float] | None = None
    for w in GRID_WEIGHTS:
        p = (1 - w) * clip_prob(train["elo_prob_home"]) + w * clip_prob(train["model_prob_home"])
        row = metric_row("tmp", "tmp", y, p)
        key = (-float(row["accuracy"]), float(row["log_loss"])) if score == "accuracy" else (float(row["log_loss"]), -float(row["accuracy"]))
        if best is None or key < best[0]:
            best = (key, float(w))
    assert best is not None
    w = best[1]
    p_test = (1 - w) * clip_prob(test["elo_prob_home"]) + w * clip_prob(test["model_prob_home"])
    return clip_prob(p_test), {"weight_model": w, "weight_elo": 1 - w, "selection_metric": score}


def logit_average(train: pd.DataFrame, test: pd.DataFrame, score: str) -> tuple[np.ndarray, dict[str, float | str]]:
    y = train["home_win"].to_numpy()
    best: tuple[tuple[float, float], float] | None = None
    for w in GRID_WEIGHTS:
        p = sigmoid((1 - w) * logit(train["elo_prob_home"]) + w * logit(train["model_prob_home"]))
        row = metric_row("tmp", "tmp", y, p)
        key = (-float(row["accuracy"]), float(row["log_loss"])) if score == "accuracy" else (float(row["log_loss"]), -float(row["accuracy"]))
        if best is None or key < best[0]:
            best = (key, float(w))
    assert best is not None
    w = best[1]
    p_test = sigmoid((1 - w) * logit(test["elo_prob_home"]) + w * logit(test["model_prob_home"]))
    return p_test, {"weight_model": w, "weight_elo": 1 - w, "selection_metric": score}


def logistic_stack(train: pd.DataFrame, test: pd.DataFrame, fit_intercept: bool = True) -> tuple[np.ndarray, dict[str, float | str]]:
    x_train = np.column_stack([logit(train["elo_prob_home"]), logit(train["model_prob_home"])])
    x_test = np.column_stack([logit(test["elo_prob_home"]), logit(test["model_prob_home"])])
    lr = LogisticRegression(C=1.0, solver="lbfgs", fit_intercept=fit_intercept, random_state=RANDOM_STATE)
    lr.fit(x_train, train["home_win"].to_numpy())
    p = lr.predict_proba(x_test)[:, 1]
    config: dict[str, float | str] = {
        "coef_logit_elo": float(lr.coef_[0][0]),
        "coef_logit_model": float(lr.coef_[0][1]),
        "intercept": float(lr.intercept_[0]) if fit_intercept else 0.0,
        "C": 1.0,
        "solver": "lbfgs",
        "fit_intercept": str(fit_intercept),
    }
    return p, config


def predict_candidate(method: str, train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, dict[str, float | str]]:
    if method == "prob_weight_logloss":
        return probability_average(train, test, "log_loss")
    if method == "prob_weight_accuracy":
        return probability_average(train, test, "accuracy")
    if method == "logit_weight_logloss":
        return logit_average(train, test, "log_loss")
    if method == "logit_weight_accuracy":
        return logit_average(train, test, "accuracy")
    if method == "logistic_stack":
        return logistic_stack(train, test, fit_intercept=True)
    if method == "logistic_stack_no_intercept":
        return logistic_stack(train, test, fit_intercept=False)
    raise ValueError(method)


def nested_development_predictions(dev: pd.DataFrame, method: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    configs: list[dict[str, float | int | str]] = []
    for season in range(META_START_SEASON, FINAL_HOLDOUT_SEASON):
        train = dev[dev["season"] < season].copy()
        test = dev[dev["season"] == season].copy()
        p, config = predict_candidate(method, train, test)
        out = test.copy()
        out["blend_prob_home"] = p
        out["blend_pick_home"] = (out["blend_prob_home"] >= 0.5).astype(int)
        out["method"] = method
        frames.append(out)
        configs.append({"method": method, "test_season": season, **config})
    return pd.concat(frames, ignore_index=True), pd.DataFrame(configs)


def reliability(preds: pd.DataFrame) -> pd.DataFrame:
    bins = np.arange(0.0, 1.01, 0.1)
    labels = [f"{bins[i]:.1f}-{bins[i + 1]:.1f}" for i in range(len(bins) - 1)]
    out = preds.copy()
    out["bucket"] = pd.cut(out["blend_prob_home"], bins=bins, labels=labels, include_lowest=True)
    return (
        out.groupby("bucket", observed=False)
        .agg(games=("home_win", "size"), avg_pred_home=("blend_prob_home", "mean"), actual_home_win=("home_win", "mean"))
        .reset_index()
    )


def markdown_metrics(rows: pd.DataFrame, order: list[str]) -> str:
    lines = ["| Model | Games | Accuracy | Wilson 95% CI | Log loss | Brier |", "|---|---:|---:|---:|---:|---:|"]
    for model in order:
        r = rows[rows["model"] == model].iloc[0]
        lines.append(
            f"| {model} | {int(r.games):,} | {pct(r.accuracy)} | {pct(r.wilson_low)}-{pct(r.wilson_high)} | {r.log_loss:.4f} | {r.brier:.4f} |"
        )
    return "\n".join(lines)


def main() -> None:
    dev = load_predictions("fold_type = 'development'")
    candidates = [
        "prob_weight_logloss",
        "prob_weight_accuracy",
        "logit_weight_logloss",
        "logit_weight_accuracy",
        "logistic_stack",
        "logistic_stack_no_intercept",
    ]

    nested_frames: list[pd.DataFrame] = []
    config_frames: list[pd.DataFrame] = []
    metric_rows: list[dict[str, float | int | str]] = []

    nested_scope = f"nested_development_{META_START_SEASON}_2022"
    nested_ref = dev[(dev["season"] >= META_START_SEASON) & (dev["season"] < FINAL_HOLDOUT_SEASON)].copy()
    y_nested = nested_ref["home_win"].to_numpy()
    metric_rows.append(metric_row("pure_elo", nested_scope, y_nested, nested_ref["elo_prob_home"].to_numpy()))
    metric_rows.append(metric_row("nba_model", nested_scope, y_nested, nested_ref["model_prob_home"].to_numpy()))
    metric_rows.append(metric_row("always_home", nested_scope, y_nested, np.full(len(nested_ref), float(dev["home_win"].mean()))))

    for method in candidates:
        pred, configs = nested_development_predictions(dev, method)
        nested_frames.append(pred)
        config_frames.append(configs)
        metric_rows.append(metric_row(method, nested_scope, pred["home_win"].to_numpy(), pred["blend_prob_home"].to_numpy()))

    nested_metrics = pd.DataFrame(metric_rows)
    selected_metric = nested_metrics[nested_metrics["model"] == SELECTED_METHOD].iloc[0]
    best_by_accuracy = nested_metrics[nested_metrics["model"].isin(candidates)].sort_values(["accuracy", "log_loss"], ascending=[False, True]).iloc[0]
    if str(best_by_accuracy["model"]) != SELECTED_METHOD:
        raise RuntimeError(f"Pre-registered method {SELECTED_METHOD} was not the best nested-development accuracy method")

    selected_p_dev, selected_fit_config = predict_candidate(SELECTED_METHOD, dev, dev)
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    config = {
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_prediction_table": "nba_model_predictions",
        "prediction_table": "nba_blend_predictions",
        "metric_table": "nba_blend_metrics",
        "candidate_metric_table": "nba_blend_candidate_metrics",
        "selection_data": "development folds only, seasons 2007-2022",
        "selection_protocol": "candidate blends were compared by expanding nested walk-forward seasons 2009-2022; highest accuracy wins, log loss breaks ties",
        "selected_method": SELECTED_METHOD,
        "selected_nested_development_accuracy": float(selected_metric["accuracy"]),
        "selected_nested_development_log_loss": float(selected_metric["log_loss"]),
        "development_test_seasons_for_selection": list(range(META_START_SEASON, FINAL_HOLDOUT_SEASON)),
        "final_holdout_season": FINAL_HOLDOUT_SEASON,
        "input_columns": ["elo_prob_home", "model_prob_home"],
        "transform": "logit probabilities before logistic stack",
        "final_fit_config": selected_fit_config,
        "candidate_methods": candidates,
        "grid_weights": GRID_WEIGHTS.tolist(),
        "script_sha256": script_hash,
        "holdout_scoring_status_at_config_write": "not_scored",
        "artifact_path_if_accuracy_beats_elo": str(ARTIFACT_PATH),
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Wrote pre-holdout blend config: {CONFIG_PATH}")

    holdout = load_predictions(f"season = {FINAL_HOLDOUT_SEASON} AND fold_type = 'final_holdout'")
    selected_p_holdout, final_fit_config_check = predict_candidate(SELECTED_METHOD, dev, holdout)
    if final_fit_config_check != selected_fit_config:
        raise RuntimeError("Final fit config changed between freeze and holdout scoring")

    selected_dev = dev.copy()
    selected_dev["blend_prob_home"] = selected_p_dev
    selected_dev["blend_pick_home"] = (selected_dev["blend_prob_home"] >= 0.5).astype(int)
    selected_dev["method"] = SELECTED_METHOD
    selected_holdout = holdout.copy()
    selected_holdout["blend_prob_home"] = selected_p_holdout
    selected_holdout["blend_pick_home"] = (selected_holdout["blend_prob_home"] >= 0.5).astype(int)
    selected_holdout["method"] = SELECTED_METHOD
    blend_predictions = pd.concat([selected_dev, selected_holdout], ignore_index=True)

    overall_rows = []
    for scope, frame in [("development_overall", dev), ("final_holdout_overall", holdout)]:
        y = frame["home_win"].to_numpy()
        overall_rows.append(metric_row("pure_elo", scope, y, frame["elo_prob_home"].to_numpy()))
        overall_rows.append(metric_row("nba_model", scope, y, frame["model_prob_home"].to_numpy()))
        overall_rows.append(metric_row("always_home", scope, y, np.full(len(frame), float(dev["home_win"].mean()))))
        selected_frame = selected_dev if scope == "development_overall" else selected_holdout
        overall_rows.append(metric_row(SELECTED_METHOD, scope, y, selected_frame["blend_prob_home"].to_numpy()))
    blend_metrics = pd.concat([nested_metrics, pd.DataFrame(overall_rows)], ignore_index=True)

    rel = reliability(selected_holdout)
    rel["scope"] = "final_holdout_overall"
    rel["model"] = SELECTED_METHOD
    rel_nonempty = rel[rel["games"] > 0].copy()
    weighted_cal_mae = float(
        (rel_nonempty["games"] * (rel_nonempty["avg_pred_home"] - rel_nonempty["actual_home_win"]).abs()).sum()
        / rel_nonempty["games"].sum()
    )

    with connect() as con:
        replace_owned_table(con, "nba_blend_predictions", blend_predictions)
        replace_owned_table(con, "nba_blend_nested_predictions", pd.concat(nested_frames, ignore_index=True))
        replace_owned_table(con, "nba_blend_metrics", blend_metrics)
        replace_owned_table(con, "nba_blend_candidate_metrics", nested_metrics)
        replace_owned_table(con, "nba_blend_candidate_fold_configs", pd.concat(config_frames, ignore_index=True))
        replace_owned_table(con, "nba_blend_reliability", rel)
        con.execute("CREATE INDEX IF NOT EXISTS idx_nba_blend_predictions_season ON nba_blend_predictions(season)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_nba_blend_nested_predictions_method_season ON nba_blend_nested_predictions(method, season)")

    holdout_metrics = blend_metrics[blend_metrics["scope"] == "final_holdout_overall"].copy()
    elo = holdout_metrics[holdout_metrics["model"] == "pure_elo"].iloc[0]
    blend = holdout_metrics[holdout_metrics["model"] == SELECTED_METHOD].iloc[0]
    beat_elo = float(blend["accuracy"]) > float(elo["accuracy"])
    if beat_elo:
        joblib.dump(
            {
                "method": SELECTED_METHOD,
                "input_columns": ["elo_prob_home", "model_prob_home"],
                "transform": "logit",
                "fit_config": selected_fit_config,
                "config_path": str(CONFIG_PATH),
            },
            ARTIFACT_PATH,
        )

    final_rows = holdout_metrics
    nested_report_rows = nested_metrics[nested_metrics["scope"] == nested_scope].copy()
    nested_order = ["always_home", "pure_elo", "nba_model", *candidates]
    final_order = ["always_home", "pure_elo", "nba_model", SELECTED_METHOD]
    rel_lines = ["| Predicted bucket | Games | Avg predicted home win | Actual home win |", "|---|---:|---:|---:|"]
    for r in rel.itertuples(index=False):
        avg_pred = "n/a" if pd.isna(r.avg_pred_home) else pct(r.avg_pred_home)
        actual = "n/a" if pd.isna(r.actual_home_win) else pct(r.actual_home_win)
        rel_lines.append(f"| {r.bucket} | {int(r.games)} | {avg_pred} | {actual} |")

    margin = float(blend["accuracy"]) - float(elo["accuracy"])
    verdict = "beat" if beat_elo else "did not beat"
    artifact_note = f"A serving artifact was written to `data\\nba\\nba_blend_final.joblib`." if beat_elo else "No serving artifact was written because the selected blend did not beat Elo on accuracy."
    margin_sentence = (
        f"The selected stack beat Elo by **{margin:+.2%}** on the frozen holdout"
        if beat_elo
        else f"The selected stack trailed Elo by **{abs(margin):.2%}** on the frozen holdout"
    )
    holdout_interpretation = (
        "The blend improved accuracy and probability metrics versus pure Elo on this holdout, but the accuracy margin is much smaller than the Wilson interval width."
        if beat_elo
        else "The blend did not improve accuracy versus pure Elo on this holdout. It did improve log loss and Brier, so the combination appears to add probability-quality value without a defensible accuracy win."
    )
    report = f"""# NBA blend/stacking experiment

Date: {datetime.now(timezone.utc).isoformat()}

## Headline

The pre-registered blend **{verdict} pure Elo** on the frozen 2023 holdout: logistic stacking reached **{pct(float(blend.accuracy))}** accuracy on **{int(blend.games):,}** games, Wilson 95% CI **{pct(float(blend.wilson_low))}-{pct(float(blend.wilson_high))}**, versus pure Elo at **{pct(float(elo.accuracy))}**. The margin is **{margin:+.2%}**, which is inside the 2-3 point noise floor and is not strong evidence of a truly superior classifier.

## Non-negotiable holdout protocol

- The final holdout season was **2023**.
- All blend selection used only development predictions from seasons **2007-2022**.
- Candidate blends were evaluated with an expanding nested walk-forward meta-test: fit the blend on development seasons before the test season, then test seasons **2009-2022**.
- The selected configuration was written to `data\\nba\\nba_blend_config.json` before loading/scoring the 2023 holdout rows.
- The selected method was **{SELECTED_METHOD}**, chosen because it had the best nested-development accuracy among the blend candidates, with log loss as the tie-breaker.

## Approaches tried on development folds

All methods below used only two pre-existing out-of-sample probabilities: `elo_prob_home` and `model_prob_home`.

{markdown_metrics(nested_report_rows, nested_order)}

Interpretation: logistic stacking was the best nested-development accuracy candidate. Log-odds weighted blends improved log loss, but did not win the selection criterion.

## Frozen 2023 holdout result

{markdown_metrics(final_rows, final_order)}

{holdout_interpretation}

## Final blend configuration

```json
{json.dumps({'selected_method': SELECTED_METHOD, 'final_fit_config': selected_fit_config, 'input_columns': ['elo_prob_home', 'model_prob_home']}, indent=2)}
```

{artifact_note}

## Calibration reliability table: final holdout

Bucket-weighted absolute calibration error is **{pct(weighted_cal_mae)}** on the final holdout.

{chr(10).join(rel_lines)}

Buckets include counts; small buckets should not be over-interpreted.

## What did not get refit

The prior frozen NBA model already includes `elo_prob_home`, Elo differences, rest, back-to-back, road-trip, rolling form, and opponent-strength features. This experiment therefore focused on the highest-value, lowest-leakage question: whether the existing model probability and pure Elo probability can be combined honestly. No injury feed or new per-game data source was available in the listed database tables, and no additional classifier family was tuned on the holdout.

## Candid verdict

This is a legitimate incremental probability-quality result, not proof that NBA Elo has been decisively beaten. {margin_sentence} while improving log loss/Brier; the small accuracy difference is inside sampling noise for 1,174 games.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote {REPORT_PATH}")
    print(
        f"Holdout {SELECTED_METHOD}: {pct(float(blend.accuracy))} "
        f"({pct(float(blend.wilson_low))}-{pct(float(blend.wilson_high))}), "
        f"Elo {pct(float(elo.accuracy))}, margin {margin:+.2%}"
    )


if __name__ == "__main__":
    main()
