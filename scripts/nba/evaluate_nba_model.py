"""Write the NBA model evaluation report from stored predictions and metrics."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "nba" / "nba_research.db"
CONFIG_PATH = ROOT / "data" / "nba" / "nba_model_config.json"
REPORT_PATH = ROOT / "data" / "reports" / "nba_model_results.md"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def reliability(preds: pd.DataFrame) -> pd.DataFrame:
    bins = np.arange(0.0, 1.01, 0.1)
    labels = [f"{bins[i]:.1f}-{bins[i+1]:.1f}" for i in range(len(bins) - 1)]
    out = preds.copy()
    out["bucket"] = pd.cut(out["model_prob_home"], bins=bins, labels=labels, include_lowest=True)
    return (
        out.groupby("bucket", observed=False)
        .agg(games=("home_win", "size"), avg_pred_home=("model_prob_home", "mean"), actual_home_win=("home_win", "mean"))
        .reset_index()
    )


def metrics_table(metrics: pd.DataFrame, seasons_only: bool = True) -> str:
    rows = metrics[metrics["model"] == "nba_model"].copy()
    if seasons_only:
        rows = rows[rows["season"].astype(str).str.fullmatch(r"\d+")]
    else:
        rows = rows[~rows["season"].astype(str).str.fullmatch(r"\d+")]
    rows = rows.sort_values("season", key=lambda s: s.astype(str))
    lines = ["| Season/scope | Games | Accuracy | Wilson 95% CI | Log loss | Brier |", "|---|---:|---:|---:|---:|---:|"]
    for r in rows.itertuples(index=False):
        lines.append(
            f"| {r.season} | {int(r.games):,} | {pct(r.accuracy)} | {pct(r.wilson_low)}-{pct(r.wilson_high)} | {r.log_loss:.4f} | {r.brier:.4f} |"
        )
    return "\n".join(lines)


def baseline_table(metrics: pd.DataFrame, scope: str) -> str:
    rows = metrics[metrics["season"].astype(str).eq(scope)].copy()
    lines = ["| Model/baseline | Games | Accuracy | Wilson 95% CI | Log loss | Brier |", "|---|---:|---:|---:|---:|---:|"]
    for model in ["always_home", "pure_elo", "nba_model"]:
        r = rows[rows["model"] == model].iloc[0]
        lines.append(
            f"| {model} | {int(r.games):,} | {pct(r.accuracy)} | {pct(r.wilson_low)}-{pct(r.wilson_high)} | {r.log_loss:.4f} | {r.brier:.4f} |"
        )
    return "\n".join(lines)


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    with connect() as con:
        preds = pd.read_sql_query("SELECT * FROM nba_model_predictions", con)
        metrics = pd.read_sql_query("SELECT * FROM nba_model_metrics", con)
        leak = pd.read_sql_query("SELECT * FROM nba_model_leakage_checks", con)
        folds = pd.read_sql_query("SELECT * FROM nba_model_fold_boundaries", con)

    holdout = preds[preds["fold_type"] == "final_holdout"].copy()
    rel = reliability(holdout)
    rel_nonempty = rel[rel["games"] > 0].copy()
    weighted_cal_mae = (
        (rel_nonempty["games"] * (rel_nonempty["avg_pred_home"] - rel_nonempty["actual_home_win"]).abs()).sum()
        / rel_nonempty["games"].sum()
    )
    rel_lines = ["| Predicted bucket | Games | Avg predicted home win | Actual home win |", "|---|---:|---:|---:|"]
    for r in rel.itertuples(index=False):
        avg_pred = "n/a" if pd.isna(r.avg_pred_home) else pct(r.avg_pred_home)
        actual = "n/a" if pd.isna(r.actual_home_win) else pct(r.actual_home_win)
        rel_lines.append(f"| {r.bucket} | {int(r.games)} | {avg_pred} | {actual} |")

    holdout_metrics = metrics[(metrics["season"].astype(str) == "final_holdout_overall")]
    m = holdout_metrics[holdout_metrics["model"] == "nba_model"].iloc[0]
    home = holdout_metrics[holdout_metrics["model"] == "always_home"].iloc[0]
    elo = holdout_metrics[holdout_metrics["model"] == "pure_elo"].iloc[0]
    margin_home = m.accuracy - home.accuracy
    margin_elo = m.accuracy - elo.accuracy

    leak_map = dict(zip(leak["check_name"], leak["value"]))
    feature_preview = config["feature_columns"][:20]
    feature_summary = (
        "Elo, rest/back-to-back context, road-trip flags, season-to-date win percentage, "
        "rolling 3/5/10/20-game form, offensive/defensive rating, estimated pace, eFG%, 3P rate, "
        "rebounding rates, turnover rate, margin/points form, and recent opponent Elo strength. "
        f"The DB stores {len(config['feature_columns'])} model columns; examples: {', '.join(feature_preview)}."
    )

    report = f"""# NBA model results

Date: {config['frozen_at_utc']}

## Headline

The frozen final-holdout evaluation is **{pct(m.accuracy)}** accuracy on **{int(m.games):,}** 2023 regular-season games, Wilson 95% CI **{pct(m.wilson_low)}-{pct(m.wilson_high)}**. Always-pick-home on the same holdout is **{pct(home.accuracy)}**; pure Elo is **{pct(elo.accuracy)}**. The model margins are {margin_home:+.2%} vs always-home and {margin_elo:+.2%} vs Elo, so differences should be read against the CI/noise floor.

## Data window and scope

- Source DB: `data\\nba\\nba_research.db`.
- Per-game modeling rows: completed, non-neutral NBA regular-season games, seasons **{config['per_game_data_window']}**.
- The 2023-24, 2024-25, and 2025-26 `nba_current_*` tables are season-level aggregates only. They were **not** used for per-game training or testing.
- No fabricated, simulated, synthetic, market, betting, or postgame-derived feature rows are used.

## Pregame features

{feature_summary}

All rolling/expanding values are shifted by one game within team history. Season-to-date values use only games already played in that season. Elo ratings are recorded before updating with the current game.

## Frozen configuration and fold structure

Config was written to `data\\nba\\nba_model_config.json` before final holdout scoring. Stored serving artifact: `data\\nba\\nba_model_final.joblib`. Predictions are in DB table `nba_model_predictions`; metrics in `nba_model_metrics`.

```text
{chr(10).join(folds['fold'].tolist())}
```

## Baselines and final holdout

{baseline_table(metrics, 'final_holdout_overall')}

## Per-season walk-forward model results

{metrics_table(metrics, seasons_only=True)}

## Overall scopes

{metrics_table(metrics, seasons_only=False)}

## Calibration reliability table: final holdout

Bucket-weighted absolute calibration error is **{pct(weighted_cal_mae)}** on the final holdout.

{chr(10).join(rel_lines)}

Calibration is Platt scaling fitted only on the immediately prior season for each fold. Buckets with fewer than 150 games are shown for transparency but should not be used as confidence tiers.

## Leakage checks

- Fold boundaries above show every test season trains on earlier seasons only and calibrates on the immediately prior season.
- A high-capacity margin reconstruction check trained before the final holdout and predicted the held-out final margin with R² **{leak_map['holdout_margin_r2']:.4f}**, MAE **{leak_map['holdout_margin_mae']:.2f}** points, and only **{pct(leak_map['exact_margin_within_1_point_rate'])}** within one point.
- The maximum absolute single-feature correlation with final margin was **{leak_map['max_abs_single_feature_margin_corr']:.4f}**. This is not consistent with a leaked final-score identity.

## Limitations

- There is no real betting-market baseline in this NBA database; comparisons are always-home and pure Elo only.
- Per-game NBA modeling data currently stops at the 2023 season; current-season aggregate tables cannot support per-game training.
- The model was not tuned across dozens of variants on the holdout. This is intentionally conservative, but not proof of an optimal NBA ceiling.
- Reported confidence tiers are avoided because most calibration buckets contain fewer than 150 games.
- Accuracy margins over baselines are small relative to Wilson intervals; treat them as noisy estimates, not betting advice.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote {REPORT_PATH}")
    print(f"Holdout: {pct(m.accuracy)} ({pct(m.wilson_low)}-{pct(m.wilson_high)}), n={int(m.games):,}")


if __name__ == "__main__":
    main()
