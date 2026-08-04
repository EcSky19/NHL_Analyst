import argparse
import csv
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Set, Tuple


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
    ("home_pregame_goalie_starter_certainty", "REAL"),
    ("away_pregame_goalie_starter_certainty", "REAL"),
    ("home_pregame_goalie_starter_quality_gap_last5", "REAL"),
    ("away_pregame_goalie_starter_quality_gap_last5", "REAL"),
    ("home_pregame_goalie_starter_quality_gap_last10", "REAL"),
    ("away_pregame_goalie_starter_quality_gap_last10", "REAL"),
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
    ("delta_pregame_goalie_starter_certainty_home_minus_away", "REAL"),
    ("delta_pregame_goalie_starter_quality_gap_last5_home_minus_away", "REAL"),
    ("delta_pregame_goalie_starter_quality_gap_last10_home_minus_away", "REAL"),
    ("home_roster_source_tag", "TEXT"),
    ("away_roster_source_tag", "TEXT"),
    ("home_roster_source_stats_through_date", "TEXT"),
    ("away_roster_source_stats_through_date", "TEXT"),
]

FINAL_COLUMNS: List[Tuple[str, str]] = BASE_BACKTEST_COLUMNS + ROSTER_FEATURE_COLUMNS

TEAM_FEATURE_COLUMN_MAP = {
    "pregame_roster_quality_idx": "pregame_roster_quality_idx",
    "pregame_top6_points_pg": "pregame_top6_points_pg",
    "pregame_top4_avg_toi": "pregame_top4_avg_toi",
    "pregame_goalie_save_pct": "pregame_goalie_save_pct",
    "pregame_skater_points_pg_last5": "pregame_skater_points_pg_last5",
    "pregame_skater_points_pg_last3": "pregame_skater_points_pg_last3",
    "pregame_skater_points_pg_last10": "pregame_skater_points_pg_last10",
    "pregame_skater_two_way_idx_last5": "pregame_skater_two_way_idx_last5",
    "pregame_skater_two_way_idx_last3": "pregame_skater_two_way_idx_last3",
    "pregame_skater_two_way_idx_last10": "pregame_skater_two_way_idx_last10",
    "pregame_skater_points_pg_ewm": "pregame_skater_points_pg_ewm",
    "pregame_skater_two_way_idx_ewm": "pregame_skater_two_way_idx_ewm",
    "pregame_goalie_save_pct_last10": "pregame_goalie_save_pct_last10",
    "pregame_goalie_save_pct_ewm": "pregame_goalie_save_pct_ewm",
    "pregame_goalie_save_pct_last3": "pregame_goalie_save_pct_last3",
    "pregame_goalie_shots_against_pg_last5": "pregame_goalie_shots_against_pg_last5",
    "pregame_goalie_shots_against_pg_trend": "pregame_goalie_shots_against_pg_trend",
    "pregame_goalie_recent_starts_last5": "pregame_goalie_recent_starts_last5",
    "pregame_goalie_days_since_last_start": "pregame_goalie_days_since_last_start",
    "pregame_recent_form_adj_last5": "pregame_recent_form_adj_last5",
    "pregame_recent_form_adj_last10": "pregame_recent_form_adj_last10",
    "pregame_recent_form_volatility_last5": "pregame_recent_form_volatility_last5",
    "pregame_recent_form_volatility_last10": "pregame_recent_form_volatility_last10",
    "pregame_lineup_continuity_pct": "pregame_lineup_continuity_pct",
    "pregame_lineup_continuity_ewm": "pregame_lineup_continuity_ewm",
    "pregame_lineup_stability_last5": "pregame_lineup_stability_last5",
    "pregame_roster_turnover_count": "pregame_roster_turnover_count",
    "pregame_core_retention_pct": "pregame_core_retention_pct",
    "pregame_key_contributor_continuity_pct": "pregame_key_contributor_continuity_pct",
    "pregame_key_contributor_change_rate_last5": "pregame_key_contributor_change_rate_last5",
    "pregame_lineup_change_rate_last5": "pregame_lineup_change_rate_last5",
    "pregame_roster_games_covered": "pregame_roster_games_covered",
    "pregame_roster_data_coverage_pct": "pregame_roster_data_coverage_pct",
    "pregame_injury_count": "pregame_injury_count",
    "pregame_top9_points_pg": "pregame_top9_points_pg",
    "pregame_depth_points_share_last5": "pregame_depth_points_share_last5",
    "pregame_special_teams_contributor_share_last5": "pregame_special_teams_contributor_share_last5",
    "pregame_confirmed_starters_count": "pregame_confirmed_starters_count",
    "pregame_goalie_starter_certainty": "pregame_goalie_starter_certainty",
    "pregame_goalie_starter_quality_gap_last5": "pregame_goalie_starter_quality_gap_last5",
    "pregame_goalie_starter_quality_gap_last10": "pregame_goalie_starter_quality_gap_last10",
    "roster_source_tag": "roster_source_tag",
    "source_stats_through_date": "source_stats_through_date",
}


@dataclass
class PlayerHistory:
    games_played: int = 0
    points_last10: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    goals_last10: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    assists_last10: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    toi_minutes_last10: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    plus_minus_last10: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    goalie_save_pct_last10: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    goalie_shots_against_last10: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    goalie_start_flags_last10: Deque[int] = field(default_factory=lambda: deque(maxlen=10))
    points_last5: Deque[float] = field(default_factory=lambda: deque(maxlen=5))
    goals_last5: Deque[float] = field(default_factory=lambda: deque(maxlen=5))
    assists_last5: Deque[float] = field(default_factory=lambda: deque(maxlen=5))
    toi_minutes_last5: Deque[float] = field(default_factory=lambda: deque(maxlen=5))
    plus_minus_last5: Deque[float] = field(default_factory=lambda: deque(maxlen=5))
    goalie_save_pct_last5: Deque[float] = field(default_factory=lambda: deque(maxlen=5))
    goalie_shots_against_last5: Deque[float] = field(default_factory=lambda: deque(maxlen=5))
    goalie_start_flags_last5: Deque[int] = field(default_factory=lambda: deque(maxlen=5))
    power_play_goals_last5: Deque[float] = field(default_factory=lambda: deque(maxlen=5))
    last_goalie_start_date: Optional[str] = None
    latest_prior_date: Optional[str] = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build roster-aware last-5-seasons backtest feature rows. "
            "Deterministic and pregame-only; outputs schema-valid rows even when roster inputs are unavailable."
        )
    )
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--sqlite-db", default=None, help="Defaults to data\\processed\\nhl_research.db")
    parser.add_argument("--base-table-name", default="backtest_features_last5")
    parser.add_argument("--player-stats-table-name", default="historical_player_game_stats")
    parser.add_argument("--game-rosters-table-name", default="historical_game_rosters")
    parser.add_argument("--team-roster-table-name", default="roster_team_pregame_features_last5")
    parser.add_argument("--player-roster-table-name", default="roster_player_pregame_stats_last5")
    parser.add_argument("--final-table-name", default="backtest_features_last5_roster")
    parser.add_argument(
        "--output-csv",
        default=None,
        help="Defaults to data\\processed\\backtest_features_last5_roster.csv",
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help="Defaults to data\\reports\\roster_advanced_temporal_features_notes.md",
    )
    return parser.parse_args()


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table_name,)
    ).fetchone()
    return row is not None


def optional_subtract(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def safe_avg(values: Iterable[Optional[float]]) -> Optional[float]:
    materialized = [float(v) for v in values if v is not None]
    if not materialized:
        return None
    return sum(materialized) / float(len(materialized))


def trailing_mean(values: Iterable[float], window: int) -> Optional[float]:
    materialized = list(values)
    if not materialized:
        return None
    subset = materialized[-window:]
    if not subset:
        return None
    return sum(subset) / float(len(subset))


def trailing_variance(values: Iterable[float], window: int) -> Optional[float]:
    materialized = list(values)
    if not materialized:
        return None
    subset = materialized[-window:]
    if len(subset) <= 1:
        return 0.0 if len(subset) == 1 else None
    mean = sum(subset) / float(len(subset))
    return sum((x - mean) ** 2 for x in subset) / float(len(subset))


def ewm_mean(values: Iterable[float], alpha: float = 0.45) -> Optional[float]:
    materialized = list(values)
    if not materialized:
        return None
    value = float(materialized[0])
    for sample in materialized[1:]:
        value = alpha * float(sample) + ((1.0 - alpha) * value)
    return value


def load_alias_map(conn: sqlite3.Connection) -> Dict[str, str]:
    alias_to_canonical: Dict[str, str] = {}
    if not table_exists(conn, "team_alias_map"):
        return alias_to_canonical

    rows = conn.execute("SELECT canonical_abbrev, alias_abbrevs FROM team_alias_map").fetchall()
    for canonical_abbrev, alias_abbrevs in rows:
        canonical = (canonical_abbrev or "").strip().upper()
        if not canonical:
            continue
        alias_to_canonical[canonical] = canonical
        for alias in (alias_abbrevs or "").split("|"):
            token = alias.strip().upper()
            if token:
                alias_to_canonical[token] = canonical
    return alias_to_canonical


def canonical_team(team_abbrev: Optional[str], alias_map: Dict[str, str]) -> str:
    normalized = (team_abbrev or "").strip().upper()
    return alias_map.get(normalized, normalized)


def ensure_final_table(conn: sqlite3.Connection, table_name: str) -> None:
    col_defs = ", ".join([f'"{c}" {t}' for c, t in FINAL_COLUMNS])
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs})')


def load_base_rows(conn: sqlite3.Connection, table_name: str) -> List[Dict]:
    if not table_exists(conn, table_name):
        return []

    columns = [name for name, _ in BASE_BACKTEST_COLUMNS]
    quoted_cols = ", ".join([f'"{c}"' for c in columns])
    query = f'SELECT {quoted_cols} FROM "{table_name}" ORDER BY season, game_date, game_id'
    rows: List[Dict] = []
    for raw in conn.execute(query).fetchall():
        row = {}
        for idx, col in enumerate(columns):
            row[col] = raw[idx]
        rows.append(row)
    return rows


def ensure_player_roster_table(conn: sqlite3.Connection, table_name: str) -> None:
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    conn.execute(
        f"""
        CREATE TABLE "{table_name}" (
            season INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            game_date TEXT NOT NULL,
            team_abbrev TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            player_name TEXT,
            position TEXT,
            lineup_role TEXT,
            goalie_starter_source TEXT,
            goalie_starter_api_flag INTEGER,
            goalie_starter_certainty REAL,
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


def ensure_team_roster_table(conn: sqlite3.Connection, table_name: str) -> None:
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    conn.execute(
        f"""
        CREATE TABLE "{table_name}" (
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
            pregame_goalie_starter_certainty REAL,
            pregame_goalie_starter_quality_gap_last5 REAL,
            pregame_goalie_starter_quality_gap_last10 REAL,
            roster_source_tag TEXT,
            source_stats_through_date TEXT,
            PRIMARY KEY (season, game_id, team_abbrev)
        )
        """
    )
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_team_date" ON "{table_name}" (team_abbrev, game_date, game_id)'
    )


def available_columns(conn: sqlite3.Connection, table_name: str) -> List[str]:
    if not table_exists(conn, table_name):
        return []
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]


def load_roster_team_features(conn: sqlite3.Connection, table_name: str) -> Dict[Tuple[int, int, str], Dict]:
    table_cols = set(available_columns(conn, table_name))
    if not table_cols:
        return {}

    required = ["season", "game_id", "team_abbrev"]
    if any(col not in table_cols for col in required):
        return {}

    selected = required + [c for c in TEAM_FEATURE_COLUMN_MAP.keys() if c in table_cols]
    quoted = ", ".join([f'"{c}"' for c in selected])
    query = f'SELECT {quoted} FROM "{table_name}" ORDER BY season, game_id, team_abbrev'
    out: Dict[Tuple[int, int, str], Dict] = {}
    for raw in conn.execute(query).fetchall():
        local = {selected[i]: raw[i] for i in range(len(selected))}
        key = (int(local["season"]), int(local["game_id"]), str(local["team_abbrev"]).upper())
        out[key] = local
    return out


def load_games(conn: sqlite3.Connection, alias_map: Dict[str, str]) -> List[Dict]:
    rows = conn.execute(
        """
        SELECT season, game_id, game_date, home_team_abbrev, away_team_abbrev
        FROM historical_games_last5
        WHERE is_final = 1 AND game_type = '2'
        ORDER BY season, game_date, game_id
        """
    ).fetchall()
    games: List[Dict] = []
    for season, game_id, game_date, home_team_abbrev, away_team_abbrev in rows:
        games.append(
            {
                "season": int(season),
                "game_id": int(game_id),
                "game_date": str(game_date),
                "game_date_obj": date.fromisoformat(str(game_date)),
                "home_team_abbrev": canonical_team(home_team_abbrev, alias_map),
                "away_team_abbrev": canonical_team(away_team_abbrev, alias_map),
            }
        )
    return games


def load_pregame_context(
    conn: sqlite3.Connection,
    table_name: str,
    alias_map: Dict[str, str],
) -> Dict[Tuple[int, int, str], Dict[str, Optional[float]]]:
    if not table_exists(conn, table_name):
        return {}
    rows = conn.execute(
        f"""
        SELECT
            season,
            game_id,
            home_team_abbrev,
            away_team_abbrev,
            home_pregame_season_points_pct,
            away_pregame_season_points_pct
        FROM "{table_name}"
        ORDER BY season, game_id
        """
    ).fetchall()
    out: Dict[Tuple[int, int, str], Dict[str, Optional[float]]] = {}
    for season, game_id, home_abbrev, away_abbrev, home_ppct, away_ppct in rows:
        home = canonical_team(home_abbrev, alias_map)
        away = canonical_team(away_abbrev, alias_map)
        key_home = (int(season), int(game_id), home)
        key_away = (int(season), int(game_id), away)
        out[key_home] = {
            "opponent_pregame_points_pct": float(away_ppct) if away_ppct is not None else None,
            "team_pregame_points_pct": float(home_ppct) if home_ppct is not None else None,
        }
        out[key_away] = {
            "opponent_pregame_points_pct": float(home_ppct) if home_ppct is not None else None,
            "team_pregame_points_pct": float(away_ppct) if away_ppct is not None else None,
        }
    return out


def load_roster_stats_by_game_team(
    conn: sqlite3.Connection,
    roster_table_name: str,
    stats_table_name: str,
    alias_map: Dict[str, str],
) -> Dict[Tuple[int, int, str], List[Dict]]:
    roster_cols = set(available_columns(conn, roster_table_name))
    stats_cols = set(available_columns(conn, stats_table_name))
    if not roster_cols:
        return {}

    def r_col(name: str) -> str:
        return f'r."{name}"' if name in roster_cols else f'NULL AS "{name}"'

    def s_col(name: str) -> str:
        return f's."{name}"' if name in stats_cols else f'NULL AS "{name}"'

    rows = conn.execute(
        f"""
        SELECT
            {r_col("season")},
            {r_col("game_id")},
            {r_col("team_abbrev")},
            {r_col("player_id")},
            {r_col("player_name")},
            {r_col("position")},
            {r_col("is_goalie")},
            {r_col("is_starter_goalie")},
            {r_col("starter_goalie_api_flag")},
            {r_col("starter_goalie_source")},
            {r_col("starter_goalie_confidence")},
            {r_col("played")},
            {s_col("goals")},
            {s_col("assists")},
            {s_col("points")},
            {s_col("plus_minus")},
            {s_col("toi_seconds")},
            {s_col("power_play_goals")},
            {s_col("shots_against")},
            {s_col("saves")}
        FROM "{roster_table_name}" r
        LEFT JOIN "{stats_table_name}" s
            ON s.game_id = r.game_id
            AND s.team_abbrev = r.team_abbrev
            AND s.player_id = r.player_id
        ORDER BY r.season, r.game_id, r.team_abbrev, r.player_id
        """
    ).fetchall()
    grouped: Dict[Tuple[int, int, str], List[Dict]] = defaultdict(list)
    for (
        season,
        game_id,
        team_abbrev,
        player_id,
        player_name,
        position,
        is_goalie,
        is_starter_goalie,
        starter_goalie_api_flag,
        starter_goalie_source,
        starter_goalie_confidence,
        played,
        goals,
        assists,
        points,
        plus_minus,
        toi_seconds,
        power_play_goals,
        shots_against,
        saves,
    ) in rows:
        key = (int(season), int(game_id), canonical_team(team_abbrev, alias_map))
        grouped[key].append(
            {
                "season": int(season),
                "game_id": int(game_id),
                "team_abbrev": canonical_team(team_abbrev, alias_map),
                "player_id": int(player_id),
                "player_name": player_name,
                "position": (position or "").strip().upper() or None,
                "is_goalie": int(is_goalie or 0),
                "is_starter_goalie": int(is_starter_goalie or 0),
                "starter_goalie_api_flag": int(starter_goalie_api_flag) if starter_goalie_api_flag is not None else None,
                "starter_goalie_source": str(starter_goalie_source) if starter_goalie_source is not None else None,
                "starter_goalie_confidence": (
                    float(starter_goalie_confidence) if starter_goalie_confidence is not None else None
                ),
                "played": int(played or 0),
                "goals": goals,
                "assists": assists,
                "points": points,
                "plus_minus": plus_minus,
                "toi_seconds": toi_seconds,
                "power_play_goals": power_play_goals,
                "shots_against": shots_against,
                "saves": saves,
            }
        )
    return grouped


def mean_of_deque(values: Deque[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / float(len(values))


def scorer_projection_from_history(history: PlayerHistory, is_goalie: bool) -> float:
    if is_goalie:
        save_pct = mean_of_deque(history.goalie_save_pct_last5)
        return 2.0 * (save_pct if save_pct is not None else 0.9)
    points_pg = mean_of_deque(history.points_last5) or 0.0
    toi_pg = mean_of_deque(history.toi_minutes_last5) or 0.0
    plus_minus_pg = mean_of_deque(history.plus_minus_last5) or 0.0
    return (1.6 * points_pg) + (0.04 * toi_pg) + (0.12 * plus_minus_pg)


def make_player_feature_row(entry: Dict, game_date: str, history: Optional[PlayerHistory]) -> Dict:
    points_pg = mean_of_deque(history.points_last5) if history else None
    goals_pg = mean_of_deque(history.goals_last5) if history else None
    assists_pg = mean_of_deque(history.assists_last5) if history else None
    toi_pg = mean_of_deque(history.toi_minutes_last5) if history else None
    goalie_save_pct = mean_of_deque(history.goalie_save_pct_last5) if history else None
    plus_minus_pg = mean_of_deque(history.plus_minus_last5) if history else None
    points_pg_last3 = trailing_mean(history.points_last10, 3) if history else None
    points_pg_last10 = trailing_mean(history.points_last10, 10) if history else None
    two_way_idx_last3 = (
        trailing_mean(
            [(history.points_last10[i] + (0.18 * history.plus_minus_last10[i])) for i in range(len(history.points_last10))],
            3,
        )
        if history
        else None
    )
    two_way_idx_last10 = (
        trailing_mean(
            [(history.points_last10[i] + (0.18 * history.plus_minus_last10[i])) for i in range(len(history.points_last10))],
            10,
        )
        if history
        else None
    )
    points_pg_ewm = ewm_mean(history.points_last10) if history else None
    two_way_idx_ewm = (
        ewm_mean([(history.points_last10[i] + (0.18 * history.plus_minus_last10[i])) for i in range(len(history.points_last10))])
        if history
        else None
    )
    goalie_save_pct_last10 = trailing_mean(history.goalie_save_pct_last10, 10) if history else None
    goalie_save_pct_ewm = ewm_mean(history.goalie_save_pct_last10, alpha=0.35) if history else None
    goalie_save_pct_last3 = trailing_mean(history.goalie_save_pct_last10, 3) if history else None
    goalie_shots_against_pg_last5 = mean_of_deque(history.goalie_shots_against_last5) if history else None
    goalie_shots_against_pg_last3 = trailing_mean(history.goalie_shots_against_last10, 3) if history else None
    goalie_shots_against_pg_last10 = mean_of_deque(history.goalie_shots_against_last10) if history else None
    goalie_starts_last5 = float(sum(history.goalie_start_flags_last5)) if history else None
    goalie_starts_last10 = float(sum(history.goalie_start_flags_last10)) if history else None
    rolling_power_play_goals_pg_last5 = mean_of_deque(history.power_play_goals_last5) if history else None
    goalie_days_since_last_start = None
    if history and history.last_goalie_start_date:
        try:
            goalie_days_since_last_start = float(
                (date.fromisoformat(game_date) - date.fromisoformat(history.last_goalie_start_date)).days
            )
        except ValueError:
            goalie_days_since_last_start = None

    if entry["is_goalie"] == 1 and entry["is_starter_goalie"] == 1:
        role = "goalie_starter"
    elif entry["is_goalie"] == 1:
        role = "goalie_backup"
    elif entry["position"] in {"D"}:
        role = "defense"
    else:
        role = "skater"

    return {
        "season": entry["season"],
        "game_id": entry["game_id"],
        "game_date": game_date,
        "team_abbrev": entry["team_abbrev"],
        "player_id": entry["player_id"],
        "player_name": entry["player_name"],
        "position": entry["position"],
        "lineup_role": role,
        "goalie_starter_source": entry.get("starter_goalie_source"),
        "goalie_starter_api_flag": entry.get("starter_goalie_api_flag"),
        "goalie_starter_certainty": (
            float(entry["starter_goalie_confidence"])
            if entry.get("starter_goalie_confidence") is not None
            else (1.0 if role == "goalie_starter" else 0.0)
        ),
        "is_expected_active": int(entry["played"] == 1),
        "player_games_sample": int(history.games_played) if history else 0,
        "rolling_points_pg_last5": points_pg,
        "rolling_goals_pg_last5": goals_pg,
        "rolling_assists_pg_last5": assists_pg,
        "rolling_toi_minutes_pg_last5": toi_pg,
        "rolling_goalie_save_pct_last5": goalie_save_pct,
        "rolling_plus_minus_pg_last5": plus_minus_pg,
        "rolling_points_pg_last3": points_pg_last3,
        "rolling_points_pg_last10": points_pg_last10,
        "rolling_two_way_idx_last3": two_way_idx_last3,
        "rolling_two_way_idx_last10": two_way_idx_last10,
        "rolling_points_pg_ewm": points_pg_ewm,
        "rolling_two_way_idx_ewm": two_way_idx_ewm,
        "rolling_goalie_save_pct_last10": goalie_save_pct_last10,
        "rolling_goalie_save_pct_ewm": goalie_save_pct_ewm,
        "rolling_goalie_save_pct_last3": goalie_save_pct_last3,
        "rolling_goalie_shots_against_pg_last5": goalie_shots_against_pg_last5,
        "rolling_goalie_shots_against_pg_last3": goalie_shots_against_pg_last3,
        "rolling_goalie_shots_against_pg_last10": goalie_shots_against_pg_last10,
        "rolling_goalie_starts_last5": goalie_starts_last5,
        "rolling_goalie_starts_last10": goalie_starts_last10,
        "goalie_days_since_last_start": goalie_days_since_last_start,
        "rolling_power_play_goals_pg_last5": rolling_power_play_goals_pg_last5,
        "source_stats_through_date": history.latest_prior_date if history else None,
    }


def build_team_feature_row(
    *,
    season: int,
    game_id: int,
    game_date: str,
    team_abbrev: str,
    player_rows: List[Dict],
    active_player_ids: Set[int],
    team_contributor_history: Dict[int, Deque[float]],
    previous_active_players: Optional[Set[int]],
    team_form_history: Deque[float],
    team_adjusted_form_history: Deque[float],
    lineup_continuity_history: Deque[float],
    key_contributor_continuity_history: Deque[float],
    lineup_change_rate_history: Deque[float],
    previous_active_key_contributors: Optional[Set[int]],
) -> Dict:
    active_rows = [row for row in player_rows if row["is_expected_active"] == 1]
    active_skaters = [r for r in active_rows if r["lineup_role"] != "goalie_starter" and r["lineup_role"] != "goalie_backup"]
    active_defense = [r for r in active_rows if r["lineup_role"] == "defense"]
    active_goalies = [r for r in active_rows if "goalie" in str(r["lineup_role"])]

    top6_points = sorted(
        [r["rolling_points_pg_last5"] for r in active_skaters if r["rolling_points_pg_last5"] is not None],
        reverse=True,
    )[:6]
    top9_points = sorted(
        [r["rolling_points_pg_last5"] for r in active_skaters if r["rolling_points_pg_last5"] is not None],
        reverse=True,
    )[:9]
    top4_toi = sorted(
        [r["rolling_toi_minutes_pg_last5"] for r in active_defense if r["rolling_toi_minutes_pg_last5"] is not None],
        reverse=True,
    )[:4]

    starter_candidates = [r for r in active_goalies if r["lineup_role"] == "goalie_starter"]
    starter_goalie = None
    if starter_candidates:
        starter_goalie = sorted(
            starter_candidates,
            key=lambda r: (
                float(r.get("goalie_starter_certainty") or 0.0),
                float(r.get("rolling_goalie_starts_last10") or 0.0),
                float(r.get("rolling_toi_minutes_pg_last5") or 0.0),
                -int(r.get("player_id") or 0),
            ),
            reverse=True,
        )[0]

    backup_goalies = [r for r in active_goalies if starter_goalie is None or r["player_id"] != starter_goalie["player_id"]]
    goalie_starter_certainty = (
        float(starter_goalie.get("goalie_starter_certainty") or 0.0)
        if starter_goalie
        else safe_avg([r.get("goalie_starter_certainty") for r in active_goalies])
    )
    pregame_goalie_save_pct = (
        starter_goalie["rolling_goalie_save_pct_last5"]
        if starter_goalie and starter_goalie["rolling_goalie_save_pct_last5"] is not None
        else safe_avg([r["rolling_goalie_save_pct_last5"] for r in active_goalies])
    )
    pregame_goalie_save_pct_last10 = (
        starter_goalie["rolling_goalie_save_pct_last10"]
        if starter_goalie and starter_goalie["rolling_goalie_save_pct_last10"] is not None
        else safe_avg([r["rolling_goalie_save_pct_last10"] for r in active_goalies])
    )
    pregame_goalie_save_pct_ewm = (
        starter_goalie["rolling_goalie_save_pct_ewm"]
        if starter_goalie and starter_goalie["rolling_goalie_save_pct_ewm"] is not None
        else safe_avg([r["rolling_goalie_save_pct_ewm"] for r in active_goalies])
    )
    pregame_goalie_save_pct_last3 = (
        starter_goalie["rolling_goalie_save_pct_last3"]
        if starter_goalie and starter_goalie["rolling_goalie_save_pct_last3"] is not None
        else safe_avg([r["rolling_goalie_save_pct_last3"] for r in active_goalies])
    )
    pregame_goalie_shots_against_pg_last5 = (
        starter_goalie["rolling_goalie_shots_against_pg_last5"]
        if starter_goalie and starter_goalie["rolling_goalie_shots_against_pg_last5"] is not None
        else safe_avg([r["rolling_goalie_shots_against_pg_last5"] for r in active_goalies])
    )
    goalie_shots_against_pg_last3 = (
        starter_goalie["rolling_goalie_shots_against_pg_last3"]
        if starter_goalie and starter_goalie["rolling_goalie_shots_against_pg_last3"] is not None
        else safe_avg([r["rolling_goalie_shots_against_pg_last3"] for r in active_goalies])
    )
    goalie_shots_against_pg_last10 = (
        starter_goalie["rolling_goalie_shots_against_pg_last10"]
        if starter_goalie and starter_goalie["rolling_goalie_shots_against_pg_last10"] is not None
        else safe_avg([r["rolling_goalie_shots_against_pg_last10"] for r in active_goalies])
    )
    pregame_goalie_shots_against_pg_trend = optional_subtract(goalie_shots_against_pg_last3, goalie_shots_against_pg_last10)
    pregame_goalie_recent_starts_last5 = (
        starter_goalie["rolling_goalie_starts_last5"]
        if starter_goalie and starter_goalie["rolling_goalie_starts_last5"] is not None
        else safe_avg([r["rolling_goalie_starts_last5"] for r in active_goalies])
    )
    pregame_goalie_days_since_last_start = (
        starter_goalie["goalie_days_since_last_start"]
        if starter_goalie and starter_goalie["goalie_days_since_last_start"] is not None
        else safe_avg([r["goalie_days_since_last_start"] for r in active_goalies])
    )
    pregame_goalie_starter_quality_gap_last5 = (
        optional_subtract(
            starter_goalie.get("rolling_goalie_save_pct_last5"),
            safe_avg([r.get("rolling_goalie_save_pct_last5") for r in backup_goalies]),
        )
        if starter_goalie
        else None
    )
    pregame_goalie_starter_quality_gap_last10 = (
        optional_subtract(
            starter_goalie.get("rolling_goalie_save_pct_last10"),
            safe_avg([r.get("rolling_goalie_save_pct_last10") for r in backup_goalies]),
        )
        if starter_goalie
        else None
    )

    expected_prior_core = sorted(
        [
            (pid, sum(scores) / float(len(scores)))
            for pid, scores in team_contributor_history.items()
            if len(scores) > 0
        ],
        key=lambda x: x[1],
        reverse=True,
    )
    core_size = 14
    expected_core_ids = {pid for pid, _score in expected_prior_core[:core_size]}
    expected_key_ids = {pid for pid, _score in expected_prior_core[:6]}
    inferred_absent = len(expected_core_ids - active_player_ids) if expected_core_ids else 0

    covered = len([r for r in active_rows if int(r["player_games_sample"] or 0) > 0])
    active_count = len(active_rows)
    coverage_pct = safe_div(covered, active_count)

    continuity = None
    if previous_active_players is not None and active_count > 0:
        continuity = len(previous_active_players.intersection(active_player_ids)) / float(active_count)
    turnover_count = 0
    if previous_active_players is not None:
        turnover_count = len(previous_active_players.symmetric_difference(active_player_ids))

    top6_points_pg = safe_avg(top6_points)
    top9_points_pg = safe_avg(top9_points)
    top4_avg_toi = safe_avg(top4_toi)
    skater_points_pg_last5 = safe_avg([r["rolling_points_pg_last5"] for r in active_skaters])
    skater_points_pg_last3 = safe_avg([r["rolling_points_pg_last3"] for r in active_skaters])
    skater_points_pg_last10 = safe_avg([r["rolling_points_pg_last10"] for r in active_skaters])
    two_way_samples: List[float] = []
    for r in active_skaters:
        if r["rolling_points_pg_last5"] is None and r["rolling_plus_minus_pg_last5"] is None:
            continue
        points_part = r["rolling_points_pg_last5"] or 0.0
        plus_minus_part = r["rolling_plus_minus_pg_last5"] or 0.0
        two_way_samples.append(points_part + (0.18 * plus_minus_part))
    skater_two_way_idx_last5 = safe_avg(two_way_samples)
    skater_two_way_idx_last3 = safe_avg([r["rolling_two_way_idx_last3"] for r in active_skaters])
    skater_two_way_idx_last10 = safe_avg([r["rolling_two_way_idx_last10"] for r in active_skaters])
    skater_points_pg_ewm = safe_avg([r["rolling_points_pg_ewm"] for r in active_skaters])
    skater_two_way_idx_ewm = safe_avg([r["rolling_two_way_idx_ewm"] for r in active_skaters])
    recent_form_adj_last5 = trailing_mean(team_adjusted_form_history, 5)
    recent_form_adj_last10 = trailing_mean(team_adjusted_form_history, 10)
    recent_form_volatility_last5 = trailing_variance(team_form_history, 5)
    recent_form_volatility_last10 = trailing_variance(team_form_history, 10)
    continuity_ewm = ewm_mean(lineup_continuity_history, alpha=0.5)
    lineup_stability_last5 = trailing_mean(lineup_continuity_history, 5)
    core_retention_pct = safe_div(len(expected_core_ids.intersection(active_player_ids)), len(expected_core_ids))
    active_key_contributors = expected_key_ids.intersection(active_player_ids)
    key_contributor_continuity_pct = safe_div(len(active_key_contributors), len(expected_key_ids))
    key_contributor_change_rate_last5 = trailing_mean(
        [1.0 - x for x in key_contributor_continuity_history if x is not None],
        5,
    )
    lineup_change_rate_last5 = trailing_mean(lineup_change_rate_history, 5)
    total_skater_points_pg_last5 = sum([r["rolling_points_pg_last5"] or 0.0 for r in active_skaters])
    top6_points_total = sum(top6_points)
    depth_points_share_last5 = safe_div(total_skater_points_pg_last5 - top6_points_total, total_skater_points_pg_last5)
    special_teams_contributors = len(
        [r for r in active_skaters if (r.get("rolling_power_play_goals_pg_last5") or 0.0) > 0.0]
    )
    special_teams_contributor_share_last5 = safe_div(special_teams_contributors, len(active_skaters))
    avg_experience_games = safe_avg([float(r["player_games_sample"] or 0) for r in active_rows]) or 0.0
    goalie_component = (pregame_goalie_save_pct - 0.885) * 65.0 if pregame_goalie_save_pct is not None else 0.0
    scoring_component = (top6_points_pg or 0.0) * 2.8
    two_way_component = (skater_two_way_idx_last5 or 0.0) * 1.4
    continuity_component = (continuity or 0.0) * 3.0
    experience_component = avg_experience_games * 0.045
    injury_component = inferred_absent * -0.7
    stability_component = (lineup_stability_last5 or 0.0) * 1.5
    adjusted_form_component = (recent_form_adj_last5 or 0.0) * 1.8
    volatility_component = (recent_form_volatility_last5 or 0.0) * -0.9
    roster_quality_idx = (
        goalie_component
        + scoring_component
        + two_way_component
        + continuity_component
        + experience_component
        + injury_component
        + stability_component
        + adjusted_form_component
        + volatility_component
    )

    source_dates = sorted(
        {
            str(r["source_stats_through_date"])
            for r in active_rows
            if r["source_stats_through_date"] is not None
        }
    )

    return {
        "season": season,
        "game_id": game_id,
        "game_date": game_date,
        "team_abbrev": team_abbrev,
        "pregame_roster_quality_idx": roster_quality_idx,
        "pregame_top6_points_pg": top6_points_pg,
        "pregame_top4_avg_toi": top4_avg_toi,
        "pregame_goalie_save_pct": pregame_goalie_save_pct,
        "pregame_skater_points_pg_last5": skater_points_pg_last5,
        "pregame_skater_points_pg_last3": skater_points_pg_last3,
        "pregame_skater_points_pg_last10": skater_points_pg_last10,
        "pregame_skater_two_way_idx_last5": skater_two_way_idx_last5,
        "pregame_skater_two_way_idx_last3": skater_two_way_idx_last3,
        "pregame_skater_two_way_idx_last10": skater_two_way_idx_last10,
        "pregame_skater_points_pg_ewm": skater_points_pg_ewm,
        "pregame_skater_two_way_idx_ewm": skater_two_way_idx_ewm,
        "pregame_goalie_save_pct_last10": pregame_goalie_save_pct_last10,
        "pregame_goalie_save_pct_ewm": pregame_goalie_save_pct_ewm,
        "pregame_goalie_save_pct_last3": pregame_goalie_save_pct_last3,
        "pregame_goalie_shots_against_pg_last5": pregame_goalie_shots_against_pg_last5,
        "pregame_goalie_shots_against_pg_trend": pregame_goalie_shots_against_pg_trend,
        "pregame_goalie_recent_starts_last5": pregame_goalie_recent_starts_last5,
        "pregame_goalie_days_since_last_start": pregame_goalie_days_since_last_start,
        "pregame_recent_form_adj_last5": recent_form_adj_last5,
        "pregame_recent_form_adj_last10": recent_form_adj_last10,
        "pregame_recent_form_volatility_last5": recent_form_volatility_last5,
        "pregame_recent_form_volatility_last10": recent_form_volatility_last10,
        "pregame_lineup_continuity_pct": continuity,
        "pregame_lineup_continuity_ewm": continuity_ewm,
        "pregame_lineup_stability_last5": lineup_stability_last5,
        "pregame_roster_turnover_count": turnover_count,
        "pregame_core_retention_pct": core_retention_pct,
        "pregame_key_contributor_continuity_pct": key_contributor_continuity_pct,
        "pregame_key_contributor_change_rate_last5": key_contributor_change_rate_last5,
        "pregame_lineup_change_rate_last5": lineup_change_rate_last5,
        "pregame_roster_games_covered": covered,
        "pregame_roster_data_coverage_pct": coverage_pct,
        "pregame_injury_count": inferred_absent,
        "pregame_top9_points_pg": top9_points_pg,
        "pregame_depth_points_share_last5": depth_points_share_last5,
        "pregame_special_teams_contributor_share_last5": special_teams_contributor_share_last5,
        "pregame_confirmed_starters_count": active_count,
        "pregame_goalie_starter_certainty": goalie_starter_certainty,
        "pregame_goalie_starter_quality_gap_last5": pregame_goalie_starter_quality_gap_last5,
        "pregame_goalie_starter_quality_gap_last10": pregame_goalie_starter_quality_gap_last10,
        "roster_source_tag": "historical_game_rosters+historical_player_game_stats",
        "source_stats_through_date": source_dates[-1] if source_dates else None,
    }


def update_player_history(history: PlayerHistory, entry: Dict, game_date: str) -> None:
    if entry["played"] != 1:
        return

    history.games_played += 1
    history.points_last10.append(float(entry["points"] or 0))
    history.goals_last10.append(float(entry["goals"] or 0))
    history.assists_last10.append(float(entry["assists"] or 0))
    history.toi_minutes_last10.append(float(entry["toi_seconds"] or 0) / 60.0)
    history.plus_minus_last10.append(float(entry["plus_minus"] or 0))
    history.points_last5.append(float(entry["points"] or 0))
    history.goals_last5.append(float(entry["goals"] or 0))
    history.assists_last5.append(float(entry["assists"] or 0))
    history.toi_minutes_last5.append(float(entry["toi_seconds"] or 0) / 60.0)
    history.plus_minus_last5.append(float(entry["plus_minus"] or 0))
    history.power_play_goals_last5.append(float(entry.get("power_play_goals") or 0))

    shots_against = entry["shots_against"]
    saves = entry["saves"]
    if entry["is_goalie"] == 1:
        history.goalie_start_flags_last10.append(1 if int(entry.get("is_starter_goalie") or 0) == 1 else 0)
        history.goalie_start_flags_last5.append(1 if int(entry.get("is_starter_goalie") or 0) == 1 else 0)
        if shots_against is not None:
            history.goalie_shots_against_last10.append(float(shots_against))
            history.goalie_shots_against_last5.append(float(shots_against))
        if int(entry.get("is_starter_goalie") or 0) == 1:
            history.last_goalie_start_date = game_date
    if entry["is_goalie"] == 1 and shots_against not in (None, 0) and saves is not None:
        save_pct = safe_div(float(saves), float(shots_against))
        if save_pct is not None:
            history.goalie_save_pct_last10.append(save_pct)
            history.goalie_save_pct_last5.append(save_pct)

    history.latest_prior_date = game_date


def build_roster_tables(
    conn: sqlite3.Connection,
    *,
    roster_table_name: str,
    stats_table_name: str,
    base_table_name: str,
    team_output_table_name: str,
    player_output_table_name: str,
) -> Dict[str, int]:
    alias_map = load_alias_map(conn)
    games = load_games(conn, alias_map)
    pregame_context = load_pregame_context(conn, base_table_name, alias_map)
    roster_stats = load_roster_stats_by_game_team(conn, roster_table_name, stats_table_name, alias_map)

    player_histories: Dict[int, PlayerHistory] = {}
    team_contributor_history: Dict[str, Dict[int, Deque[float]]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=8)))
    team_last_active_players: Dict[str, Set[int]] = {}
    team_form_history: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=10))
    team_adjusted_form_history: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=10))
    team_lineup_continuity_history: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=10))
    team_key_contributor_continuity_history: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=10))
    team_lineup_change_rate_history: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=10))
    player_rows: List[Dict] = []
    team_rows: List[Dict] = []
    team_last_active_key_contributors: Dict[str, Set[int]] = {}

    for game in games:
        season = game["season"]
        game_id = game["game_id"]
        game_date = game["game_date"]
        for team_abbrev in (game["home_team_abbrev"], game["away_team_abbrev"]):
            entries = roster_stats.get((season, game_id, team_abbrev), [])
            if not entries:
                team_rows.append(
                    {
                        "season": season,
                        "game_id": game_id,
                        "game_date": game_date,
                        "team_abbrev": team_abbrev,
                        "pregame_roster_quality_idx": None,
                        "pregame_top6_points_pg": None,
                        "pregame_top4_avg_toi": None,
                        "pregame_goalie_save_pct": None,
                        "pregame_skater_points_pg_last5": None,
                        "pregame_skater_points_pg_last3": None,
                        "pregame_skater_points_pg_last10": None,
                        "pregame_skater_two_way_idx_last5": None,
                        "pregame_skater_two_way_idx_last3": None,
                        "pregame_skater_two_way_idx_last10": None,
                        "pregame_skater_points_pg_ewm": None,
                        "pregame_skater_two_way_idx_ewm": None,
                        "pregame_goalie_save_pct_last10": None,
                        "pregame_goalie_save_pct_ewm": None,
                        "pregame_goalie_save_pct_last3": None,
                        "pregame_goalie_shots_against_pg_last5": None,
                        "pregame_goalie_shots_against_pg_trend": None,
                        "pregame_goalie_recent_starts_last5": None,
                        "pregame_goalie_days_since_last_start": None,
                        "pregame_recent_form_adj_last5": None,
                        "pregame_recent_form_adj_last10": None,
                        "pregame_recent_form_volatility_last5": None,
                        "pregame_recent_form_volatility_last10": None,
                        "pregame_lineup_continuity_pct": None,
                        "pregame_lineup_continuity_ewm": None,
                        "pregame_lineup_stability_last5": None,
                        "pregame_roster_turnover_count": 0,
                        "pregame_core_retention_pct": None,
                        "pregame_key_contributor_continuity_pct": None,
                        "pregame_key_contributor_change_rate_last5": None,
                        "pregame_lineup_change_rate_last5": None,
                        "pregame_roster_games_covered": 0,
                        "pregame_roster_data_coverage_pct": 0.0,
                        "pregame_injury_count": 0,
                        "pregame_top9_points_pg": None,
                        "pregame_depth_points_share_last5": None,
                        "pregame_special_teams_contributor_share_last5": None,
                        "pregame_confirmed_starters_count": 0,
                        "pregame_goalie_starter_certainty": None,
                        "pregame_goalie_starter_quality_gap_last5": None,
                        "pregame_goalie_starter_quality_gap_last10": None,
                        "roster_source_tag": "missing_roster_rows",
                        "source_stats_through_date": None,
                    }
                )
                continue

            per_team_player_rows: List[Dict] = []
            active_player_ids: Set[int] = set()

            for entry in entries:
                player_id = entry["player_id"]
                history = player_histories.get(player_id)
                feature_row = make_player_feature_row(entry, game_date, history)
                per_team_player_rows.append(feature_row)
                if feature_row["is_expected_active"] == 1:
                    active_player_ids.add(player_id)

            team_feature_row = build_team_feature_row(
                season=season,
                game_id=game_id,
                game_date=game_date,
                team_abbrev=team_abbrev,
                player_rows=per_team_player_rows,
                active_player_ids=active_player_ids,
                team_contributor_history=team_contributor_history[team_abbrev],
                previous_active_players=team_last_active_players.get(team_abbrev),
                team_form_history=team_form_history[team_abbrev],
                team_adjusted_form_history=team_adjusted_form_history[team_abbrev],
                lineup_continuity_history=team_lineup_continuity_history[team_abbrev],
                key_contributor_continuity_history=team_key_contributor_continuity_history[team_abbrev],
                lineup_change_rate_history=team_lineup_change_rate_history[team_abbrev],
                previous_active_key_contributors=team_last_active_key_contributors.get(team_abbrev),
            )

            team_rows.append(team_feature_row)
            player_rows.extend(per_team_player_rows)

        for team_abbrev in (game["home_team_abbrev"], game["away_team_abbrev"]):
            entries = roster_stats.get((season, game_id, team_abbrev), [])
            active_ids_for_postgame: Set[int] = set()
            for entry in entries:
                player_id = entry["player_id"]
                history = player_histories.setdefault(player_id, PlayerHistory())
                if entry["played"] == 1:
                    active_ids_for_postgame.add(player_id)
                update_player_history(history, entry, game_date)
                if entry["played"] == 1:
                    team_contributor_history[team_abbrev][player_id].append(
                        scorer_projection_from_history(history, is_goalie=entry["is_goalie"] == 1)
                    )
            active_entries = [e for e in entries if int(e["played"] or 0) == 1]
            if active_entries:
                skater_points_pg = safe_avg(
                    [float(e["points"] or 0) for e in active_entries if int(e["is_goalie"] or 0) != 1]
                )
                goalie_save_samples: List[float] = []
                for e in active_entries:
                    if int(e["is_goalie"] or 0) != 1:
                        continue
                    save_pct = safe_div(e["saves"], e["shots_against"])
                    if save_pct is not None:
                        goalie_save_samples.append(save_pct)
                goalie_save_pg = safe_avg(goalie_save_samples)
                postgame_form_score = (1.8 * (skater_points_pg or 0.0)) + (65.0 * ((goalie_save_pg or 0.885) - 0.885))
                team_form_history[team_abbrev].append(postgame_form_score)
                opp_strength = pregame_context.get((season, game_id, team_abbrev), {}).get("opponent_pregame_points_pct")
                if opp_strength is not None:
                    team_adjusted_form_history[team_abbrev].append(postgame_form_score - float(opp_strength))

            previous = team_last_active_players.get(team_abbrev)
            if previous is not None and len(active_ids_for_postgame) > 0:
                continuity_value = len(previous.intersection(active_ids_for_postgame)) / float(len(active_ids_for_postgame))
                team_lineup_continuity_history[team_abbrev].append(continuity_value)
                team_lineup_change_rate_history[team_abbrev].append(
                    len(previous.symmetric_difference(active_ids_for_postgame)) / float(len(active_ids_for_postgame))
                )

            expected_postgame_rank = sorted(
                [
                    (pid, sum(scores) / float(len(scores)))
                    for pid, scores in team_contributor_history[team_abbrev].items()
                    if len(scores) > 0
                ],
                key=lambda x: x[1],
                reverse=True,
            )
            expected_postgame_key_ids = {pid for pid, _score in expected_postgame_rank[:6]}
            active_key_ids_postgame = expected_postgame_key_ids.intersection(active_ids_for_postgame)
            previous_key_ids = team_last_active_key_contributors.get(team_abbrev)
            if previous_key_ids is not None and len(active_key_ids_postgame) > 0:
                team_key_contributor_continuity_history[team_abbrev].append(
                    len(previous_key_ids.intersection(active_key_ids_postgame)) / float(len(active_key_ids_postgame))
                )
            team_last_active_key_contributors[team_abbrev] = active_key_ids_postgame
            team_last_active_players[team_abbrev] = active_ids_for_postgame

    ensure_player_roster_table(conn, player_output_table_name)
    ensure_team_roster_table(conn, team_output_table_name)

    if player_rows:
        conn.executemany(
            f"""
            INSERT INTO "{player_output_table_name}" (
                season, game_id, game_date, team_abbrev, player_id, player_name, position, lineup_role,
                goalie_starter_source, goalie_starter_api_flag, goalie_starter_certainty,
                is_expected_active, player_games_sample, rolling_points_pg_last5, rolling_goals_pg_last5,
                rolling_assists_pg_last5, rolling_toi_minutes_pg_last5, rolling_goalie_save_pct_last5,
                rolling_plus_minus_pg_last5, rolling_points_pg_last3, rolling_points_pg_last10,
                rolling_two_way_idx_last3, rolling_two_way_idx_last10, rolling_points_pg_ewm, rolling_two_way_idx_ewm,
                rolling_goalie_save_pct_last10, rolling_goalie_save_pct_ewm, rolling_goalie_save_pct_last3,
                rolling_goalie_shots_against_pg_last5, rolling_goalie_shots_against_pg_last3,
                rolling_goalie_shots_against_pg_last10, rolling_goalie_starts_last5, rolling_goalie_starts_last10,
                goalie_days_since_last_start, rolling_power_play_goals_pg_last5, source_stats_through_date
            ) VALUES (
                :season, :game_id, :game_date, :team_abbrev, :player_id, :player_name, :position, :lineup_role,
                :goalie_starter_source, :goalie_starter_api_flag, :goalie_starter_certainty,
                :is_expected_active, :player_games_sample, :rolling_points_pg_last5, :rolling_goals_pg_last5,
                :rolling_assists_pg_last5, :rolling_toi_minutes_pg_last5, :rolling_goalie_save_pct_last5,
                :rolling_plus_minus_pg_last5, :rolling_points_pg_last3, :rolling_points_pg_last10,
                :rolling_two_way_idx_last3, :rolling_two_way_idx_last10, :rolling_points_pg_ewm, :rolling_two_way_idx_ewm,
                :rolling_goalie_save_pct_last10, :rolling_goalie_save_pct_ewm, :rolling_goalie_save_pct_last3,
                :rolling_goalie_shots_against_pg_last5, :rolling_goalie_shots_against_pg_last3,
                :rolling_goalie_shots_against_pg_last10, :rolling_goalie_starts_last5, :rolling_goalie_starts_last10,
                :goalie_days_since_last_start, :rolling_power_play_goals_pg_last5, :source_stats_through_date
            )
            """,
            player_rows,
        )
    if team_rows:
        conn.executemany(
            f"""
            INSERT INTO "{team_output_table_name}" (
                season, game_id, game_date, team_abbrev, pregame_roster_quality_idx, pregame_top6_points_pg,
                pregame_top4_avg_toi, pregame_goalie_save_pct, pregame_skater_points_pg_last5,
                pregame_skater_points_pg_last3, pregame_skater_points_pg_last10, pregame_skater_two_way_idx_last5,
                pregame_skater_two_way_idx_last3, pregame_skater_two_way_idx_last10, pregame_skater_points_pg_ewm,
                pregame_skater_two_way_idx_ewm, pregame_goalie_save_pct_last10, pregame_goalie_save_pct_ewm,
                pregame_goalie_save_pct_last3, pregame_goalie_shots_against_pg_last5, pregame_goalie_shots_against_pg_trend,
                pregame_goalie_recent_starts_last5, pregame_goalie_days_since_last_start,
                pregame_recent_form_adj_last5, pregame_recent_form_adj_last10, pregame_recent_form_volatility_last5,
                pregame_recent_form_volatility_last10, pregame_lineup_continuity_pct, pregame_lineup_continuity_ewm,
                pregame_lineup_stability_last5, pregame_roster_turnover_count, pregame_core_retention_pct,
                pregame_key_contributor_continuity_pct, pregame_key_contributor_change_rate_last5, pregame_lineup_change_rate_last5,
                pregame_roster_games_covered, pregame_roster_data_coverage_pct, pregame_injury_count, pregame_top9_points_pg,
                pregame_depth_points_share_last5, pregame_special_teams_contributor_share_last5,
                pregame_confirmed_starters_count, pregame_goalie_starter_certainty,
                pregame_goalie_starter_quality_gap_last5, pregame_goalie_starter_quality_gap_last10,
                roster_source_tag, source_stats_through_date
            ) VALUES (
                :season, :game_id, :game_date, :team_abbrev, :pregame_roster_quality_idx, :pregame_top6_points_pg,
                :pregame_top4_avg_toi, :pregame_goalie_save_pct, :pregame_skater_points_pg_last5,
                :pregame_skater_points_pg_last3, :pregame_skater_points_pg_last10, :pregame_skater_two_way_idx_last5,
                :pregame_skater_two_way_idx_last3, :pregame_skater_two_way_idx_last10, :pregame_skater_points_pg_ewm,
                :pregame_skater_two_way_idx_ewm, :pregame_goalie_save_pct_last10, :pregame_goalie_save_pct_ewm,
                :pregame_goalie_save_pct_last3, :pregame_goalie_shots_against_pg_last5, :pregame_goalie_shots_against_pg_trend,
                :pregame_goalie_recent_starts_last5, :pregame_goalie_days_since_last_start,
                :pregame_recent_form_adj_last5, :pregame_recent_form_adj_last10, :pregame_recent_form_volatility_last5,
                :pregame_recent_form_volatility_last10, :pregame_lineup_continuity_pct, :pregame_lineup_continuity_ewm,
                :pregame_lineup_stability_last5, :pregame_roster_turnover_count, :pregame_core_retention_pct,
                :pregame_key_contributor_continuity_pct, :pregame_key_contributor_change_rate_last5, :pregame_lineup_change_rate_last5,
                :pregame_roster_games_covered, :pregame_roster_data_coverage_pct, :pregame_injury_count, :pregame_top9_points_pg,
                :pregame_depth_points_share_last5, :pregame_special_teams_contributor_share_last5,
                :pregame_confirmed_starters_count, :pregame_goalie_starter_certainty,
                :pregame_goalie_starter_quality_gap_last5, :pregame_goalie_starter_quality_gap_last10,
                :roster_source_tag, :source_stats_through_date
            )
            """,
            team_rows,
        )

    return {
        "games_loaded": len(games),
        "player_rows_built": len(player_rows),
        "team_rows_built": len(team_rows),
    }


def build_rows(base_rows: List[Dict], roster_features: Dict[Tuple[int, int, str], Dict]) -> List[Dict]:
    out_rows: List[Dict] = []

    for base in base_rows:
        season = int(base["season"])
        game_id = int(base["game_id"])
        home_abbrev = str(base["home_team_abbrev"]).upper()
        away_abbrev = str(base["away_team_abbrev"]).upper()

        home = roster_features.get((season, game_id, home_abbrev), {})
        away = roster_features.get((season, game_id, away_abbrev), {})

        row = dict(base)
        row["home_pregame_roster_quality_idx"] = home.get("pregame_roster_quality_idx")
        row["away_pregame_roster_quality_idx"] = away.get("pregame_roster_quality_idx")
        row["home_pregame_top6_points_pg"] = home.get("pregame_top6_points_pg")
        row["away_pregame_top6_points_pg"] = away.get("pregame_top6_points_pg")
        row["home_pregame_top4_avg_toi"] = home.get("pregame_top4_avg_toi")
        row["away_pregame_top4_avg_toi"] = away.get("pregame_top4_avg_toi")
        row["home_pregame_goalie_save_pct"] = home.get("pregame_goalie_save_pct")
        row["away_pregame_goalie_save_pct"] = away.get("pregame_goalie_save_pct")
        row["home_pregame_skater_points_pg_last5"] = home.get("pregame_skater_points_pg_last5")
        row["away_pregame_skater_points_pg_last5"] = away.get("pregame_skater_points_pg_last5")
        row["home_pregame_skater_points_pg_last3"] = home.get("pregame_skater_points_pg_last3")
        row["away_pregame_skater_points_pg_last3"] = away.get("pregame_skater_points_pg_last3")
        row["home_pregame_skater_points_pg_last10"] = home.get("pregame_skater_points_pg_last10")
        row["away_pregame_skater_points_pg_last10"] = away.get("pregame_skater_points_pg_last10")
        row["home_pregame_skater_two_way_idx_last5"] = home.get("pregame_skater_two_way_idx_last5")
        row["away_pregame_skater_two_way_idx_last5"] = away.get("pregame_skater_two_way_idx_last5")
        row["home_pregame_skater_two_way_idx_last3"] = home.get("pregame_skater_two_way_idx_last3")
        row["away_pregame_skater_two_way_idx_last3"] = away.get("pregame_skater_two_way_idx_last3")
        row["home_pregame_skater_two_way_idx_last10"] = home.get("pregame_skater_two_way_idx_last10")
        row["away_pregame_skater_two_way_idx_last10"] = away.get("pregame_skater_two_way_idx_last10")
        row["home_pregame_skater_points_pg_ewm"] = home.get("pregame_skater_points_pg_ewm")
        row["away_pregame_skater_points_pg_ewm"] = away.get("pregame_skater_points_pg_ewm")
        row["home_pregame_skater_two_way_idx_ewm"] = home.get("pregame_skater_two_way_idx_ewm")
        row["away_pregame_skater_two_way_idx_ewm"] = away.get("pregame_skater_two_way_idx_ewm")
        row["home_pregame_goalie_save_pct_last10"] = home.get("pregame_goalie_save_pct_last10")
        row["away_pregame_goalie_save_pct_last10"] = away.get("pregame_goalie_save_pct_last10")
        row["home_pregame_goalie_save_pct_ewm"] = home.get("pregame_goalie_save_pct_ewm")
        row["away_pregame_goalie_save_pct_ewm"] = away.get("pregame_goalie_save_pct_ewm")
        row["home_pregame_goalie_save_pct_last3"] = home.get("pregame_goalie_save_pct_last3")
        row["away_pregame_goalie_save_pct_last3"] = away.get("pregame_goalie_save_pct_last3")
        row["home_pregame_goalie_shots_against_pg_last5"] = home.get("pregame_goalie_shots_against_pg_last5")
        row["away_pregame_goalie_shots_against_pg_last5"] = away.get("pregame_goalie_shots_against_pg_last5")
        row["home_pregame_goalie_shots_against_pg_trend"] = home.get("pregame_goalie_shots_against_pg_trend")
        row["away_pregame_goalie_shots_against_pg_trend"] = away.get("pregame_goalie_shots_against_pg_trend")
        row["home_pregame_goalie_recent_starts_last5"] = home.get("pregame_goalie_recent_starts_last5")
        row["away_pregame_goalie_recent_starts_last5"] = away.get("pregame_goalie_recent_starts_last5")
        row["home_pregame_goalie_days_since_last_start"] = home.get("pregame_goalie_days_since_last_start")
        row["away_pregame_goalie_days_since_last_start"] = away.get("pregame_goalie_days_since_last_start")
        row["home_pregame_recent_form_adj_last5"] = home.get("pregame_recent_form_adj_last5")
        row["away_pregame_recent_form_adj_last5"] = away.get("pregame_recent_form_adj_last5")
        row["home_pregame_recent_form_adj_last10"] = home.get("pregame_recent_form_adj_last10")
        row["away_pregame_recent_form_adj_last10"] = away.get("pregame_recent_form_adj_last10")
        row["home_pregame_recent_form_volatility_last5"] = home.get("pregame_recent_form_volatility_last5")
        row["away_pregame_recent_form_volatility_last5"] = away.get("pregame_recent_form_volatility_last5")
        row["home_pregame_recent_form_volatility_last10"] = home.get("pregame_recent_form_volatility_last10")
        row["away_pregame_recent_form_volatility_last10"] = away.get("pregame_recent_form_volatility_last10")
        row["home_pregame_lineup_continuity_pct"] = home.get("pregame_lineup_continuity_pct")
        row["away_pregame_lineup_continuity_pct"] = away.get("pregame_lineup_continuity_pct")
        row["home_pregame_lineup_continuity_ewm"] = home.get("pregame_lineup_continuity_ewm")
        row["away_pregame_lineup_continuity_ewm"] = away.get("pregame_lineup_continuity_ewm")
        row["home_pregame_lineup_stability_last5"] = home.get("pregame_lineup_stability_last5")
        row["away_pregame_lineup_stability_last5"] = away.get("pregame_lineup_stability_last5")
        row["home_pregame_roster_turnover_count"] = home.get("pregame_roster_turnover_count")
        row["away_pregame_roster_turnover_count"] = away.get("pregame_roster_turnover_count")
        row["home_pregame_core_retention_pct"] = home.get("pregame_core_retention_pct")
        row["away_pregame_core_retention_pct"] = away.get("pregame_core_retention_pct")
        row["home_pregame_key_contributor_continuity_pct"] = home.get("pregame_key_contributor_continuity_pct")
        row["away_pregame_key_contributor_continuity_pct"] = away.get("pregame_key_contributor_continuity_pct")
        row["home_pregame_key_contributor_change_rate_last5"] = home.get("pregame_key_contributor_change_rate_last5")
        row["away_pregame_key_contributor_change_rate_last5"] = away.get("pregame_key_contributor_change_rate_last5")
        row["home_pregame_lineup_change_rate_last5"] = home.get("pregame_lineup_change_rate_last5")
        row["away_pregame_lineup_change_rate_last5"] = away.get("pregame_lineup_change_rate_last5")
        row["home_pregame_roster_games_covered"] = home.get("pregame_roster_games_covered")
        row["away_pregame_roster_games_covered"] = away.get("pregame_roster_games_covered")
        row["home_pregame_roster_data_coverage_pct"] = home.get("pregame_roster_data_coverage_pct")
        row["away_pregame_roster_data_coverage_pct"] = away.get("pregame_roster_data_coverage_pct")
        row["home_pregame_injury_count"] = home.get("pregame_injury_count")
        row["away_pregame_injury_count"] = away.get("pregame_injury_count")
        row["home_pregame_top9_points_pg"] = home.get("pregame_top9_points_pg")
        row["away_pregame_top9_points_pg"] = away.get("pregame_top9_points_pg")
        row["home_pregame_depth_points_share_last5"] = home.get("pregame_depth_points_share_last5")
        row["away_pregame_depth_points_share_last5"] = away.get("pregame_depth_points_share_last5")
        row["home_pregame_special_teams_contributor_share_last5"] = home.get(
            "pregame_special_teams_contributor_share_last5"
        )
        row["away_pregame_special_teams_contributor_share_last5"] = away.get(
            "pregame_special_teams_contributor_share_last5"
        )
        row["home_pregame_confirmed_starters_count"] = home.get("pregame_confirmed_starters_count")
        row["away_pregame_confirmed_starters_count"] = away.get("pregame_confirmed_starters_count")
        row["home_pregame_goalie_starter_certainty"] = home.get("pregame_goalie_starter_certainty")
        row["away_pregame_goalie_starter_certainty"] = away.get("pregame_goalie_starter_certainty")
        row["home_pregame_goalie_starter_quality_gap_last5"] = home.get("pregame_goalie_starter_quality_gap_last5")
        row["away_pregame_goalie_starter_quality_gap_last5"] = away.get("pregame_goalie_starter_quality_gap_last5")
        row["home_pregame_goalie_starter_quality_gap_last10"] = home.get("pregame_goalie_starter_quality_gap_last10")
        row["away_pregame_goalie_starter_quality_gap_last10"] = away.get("pregame_goalie_starter_quality_gap_last10")
        row["home_roster_source_tag"] = home.get("roster_source_tag")
        row["away_roster_source_tag"] = away.get("roster_source_tag")
        row["home_roster_source_stats_through_date"] = home.get("source_stats_through_date")
        row["away_roster_source_stats_through_date"] = away.get("source_stats_through_date")

        row["delta_pregame_roster_quality_idx_home_minus_away"] = optional_subtract(
            row["home_pregame_roster_quality_idx"], row["away_pregame_roster_quality_idx"]
        )
        row["delta_pregame_goalie_save_pct_home_minus_away"] = optional_subtract(
            row["home_pregame_goalie_save_pct"], row["away_pregame_goalie_save_pct"]
        )
        row["delta_pregame_skater_points_pg_last5_home_minus_away"] = optional_subtract(
            row["home_pregame_skater_points_pg_last5"], row["away_pregame_skater_points_pg_last5"]
        )
        row["delta_pregame_skater_two_way_idx_last5_home_minus_away"] = optional_subtract(
            row["home_pregame_skater_two_way_idx_last5"], row["away_pregame_skater_two_way_idx_last5"]
        )
        row["delta_pregame_recent_form_adj_last5_home_minus_away"] = optional_subtract(
            row["home_pregame_recent_form_adj_last5"], row["away_pregame_recent_form_adj_last5"]
        )
        row["delta_pregame_recent_form_volatility_last5_home_minus_away"] = optional_subtract(
            row["home_pregame_recent_form_volatility_last5"], row["away_pregame_recent_form_volatility_last5"]
        )
        row["delta_pregame_lineup_continuity_pct_home_minus_away"] = optional_subtract(
            row["home_pregame_lineup_continuity_pct"], row["away_pregame_lineup_continuity_pct"]
        )
        row["delta_pregame_roster_turnover_count_home_minus_away"] = optional_subtract(
            row["home_pregame_roster_turnover_count"], row["away_pregame_roster_turnover_count"]
        )
        row["delta_pregame_injury_count_home_minus_away"] = optional_subtract(
            row["home_pregame_injury_count"], row["away_pregame_injury_count"]
        )
        row["delta_pregame_goalie_shots_against_pg_trend_home_minus_away"] = optional_subtract(
            row["home_pregame_goalie_shots_against_pg_trend"], row["away_pregame_goalie_shots_against_pg_trend"]
        )
        row["delta_pregame_goalie_recent_starts_last5_home_minus_away"] = optional_subtract(
            row["home_pregame_goalie_recent_starts_last5"], row["away_pregame_goalie_recent_starts_last5"]
        )
        row["delta_pregame_goalie_days_since_last_start_home_minus_away"] = optional_subtract(
            row["home_pregame_goalie_days_since_last_start"], row["away_pregame_goalie_days_since_last_start"]
        )
        row["delta_pregame_top9_points_pg_home_minus_away"] = optional_subtract(
            row["home_pregame_top9_points_pg"], row["away_pregame_top9_points_pg"]
        )
        row["delta_pregame_depth_points_share_last5_home_minus_away"] = optional_subtract(
            row["home_pregame_depth_points_share_last5"], row["away_pregame_depth_points_share_last5"]
        )
        row["delta_pregame_special_teams_contributor_share_last5_home_minus_away"] = optional_subtract(
            row["home_pregame_special_teams_contributor_share_last5"],
            row["away_pregame_special_teams_contributor_share_last5"],
        )
        row["delta_pregame_key_contributor_continuity_pct_home_minus_away"] = optional_subtract(
            row["home_pregame_key_contributor_continuity_pct"], row["away_pregame_key_contributor_continuity_pct"]
        )
        row["delta_pregame_lineup_change_rate_last5_home_minus_away"] = optional_subtract(
            row["home_pregame_lineup_change_rate_last5"], row["away_pregame_lineup_change_rate_last5"]
        )
        row["delta_pregame_goalie_starter_certainty_home_minus_away"] = optional_subtract(
            row["home_pregame_goalie_starter_certainty"], row["away_pregame_goalie_starter_certainty"]
        )
        row["delta_pregame_goalie_starter_quality_gap_last5_home_minus_away"] = optional_subtract(
            row["home_pregame_goalie_starter_quality_gap_last5"],
            row["away_pregame_goalie_starter_quality_gap_last5"],
        )
        row["delta_pregame_goalie_starter_quality_gap_last10_home_minus_away"] = optional_subtract(
            row["home_pregame_goalie_starter_quality_gap_last10"],
            row["away_pregame_goalie_starter_quality_gap_last10"],
        )

        out_rows.append(row)

    return out_rows


def write_csv(rows: List[Dict], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [name for name, _ in FINAL_COLUMNS]
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_sqlite(conn: sqlite3.Connection, table_name: str, rows: List[Dict]) -> None:
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    col_defs = ", ".join([f'"{c}" {t}' for c, t in FINAL_COLUMNS])
    conn.execute(f'CREATE TABLE "{table_name}" ({col_defs})')

    col_names = [c for c, _ in FINAL_COLUMNS]
    placeholders = ", ".join(["?"] * len(col_names))
    quoted_cols = ", ".join([f'"{c}"' for c in col_names])
    insert_sql = f'INSERT INTO "{table_name}" ({quoted_cols}) VALUES ({placeholders})'
    if rows:
        conn.executemany(insert_sql, [[row.get(c) for c in col_names] for row in rows])
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_season_date" ON "{table_name}" (season, game_date, game_id)'
    )


NEW_TEMPORAL_COLUMNS: List[str] = [
    "home_pregame_skater_points_pg_last3",
    "away_pregame_skater_points_pg_last3",
    "home_pregame_skater_points_pg_last10",
    "away_pregame_skater_points_pg_last10",
    "home_pregame_skater_two_way_idx_last3",
    "away_pregame_skater_two_way_idx_last3",
    "home_pregame_skater_two_way_idx_last10",
    "away_pregame_skater_two_way_idx_last10",
    "home_pregame_skater_points_pg_ewm",
    "away_pregame_skater_points_pg_ewm",
    "home_pregame_skater_two_way_idx_ewm",
    "away_pregame_skater_two_way_idx_ewm",
    "home_pregame_goalie_save_pct_last10",
    "away_pregame_goalie_save_pct_last10",
    "home_pregame_goalie_save_pct_ewm",
    "away_pregame_goalie_save_pct_ewm",
    "home_pregame_goalie_save_pct_last3",
    "away_pregame_goalie_save_pct_last3",
    "home_pregame_goalie_shots_against_pg_last5",
    "away_pregame_goalie_shots_against_pg_last5",
    "home_pregame_goalie_shots_against_pg_trend",
    "away_pregame_goalie_shots_against_pg_trend",
    "home_pregame_goalie_recent_starts_last5",
    "away_pregame_goalie_recent_starts_last5",
    "home_pregame_goalie_days_since_last_start",
    "away_pregame_goalie_days_since_last_start",
    "home_pregame_recent_form_adj_last5",
    "away_pregame_recent_form_adj_last5",
    "home_pregame_recent_form_adj_last10",
    "away_pregame_recent_form_adj_last10",
    "home_pregame_recent_form_volatility_last5",
    "away_pregame_recent_form_volatility_last5",
    "home_pregame_recent_form_volatility_last10",
    "away_pregame_recent_form_volatility_last10",
    "home_pregame_lineup_continuity_pct",
    "away_pregame_lineup_continuity_pct",
    "home_pregame_lineup_continuity_ewm",
    "away_pregame_lineup_continuity_ewm",
    "home_pregame_lineup_stability_last5",
    "away_pregame_lineup_stability_last5",
    "home_pregame_key_contributor_continuity_pct",
    "away_pregame_key_contributor_continuity_pct",
    "home_pregame_key_contributor_change_rate_last5",
    "away_pregame_key_contributor_change_rate_last5",
    "home_pregame_lineup_change_rate_last5",
    "away_pregame_lineup_change_rate_last5",
    "home_pregame_roster_turnover_count",
    "away_pregame_roster_turnover_count",
    "home_pregame_top9_points_pg",
    "away_pregame_top9_points_pg",
    "home_pregame_depth_points_share_last5",
    "away_pregame_depth_points_share_last5",
    "home_pregame_special_teams_contributor_share_last5",
    "away_pregame_special_teams_contributor_share_last5",
    "home_pregame_core_retention_pct",
    "away_pregame_core_retention_pct",
    "delta_pregame_goalie_shots_against_pg_trend_home_minus_away",
    "delta_pregame_goalie_recent_starts_last5_home_minus_away",
    "delta_pregame_goalie_days_since_last_start_home_minus_away",
    "delta_pregame_top9_points_pg_home_minus_away",
    "delta_pregame_depth_points_share_last5_home_minus_away",
    "delta_pregame_special_teams_contributor_share_last5_home_minus_away",
    "delta_pregame_key_contributor_continuity_pct_home_minus_away",
    "delta_pregame_lineup_change_rate_last5_home_minus_away",
    "delta_pregame_recent_form_adj_last5_home_minus_away",
    "delta_pregame_recent_form_volatility_last5_home_minus_away",
    "delta_pregame_lineup_continuity_pct_home_minus_away",
    "delta_pregame_roster_turnover_count_home_minus_away",
    "home_pregame_goalie_starter_certainty",
    "away_pregame_goalie_starter_certainty",
    "home_pregame_goalie_starter_quality_gap_last5",
    "away_pregame_goalie_starter_quality_gap_last5",
    "home_pregame_goalie_starter_quality_gap_last10",
    "away_pregame_goalie_starter_quality_gap_last10",
    "delta_pregame_goalie_starter_certainty_home_minus_away",
    "delta_pregame_goalie_starter_quality_gap_last5_home_minus_away",
    "delta_pregame_goalie_starter_quality_gap_last10_home_minus_away",
]


def compute_coverage_diagnostics(rows: List[Dict], columns: List[str]) -> List[Dict]:
    total = len(rows)
    diagnostics: List[Dict] = []
    for col in columns:
        non_null = sum(1 for row in rows if row.get(col) is not None)
        coverage_pct = (100.0 * non_null / float(total)) if total else 0.0
        diagnostics.append(
            {
                "column": col,
                "non_null_count": non_null,
                "total_rows": total,
                "coverage_pct": coverage_pct,
            }
        )
    return diagnostics


def write_feature_report(report_path: Path, diagnostics: List[Dict]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Advanced temporal roster feature update",
        "",
        "## Added leakage-safe pregame temporal features",
        "- Goalie trend/workload: save% windows, shots-against trend, recent starter workload, days since last start.",
        "- Starter-goalie fidelity: deterministic starter certainty plus starter-vs-backup quality gap (last5/last10 save%).",
        "- Skater depth production: top-9 scoring signal, depth scoring share, and special-teams contributor share.",
        "- Availability continuity proxies: key-contributor continuity and lineup/key-contributor change rates.",
        "- Multi-window rolling windows (last 3/5/10) for skater scoring and two-way form.",
        "- Exponentially weighted recency (EWM) for skaters, two-way index, and goalie save%.",
        "- Team recent-form volatility (variance) and opponent-strength-adjusted form trends.",
        "- Roster stability and continuity: lineup continuity, recent stability, turnover, and core retention.",
        "",
        "## Leakage guardrail",
        "- Every feature is computed strictly from each team/player history prior to the current game.",
        "- Current-game stats are only applied to history after feature rows are emitted.",
        "",
        "## Coverage diagnostics (new columns)",
        "| column | non_null_count | total_rows | coverage_pct |",
        "|---|---:|---:|---:|",
    ]
    for item in diagnostics:
        lines.append(
            f"| `{item['column']}` | {item['non_null_count']} | {item['total_rows']} | {item['coverage_pct']:.2f}% |"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    sqlite_db = Path(args.sqlite_db).resolve() if args.sqlite_db else repo_root / "data" / "processed" / "nhl_research.db"
    output_csv = (
        Path(args.output_csv).resolve()
        if args.output_csv
        else repo_root / "data" / "processed" / "backtest_features_last5_roster.csv"
    )
    report_path = (
        Path(args.report_path).resolve()
        if args.report_path
        else repo_root / "data" / "reports" / "roster_advanced_temporal_features_notes.md"
    )

    with sqlite3.connect(sqlite_db) as conn:
        build_summary = build_roster_tables(
            conn,
            roster_table_name=args.game_rosters_table_name,
            stats_table_name=args.player_stats_table_name,
            base_table_name=args.base_table_name,
            team_output_table_name=args.team_roster_table_name,
            player_output_table_name=args.player_roster_table_name,
        )
        ensure_final_table(conn, args.final_table_name)
        base_rows = load_base_rows(conn, args.base_table_name)
        roster_features = load_roster_team_features(conn, args.team_roster_table_name)
        final_rows = build_rows(base_rows, roster_features)
        write_sqlite(conn, args.final_table_name, final_rows)
        conn.commit()

    write_csv(final_rows, output_csv)
    diagnostics = compute_coverage_diagnostics(final_rows, NEW_TEMPORAL_COLUMNS)
    write_feature_report(report_path, diagnostics)

    print(f"sqlite_db={sqlite_db}")
    print(f"base_table={args.base_table_name}")
    print(f"roster_team_input_table={args.team_roster_table_name}")
    print(f"roster_player_output_table={args.player_roster_table_name}")
    print(f"final_table={args.final_table_name}")
    print(f"games_loaded={build_summary['games_loaded']}")
    print(f"roster_player_rows_built={build_summary['player_rows_built']}")
    print(f"roster_team_rows_built={build_summary['team_rows_built']}")
    print(f"rows_built={len(final_rows)}")
    print(f"output_csv={output_csv}")
    print(f"report_path={report_path}")
    for item in diagnostics:
        print(
            f"coverage[{item['column']}]={item['non_null_count']}/{item['total_rows']} ({item['coverage_pct']:.2f}%)"
        )


if __name__ == "__main__":
    main()
