import argparse
import sqlite3
from pathlib import Path
from typing import List, Tuple


BASE_BACKTEST_COLUMNS: List[Tuple[str, str]] = [
    ("season", "INTEGER"),
    ("game_id", "INTEGER"),
    ("game_date", "TEXT"),
    ("home_team_abbrev", "TEXT"),
    ("away_team_abbrev", "TEXT"),
    ("home_pregame_streak_signed", "INTEGER"),
    ("away_pregame_streak_signed", "INTEGER"),
    ("home_pregame_last10_points_pct", "REAL"),
    ("away_pregame_last10_points_pct", "REAL"),
    ("home_pregame_last10_goal_diff_pg", "REAL"),
    ("away_pregame_last10_goal_diff_pg", "REAL"),
    ("home_pregame_season_points_pct", "REAL"),
    ("away_pregame_season_points_pct", "REAL"),
    ("home_pregame_season_goal_diff_pg", "REAL"),
    ("away_pregame_season_goal_diff_pg", "REAL"),
    ("home_pregame_home_points_pct", "REAL"),
    ("away_pregame_road_points_pct", "REAL"),
    ("home_pregame_rest_days", "INTEGER"),
    ("away_pregame_rest_days", "INTEGER"),
    ("home_back_to_back", "INTEGER"),
    ("away_back_to_back", "INTEGER"),
    ("home_three_in_four", "INTEGER"),
    ("away_three_in_four", "INTEGER"),
    ("home_four_in_six", "INTEGER"),
    ("away_four_in_six", "INTEGER"),
    ("home_pregame_travel_miles", "REAL"),
    ("away_pregame_travel_miles", "REAL"),
    ("delta_travel_miles_home_minus_away", "REAL"),
    ("home_timezone_shift_hours", "REAL"),
    ("away_timezone_shift_hours", "REAL"),
    ("delta_timezone_shift_hours_home_minus_away", "REAL"),
    ("home_pregame_home_stand_len", "INTEGER"),
    ("away_pregame_home_stand_len", "INTEGER"),
    ("home_pregame_road_trip_len", "INTEGER"),
    ("away_pregame_road_trip_len", "INTEGER"),
    ("delta_home_stand_len_home_minus_away", "INTEGER"),
    ("delta_road_trip_len_home_minus_away", "INTEGER"),
    ("rest_days_delta_home_minus_away", "INTEGER"),
    ("home_location_edge_points_pct", "REAL"),
    ("home_prior_prev_season_points_pct", "REAL"),
    ("away_prior_prev_season_points_pct", "REAL"),
    ("home_prior_prev_season_goal_diff_pg", "REAL"),
    ("away_prior_prev_season_goal_diff_pg", "REAL"),
    ("home_prior_prev_season_games", "INTEGER"),
    ("away_prior_prev_season_games", "INTEGER"),
    ("delta_pregame_last10_points_pct_home_minus_away", "REAL"),
    ("delta_pregame_last10_goal_diff_pg_home_minus_away", "REAL"),
    ("delta_pregame_season_points_pct_home_minus_away", "REAL"),
    ("delta_pregame_season_goal_diff_pg_home_minus_away", "REAL"),
    ("home_win", "INTEGER"),
    ("winner_abbrev", "TEXT"),
]

ROSTER_FEATURE_COLUMNS: List[Tuple[str, str]] = [
    ("home_pregame_roster_quality_idx", "REAL"),
    ("away_pregame_roster_quality_idx", "REAL"),
    ("home_pregame_top6_points_pg", "REAL"),
    ("away_pregame_top6_points_pg", "REAL"),
    ("home_pregame_top4_avg_toi", "REAL"),
    ("away_pregame_top4_avg_toi", "REAL"),
    ("home_pregame_goalie_save_pct", "REAL"),
    ("away_pregame_goalie_save_pct", "REAL"),
    ("home_pregame_skater_points_pg_last5", "REAL"),
    ("away_pregame_skater_points_pg_last5", "REAL"),
    ("home_pregame_skater_points_pg_last3", "REAL"),
    ("away_pregame_skater_points_pg_last3", "REAL"),
    ("home_pregame_skater_points_pg_last10", "REAL"),
    ("away_pregame_skater_points_pg_last10", "REAL"),
    ("home_pregame_skater_two_way_idx_last5", "REAL"),
    ("away_pregame_skater_two_way_idx_last5", "REAL"),
    ("home_pregame_skater_two_way_idx_last3", "REAL"),
    ("away_pregame_skater_two_way_idx_last3", "REAL"),
    ("home_pregame_skater_two_way_idx_last10", "REAL"),
    ("away_pregame_skater_two_way_idx_last10", "REAL"),
    ("home_pregame_skater_points_pg_ewm", "REAL"),
    ("away_pregame_skater_points_pg_ewm", "REAL"),
    ("home_pregame_skater_two_way_idx_ewm", "REAL"),
    ("away_pregame_skater_two_way_idx_ewm", "REAL"),
    ("home_pregame_goalie_save_pct_last10", "REAL"),
    ("away_pregame_goalie_save_pct_last10", "REAL"),
    ("home_pregame_goalie_save_pct_ewm", "REAL"),
    ("away_pregame_goalie_save_pct_ewm", "REAL"),
    ("home_pregame_goalie_save_pct_last3", "REAL"),
    ("away_pregame_goalie_save_pct_last3", "REAL"),
    ("home_pregame_goalie_shots_against_pg_last5", "REAL"),
    ("away_pregame_goalie_shots_against_pg_last5", "REAL"),
    ("home_pregame_goalie_shots_against_pg_trend", "REAL"),
    ("away_pregame_goalie_shots_against_pg_trend", "REAL"),
    ("home_pregame_goalie_recent_starts_last5", "REAL"),
    ("away_pregame_goalie_recent_starts_last5", "REAL"),
    ("home_pregame_goalie_days_since_last_start", "REAL"),
    ("away_pregame_goalie_days_since_last_start", "REAL"),
    ("home_pregame_recent_form_adj_last5", "REAL"),
    ("away_pregame_recent_form_adj_last5", "REAL"),
    ("home_pregame_recent_form_adj_last10", "REAL"),
    ("away_pregame_recent_form_adj_last10", "REAL"),
    ("home_pregame_recent_form_volatility_last5", "REAL"),
    ("away_pregame_recent_form_volatility_last5", "REAL"),
    ("home_pregame_recent_form_volatility_last10", "REAL"),
    ("away_pregame_recent_form_volatility_last10", "REAL"),
    ("home_pregame_lineup_continuity_pct", "REAL"),
    ("away_pregame_lineup_continuity_pct", "REAL"),
    ("home_pregame_lineup_continuity_ewm", "REAL"),
    ("away_pregame_lineup_continuity_ewm", "REAL"),
    ("home_pregame_lineup_stability_last5", "REAL"),
    ("away_pregame_lineup_stability_last5", "REAL"),
    ("home_pregame_roster_turnover_count", "INTEGER"),
    ("away_pregame_roster_turnover_count", "INTEGER"),
    ("home_pregame_core_retention_pct", "REAL"),
    ("away_pregame_core_retention_pct", "REAL"),
    ("home_pregame_key_contributor_continuity_pct", "REAL"),
    ("away_pregame_key_contributor_continuity_pct", "REAL"),
    ("home_pregame_key_contributor_change_rate_last5", "REAL"),
    ("away_pregame_key_contributor_change_rate_last5", "REAL"),
    ("home_pregame_lineup_change_rate_last5", "REAL"),
    ("away_pregame_lineup_change_rate_last5", "REAL"),
    ("home_pregame_roster_games_covered", "INTEGER"),
    ("away_pregame_roster_games_covered", "INTEGER"),
    ("home_pregame_roster_data_coverage_pct", "REAL"),
    ("away_pregame_roster_data_coverage_pct", "REAL"),
    ("home_pregame_injury_count", "INTEGER"),
    ("away_pregame_injury_count", "INTEGER"),
    ("home_pregame_top9_points_pg", "REAL"),
    ("away_pregame_top9_points_pg", "REAL"),
    ("home_pregame_depth_points_share_last5", "REAL"),
    ("away_pregame_depth_points_share_last5", "REAL"),
    ("home_pregame_special_teams_contributor_share_last5", "REAL"),
    ("away_pregame_special_teams_contributor_share_last5", "REAL"),
    ("home_pregame_confirmed_starters_count", "INTEGER"),
    ("away_pregame_confirmed_starters_count", "INTEGER"),
    ("delta_pregame_roster_quality_idx_home_minus_away", "REAL"),
    ("delta_pregame_goalie_save_pct_home_minus_away", "REAL"),
    ("delta_pregame_skater_points_pg_last5_home_minus_away", "REAL"),
    ("delta_pregame_skater_two_way_idx_last5_home_minus_away", "REAL"),
    ("delta_pregame_recent_form_adj_last5_home_minus_away", "REAL"),
    ("delta_pregame_recent_form_volatility_last5_home_minus_away", "REAL"),
    ("delta_pregame_lineup_continuity_pct_home_minus_away", "REAL"),
    ("delta_pregame_roster_turnover_count_home_minus_away", "REAL"),
    ("delta_pregame_injury_count_home_minus_away", "REAL"),
    ("delta_pregame_goalie_shots_against_pg_trend_home_minus_away", "REAL"),
    ("delta_pregame_goalie_recent_starts_last5_home_minus_away", "REAL"),
    ("delta_pregame_goalie_days_since_last_start_home_minus_away", "REAL"),
    ("delta_pregame_top9_points_pg_home_minus_away", "REAL"),
    ("delta_pregame_depth_points_share_last5_home_minus_away", "REAL"),
    ("delta_pregame_special_teams_contributor_share_last5_home_minus_away", "REAL"),
    ("delta_pregame_key_contributor_continuity_pct_home_minus_away", "REAL"),
    ("delta_pregame_lineup_change_rate_last5_home_minus_away", "REAL"),
    ("home_roster_source_tag", "TEXT"),
    ("away_roster_source_tag", "TEXT"),
    ("home_roster_source_stats_through_date", "TEXT"),
    ("away_roster_source_stats_through_date", "TEXT"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create roster-aware backtest schema tables for deterministic pregame feature generation."
    )
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--sqlite-db", default=None, help="Defaults to data\\processed\\nhl_research.db")
    parser.add_argument("--final-table-name", default="backtest_features_last5_roster")
    parser.add_argument("--team-roster-table-name", default="roster_team_pregame_features_last5")
    parser.add_argument("--player-roster-table-name", default="roster_player_pregame_stats_last5")
    return parser.parse_args()


def create_final_table(conn: sqlite3.Connection, table_name: str) -> None:
    cols = BASE_BACKTEST_COLUMNS + ROSTER_FEATURE_COLUMNS
    col_defs = ", ".join([f'"{col}" {col_type}' for col, col_type in cols])
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs})')
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_season_date" ON "{table_name}" (season, game_date, game_id)'
    )


def create_team_roster_table(conn: sqlite3.Connection, table_name: str) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            season INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            game_date TEXT NOT NULL,
            team_abbrev TEXT NOT NULL,
            pregame_roster_quality_idx REAL,
            pregame_top6_points_pg REAL,
            pregame_top4_avg_toi REAL,
            pregame_goalie_save_pct REAL,
            pregame_skater_points_pg_last5 REAL,
            pregame_skater_points_pg_last3 REAL,
            pregame_skater_points_pg_last10 REAL,
            pregame_skater_two_way_idx_last5 REAL,
            pregame_skater_two_way_idx_last3 REAL,
            pregame_skater_two_way_idx_last10 REAL,
            pregame_skater_points_pg_ewm REAL,
            pregame_skater_two_way_idx_ewm REAL,
            pregame_goalie_save_pct_last10 REAL,
            pregame_goalie_save_pct_ewm REAL,
            pregame_goalie_save_pct_last3 REAL,
            pregame_goalie_shots_against_pg_last5 REAL,
            pregame_goalie_shots_against_pg_trend REAL,
            pregame_goalie_recent_starts_last5 REAL,
            pregame_goalie_days_since_last_start REAL,
            pregame_recent_form_adj_last5 REAL,
            pregame_recent_form_adj_last10 REAL,
            pregame_recent_form_volatility_last5 REAL,
            pregame_recent_form_volatility_last10 REAL,
            pregame_lineup_continuity_pct REAL,
            pregame_lineup_continuity_ewm REAL,
            pregame_lineup_stability_last5 REAL,
            pregame_roster_turnover_count INTEGER,
            pregame_core_retention_pct REAL,
            pregame_key_contributor_continuity_pct REAL,
            pregame_key_contributor_change_rate_last5 REAL,
            pregame_lineup_change_rate_last5 REAL,
            pregame_roster_games_covered INTEGER,
            pregame_roster_data_coverage_pct REAL,
            pregame_injury_count INTEGER,
            pregame_top9_points_pg REAL,
            pregame_depth_points_share_last5 REAL,
            pregame_special_teams_contributor_share_last5 REAL,
            pregame_confirmed_starters_count INTEGER,
            roster_source_tag TEXT,
            source_stats_through_date TEXT,
            PRIMARY KEY (season, game_id, team_abbrev)
        )
        """
    )
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_team_date" ON "{table_name}" (team_abbrev, game_date, game_id)'
    )


def create_player_roster_table(conn: sqlite3.Connection, table_name: str) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            season INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            game_date TEXT NOT NULL,
            team_abbrev TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            player_name TEXT,
            position TEXT,
            lineup_role TEXT,
            is_expected_active INTEGER,
            player_games_sample INTEGER,
            rolling_points_pg_last5 REAL,
            rolling_goals_pg_last5 REAL,
            rolling_assists_pg_last5 REAL,
            rolling_toi_minutes_pg_last5 REAL,
            rolling_goalie_save_pct_last5 REAL,
            rolling_plus_minus_pg_last5 REAL,
            rolling_points_pg_last3 REAL,
            rolling_points_pg_last10 REAL,
            rolling_two_way_idx_last3 REAL,
            rolling_two_way_idx_last10 REAL,
            rolling_points_pg_ewm REAL,
            rolling_two_way_idx_ewm REAL,
            rolling_goalie_save_pct_last10 REAL,
            rolling_goalie_save_pct_ewm REAL,
            rolling_goalie_save_pct_last3 REAL,
            rolling_goalie_shots_against_pg_last5 REAL,
            rolling_goalie_shots_against_pg_last3 REAL,
            rolling_goalie_shots_against_pg_last10 REAL,
            rolling_goalie_starts_last5 REAL,
            rolling_goalie_starts_last10 REAL,
            goalie_days_since_last_start REAL,
            rolling_power_play_goals_pg_last5 REAL,
            source_stats_through_date TEXT,
            PRIMARY KEY (season, game_id, team_abbrev, player_id)
        )
        """
    )
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_team_game" ON "{table_name}" (team_abbrev, game_id, player_id)'
    )


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    sqlite_db = Path(args.sqlite_db).resolve() if args.sqlite_db else repo_root / "data" / "processed" / "nhl_research.db"
    sqlite_db.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(sqlite_db) as conn:
        create_final_table(conn, args.final_table_name)
        create_team_roster_table(conn, args.team_roster_table_name)
        create_player_roster_table(conn, args.player_roster_table_name)
        conn.commit()

    print(f"sqlite_db={sqlite_db}")
    print(f"final_table={args.final_table_name}")
    print(f"intermediate_team_table={args.team_roster_table_name}")
    print(f"intermediate_player_table={args.player_roster_table_name}")


if __name__ == "__main__":
    main()
