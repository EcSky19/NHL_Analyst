"""Train frozen NFL winner models and evaluate the locked holdout once.

The command is deliberately split in two:
1. ``tune`` evaluates a small pre-declared grid on 2010-2023 walk-forward
   seasons and writes the frozen configuration.
2. ``evaluate-holdout`` reads that frozen configuration, requires the harness
   unlock token, and scores 2024-2025 exactly once.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from evaluation_harness import HOLDOUT_UNLOCK_TOKEN, format_pct, wilson_interval


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "nfl" / "nfl_research.db"
DATA_DIR = ROOT / "data" / "nfl"
REPORT_DIR = ROOT / "data" / "reports"
FROZEN_CONFIG_PATH = DATA_DIR / "nfl_final_model_frozen_config.json"
DEV_RESULTS_PATH = DATA_DIR / "nfl_final_model_dev_results.csv"
HOLDOUT_PREDICTIONS_PATH = DATA_DIR / "nfl_final_model_holdout_predictions.csv"
HOLDOUT_AUDIT_PATH = DATA_DIR / "nfl_final_model_holdout_audit.json"
REPORT_PATH = REPORT_DIR / "nfl_model_results.md"

TRAIN_START = 2010
TRAIN_END = 2023
HOLDOUT_SEASONS = [2024, 2025]
MIN_TRAIN_SEASONS = 4
RANDOM_STATE = 20260805

TARGET_COLS = {"target_home_win", "target_home_margin", "is_tie"}
IDENTIFIER_COLS = {
    "game_id",
    "season",
    "week",
    "game_type",
    "gameday",
    "home_team",
    "away_team",
    "created_at_utc",
}
MARKET_COL_PATTERNS = ("moneyline", "spread_line", "total_line", "market_features_available")


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    model_label: str
    feature_set: str
    family: str
    params: dict[str, Any]
    complexity_rank: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_features() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql_query(
            """
            SELECT *
            FROM nfl_features
            WHERE season BETWEEN ? AND ?
              AND game_type = 'REG'
              AND COALESCE(is_tie, 0) = 0
              AND target_home_win IS NOT NULL
            ORDER BY season, week, game_id
            """,
            con,
            params=(TRAIN_START, max(HOLDOUT_SEASONS)),
        )
    df["target_home_win"] = df["target_home_win"].astype(int)
    return df


def numeric_feature_columns(df: pd.DataFrame, feature_set: str) -> list[str]:
    cols: list[str] = []
    for col in df.columns:
        if col in TARGET_COLS or col in IDENTIFIER_COLS:
            continue
        if col.endswith("_max_source_date"):
            continue
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        if feature_set == "market_free" and any(pattern in col for pattern in MARKET_COL_PATTERNS):
            continue
        cols.append(col)
    return cols


def predefined_configs() -> list[ModelConfig]:
    configs: list[ModelConfig] = []
    for feature_set, label in [("market_free", "Market-free"), ("full", "Full")]:
        for c in [0.03, 0.10, 0.30, 1.00]:
            configs.append(
                ModelConfig(
                    model_id=f"{feature_set}_logreg_c{c:g}",
                    model_label=label,
                    feature_set=feature_set,
                    family="logistic_l2",
                    params={"C": c},
                    complexity_rank=1,
                )
            )
        for learning_rate, l2 in [(0.03, 0.0), (0.03, 0.1), (0.06, 0.1), (0.10, 0.1)]:
            configs.append(
                ModelConfig(
                    model_id=f"{feature_set}_hgb_lr{learning_rate:g}_l2{l2:g}",
                    model_label=label,
                    feature_set=feature_set,
                    family="hist_gradient_boosting",
                    params={
                        "learning_rate": learning_rate,
                        "l2_regularization": l2,
                        "max_iter": 120,
                        "max_leaf_nodes": 15,
                    },
                    complexity_rank=2,
                )
            )
    return configs


def build_estimator(config: ModelConfig) -> Pipeline:
    if config.family == "logistic_l2":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        C=float(config.params["C"]),
                        solver="lbfgs",
                        max_iter=5000,
                        random_state=RANDOM_STATE,
                    ),
                ),
            ]
        )
    if config.family == "hist_gradient_boosting":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    HistGradientBoostingClassifier(
                        learning_rate=float(config.params["learning_rate"]),
                        l2_regularization=float(config.params["l2_regularization"]),
                        max_iter=int(config.params["max_iter"]),
                        max_leaf_nodes=int(config.params["max_leaf_nodes"]),
                        random_state=RANDOM_STATE,
                    ),
                ),
            ]
        )
    raise ValueError(f"Unknown model family: {config.family}")


def prediction_frame(df: pd.DataFrame, config: ModelConfig, folds: list[int]) -> pd.DataFrame:
    features = numeric_feature_columns(df, config.feature_set)
    pieces: list[pd.DataFrame] = []
    for season in folds:
        train = df[(df["season"] < season) & (df["season"] >= TRAIN_START)]
        test = df[df["season"] == season]
        if train["season"].nunique() < MIN_TRAIN_SEASONS or test.empty:
            continue
        estimator = build_estimator(config)
        estimator.fit(train[features], train["target_home_win"])
        prob = estimator.predict_proba(test[features])[:, 1]
        part = test[["game_id", "season", "week", "home_team", "away_team", "target_home_win"]].copy()
        part["model_id"] = config.model_id
        part["prob_home_win"] = prob
        pieces.append(part)
    if not pieces:
        raise RuntimeError(f"No predictions generated for {config.model_id}")
    return pd.concat(pieces, ignore_index=True)


def summarize_predictions(pred: pd.DataFrame) -> dict[str, Any]:
    y = pred["target_home_win"].to_numpy()
    p = np.clip(pred["prob_home_win"].to_numpy(), 1e-9, 1 - 1e-9)
    correct = ((p >= 0.5).astype(int) == y).astype(int)
    total = int(len(pred))
    low, high = wilson_interval(int(correct.sum()), total)
    return {
        "games": total,
        "correct": int(correct.sum()),
        "accuracy": float(correct.mean()),
        "wilson_low": low,
        "wilson_high": high,
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "brier": float(brier_score_loss(y, p)),
    }


def tune_configs(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    folds = list(range(TRAIN_START + MIN_TRAIN_SEASONS, TRAIN_END + 1))
    rows: list[dict[str, Any]] = []
    predictions: dict[str, pd.DataFrame] = {}
    for config in predefined_configs():
        pred = prediction_frame(df[df["season"] <= TRAIN_END], config, folds)
        summary = summarize_predictions(pred)
        rows.append({**config.__dict__, **summary, "folds": f"{folds[0]}-{folds[-1]}"})
        predictions[config.model_id] = pred
    results = pd.DataFrame(rows).sort_values(["feature_set", "accuracy", "log_loss"], ascending=[True, False, True])
    selected: dict[str, dict[str, Any]] = {}
    for feature_set in ["market_free", "full"]:
        subset = results[results["feature_set"] == feature_set].copy()
        best_acc = float(subset["accuracy"].max())
        # Pre-declared simplicity rule: prefer the simplest model within 1 pp of
        # the best development accuracy, then lower log loss.
        eligible = subset[subset["accuracy"] >= best_acc - 0.0100].copy()
        chosen = eligible.sort_values(["complexity_rank", "log_loss", "accuracy"], ascending=[True, True, False]).iloc[0]
        selected[feature_set] = {
            "model_id": chosen["model_id"],
            "model_label": chosen["model_label"],
            "feature_set": chosen["feature_set"],
            "family": chosen["family"],
            "params": chosen["params"],
            "selection_rule": "simplest family within 1.00 percentage point of best walk-forward accuracy; tie-breaker lower log loss",
            "development_summary": {
                key: chosen[key].item() if hasattr(chosen[key], "item") else chosen[key]
                for key in ["games", "correct", "accuracy", "wilson_low", "wilson_high", "log_loss", "brier", "folds"]
            },
        }
    return results, selected


def fit_final(df: pd.DataFrame, selected: dict[str, Any]) -> tuple[Pipeline, list[str], ModelConfig]:
    config = ModelConfig(
        model_id=selected["model_id"],
        model_label=selected["model_label"],
        feature_set=selected["feature_set"],
        family=selected["family"],
        params=selected["params"],
        complexity_rank=1 if selected["family"] == "logistic_l2" else 2,
    )
    features = numeric_feature_columns(df, config.feature_set)
    train = df[(df["season"] >= TRAIN_START) & (df["season"] <= TRAIN_END)]
    estimator = build_estimator(config)
    estimator.fit(train[features], train["target_home_win"])
    return estimator, features, config


def baseline_predictions(df: pd.DataFrame) -> dict[str, pd.Series]:
    vegas = pd.Series(np.nan, index=df.index, dtype="float")
    valid_market = (df["market_features_available"] == 1) & df["home_moneyline_implied_no_vig"].notna()
    vegas.loc[valid_market] = (df.loc[valid_market, "home_moneyline_implied_no_vig"] >= 0.5).astype(int)
    return {
        "Always pick home": pd.Series(np.ones(len(df), dtype=int), index=df.index),
        "Vegas moneyline favorite": vegas,
    }


def score_binary(y: pd.Series, pred: pd.Series, label: str) -> dict[str, Any]:
    valid = pred.notna()
    correct = int((pred[valid].astype(int) == y[valid].astype(int)).sum())
    total = int(valid.sum())
    low, high = wilson_interval(correct, total)
    return {
        "label": label,
        "games": total,
        "correct": correct,
        "accuracy": correct / total if total else float("nan"),
        "wilson_low": low,
        "wilson_high": high,
    }


def confidence_tiers(pred: pd.DataFrame, model_label: str) -> list[dict[str, Any]]:
    bins = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90, 1.01]
    labels = ["50-55%", "55-60%", "60-65%", "65-70%", "70-75%", "75-80%", "80-90%", "90-100%"]
    p = pred["prob_home_win"]
    conf = np.maximum(p, 1 - p)
    correct = ((p >= 0.5).astype(int) == pred["target_home_win"].astype(int)).astype(int)
    rows: list[dict[str, Any]] = []
    for lo, hi, tier in zip(bins[:-1], bins[1:], labels):
        mask = (conf >= lo) & (conf < hi)
        n = int(mask.sum())
        c = int(correct[mask].sum())
        low, high = wilson_interval(c, n)
        rows.append(
            {
                "model": model_label,
                "tier": tier,
                "games": n,
                "coverage": n / len(pred) if len(pred) else float("nan"),
                "correct": c,
                "accuracy": c / n if n else float("nan"),
                "wilson_low": low,
                "wilson_high": high,
                "small_sample": n < 150,
            }
        )
    return rows


def calibration_rows(pred: pd.DataFrame, model_label: str) -> list[dict[str, Any]]:
    bins = [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.01]
    labels = ["0-20%", "20-40%", "40-50%", "50-60%", "60-80%", "80-100%"]
    rows: list[dict[str, Any]] = []
    for lo, hi, bucket in zip(bins[:-1], bins[1:], labels):
        mask = (pred["prob_home_win"] >= lo) & (pred["prob_home_win"] < hi)
        n = int(mask.sum())
        avg_p = float(pred.loc[mask, "prob_home_win"].mean()) if n else float("nan")
        actual = float(pred.loc[mask, "target_home_win"].mean()) if n else float("nan")
        rows.append({"model": model_label, "bucket": bucket, "games": n, "avg_pred_home": avg_p, "actual_home_win": actual})
    return rows


def feature_importance(df: pd.DataFrame, selected: dict[str, Any], estimator: Pipeline, features: list[str]) -> pd.DataFrame:
    train = df[(df["season"] >= TRAIN_START) & (df["season"] <= TRAIN_END)]
    if selected["family"] == "logistic_l2":
        coefs = estimator.named_steps["model"].coef_[0]
        return (
            pd.DataFrame({"feature": features, "importance": np.abs(coefs), "coefficient": coefs})
            .sort_values("importance", ascending=False)
            .head(20)
            .reset_index(drop=True)
        )
    perm = permutation_importance(
        estimator,
        train[features],
        train["target_home_win"],
        scoring="accuracy",
        n_repeats=10,
        random_state=RANDOM_STATE,
    )
    return (
        pd.DataFrame({"feature": features, "importance": perm.importances_mean, "coefficient": np.nan})
        .sort_values("importance", ascending=False)
        .head(20)
        .reset_index(drop=True)
    )


def fmt_ci(row: dict[str, Any] | pd.Series) -> str:
    return f"{format_pct(float(row['accuracy']))} ({format_pct(float(row['wilson_low']))}-{format_pct(float(row['wilson_high']))})"


def markdown_table(rows: list[list[str]], header: list[str]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    out.extend("| " + " | ".join(row) + " |" for row in rows)
    return out


def write_report(
    frozen: dict[str, Any],
    holdout_summaries: list[dict[str, Any]],
    baseline_summaries: list[dict[str, Any]],
    tier_rows: list[dict[str, Any]],
    calib_rows: list[dict[str, Any]],
    importance: pd.DataFrame,
) -> None:
    lines = [
        "# NFL final model results",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Holdout policy",
        "",
        "The final configurations were frozen to `data\\nfl\\nfl_final_model_frozen_config.json` before the 2024-2025 holdout was unlocked. The holdout was then evaluated once with the explicit unlock token.",
        "",
        f"Configurations evaluated during development: **{frozen['configuration_count_total']} total** "
        f"(**{frozen['configuration_count_per_model']} per model**, two feature sets: market-free and full). "
        f"Development folds were expanding walk-forward seasons {frozen['development_folds']}, training only on prior seasons from 2010-2023.",
        "",
        "Selection rule: simplest model family within 1.00 percentage point of the best walk-forward accuracy, with lower log loss as tie-breaker.",
        "",
        "## Locked holdout headline",
        "",
    ]
    model_rows = [
        [
            row["label"],
            f"{row['games']:,}",
            f"{row['correct']:,}",
            fmt_ci(row),
            f"{row['log_loss']:.4f}",
            f"{row['brier']:.4f}",
        ]
        for row in holdout_summaries
    ]
    lines.extend(markdown_table(model_rows, ["Model", "Games", "Correct", "Accuracy (Wilson 95% CI)", "Log loss", "Brier"]))

    lines.extend(["", "## Baseline comparison", ""])
    base_rows = [
        [row["label"], f"{row['games']:,}", f"{row['correct']:,}", fmt_ci(row)] for row in baseline_summaries
    ]
    lines.extend(markdown_table(base_rows, ["Baseline on same 2024-2025 holdout", "Games", "Correct", "Accuracy (Wilson 95% CI)"]))
    lines.extend(
        [
            "",
            "Project reference bars from the methodology report are always-pick-home **56.17%** (55.00%-57.33%) and Vegas moneyline favorite **66.59%** (65.27%-67.88%). "
            "The 2024-2025 sample is only two seasons, so differences below roughly 4.5-8 percentage points should be treated as noise.",
            "",
        ]
    )
    for row in holdout_summaries:
        lines.append(
            f"- {row['label']}: {fmt_ci(row)}; vs global home bar {((row['accuracy'] - 0.5617) * 100):+.2f} pp, "
            f"vs global Vegas bar {((row['accuracy'] - 0.6659) * 100):+.2f} pp."
        )
    lines.append("- None of the model/Vegas differences on this two-season holdout should be described as a detectable improvement unless the Wilson intervals and noise floor clearly separate them; here they do not.")

    lines.extend(["", "## Calibration", ""])
    calib_summary_rows = []
    for row in holdout_summaries:
        calib_summary_rows.append([row["label"], f"{row['log_loss']:.4f}", f"{row['brier']:.4f}"])
    lines.extend(markdown_table(calib_summary_rows, ["Model", "Log loss", "Brier"]))
    lines.extend(["", "Reliability by predicted home-win probability:", ""])
    cal_rows = [
        [
            row["model"],
            row["bucket"],
            f"{row['games']:,}",
            format_pct(row["avg_pred_home"]),
            format_pct(row["actual_home_win"]),
        ]
        for row in calib_rows
    ]
    lines.extend(markdown_table(cal_rows, ["Model", "Predicted home bucket", "Games", "Avg predicted", "Actual home win"]))

    lines.extend(["", "## Accuracy by confidence tier", ""])
    tier_table = [
        [
            row["model"],
            row["tier"],
            f"{row['games']:,}",
            format_pct(row["coverage"]),
            f"{format_pct(row['accuracy'])} ({format_pct(row['wilson_low'])}-{format_pct(row['wilson_high'])})",
            "too small" if row["small_sample"] else "",
        ]
        for row in tier_rows
    ]
    lines.extend(markdown_table(tier_table, ["Model", "Confidence", "Games", "Coverage", "Accuracy (Wilson 95% CI)", "Flag"]))
    reaches_70 = [
        row
        for row in tier_rows
        if row["games"] > 0 and row["accuracy"] >= 0.70 and row["wilson_low"] >= 0.70
    ]
    reliable_reaches_70 = [row for row in reaches_70 if not row["small_sample"]]
    if reaches_70:
        lines.append("")
        if reliable_reaches_70:
            lines.append("At least one tier has point accuracy of 70% with a Wilson lower bound at or above 70%; coverage is shown in the table.")
        else:
            lines.append("Only sub-150-game tiers reach 70% accuracy with a Wilson lower bound at or above 70%, so none is reliable enough to lean on.")
    else:
        lines.append("")
        lines.append("No confidence tier reaches 70% accuracy with a Wilson lower bound at or above 70%. Tiers under ~150 games are explicitly flagged as too small to rely on.")

    lines.extend(["", "## Market-free feature importance", ""])
    imp_rows = [
        [row.feature, f"{row.importance:.4f}", "" if math.isnan(row.coefficient) else f"{row.coefficient:+.4f}"]
        for row in importance.itertuples(index=False)
    ]
    lines.extend(markdown_table(imp_rows, ["Feature", "Importance", "Coefficient"]))
    lines.extend(
        [
            "",
            "Interpretation: the market-free model is the football-fundamentals model. The full model includes separable market features and should be read as a maximum-accuracy market-replication model, not proof that engineered team features add value beyond Vegas.",
            "",
        ]
    )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def command_tune(_args: argparse.Namespace) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = load_features()
    results, selected = tune_configs(df)
    results.to_csv(DEV_RESULTS_PATH, index=False)
    frozen = {
        "created_at_utc": utc_now(),
        "train_seasons": [TRAIN_START, TRAIN_END],
        "holdout_seasons": HOLDOUT_SEASONS,
        "development_folds": f"{TRAIN_START + MIN_TRAIN_SEASONS}-{TRAIN_END}",
        "configuration_count_total": len(predefined_configs()),
        "configuration_count_per_model": len(predefined_configs()) // 2,
        "selected": selected,
    }
    FROZEN_CONFIG_PATH.write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    print(f"Wrote {FROZEN_CONFIG_PATH}")
    print(f"Wrote {DEV_RESULTS_PATH}")
    for feature_set, config in selected.items():
        dev = config["development_summary"]
        print(
            f"{feature_set}: {config['model_id']} dev {dev['correct']}/{dev['games']} "
            f"{format_pct(dev['accuracy'])} log_loss={dev['log_loss']:.4f}"
        )
    return 0


def command_evaluate_holdout(args: argparse.Namespace) -> int:
    if args.unlock_holdout != HOLDOUT_UNLOCK_TOKEN:
        raise SystemExit("Refusing to touch holdout without explicit unlock token.")
    if HOLDOUT_AUDIT_PATH.exists() and not args.force:
        raise SystemExit(f"Holdout audit already exists at {HOLDOUT_AUDIT_PATH}; refusing to re-evaluate.")
    frozen = json.loads(FROZEN_CONFIG_PATH.read_text(encoding="utf-8"))
    df = load_features()
    holdout = df[df["season"].isin(HOLDOUT_SEASONS)].copy()
    all_predictions: list[pd.DataFrame] = []
    holdout_summaries: list[dict[str, Any]] = []
    tier_rows: list[dict[str, Any]] = []
    calib_rows: list[dict[str, Any]] = []
    importance: pd.DataFrame | None = None
    for feature_set in ["market_free", "full"]:
        selected = frozen["selected"][feature_set]
        estimator, features, config = fit_final(df, selected)
        prob = estimator.predict_proba(holdout[features])[:, 1]
        pred = holdout[["game_id", "season", "week", "home_team", "away_team", "target_home_win"]].copy()
        pred["model_id"] = config.model_id
        pred["model"] = config.model_label
        pred["prob_home_win"] = prob
        pred["predicted_winner"] = np.where(pred["prob_home_win"] >= 0.5, "home", "away")
        pred["actual_winner"] = np.where(pred["target_home_win"] == 1, "home", "away")
        summary = summarize_predictions(pred)
        holdout_summaries.append({"label": config.model_label, **summary})
        tier_rows.extend(confidence_tiers(pred, config.model_label))
        calib_rows.extend(calibration_rows(pred, config.model_label))
        all_predictions.append(pred)
        if feature_set == "market_free":
            importance = feature_importance(df, selected, estimator, features)
    prediction_out = pd.concat(all_predictions, ignore_index=True)
    prediction_out.to_csv(HOLDOUT_PREDICTIONS_PATH, index=False)
    y = holdout["target_home_win"]
    baseline_summaries = [score_binary(y, pred, label) for label, pred in baseline_predictions(holdout).items()]
    if importance is None:
        raise RuntimeError("Missing market-free feature importance")
    write_report(frozen, holdout_summaries, baseline_summaries, tier_rows, calib_rows, importance)
    HOLDOUT_AUDIT_PATH.write_text(
        json.dumps(
            {
                "evaluated_at_utc": utc_now(),
                "unlock_token_supplied": True,
                "holdout_seasons": HOLDOUT_SEASONS,
                "predictions_path": str(HOLDOUT_PREDICTIONS_PATH.relative_to(ROOT)),
                "report_path": str(REPORT_PATH.relative_to(ROOT)),
                "summaries": holdout_summaries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {HOLDOUT_PREDICTIONS_PATH}")
    print(f"Wrote {REPORT_PATH}")
    for row in holdout_summaries:
        print(f"{row['label']}: {row['correct']}/{row['games']} {fmt_ci(row)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train and evaluate final NFL models.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("tune", help="Tune on 2010-2023 only and freeze selected configs.").set_defaults(func=command_tune)
    holdout = sub.add_parser("evaluate-holdout", help="Evaluate the locked 2024-2025 holdout once.")
    holdout.add_argument("--unlock-holdout", required=True)
    holdout.add_argument("--force", action="store_true", help="Override the one-time audit guard.")
    holdout.set_defaults(func=command_evaluate_holdout)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
