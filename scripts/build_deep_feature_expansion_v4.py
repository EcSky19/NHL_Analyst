#!/usr/bin/env python
"""Build the deep feature expansion v4 table for NHL walk-forward evaluation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = REPO_ROOT / "data" / "processed" / "backtest_features_last5_roster_v2.csv"
OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "execution_plan" / "deep_feature_expansion_v4"
OUTPUT_CSV = OUTPUT_DIR / "deep_feature_expansion_v4_features.csv"
OUTPUT_TABLE = "deep_feature_expansion_v4_features"
DB_PATH = REPO_ROOT / "data" / "processed" / "nhl_research.db"


def to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if col not in {
            "season",
            "game_id",
            "game_date",
            "home_team_abbrev",
            "away_team_abbrev",
            "home_roster_source_tag",
            "away_roster_source_tag",
            "home_roster_source_stats_through_date",
            "away_roster_source_stats_through_date",
            "winner_abbrev",
        }:
            if df[col].dtype == object:
                df[col] = pd.to_numeric(df[col], errors="ignore")

    def n(col: str) -> pd.Series:
        return to_num(df[col]) if col in df.columns else pd.Series(0.0, index=df.index)

    # Lineup stability / roster continuity
    df["lineup_continuity_gap"] = n("home_pregame_lineup_continuity_pct") - n("away_pregame_lineup_continuity_pct")
    df["lineup_stability_gap"] = n("home_pregame_lineup_stability_last5") - n("away_pregame_lineup_stability_last5")
    df["core_retention_gap"] = n("home_pregame_core_retention_pct") - n("away_pregame_core_retention_pct")
    df["lineup_continuity_x_recent_form"] = df["lineup_continuity_gap"] * n("delta_pregame_last10_points_pct_home_minus_away")
    df["lineup_stability_x_coverage"] = df["lineup_stability_gap"] * (
        1.0 + (n("home_pregame_roster_data_coverage_pct") - n("away_pregame_roster_data_coverage_pct"))
    )
    df["lineup_turnover_relief"] = -(n("delta_pregame_roster_turnover_count_home_minus_away"))

    # Goalie confirmation latency / starter certainty
    df["goalie_certainty_gap"] = n("delta_pregame_goalie_starter_certainty_home_minus_away")
    df["goalie_latency_gap"] = n("delta_pregame_goalie_days_since_last_start_home_minus_away")
    df["goalie_certainty_x_latency"] = df["goalie_certainty_gap"] * (1.0 - 0.10 * df["goalie_latency_gap"].abs())
    df["goalie_certainty_x_quality_gap"] = df["goalie_certainty_gap"] * n("delta_pregame_goalie_starter_quality_gap_last10_home_minus_away")
    df["goalie_freshness_edge"] = df["goalie_certainty_gap"] * (
        1.0 + 0.05 * n("delta_pregame_goalie_recent_starts_last5_home_minus_away")
        - 0.05 * df["goalie_latency_gap"].abs()
    )

    # Special teams form / differential
    df["special_teams_net_edge"] = n("delta_power_play_pct_home_minus_away") + n("delta_penalty_kill_pct_home_minus_away")
    df["special_teams_balance_edge"] = n("delta_power_play_pct_home_minus_away") - n("delta_penalty_kill_pct_home_minus_away")
    df["special_teams_form_x_recent_form"] = df["special_teams_net_edge"] * n("delta_pregame_recent_form_adj_last5_home_minus_away")
    df["special_teams_form_x_quality"] = df["special_teams_net_edge"] * n("delta_pregame_roster_quality_idx_home_minus_away")

    # Opponent-adjusted rest / schedule compression
    home_compression = n("home_back_to_back") + 0.50 * n("home_three_in_four") + 0.25 * n("home_four_in_six")
    away_compression = n("away_back_to_back") + 0.50 * n("away_three_in_four") + 0.25 * n("away_four_in_six")
    df["schedule_compression_relief"] = (-home_compression) + away_compression
    df["opponent_adjusted_rest_edge"] = n("rest_days_delta_home_minus_away") - 0.50 * (
        n("home_three_in_four") - n("away_three_in_four")
    ) - 0.25 * (n("home_four_in_six") - n("away_four_in_six"))
    df["travel_adjusted_rest_edge"] = df["opponent_adjusted_rest_edge"] - 0.10 * (n("delta_travel_miles_home_minus_away") / 1000.0) - 0.05 * n("delta_timezone_shift_hours_home_minus_away")

    # Rolling team/player microtrends
    df["microtrend_skater_points_accel"] = n("delta_pregame_skater_points_pg_last3_home_minus_away") - n("delta_pregame_skater_points_pg_last10_home_minus_away")
    df["microtrend_two_way_accel"] = n("delta_pregame_skater_two_way_idx_last3_home_minus_away") - n("delta_pregame_skater_two_way_idx_last10_home_minus_away")
    df["microtrend_goalie_save_accel"] = n("delta_pregame_goalie_save_pct_last3_home_minus_away") - n("delta_pregame_goalie_save_pct_last10_home_minus_away")
    df["microtrend_form_accel"] = n("delta_pregame_recent_form_adj_last5_home_minus_away") - n("delta_pregame_recent_form_adj_last10_home_minus_away")
    df["microtrend_volatility_penalty"] = n("delta_pregame_recent_form_adj_last5_home_minus_away") / (1.0 + n("delta_pregame_recent_form_volatility_last5_home_minus_away").abs())
    df["microtrend_goalie_workload_edge"] = n("delta_pregame_goalie_recent_starts_last5_home_minus_away") - n("delta_pregame_goalie_shots_against_pg_last5_home_minus_away")

    # Home/away split deltas with recent form
    df["home_away_split_edge"] = n("home_home_vs_away_win_pct_diff") - n("away_home_vs_away_win_pct_diff")
    df["home_away_split_form_edge"] = n("home_home_vs_away_win_pct_diff") * n("home_momentum_10game_trend") - n("away_home_vs_away_win_pct_diff") * n("away_momentum_10game_trend")
    df["home_away_split_momentum_direction"] = n("home_momentum_trend_direction") - n("away_momentum_trend_direction")

    # Deadline timing proxy
    df["deadline_pressure_edge"] = (1.0 / (1.0 + n("games_until_deadline"))) - (1.0 / (1.0 + n("games_since_deadline")))

    return df


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(INPUT_CSV)
    out = build_features(df)
    out.to_csv(OUTPUT_CSV, index=False)
    with sqlite3.connect(DB_PATH) as con:
        out.to_sql(OUTPUT_TABLE, con, if_exists="replace", index=False)

    manifest = {
        "input_csv": str(INPUT_CSV),
        "output_csv": str(OUTPUT_CSV),
        "output_table": OUTPUT_TABLE,
        "rows": int(out.shape[0]),
        "columns": int(out.shape[1]),
        "new_columns": [
            "lineup_continuity_gap",
            "lineup_stability_gap",
            "core_retention_gap",
            "lineup_continuity_x_recent_form",
            "lineup_stability_x_coverage",
            "lineup_turnover_relief",
            "goalie_certainty_gap",
            "goalie_latency_gap",
            "goalie_certainty_x_latency",
            "goalie_certainty_x_quality_gap",
            "goalie_freshness_edge",
            "special_teams_net_edge",
            "special_teams_balance_edge",
            "special_teams_form_x_recent_form",
            "special_teams_form_x_quality",
            "schedule_compression_relief",
            "opponent_adjusted_rest_edge",
            "travel_adjusted_rest_edge",
            "microtrend_skater_points_accel",
            "microtrend_two_way_accel",
            "microtrend_goalie_save_accel",
            "microtrend_form_accel",
            "microtrend_volatility_penalty",
            "microtrend_goalie_workload_edge",
            "home_away_split_edge",
            "home_away_split_form_edge",
            "home_away_split_momentum_direction",
            "deadline_pressure_edge",
        ],
    }
    (OUTPUT_DIR / "deep_feature_expansion_v4_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
