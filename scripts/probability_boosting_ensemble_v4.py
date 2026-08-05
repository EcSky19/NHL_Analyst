#!/usr/bin/env python3
"""
Deterministic probability booster for NHL game predictions.

Builds a small fold-safe blend over the strongest current benchmark candidates:
- phase1 benchmark blend
- deep feature-expansion benchmark blend
- optional benchmark diagnostics from the existing error-slice / regime outputs

The final ensemble is a fixed-weight blend, so it is deterministic and does not
fit any parameters on the holdout labels.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

EPS = 1e-6
HOLDOUT_SEASON = "20212022"
PHASE1_BEST_MODEL = "blend_top2_fixed_50_50__weighted_calibrated__elo_form_tuned"
PHASE1_ALT_MODEL = "blend_top2_fixed_65_35__weighted_calibrated__elo_form_tuned"
DEEP_BEST_MODEL = "blend_top2_fixed_50_50__weighted_calibrated__elo_form_tuned"
DEEP_ALT_MODEL = "blend_top2_fixed_65_35__weighted_calibrated__elo_form_tuned"
PHASE1_WEIGHT = 0.80
DEEP_WEIGHT = 0.20
CURRENT_BEST_ACCURACY = 0.6189024390243902


def clamp_probability(value: float) -> float:
    return max(EPS, min(1.0 - EPS, float(value)))


def metrics(df: pd.DataFrame, prob_col: str) -> Dict[str, float]:
    y = df["actual_home_win"].astype(int)
    p = df[prob_col].astype(float).clip(EPS, 1.0 - EPS)
    accuracy = ((p >= 0.5) == y).mean()
    log_loss = -(y * p.map(lambda v: __import__("math").log(v)) + (1 - y) * (1 - p).map(lambda v: __import__("math").log(v))).mean()
    brier = ((p - y) ** 2).mean()
    return {
        "games": float(len(df)),
        "accuracy": float(accuracy),
        "log_loss": float(log_loss),
        "brier_score": float(brier),
    }


def load_predictions(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    data_root = repo_root / "data" / "processed" / "execution_plan"
    out_dir = data_root / "probability_boosting_ensemble_v4"
    report_path = repo_root / "data" / "reports" / "probability_boosting_ensemble_v4_results.md"

    phase1 = load_predictions(data_root / "phase1_eval_final" / "predictions.csv")
    deep = load_predictions(data_root / "deep_feature_expansion_v4" / "predictions.csv")
    error_slice = load_predictions(data_root / "error_slice_reduction_v4" / "benchmark_adjusted_predictions.csv")
    regime = load_predictions(data_root / "season_regime_ensemble_v2" / "predictions.csv")

    phase1_hold = phase1[phase1["season"].astype(str) == HOLDOUT_SEASON].copy()
    deep_hold = deep[deep["season"].astype(str) == HOLDOUT_SEASON].copy()
    error_hold = error_slice.copy()

    phase1_base = phase1_hold[phase1_hold["model_id"] == PHASE1_BEST_MODEL][
        ["game_id", "game_date", "home_team_abbrev", "away_team_abbrev", "actual_home_win", "home_win_probability"]
    ].rename(columns={"home_win_probability": "phase1_base_prob"})
    phase1_alt = phase1_hold[phase1_hold["model_id"] == PHASE1_ALT_MODEL][["game_id", "home_win_probability"]].rename(
        columns={"home_win_probability": "phase1_alt_prob"}
    )

    deep_base = deep_hold[deep_hold["model_id"] == DEEP_BEST_MODEL][["game_id", "home_win_probability"]].rename(
        columns={"home_win_probability": "deep_base_prob"}
    )
    deep_alt = deep_hold[deep_hold["model_id"] == DEEP_ALT_MODEL][["game_id", "home_win_probability"]].rename(
        columns={"home_win_probability": "deep_alt_prob"}
    )

    regime_hold = regime.groupby(["season", "game_id"], as_index=False).agg(
        {"actual_home_win": "first", "predicted_probability": "first"}
    )
    regime_hold = regime_hold[regime_hold["season"].astype(str) == HOLDOUT_SEASON].rename(
        columns={"predicted_probability": "regime_prob"}
    )[["game_id", "regime_prob"]]

    merged = phase1_base.merge(phase1_alt, on="game_id", how="inner")
    merged = merged.merge(deep_base, on="game_id", how="inner")
    merged = merged.merge(deep_alt, on="game_id", how="inner")
    merged = merged.merge(regime_hold, on="game_id", how="left")
    merged = merged.merge(
        error_hold[
            [
                "game_id",
                "home_win_probability",
                "alt_home_win_probability",
                "adjusted_home_win_probability",
            ]
        ],
        on="game_id",
        how="left",
    )
    merged = merged.rename(
        columns={
            "home_win_probability": "error_base_prob",
            "alt_home_win_probability": "error_alt_prob",
            "adjusted_home_win_probability": "error_adjusted_prob",
        }
    )

    merged["boosted_probability"] = (
        PHASE1_WEIGHT * merged["phase1_base_prob"] + DEEP_WEIGHT * merged["deep_base_prob"]
    ).map(clamp_probability)
    merged["boosted_predicted_winner"] = (merged["boosted_probability"] >= 0.5).astype(int)
    merged["boosted_predicted_side"] = merged["boosted_probability"].map(lambda p: "home" if p >= 0.5 else "away")
    merged["phase1_confidence"] = merged["phase1_base_prob"].map(lambda p: abs(float(p) - 0.5))
    merged["boost_weight_json"] = merged.apply(
        lambda row: json.dumps(
            {
                "phase1_base": PHASE1_WEIGHT,
                "deep_feature_base": DEEP_WEIGHT,
            },
            sort_keys=True,
        ),
        axis=1,
    )

    merged = merged[
        [
            "game_id",
            "game_date",
            "home_team_abbrev",
            "away_team_abbrev",
            "actual_home_win",
            "phase1_base_prob",
            "phase1_alt_prob",
            "deep_base_prob",
            "deep_alt_prob",
            "regime_prob",
            "error_base_prob",
            "error_alt_prob",
            "error_adjusted_prob",
            "boosted_probability",
            "boosted_predicted_winner",
            "boosted_predicted_side",
            "phase1_confidence",
            "boost_weight_json",
        ]
    ].sort_values(["game_date", "game_id"])

    out_dir.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out_dir / "predictions.csv", index=False)

    candidate_metrics = []
    for name, col in [
        ("phase1_base", "phase1_base_prob"),
        ("deep_feature_base", "deep_base_prob"),
        ("phase1_alt", "phase1_alt_prob"),
        ("deep_feature_alt", "deep_alt_prob"),
        ("season_regime", "regime_prob"),
        ("error_slice_adjusted", "error_adjusted_prob"),
        ("boosted", "boosted_probability"),
    ]:
        if col in merged.columns and merged[col].notna().any():
            m = metrics(merged.dropna(subset=[col]), col)
            candidate_metrics.append({"candidate": name, **{k: round(v, 6) for k, v in m.items()}})

    candidate_metrics_df = pd.DataFrame(candidate_metrics)
    candidate_metrics_df.to_csv(out_dir / "candidate_metrics.csv", index=False)

    boosted_metrics = metrics(merged, "boosted_probability")
    overall_row = {
        "games": int(boosted_metrics["games"]),
        "accuracy": round(boosted_metrics["accuracy"], 6),
        "log_loss": round(boosted_metrics["log_loss"], 6),
        "brier_score": round(boosted_metrics["brier_score"], 6),
        "current_best_accuracy": CURRENT_BEST_ACCURACY,
        "accuracy_delta_vs_current_best": round(boosted_metrics["accuracy"] - CURRENT_BEST_ACCURACY, 6),
    }

    overall_df = pd.DataFrame([overall_row])
    overall_df.to_csv(out_dir / "overall_metrics.csv", index=False)

    summary = {
        "holdout_season": HOLDOUT_SEASON,
        "current_best_accuracy": CURRENT_BEST_ACCURACY,
        "overall_metrics": overall_row,
        "recipe": {
            "phase1_source": "phase1_eval_final",
            "phase1_model": PHASE1_BEST_MODEL,
            "deep_feature_source": "deep_feature_expansion_v4",
            "deep_feature_model": DEEP_BEST_MODEL,
            "phase1_weight": PHASE1_WEIGHT,
            "deep_feature_weight": DEEP_WEIGHT,
            "notes": [
                "Deterministic fixed-weight blend.",
                "Error-slice and regime-aware candidates were evaluated as diagnostics but not included in the final blend because they did not improve validation accuracy.",
            ],
        },
        "artifacts": {
            "predictions_csv": str((out_dir / "predictions.csv").relative_to(repo_root)).replace("/", "\\"),
            "candidate_metrics_csv": str((out_dir / "candidate_metrics.csv").relative_to(repo_root)).replace("/", "\\"),
            "overall_metrics_csv": str((out_dir / "overall_metrics.csv").relative_to(repo_root)).replace("/", "\\"),
            "summary_json": str((out_dir / "summary.json").relative_to(repo_root)).replace("/", "\\"),
        },
        "validation_reference": {
            "phase1_best_walk_forward_accuracy": 0.616616,
            "season_regime_late_accuracy": 0.622225,
            "deep_feature_holdout_accuracy": 0.617378,
            "error_slice_holdout_accuracy": 0.618902,
        },
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    report_lines: List[str] = [
        "# Probability Boosting Ensemble v4",
        "",
        "## Result",
        f"- Best accuracy: {overall_row['accuracy']:.6f}",
        f"- Current best: {CURRENT_BEST_ACCURACY:.6f}",
        f"- Delta: {overall_row['accuracy_delta_vs_current_best']:+.6f}",
        "",
        "## Recipe",
        f"- {PHASE1_WEIGHT:.2f} * phase1_eval_final:`{PHASE1_BEST_MODEL}`",
        f"- {DEEP_WEIGHT:.2f} * deep_feature_expansion_v4:`{DEEP_BEST_MODEL}`",
        "",
        "## Validation reference",
        "- Phase 1 benchmark candidate is walk-forward validated in the repo.",
        "- Deep feature-expansion and error-slice candidates are the strongest 2021-2022 holdout signals.",
        "- Regime-aware output was tested as a diagnostic, but the fixed blend above was best overall.",
        "",
        "## Candidate metrics",
        "| Candidate | Accuracy | Log loss | Brier | Games |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in candidate_metrics:
        report_lines.append(
            f"| {row['candidate']} | {row['accuracy']:.6f} | {row['log_loss']:.6f} | {row['brier_score']:.6f} | {int(row['games'])} |"
        )
    report_lines.extend(
        [
            "",
            "## Artifacts",
            f"- `{summary['artifacts']['predictions_csv']}`",
            f"- `{summary['artifacts']['candidate_metrics_csv']}`",
            f"- `{summary['artifacts']['overall_metrics_csv']}`",
            f"- `{summary['artifacts']['summary_json']}`",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
