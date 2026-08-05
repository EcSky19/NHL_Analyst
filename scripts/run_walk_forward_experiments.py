import argparse
import csv
import itertools
import json
import math
import random
import sqlite3
import subprocess
import sys
import time
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


EPS = 1e-6
INTERACTION_PRIOR_STRENGTH = 8.0


BASE_FEATURE_CANDIDATES = [
    "delta_pregame_last10_points_pct_home_minus_away",
    "delta_pregame_last10_goal_diff_pg_home_minus_away",
    "delta_pregame_season_points_pct_home_minus_away",
    "delta_pregame_season_goal_diff_pg_home_minus_away",
    "home_location_edge_points_pct",
    "rest_days_delta_home_minus_away",
    "home_back_to_back",
    "away_back_to_back",
    "home_pregame_streak_signed",
    "away_pregame_streak_signed",
    "home_prior_prev_season_points_pct",
    "away_prior_prev_season_points_pct",
    "home_prior_prev_season_goal_diff_pg",
    "away_prior_prev_season_goal_diff_pg",
    "home_three_in_four",
    "away_three_in_four",
    "home_four_in_six",
    "away_four_in_six",
    "delta_travel_miles_home_minus_away",
    "delta_timezone_shift_hours_home_minus_away",
    "delta_home_stand_len_home_minus_away",
    "delta_road_trip_len_home_minus_away",
]

ROSTER_FEATURE_CANDIDATES = [
    "delta_pregame_roster_quality_idx_home_minus_away",
    "delta_pregame_goalie_save_pct_home_minus_away",
    "delta_pregame_skater_points_pg_last5_home_minus_away",
    "delta_pregame_skater_two_way_idx_last5_home_minus_away",
    "delta_pregame_injury_count_home_minus_away",
    "home_pregame_roster_data_coverage_pct",
    "away_pregame_roster_data_coverage_pct",
    "home_pregame_roster_games_covered",
    "away_pregame_roster_games_covered",
    "delta_pregame_goalie_shots_against_pg_trend_home_minus_away",
    "delta_pregame_goalie_recent_starts_last5_home_minus_away",
    "delta_pregame_goalie_days_since_last_start_home_minus_away",
    "delta_pregame_goalie_starter_quality_gap_last5_home_minus_away",
    "delta_pregame_goalie_starter_quality_gap_last10_home_minus_away",
    "delta_pregame_top9_points_pg_home_minus_away",
    "delta_pregame_depth_points_share_last5_home_minus_away",
    "delta_pregame_special_teams_contributor_share_last5_home_minus_away",
    "delta_pregame_key_contributor_continuity_pct_home_minus_away",
    "delta_pregame_lineup_change_rate_last5_home_minus_away",
    "delta_pregame_recent_form_adj_last5_home_minus_away",
    "delta_pregame_recent_form_volatility_last5_home_minus_away",
    "delta_pregame_lineup_continuity_pct_home_minus_away",
    "delta_pregame_roster_turnover_count_home_minus_away",
    "home_power_play_pct",
    "away_power_play_pct",
    "home_penalty_kill_pct",
    "away_penalty_kill_pct",
    "delta_power_play_pct_home_minus_away",
    "delta_penalty_kill_pct_home_minus_away",
    "home_home_vs_away_win_pct_diff",
    "away_home_vs_away_win_pct_diff",
    "home_gd_volatility_last5",
    "away_gd_volatility_last5",
    "home_momentum_10game_trend",
    "away_momentum_10game_trend",
    "home_momentum_trend_direction",
    "away_momentum_trend_direction",
    "games_since_deadline",
    "games_until_deadline",
    "delta_pregame_top6_points_pg_home_minus_away",
    "delta_pregame_top4_avg_toi_home_minus_away",
    "delta_pregame_skater_points_pg_last3_home_minus_away",
    "delta_pregame_skater_points_pg_last10_home_minus_away",
    "delta_pregame_skater_two_way_idx_last3_home_minus_away",
    "delta_pregame_skater_two_way_idx_last10_home_minus_away",
    "delta_pregame_skater_points_pg_ewm_home_minus_away",
    "delta_pregame_skater_two_way_idx_ewm_home_minus_away",
    "delta_pregame_goalie_save_pct_last10_home_minus_away",
    "delta_pregame_goalie_save_pct_ewm_home_minus_away",
    "delta_pregame_goalie_save_pct_last3_home_minus_away",
    "delta_pregame_goalie_shots_against_pg_last5_home_minus_away",
    "delta_pregame_recent_form_volatility_last10_home_minus_away",
    "delta_pregame_lineup_continuity_ewm_home_minus_away",
    "delta_pregame_lineup_stability_last5_home_minus_away",
    "delta_pregame_core_retention_pct_home_minus_away",
    "delta_pregame_key_contributor_change_rate_last5_home_minus_away",
    "delta_pregame_roster_games_covered_home_minus_away",
    "delta_pregame_roster_data_coverage_pct_home_minus_away",
    "delta_pregame_confirmed_starters_count_home_minus_away",
    "delta_gd_volatility_last5_home_minus_away",
]

WEIGHTED_MODEL_WEIGHTS = {
    "delta_pregame_last10_points_pct_home_minus_away": 1.35,
    "delta_pregame_last10_goal_diff_pg_home_minus_away": 1.15,
    "delta_pregame_season_points_pct_home_minus_away": 1.00,
    "delta_pregame_season_goal_diff_pg_home_minus_away": 0.95,
    "home_location_edge_points_pct": 0.55,
    "home_pregame_streak_signed": 0.40,
    "away_pregame_streak_signed": -0.40,
    "rest_days_delta_home_minus_away": 0.30,
    "home_back_to_back": -0.35,
    "away_back_to_back": 0.35,
    "delta_pregame_roster_quality_idx_home_minus_away": 1.10,
    "delta_pregame_goalie_save_pct_home_minus_away": 0.95,
    "delta_pregame_skater_points_pg_last5_home_minus_away": 0.75,
    "delta_pregame_skater_two_way_idx_last5_home_minus_away": 0.55,
    "delta_pregame_injury_count_home_minus_away": -0.50,
    "delta_pregame_goalie_starter_quality_gap_last5_home_minus_away": 0.28,
    "delta_pregame_goalie_starter_quality_gap_last10_home_minus_away": 0.24,
    "market_consensus_home_prob": 0.18,
    "market_spread_magnitude": -0.10,
    "market_public_vs_sharp_agreement": 0.08,
    "roster_continuity_x_opponent_quality": 0.32,
    "special_teams_x_rest_fatigue": 0.24,
    "home_away_x_travel_schedule": 0.16,
    "goalie_fidelity_x_back_to_back": 0.22,
    "goalie_quality_gap_x_back_to_back": 0.14,
    "market_signals_x_model_confidence": 0.18,
    "delta_power_play_pct_home_minus_away": 0.42,
    "delta_penalty_kill_pct_home_minus_away": 0.38,
    "delta_pregame_top6_points_pg_home_minus_away": 0.30,
    "delta_pregame_top4_avg_toi_home_minus_away": 0.22,
    "delta_pregame_skater_points_pg_last3_home_minus_away": 0.28,
    "delta_pregame_skater_points_pg_last10_home_minus_away": 0.16,
    "delta_pregame_skater_two_way_idx_last3_home_minus_away": 0.21,
    "delta_pregame_skater_two_way_idx_last10_home_minus_away": 0.14,
    "delta_pregame_goalie_save_pct_last10_home_minus_away": 0.27,
    "delta_pregame_goalie_save_pct_ewm_home_minus_away": 0.24,
    "delta_pregame_goalie_save_pct_last3_home_minus_away": 0.19,
    "delta_pregame_goalie_shots_against_pg_last5_home_minus_away": -0.17,
    "delta_pregame_lineup_continuity_ewm_home_minus_away": 0.33,
    "delta_pregame_lineup_stability_last5_home_minus_away": 0.31,
    "delta_pregame_core_retention_pct_home_minus_away": 0.26,
    "delta_pregame_key_contributor_change_rate_last5_home_minus_away": -0.23,
    "delta_pregame_roster_games_covered_home_minus_away": -0.15,
    "delta_pregame_roster_data_coverage_pct_home_minus_away": 0.18,
    "delta_pregame_confirmed_starters_count_home_minus_away": 0.12,
    "delta_gd_volatility_last5_home_minus_away": -0.11,
    "special_teams_net_edge": 0.34,
    "special_teams_balance_edge": 0.18,
    "special_teams_form_x_recent_form": 0.20,
    "special_teams_form_x_quality": 0.16,
    "opponent_adjusted_rest_edge": 0.24,
    "schedule_compression_relief": 0.21,
    "lineup_continuity_x_recent_form": 0.19,
    "lineup_stability_x_coverage": 0.17,
    "goalie_certainty_x_latency": 0.20,
    "goalie_certainty_x_quality_gap": 0.18,
    "goalie_freshness_edge": 0.12,
    "microtrend_skater_points_accel": 0.17,
    "microtrend_two_way_accel": 0.13,
    "microtrend_goalie_save_accel": 0.16,
    "microtrend_form_accel": 0.19,
    "microtrend_volatility_penalty": 0.11,
    "home_away_split_edge": 0.15,
    "home_away_split_form_edge": 0.14,
    "home_away_split_momentum_direction": 0.10,
    "deadline_pressure_edge": 0.08,
}

BLEND_VARIANTS = {
    "blend_logistic_weighted_70_30": {
        "logistic_engineered": 0.70,
        "weighted_calibrated": 0.30,
    },
    "blend_logistic_weighted_60_40": {
        "logistic_engineered": 0.60,
        "weighted_calibrated": 0.40,
    },
    "blend_nonlinear_logistic_50_50": {
        "nonlinear_tree": 0.50,
        "logistic_engineered": 0.50,
    },
    "blend_nonlinear_weighted_60_40": {
        "nonlinear_tree": 0.60,
        "weighted_calibrated": 0.40,
    },
}

INTERACTION_FEATURE_NAMES = [
    "matchup_home_win_rate_prior",
    "matchup_home_games_prior_log",
    "team_vs_opponent_win_rate_prior",
    "team_vs_opponent_games_prior_log",
]

MARKET_FEATURE_CANDIDATES = [
    "market_consensus_home_prob",
    "market_spread_magnitude",
    "market_public_vs_sharp_agreement",
]

V3_INTERACTION_FEATURE_NAMES = [
    "roster_continuity_x_opponent_quality",
    "special_teams_x_rest_fatigue",
    "home_away_x_travel_schedule",
    "goalie_fidelity_x_back_to_back",
    "goalie_quality_gap_x_back_to_back",
    "market_signals_x_model_confidence",
]

V4_INTERACTION_FEATURE_NAMES = [
    "special_teams_net_edge",
    "special_teams_balance_edge",
    "special_teams_form_x_recent_form",
    "special_teams_form_x_quality",
    "opponent_adjusted_rest_edge",
    "schedule_compression_relief",
    "lineup_continuity_x_recent_form",
    "lineup_stability_x_coverage",
    "goalie_certainty_x_latency",
    "goalie_certainty_x_quality_gap",
    "goalie_freshness_edge",
    "microtrend_skater_points_accel",
    "microtrend_two_way_accel",
    "microtrend_goalie_save_accel",
    "microtrend_form_accel",
    "microtrend_volatility_penalty",
    "home_away_split_edge",
    "home_away_split_form_edge",
    "home_away_split_momentum_direction",
    "deadline_pressure_edge",
]

TOP_BLEND_FAMILY_CANDIDATES = [
    "elo_form_tuned",
    "logistic_engineered",
    "weighted_calibrated",
    "nonlinear_tree",
]


@dataclass
class FeatureRow:
    season: int
    game_id: int
    game_date: str
    home_team: str
    away_team: str
    home_win: int
    features: Dict[str, float]


@dataclass
class HistoricalGame:
    season: int
    game_id: int
    game_date: str
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    home_win: int


@dataclass
class RecencyConfig:
    mode: str = "none"
    season_half_life: float = 1.5
    game_half_life: float = 800.0
    min_weight: float = 0.2
    normalize_mean_one: bool = True


@dataclass
class RecencyCandidate:
    candidate_id: str
    base_config: RecencyConfig
    selector_mode: str = "static"


DRIFT_2025_2026_RECENCY_GRID: List[RecencyConfig] = [
    RecencyConfig(mode="none", season_half_life=1.0, game_half_life=1.0, min_weight=1.0, normalize_mean_one=True),
    RecencyConfig(mode="hybrid_exponential", season_half_life=0.50, game_half_life=180.0, min_weight=0.02, normalize_mean_one=True),
    RecencyConfig(mode="hybrid_exponential", season_half_life=0.50, game_half_life=260.0, min_weight=0.02, normalize_mean_one=True),
    RecencyConfig(mode="hybrid_exponential", season_half_life=0.65, game_half_life=260.0, min_weight=0.03, normalize_mean_one=True),
    RecencyConfig(mode="hybrid_exponential", season_half_life=0.65, game_half_life=340.0, min_weight=0.05, normalize_mean_one=True),
    RecencyConfig(mode="hybrid_exponential", season_half_life=0.80, game_half_life=340.0, min_weight=0.05, normalize_mean_one=True),
    RecencyConfig(mode="hybrid_exponential", season_half_life=0.80, game_half_life=450.0, min_weight=0.08, normalize_mean_one=True),
    RecencyConfig(mode="hybrid_exponential", season_half_life=1.00, game_half_life=450.0, min_weight=0.08, normalize_mean_one=True),
    RecencyConfig(mode="hybrid_exponential", season_half_life=1.00, game_half_life=600.0, min_weight=0.12, normalize_mean_one=True),
    RecencyConfig(mode="hybrid_exponential", season_half_life=1.25, game_half_life=600.0, min_weight=0.15, normalize_mean_one=True),
    RecencyConfig(mode="game_exponential", season_half_life=1.0, game_half_life=160.0, min_weight=0.02, normalize_mean_one=True),
    RecencyConfig(mode="game_exponential", season_half_life=1.0, game_half_life=220.0, min_weight=0.03, normalize_mean_one=True),
    RecencyConfig(mode="game_exponential", season_half_life=1.0, game_half_life=300.0, min_weight=0.05, normalize_mean_one=True),
    RecencyConfig(mode="game_exponential", season_half_life=1.0, game_half_life=420.0, min_weight=0.08, normalize_mean_one=True),
    RecencyConfig(mode="game_exponential", season_half_life=1.0, game_half_life=550.0, min_weight=0.10, normalize_mean_one=True),
    RecencyConfig(mode="season_exponential", season_half_life=0.45, game_half_life=1.0, min_weight=0.03, normalize_mean_one=True),
    RecencyConfig(mode="season_exponential", season_half_life=0.65, game_half_life=1.0, min_weight=0.05, normalize_mean_one=True),
    RecencyConfig(mode="season_exponential", season_half_life=0.85, game_half_life=1.0, min_weight=0.07, normalize_mean_one=True),
    RecencyConfig(mode="season_exponential", season_half_life=1.10, game_half_life=1.0, min_weight=0.10, normalize_mean_one=True),
]


@dataclass
class CalibrationConfig:
    selector_mode: str = "season_aware"
    validation_seasons: int = 2
    season_half_life: float = 1.0
    selection_objective: str = "joint"
    objective_margin: float = 0.0005


def clamp_probability(value: float) -> float:
    return max(EPS, min(1.0 - EPS, value))


def season_label(season_id: int) -> str:
    raw = str(int(season_id))
    if len(raw) == 8:
        return f"{raw[:4]}-{raw[4:]}"
    return raw


def table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def parse_float(value: object, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def smoothed_rate(wins: float, games: int, prior: float, prior_strength: float = INTERACTION_PRIOR_STRENGTH) -> float:
    return (wins + prior_strength * prior) / max(games + prior_strength, 1e-9)


def attach_interaction_features(rows: Sequence["FeatureRow"]) -> None:
    grouped: Dict[int, List[FeatureRow]] = {}
    for row in rows:
        grouped.setdefault(row.season, []).append(row)
    seasons = sorted(grouped.keys())

    ordered_matchup_wins: Dict[Tuple[str, str], float] = {}
    ordered_matchup_games: Dict[Tuple[str, str], int] = {}
    focal_matchup_wins: Dict[Tuple[str, str], float] = {}
    focal_matchup_games: Dict[Tuple[str, str], int] = {}
    cumulative_games = 0
    cumulative_home_wins = 0.0

    for season in seasons:
        season_rows = grouped[season]
        global_home_prior = (cumulative_home_wins / cumulative_games) if cumulative_games > 0 else 0.5
        for row in season_rows:
            ordered_key = (row.home_team, row.away_team)
            ordered_games = ordered_matchup_games.get(ordered_key, 0)
            ordered_wins = ordered_matchup_wins.get(ordered_key, 0.0)
            row.features["matchup_home_win_rate_prior"] = (
                smoothed_rate(ordered_wins, ordered_games, global_home_prior) - 0.5
            )
            row.features["matchup_home_games_prior_log"] = math.log1p(ordered_games)

            focal_key = (row.home_team, row.away_team)
            focal_games = focal_matchup_games.get(focal_key, 0)
            focal_wins = focal_matchup_wins.get(focal_key, 0.0)
            row.features["team_vs_opponent_win_rate_prior"] = smoothed_rate(focal_wins, focal_games, 0.5) - 0.5
            row.features["team_vs_opponent_games_prior_log"] = math.log1p(focal_games)

        for row in season_rows:
            home_win = float(row.home_win)
            ordered_key = (row.home_team, row.away_team)
            ordered_matchup_games[ordered_key] = ordered_matchup_games.get(ordered_key, 0) + 1
            ordered_matchup_wins[ordered_key] = ordered_matchup_wins.get(ordered_key, 0.0) + home_win

            home_focal_key = (row.home_team, row.away_team)
            away_focal_key = (row.away_team, row.home_team)
            focal_matchup_games[home_focal_key] = focal_matchup_games.get(home_focal_key, 0) + 1
            focal_matchup_wins[home_focal_key] = focal_matchup_wins.get(home_focal_key, 0.0) + home_win
            focal_matchup_games[away_focal_key] = focal_matchup_games.get(away_focal_key, 0) + 1
            focal_matchup_wins[away_focal_key] = focal_matchup_wins.get(away_focal_key, 0.0) + (1.0 - home_win)

            cumulative_games += 1
            cumulative_home_wins += home_win


def attach_v3_interaction_features(rows: Sequence["FeatureRow"]) -> None:
    for row in rows:
        f = row.features

        roster_continuity = parse_float(f.get("delta_pregame_key_contributor_continuity_pct_home_minus_away", 0.0))
        roster_quality = parse_float(f.get("delta_pregame_roster_quality_idx_home_minus_away", 0.0))
        special_teams = parse_float(f.get("delta_pregame_special_teams_contributor_share_last5_home_minus_away", 0.0))
        rest_fatigue = parse_float(f.get("rest_days_delta_home_minus_away", 0.0))
        home_edge = parse_float(f.get("home_location_edge_points_pct", 0.0))
        travel = parse_float(f.get("delta_travel_miles_home_minus_away", 0.0))
        time_shift = parse_float(f.get("delta_timezone_shift_hours_home_minus_away", 0.0))
        goalie_fidelity = parse_float(f.get("delta_pregame_goalie_starter_certainty_home_minus_away", 0.0))
        goalie_quality_gap = parse_float(f.get("delta_pregame_goalie_starter_quality_gap_last10_home_minus_away", 0.0))
        b2b_gap = parse_float(f.get("away_back_to_back", 0.0)) - parse_float(f.get("home_back_to_back", 0.0))
        market_prob = parse_float(f.get("market_consensus_home_prob", 0.5))
        model_confidence_proxy = (
            abs(parse_float(f.get("delta_pregame_season_points_pct_home_minus_away", 0.0)))
            + 0.60 * abs(roster_quality)
            + 0.35 * abs(parse_float(f.get("delta_pregame_goalie_save_pct_home_minus_away", 0.0)))
            + 0.15 * abs(rest_fatigue)
        )

        f["roster_continuity_x_opponent_quality"] = roster_continuity * roster_quality
        f["special_teams_x_rest_fatigue"] = special_teams * rest_fatigue
        f["home_away_x_travel_schedule"] = home_edge * (travel / 1000.0 + 0.5 * time_shift)
        f["goalie_fidelity_x_back_to_back"] = goalie_fidelity * b2b_gap
        f["goalie_quality_gap_x_back_to_back"] = goalie_quality_gap * b2b_gap
        f["market_signals_x_model_confidence"] = (market_prob - 0.5) * model_confidence_proxy


def attach_v4_interaction_features(rows: Sequence["FeatureRow"]) -> None:
    for row in rows:
        f = row.features

        lineup_continuity = parse_float(f.get("delta_pregame_lineup_continuity_pct_home_minus_away", 0.0))
        lineup_continuity_ewm = parse_float(f.get("delta_pregame_lineup_continuity_ewm_home_minus_away", 0.0))
        lineup_stability = parse_float(f.get("delta_pregame_lineup_stability_last5_home_minus_away", 0.0))
        key_continuity = parse_float(f.get("delta_pregame_key_contributor_continuity_pct_home_minus_away", 0.0))
        roster_turnover = parse_float(f.get("delta_pregame_roster_turnover_count_home_minus_away", 0.0))
        roster_coverage = parse_float(f.get("delta_pregame_roster_data_coverage_pct_home_minus_away", 0.0))
        roster_games = parse_float(f.get("delta_pregame_roster_games_covered_home_minus_away", 0.0))
        recent_form_5 = parse_float(f.get("delta_pregame_recent_form_adj_last5_home_minus_away", 0.0))
        recent_form_10 = parse_float(f.get("delta_pregame_recent_form_adj_last10_home_minus_away", 0.0))
        recent_vol_5 = parse_float(f.get("delta_pregame_recent_form_volatility_last5_home_minus_away", 0.0))
        recent_vol_10 = parse_float(f.get("delta_pregame_recent_form_volatility_last10_home_minus_away", 0.0))
        goalie_certainty = parse_float(f.get("delta_pregame_goalie_starter_certainty_home_minus_away", 0.0))
        goalie_latency = parse_float(f.get("delta_pregame_goalie_days_since_last_start_home_minus_away", 0.0))
        goalie_quality = parse_float(f.get("delta_pregame_goalie_starter_quality_gap_last10_home_minus_away", 0.0))
        goalie_recent_starts = parse_float(f.get("delta_pregame_goalie_recent_starts_last5_home_minus_away", 0.0))
        goalie_save_3 = parse_float(f.get("delta_pregame_goalie_save_pct_last3_home_minus_away", 0.0))
        goalie_save_10 = parse_float(f.get("delta_pregame_goalie_save_pct_last10_home_minus_away", 0.0))
        goalie_save_ewm = parse_float(f.get("delta_pregame_goalie_save_pct_ewm_home_minus_away", 0.0))
        skater_pts_3 = parse_float(f.get("delta_pregame_skater_points_pg_last3_home_minus_away", 0.0))
        skater_pts_10 = parse_float(f.get("delta_pregame_skater_points_pg_last10_home_minus_away", 0.0))
        skater_two_way_3 = parse_float(f.get("delta_pregame_skater_two_way_idx_last3_home_minus_away", 0.0))
        skater_two_way_10 = parse_float(f.get("delta_pregame_skater_two_way_idx_last10_home_minus_away", 0.0))
        power_play = parse_float(f.get("delta_power_play_pct_home_minus_away", 0.0))
        penalty_kill = parse_float(f.get("delta_penalty_kill_pct_home_minus_away", 0.0))
        home_split = parse_float(f.get("home_home_vs_away_win_pct_diff", 0.0))
        away_split = parse_float(f.get("away_home_vs_away_win_pct_diff", 0.0))
        home_momentum = parse_float(f.get("home_momentum_10game_trend", 0.0))
        away_momentum = parse_float(f.get("away_momentum_10game_trend", 0.0))
        home_momentum_dir = parse_float(f.get("home_momentum_trend_direction", 0.0))
        away_momentum_dir = parse_float(f.get("away_momentum_trend_direction", 0.0))
        home_b2b = parse_float(f.get("home_back_to_back", 0.0))
        away_b2b = parse_float(f.get("away_back_to_back", 0.0))
        home_three_in_four = parse_float(f.get("home_three_in_four", 0.0))
        away_three_in_four = parse_float(f.get("away_three_in_four", 0.0))
        home_four_in_six = parse_float(f.get("home_four_in_six", 0.0))
        away_four_in_six = parse_float(f.get("away_four_in_six", 0.0))
        home_travel = parse_float(f.get("delta_travel_miles_home_minus_away", 0.0))
        home_time = parse_float(f.get("delta_timezone_shift_hours_home_minus_away", 0.0))
        games_until_deadline = parse_float(f.get("games_until_deadline", 0.0))
        games_since_deadline = parse_float(f.get("games_since_deadline", 0.0))

        f["special_teams_net_edge"] = power_play + penalty_kill
        f["special_teams_balance_edge"] = power_play - penalty_kill
        f["special_teams_form_x_recent_form"] = (power_play + penalty_kill) * recent_form_5
        f["special_teams_form_x_quality"] = (power_play + penalty_kill) * parse_float(
            f.get("delta_pregame_roster_quality_idx_home_minus_away", 0.0)
        )

        f["opponent_adjusted_rest_edge"] = (
            parse_float(f.get("rest_days_delta_home_minus_away", 0.0))
            - 0.50 * (home_three_in_four - away_three_in_four)
            - 0.25 * (home_four_in_six - away_four_in_six)
        )
        f["schedule_compression_relief"] = (
            -(home_b2b + 0.50 * home_three_in_four + 0.25 * home_four_in_six)
            + (away_b2b + 0.50 * away_three_in_four + 0.25 * away_four_in_six)
        )

        f["lineup_continuity_x_recent_form"] = lineup_continuity * recent_form_5
        f["lineup_stability_x_coverage"] = lineup_stability * (1.0 + roster_coverage)

        f["goalie_certainty_x_latency"] = goalie_certainty * (1.0 - 0.10 * abs(goalie_latency))
        f["goalie_certainty_x_quality_gap"] = goalie_certainty * goalie_quality
        f["goalie_freshness_edge"] = goalie_certainty * (1.0 + 0.05 * goalie_recent_starts - 0.05 * abs(goalie_latency))

        f["microtrend_skater_points_accel"] = skater_pts_3 - skater_pts_10
        f["microtrend_two_way_accel"] = skater_two_way_3 - skater_two_way_10
        f["microtrend_goalie_save_accel"] = goalie_save_3 - goalie_save_10
        f["microtrend_form_accel"] = recent_form_5 - recent_form_10
        f["microtrend_volatility_penalty"] = recent_form_5 / (1.0 + abs(recent_vol_5))

        f["home_away_split_edge"] = home_split - away_split
        f["home_away_split_form_edge"] = home_split * home_momentum - away_split * away_momentum
        f["home_away_split_momentum_direction"] = home_momentum_dir - away_momentum_dir
        f["deadline_pressure_edge"] = (1.0 / (1.0 + games_until_deadline)) - (1.0 / (1.0 + games_since_deadline))


def percentile(sorted_vals: Sequence[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * pct
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def median_iqr_scale(values: Sequence[float]) -> Tuple[float, float]:
    if not values:
        return 0.0, 1.0
    sorted_vals = sorted(values)
    med = percentile(sorted_vals, 0.5)
    q1 = percentile(sorted_vals, 0.25)
    q3 = percentile(sorted_vals, 0.75)
    iqr = q3 - q1
    scale = max(iqr / 1.349 if iqr > 0 else 0.0, 1e-6)
    return med, scale


def build_robust_scaler(rows: Sequence[FeatureRow], feature_names: Sequence[str]) -> Tuple[Dict[str, float], Dict[str, float]]:
    medians: Dict[str, float] = {}
    scales: Dict[str, float] = {}
    for name in feature_names:
        values = [r.features.get(name, 0.0) for r in rows]
        med, scale = median_iqr_scale(values)
        medians[name] = med
        scales[name] = scale
    return medians, scales


def scaled_feature_value(value: float, median: float, scale: float) -> float:
    centered = (value - median) / max(scale, 1e-6)
    if centered > 6.0:
        return 6.0
    if centered < -6.0:
        return -6.0
    return centered


def build_feature_vector(
    row: FeatureRow,
    feature_names: Sequence[str],
    medians: Dict[str, float],
    scales: Dict[str, float],
) -> List[float]:
    return [
        scaled_feature_value(row.features.get(name, 0.0), medians[name], scales[name])
        for name in feature_names
    ]


def compute_recency_weights(
    train_rows: Sequence[FeatureRow],
    train_seasons: Sequence[int],
    config: RecencyConfig,
) -> List[float]:
    if not train_rows:
        return []
    if config.mode == "none":
        return [1.0 for _ in train_rows]

    season_to_idx = {season: idx for idx, season in enumerate(sorted(train_seasons))}
    latest_idx = max(season_to_idx.values()) if season_to_idx else 0
    n_rows = len(train_rows)
    season_half_life = max(float(config.season_half_life), 1e-6)
    game_half_life = max(float(config.game_half_life), 1e-6)

    weights: List[float] = []
    for row_idx, row in enumerate(train_rows):
        season_idx = season_to_idx.get(row.season, latest_idx)
        season_age = max(0, latest_idx - season_idx)
        game_age = max(0, (n_rows - 1) - row_idx)

        season_weight = math.pow(0.5, season_age / season_half_life)
        game_weight = math.pow(0.5, game_age / game_half_life)
        if config.mode == "season_exponential":
            raw_weight = season_weight
        elif config.mode == "game_exponential":
            raw_weight = game_weight
        elif config.mode == "hybrid_exponential":
            raw_weight = season_weight * game_weight
        else:
            raise ValueError(f"Unsupported recency mode: {config.mode}")
        weights.append(max(float(config.min_weight), raw_weight))

    if config.normalize_mean_one and weights:
        weight_sum = sum(weights)
        if weight_sum > 0:
            scale = len(weights) / weight_sum
            weights = [w * scale for w in weights]
    return weights


def season_regime_label(train_seasons: Sequence[int]) -> str:
    train_count = len(set(train_seasons))
    if train_count <= 2:
        return "early"
    if train_count == 3:
        return "middle"
    return "late"


def calibration_validation_regime_label(
    season: int,
    ordered_validation_seasons: Sequence[int],
) -> str:
    if not ordered_validation_seasons:
        return "late_window"
    season_to_idx = {s: i for i, s in enumerate(ordered_validation_seasons)}
    idx = season_to_idx.get(season, len(ordered_validation_seasons) - 1)
    denom = max(1, len(ordered_validation_seasons))
    pct = (idx + 1) / denom
    if pct <= 0.34:
        return "early_window"
    if pct <= 0.67:
        return "middle_window"
    return "late_window"


def select_fold_recency_config(
    base_config: RecencyConfig,
    selector_mode: str,
    train_seasons: Sequence[int],
) -> Tuple[RecencyConfig, str]:
    if selector_mode == "static":
        return base_config, "static"
    if selector_mode not in {"season_regime", "season_regime_drift"}:
        raise ValueError(f"Unsupported recency selector mode: {selector_mode}")

    regime = season_regime_label(train_seasons)
    if base_config.mode == "none":
        return base_config, regime

    if selector_mode == "season_regime_drift":
        if regime == "early":
            season_mult = 1.20
            game_mult = 1.20
            min_mult = 1.10
        elif regime == "middle":
            season_mult = 0.95
            game_mult = 0.95
            min_mult = 0.90
        else:
            season_mult = 0.65
            game_mult = 0.60
            min_mult = 0.70
    else:
        if regime == "early":
            season_mult = 0.85
            game_mult = 0.85
            min_mult = 0.90
        elif regime == "middle":
            season_mult = 1.0
            game_mult = 1.0
            min_mult = 1.0
        else:
            season_mult = 1.25
            game_mult = 1.20
            min_mult = 1.10

    selected = RecencyConfig(
        mode=base_config.mode,
        season_half_life=max(1e-6, base_config.season_half_life * season_mult),
        game_half_life=max(1e-6, base_config.game_half_life * game_mult),
        min_weight=max(0.0, min(1.0, base_config.min_weight * min_mult)),
        normalize_mean_one=base_config.normalize_mean_one,
    )
    return selected, regime


def parse_comma_list(raw: str) -> List[str]:
    return [piece.strip() for piece in str(raw).split(",") if piece.strip()]


def parse_float_list(raw: str) -> List[float]:
    values = [float(piece) for piece in parse_comma_list(raw)]
    if not values:
        raise ValueError("Expected at least one numeric value in comma-separated list.")
    return values


def parse_bool_list(raw: str) -> List[bool]:
    result: List[bool] = []
    for piece in parse_comma_list(raw):
        lowered = piece.lower()
        if lowered in ("1", "true", "t", "yes", "y"):
            result.append(True)
        elif lowered in ("0", "false", "f", "no", "n"):
            result.append(False)
        else:
            raise ValueError(f"Unsupported boolean token in list: {piece}")
    if not result:
        raise ValueError("Expected at least one boolean value in comma-separated list.")
    return result


def fit_logistic(
    x_data: Sequence[Sequence[float]],
    y_data: Sequence[int],
    learning_rate: float,
    l2: float,
    epochs: int,
    sample_weights: Optional[Sequence[float]] = None,
) -> Tuple[List[float], float]:
    if not x_data:
        return [], 0.0
    if len(x_data) != len(y_data):
        raise ValueError("x_data and y_data length mismatch in fit_logistic.")
    if sample_weights is not None and len(sample_weights) != len(x_data):
        raise ValueError("sample_weights length mismatch in fit_logistic.")

    d = len(x_data[0])
    w = [0.0 for _ in range(d)]
    b = 0.0
    n = len(x_data)
    weights = list(sample_weights) if sample_weights is not None else [1.0 for _ in range(n)]
    total_weight = max(sum(weights), 1e-12)
    for _ in range(epochs):
        grad_w = [0.0 for _ in range(d)]
        grad_b = 0.0
        for x_vec, y, ex_weight in zip(x_data, y_data, weights):
            z = b + sum(wi * xi for wi, xi in zip(w, x_vec))
            z = max(-35.0, min(35.0, z))
            p = 1.0 / (1.0 + math.exp(-z))
            err = (p - y) * ex_weight
            grad_b += err
            for i in range(d):
                grad_w[i] += err * x_vec[i]
        inv_w = 1.0 / total_weight
        grad_b *= inv_w
        for i in range(d):
            grad_w[i] = grad_w[i] * inv_w + l2 * w[i]
            w[i] -= learning_rate * grad_w[i]
        b -= learning_rate * grad_b
    return w, b


def predict_logistic_probability(x_vec: Sequence[float], w: Sequence[float], b: float) -> float:
    if not w:
        return 0.5
    z = b + sum(wi * xi for wi, xi in zip(w, x_vec))
    z = max(-35.0, min(35.0, z))
    return clamp_probability(1.0 / (1.0 + math.exp(-z)))


def tune_logistic_hyperparameters(
    train_rows: Sequence[FeatureRow],
    feature_names: Sequence[str],
    train_row_weights: Optional[Sequence[float]] = None,
) -> Dict[str, float]:
    seasons = sorted({r.season for r in train_rows})
    if len(seasons) < 2:
        return {"lr": 0.03, "l2": 0.08, "epochs": 350.0, "val_log_loss": 0.0}
    if train_row_weights is not None and len(train_row_weights) != len(train_rows):
        raise ValueError("train_row_weights length mismatch in tune_logistic_hyperparameters.")

    val_season = seasons[-1]
    fit_rows: List[FeatureRow] = []
    val_rows: List[FeatureRow] = []
    fit_weights: List[float] = []
    for idx, row in enumerate(train_rows):
        maybe_weight = float(train_row_weights[idx]) if train_row_weights is not None else 1.0
        if row.season == val_season:
            val_rows.append(row)
        else:
            fit_rows.append(row)
            fit_weights.append(maybe_weight)
    if not fit_rows or not val_rows:
        return {"lr": 0.03, "l2": 0.08, "epochs": 350.0, "val_log_loss": 0.0}

    grid: List[Dict[str, float]] = []
    for lr in (0.02, 0.03, 0.05):
        for l2 in (0.01, 0.03, 0.08, 0.15, 0.30):
            for epochs in (250.0, 350.0, 450.0):
                grid.append({"lr": lr, "l2": l2, "epochs": epochs})

    best: Optional[Dict[str, float]] = None
    for candidate in grid:
        med, sc = build_robust_scaler(fit_rows, feature_names)
        x_fit = [build_feature_vector(r, feature_names, med, sc) for r in fit_rows]
        y_fit = [r.home_win for r in fit_rows]
        x_val = [build_feature_vector(r, feature_names, med, sc) for r in val_rows]
        y_val = [r.home_win for r in val_rows]
        w, b = fit_logistic(
            x_fit,
            y_fit,
            learning_rate=float(candidate["lr"]),
            l2=float(candidate["l2"]),
            epochs=int(candidate["epochs"]),
            sample_weights=fit_weights,
        )
        probs = [predict_logistic_probability(x, w, b) for x in x_val]
        m = compute_metrics_from_arrays(y_val, probs)
        row = {**candidate, "val_log_loss": m["log_loss"], "val_accuracy": m["accuracy"]}
        if best is None:
            best = row
            continue
        if row["val_log_loss"] < best["val_log_loss"] - 1e-12:
            best = row
        elif abs(row["val_log_loss"] - best["val_log_loss"]) <= 1e-12 and row["val_accuracy"] > best["val_accuracy"]:
            best = row
    return best or {"lr": 0.03, "l2": 0.08, "epochs": 350.0, "val_log_loss": 0.0}


def build_raw_feature_vector(row: FeatureRow, feature_names: Sequence[str]) -> List[float]:
    return [float(row.features.get(name, 0.0)) for name in feature_names]


@dataclass
class DeterministicTreeNode:
    probability: float
    feature_idx: int = -1
    threshold: float = 0.0
    left: Optional["DeterministicTreeNode"] = None
    right: Optional["DeterministicTreeNode"] = None

    @property
    def is_leaf(self) -> bool:
        return self.feature_idx < 0 or self.left is None or self.right is None


class DeterministicTreeEnsemble:
    def __init__(self, trees: Sequence[DeterministicTreeNode]):
        self.trees = list(trees)

    @staticmethod
    def _predict_tree(node: DeterministicTreeNode, x_vec: Sequence[float]) -> float:
        cur = node
        while not cur.is_leaf:
            if float(x_vec[cur.feature_idx]) <= cur.threshold:
                cur = cur.left or cur
            else:
                cur = cur.right or cur
        return clamp_probability(float(cur.probability))

    def predict_proba(self, x_vec: Sequence[float]) -> float:
        if not self.trees:
            return 0.5
        return clamp_probability(sum(self._predict_tree(tree, x_vec) for tree in self.trees) / len(self.trees))


def fit_deterministic_tree_ensemble(
    x_data: Sequence[Sequence[float]],
    y_data: Sequence[int],
    sample_weights: Optional[Sequence[float]] = None,
    n_trees: int = 9,
    max_depth: int = 2,
    min_samples_split: int = 200,
    min_samples_leaf: int = 80,
) -> DeterministicTreeEnsemble:
    if not x_data:
        return DeterministicTreeEnsemble([])
    if len(x_data) != len(y_data):
        raise ValueError("x_data and y_data length mismatch in fit_deterministic_tree_ensemble.")
    if sample_weights is not None and len(sample_weights) != len(x_data):
        raise ValueError("sample_weights length mismatch in fit_deterministic_tree_ensemble.")

    n = len(x_data)
    dim = len(x_data[0]) if x_data else 0
    if dim <= 0:
        return DeterministicTreeEnsemble([])

    weights = list(sample_weights) if sample_weights is not None else [1.0 for _ in range(n)]
    all_feature_indices = list(range(dim))

    def gini_from_weighted_counts(weight_sum: float, positive_weight: float) -> float:
        if weight_sum <= 1e-12:
            return 0.0
        p = max(0.0, min(1.0, positive_weight / weight_sum))
        return 1.0 - (p * p + (1.0 - p) * (1.0 - p))

    def candidate_thresholds(values: Sequence[float]) -> List[float]:
        uniq = sorted(set(float(v) for v in values))
        if len(uniq) <= 1:
            return []
        candidates: List[float] = []
        for pct in (0.30, 0.50, 0.70):
            q = percentile(uniq, pct)
            pos = bisect_right(uniq, q)
            left_idx = max(0, min(len(uniq) - 2, pos - 1))
            right_idx = left_idx + 1
            thr = (uniq[left_idx] + uniq[right_idx]) * 0.5
            candidates.append(thr)
        return sorted(set(candidates))

    def fit_single_tree(
        sampled_indices: Sequence[int],
        feature_indices: Sequence[int],
    ) -> DeterministicTreeNode:
        def build_node(indices: Sequence[int], depth: int) -> DeterministicTreeNode:
            node_weight = sum(weights[i] for i in indices)
            node_pos = sum(weights[i] * int(y_data[i]) for i in indices)
            node_prob = 0.5 if node_weight <= 1e-12 else node_pos / node_weight
            node_prob = clamp_probability(node_prob)
            if (
                depth >= max_depth
                or len(indices) < min_samples_split
                or node_prob <= 1e-9
                or node_prob >= 1.0 - 1e-9
            ):
                return DeterministicTreeNode(probability=node_prob)

            parent_impurity = gini_from_weighted_counts(node_weight, node_pos)
            best_feature = -1
            best_threshold = 0.0
            best_gain = 0.0
            best_left: List[int] = []
            best_right: List[int] = []

            for feature_idx in feature_indices:
                feature_values = [float(x_data[i][feature_idx]) for i in indices]
                for thr in candidate_thresholds(feature_values):
                    left = [i for i in indices if float(x_data[i][feature_idx]) <= thr]
                    right = [i for i in indices if float(x_data[i][feature_idx]) > thr]
                    if len(left) < min_samples_leaf or len(right) < min_samples_leaf:
                        continue
                    left_weight = sum(weights[i] for i in left)
                    right_weight = sum(weights[i] for i in right)
                    if left_weight <= 1e-12 or right_weight <= 1e-12:
                        continue
                    left_pos = sum(weights[i] * int(y_data[i]) for i in left)
                    right_pos = sum(weights[i] * int(y_data[i]) for i in right)
                    split_impurity = (
                        (left_weight / node_weight) * gini_from_weighted_counts(left_weight, left_pos)
                        + (right_weight / node_weight) * gini_from_weighted_counts(right_weight, right_pos)
                    )
                    gain = parent_impurity - split_impurity
                    if (
                        gain > best_gain + 1e-12
                        or (
                            abs(gain - best_gain) <= 1e-12
                            and (best_feature < 0 or feature_idx < best_feature or (feature_idx == best_feature and thr < best_threshold))
                        )
                    ):
                        best_gain = gain
                        best_feature = feature_idx
                        best_threshold = thr
                        best_left = left
                        best_right = right

            if best_feature < 0:
                return DeterministicTreeNode(probability=node_prob)

            left_node = build_node(best_left, depth + 1)
            right_node = build_node(best_right, depth + 1)
            return DeterministicTreeNode(
                probability=node_prob,
                feature_idx=best_feature,
                threshold=best_threshold,
                left=left_node,
                right=right_node,
            )

        return build_node(list(sampled_indices), depth=0)

    trees: List[DeterministicTreeNode] = []
    max_features = max(3, int(math.sqrt(dim) * 0.5))
    sample_size = min(n, 3500)
    for tree_idx in range(max(1, int(n_trees))):
        rng = random.Random(20260804 + tree_idx * 101)
        sampled_indices = [rng.randrange(n) for _ in range(sample_size)]
        feature_start = (tree_idx * max_features) % dim
        feature_indices = [all_feature_indices[(feature_start + k) % dim] for k in range(max_features)]
        trees.append(fit_single_tree(sampled_indices=sampled_indices, feature_indices=feature_indices))
    return DeterministicTreeEnsemble(trees=trees)


def build_nonlinear_predictor(
    train_rows: Sequence[FeatureRow],
    feature_names: Sequence[str],
    sample_weights: Sequence[float],
) -> Tuple[Callable[[FeatureRow], float], Dict[str, Any]]:
    x_train = [build_raw_feature_vector(row, feature_names) for row in train_rows]
    y_train = [int(row.home_win) for row in train_rows]
    weights = list(sample_weights) if sample_weights else [1.0 for _ in train_rows]

    if x_train and y_train:
        try:
            import lightgbm as lgb  # type: ignore

            model = lgb.LGBMClassifier(
                objective="binary",
                n_estimators=250,
                learning_rate=0.05,
                num_leaves=31,
                max_depth=-1,
                subsample=1.0,
                colsample_bytree=1.0,
                reg_lambda=1.0,
                random_state=20260804,
                n_jobs=1,
                deterministic=True,
                force_col_wise=True,
                verbosity=-1,
            )
            model.fit(x_train, y_train, sample_weight=weights)

            def _predict_lightgbm(row: FeatureRow) -> float:
                vec = build_raw_feature_vector(row, feature_names)
                return clamp_probability(float(model.predict_proba([vec])[0][1]))

            return _predict_lightgbm, {
                "model_id": "nonlinear_tree",
                "backend": "lightgbm",
                "style": "gradient_boosted_trees",
                "deterministic": True,
            }
        except Exception:
            pass

        try:
            from xgboost import XGBClassifier  # type: ignore

            model = XGBClassifier(
                objective="binary:logistic",
                eval_metric="logloss",
                n_estimators=250,
                learning_rate=0.05,
                max_depth=4,
                subsample=1.0,
                colsample_bytree=1.0,
                reg_lambda=1.0,
                random_state=20260804,
                n_jobs=1,
                tree_method="hist",
                verbosity=0,
            )
            model.fit(x_train, y_train, sample_weight=weights)

            def _predict_xgboost(row: FeatureRow) -> float:
                vec = build_raw_feature_vector(row, feature_names)
                return clamp_probability(float(model.predict_proba([vec])[0][1]))

            return _predict_xgboost, {
                "model_id": "nonlinear_tree",
                "backend": "xgboost",
                "style": "gradient_boosted_trees",
                "deterministic": True,
            }
        except Exception:
            pass

    fallback_model = fit_deterministic_tree_ensemble(
        x_data=x_train,
        y_data=y_train,
        sample_weights=weights,
        n_trees=9,
        max_depth=2,
        min_samples_split=200,
        min_samples_leaf=80,
    )

    def _predict_fallback(row: FeatureRow) -> float:
        vec = build_raw_feature_vector(row, feature_names)
        return fallback_model.predict_proba(vec)

    return _predict_fallback, {
        "model_id": "nonlinear_tree",
        "backend": "deterministic_tree_ensemble_fallback",
        "style": "bagged_cart_trees",
        "deterministic": True,
        "n_trees": 9,
        "max_depth": 2,
        "min_samples_split": 200,
        "min_samples_leaf": 80,
    }


def weighted_score(
    row: FeatureRow,
    feature_names: Sequence[str],
    medians: Dict[str, float],
    scales: Dict[str, float],
) -> float:
    score = 0.0
    weight_sum = 0.0
    for name in feature_names:
        weight = WEIGHTED_MODEL_WEIGHTS.get(name)
        if weight is None:
            continue
        value = scaled_feature_value(row.features.get(name, 0.0), medians[name], scales[name])
        score += weight * value
        weight_sum += abs(weight)
    if weight_sum <= 0:
        return 0.0
    return score / weight_sum


def fit_platt_scaler(
    scores: Sequence[float],
    targets: Sequence[int],
    epochs: int = 600,
    lr: float = 0.04,
    sample_weights: Optional[Sequence[float]] = None,
) -> Tuple[float, float]:
    a = 1.0
    b = 0.0
    n = len(scores)
    if n == 0:
        return a, b
    if len(scores) != len(targets):
        raise ValueError("scores and targets length mismatch in fit_platt_scaler.")
    if sample_weights is not None and len(sample_weights) != n:
        raise ValueError("sample_weights length mismatch in fit_platt_scaler.")
    weights = list(sample_weights) if sample_weights is not None else [1.0 for _ in range(n)]
    total_weight = max(sum(weights), 1e-12)

    for _ in range(epochs):
        grad_a = 0.0
        grad_b = 0.0
        for s, y, ex_weight in zip(scores, targets, weights):
            z = max(-35.0, min(35.0, a * s + b))
            p = 1.0 / (1.0 + math.exp(-z))
            err = (p - y) * ex_weight
            grad_a += err * s
            grad_b += err
        inv_w = 1.0 / total_weight
        grad_a = grad_a * inv_w + 0.001 * a
        grad_b = grad_b * inv_w
        a -= lr * grad_a
        b -= lr * grad_b
    return a, b


def apply_platt(score: float, a: float, b: float) -> float:
    z = max(-35.0, min(35.0, a * score + b))
    return clamp_probability(1.0 / (1.0 + math.exp(-z)))


def fit_isotonic_calibrator(
    scores: Sequence[float],
    targets: Sequence[int],
    sample_weights: Optional[Sequence[float]] = None,
) -> Dict[str, List[float]]:
    if not scores:
        return {"breakpoints": [0.0], "values": [0.5]}
    if len(scores) != len(targets):
        raise ValueError("scores and targets length mismatch in fit_isotonic_calibrator.")
    if sample_weights is not None and len(sample_weights) != len(scores):
        raise ValueError("sample_weights length mismatch in fit_isotonic_calibrator.")

    weights = list(sample_weights) if sample_weights is not None else [1.0 for _ in scores]
    ordered = sorted((float(s), int(y), float(w)) for s, y, w in zip(scores, targets, weights))
    unique_scores: List[float] = []
    sum_targets: List[float] = []
    counts: List[float] = []
    for s, y, ex_weight in ordered:
        if unique_scores and abs(s - unique_scores[-1]) <= 1e-12:
            sum_targets[-1] += float(y) * ex_weight
            counts[-1] += ex_weight
        else:
            unique_scores.append(s)
            sum_targets.append(float(y) * ex_weight)
            counts.append(ex_weight)

    block_starts = list(range(len(unique_scores)))
    block_ends = list(range(len(unique_scores)))
    block_sum_y = sum_targets[:]
    block_count = counts[:]
    block_value = [sy / max(c, 1.0) for sy, c in zip(block_sum_y, block_count)]

    i = 0
    while i < len(block_value) - 1:
        if block_value[i] <= block_value[i + 1] + 1e-12:
            i += 1
            continue
        block_ends[i] = block_ends[i + 1]
        block_sum_y[i] += block_sum_y[i + 1]
        block_count[i] += block_count[i + 1]
        block_value[i] = block_sum_y[i] / max(block_count[i], 1.0)
        del block_starts[i + 1]
        del block_ends[i + 1]
        del block_sum_y[i + 1]
        del block_count[i + 1]
        del block_value[i + 1]
        if i > 0:
            i -= 1

    fitted: List[float] = [0.0 for _ in unique_scores]
    for start, end, value in zip(block_starts, block_ends, block_value):
        for idx in range(start, end + 1):
            fitted[idx] = clamp_probability(value)

    return {"breakpoints": unique_scores, "values": fitted}


def apply_isotonic(score: float, breakpoints: Sequence[float], values: Sequence[float]) -> float:
    if not breakpoints or not values:
        return 0.5
    if score <= breakpoints[0]:
        return clamp_probability(float(values[0]))
    if score >= breakpoints[-1]:
        return clamp_probability(float(values[-1]))
    idx = bisect_right(breakpoints, score) - 1
    idx = max(0, min(idx, len(values) - 1))
    return clamp_probability(float(values[idx]))


def metrics_for_objective(
    metric_row: Dict[str, float],
    objective: str,
) -> Tuple[float, float, float]:
    if objective == "log_loss":
        return (float(metric_row["log_loss"]), float(metric_row["brier_score"]), -float(metric_row["accuracy"]))
    if objective == "brier":
        return (float(metric_row["brier_score"]), float(metric_row["log_loss"]), -float(metric_row["accuracy"]))
    return (
        0.5 * float(metric_row["log_loss"]) + 0.5 * float(metric_row["brier_score"]),
        float(metric_row["log_loss"]),
        -float(metric_row["accuracy"]),
    )


def choose_calibration_method(
    metrics_by_method: Dict[str, Dict[str, float]],
    objective: str = "joint",
    objective_margin: float = 0.0,
) -> str:
    best_method: Optional[str] = None
    best_key: Optional[Tuple[float, float, float, str]] = None
    method_keys: Dict[str, Tuple[float, float, float, str]] = {}
    for method_name in sorted(metrics_by_method.keys()):
        m = metrics_by_method[method_name]
        objective_key = metrics_for_objective(m, objective)
        key = (objective_key[0], objective_key[1], objective_key[2], method_name)
        method_keys[method_name] = key
        if best_key is None or key < best_key:
            best_method = method_name
            best_key = key

    if best_method is None:
        return "platt"
    if objective_margin <= 0.0 or "platt" not in method_keys:
        return best_method

    platt_key = method_keys["platt"]
    if best_method != "platt" and (platt_key[0] - best_key[0]) <= float(objective_margin):
        return "platt"
    return best_method


def aggregate_weighted_metrics(
    metric_rows: Sequence[Tuple[float, Dict[str, float]]]
) -> Dict[str, float]:
    total_weight = sum(max(float(w), 0.0) for w, _ in metric_rows)
    if total_weight <= 0.0:
        return {"games": 0.0, "accuracy": 0.0, "log_loss": 0.0, "brier_score": 0.0}
    acc = 0.0
    ll = 0.0
    brier = 0.0
    games = 0.0
    for raw_weight, metrics in metric_rows:
        w = max(float(raw_weight), 0.0)
        acc += w * float(metrics["accuracy"])
        ll += w * float(metrics["log_loss"])
        brier += w * float(metrics["brier_score"])
        games += w * float(metrics["games"])
    inv = 1.0 / total_weight
    return {
        "games": games * inv,
        "accuracy": acc * inv,
        "log_loss": ll * inv,
        "brier_score": brier * inv,
    }


def metrics_sort_key(item: Tuple[str, Dict[str, float]]) -> Tuple[float, float, float, str]:
    model_id, metrics = item
    return (
        float(metrics["log_loss"]),
        float(metrics["brier_score"]),
        -float(metrics["accuracy"]),
        model_id,
    )


def normalize_model_id(name: str) -> str:
    return "".join([c.lower() if c.isalnum() else "_" for c in str(name)]).strip("_")


def choose_top_families(
    family_metrics: Dict[str, Dict[str, float]],
    max_families: int = 3,
) -> List[str]:
    ranked = sorted(family_metrics.items(), key=metrics_sort_key)
    return [model_id for model_id, _ in ranked[: max(1, int(max_families))]]


def deterministic_weight_grid_for_count(count: int) -> List[List[float]]:
    if count == 2:
        return [
            [0.50, 0.50],
            [0.55, 0.45],
            [0.60, 0.40],
            [0.65, 0.35],
            [0.70, 0.30],
        ]
    if count == 3:
        return [
            [0.50, 0.30, 0.20],
            [0.45, 0.35, 0.20],
            [0.40, 0.35, 0.25],
            [0.34, 0.33, 0.33],
        ]
    return [[round(1.0 / count, 6) for _ in range(count)]]


def evaluate_blend_weights(
    family_ids: Sequence[str],
    candidate_weights: Sequence[Sequence[float]],
    family_probs_by_model: Dict[str, Sequence[float]],
    targets: Sequence[int],
) -> Tuple[Dict[str, float], List[Dict[str, object]], Dict[str, float]]:
    diagnostics: List[Dict[str, object]] = []
    best_weights: Optional[Dict[str, float]] = None
    best_metrics: Optional[Dict[str, float]] = None

    for weight_row in candidate_weights:
        if len(weight_row) != len(family_ids):
            continue
        weight_map = {model_id: float(w) for model_id, w in zip(family_ids, weight_row)}
        probs = []
        for i in range(len(targets)):
            components = {model_id: family_probs_by_model[model_id][i] for model_id in family_ids}
            probs.append(blend_probabilities(components, weight_map))
        metrics = compute_metrics_from_arrays(targets, probs)
        diagnostics.append(
            {
                "weights": weight_map,
                "games": int(metrics["games"]),
                "accuracy": round(metrics["accuracy"], 6),
                "log_loss": round(metrics["log_loss"], 6),
                "brier_score": round(metrics["brier_score"], 6),
            }
        )
        if best_metrics is None:
            best_weights = weight_map
            best_metrics = metrics
            continue
        if metrics_sort_key(("candidate", metrics)) < metrics_sort_key(("candidate", best_metrics)):
            best_weights = weight_map
            best_metrics = metrics

    if best_weights is None or best_metrics is None:
        fallback = {model_id: round(1.0 / max(1, len(family_ids)), 6) for model_id in family_ids}
        best_weights = fallback
        best_metrics = compute_metrics_from_arrays(
            targets,
            [
                blend_probabilities(
                    {model_id: family_probs_by_model[model_id][i] for model_id in family_ids},
                    fallback,
                )
                for i in range(len(targets))
            ],
        )
    return (
        best_weights,
        diagnostics,
        {
            "games": int(best_metrics["games"]),
            "accuracy": round(best_metrics["accuracy"], 6),
            "log_loss": round(best_metrics["log_loss"], 6),
            "brier_score": round(best_metrics["brier_score"], 6),
        },
    )


def build_fold_blend_variants(
    family_metrics: Dict[str, Dict[str, float]],
    family_probs_by_model: Dict[str, Sequence[float]],
    targets: Sequence[int],
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, object]]:
    blend_variants = dict(BLEND_VARIANTS)
    ranked_families = choose_top_families(family_metrics, max_families=3)
    diagnostics: Dict[str, object] = {
        "top_family_candidates": [
            {
                "model_id": model_id,
                "games": int(metrics["games"]),
                "accuracy": round(metrics["accuracy"], 6),
                "log_loss": round(metrics["log_loss"], 6),
                "brier_score": round(metrics["brier_score"], 6),
            }
            for model_id, metrics in sorted(family_metrics.items(), key=metrics_sort_key)
        ],
        "selected_top_families": ranked_families,
        "validated_weight_selection": [],
    }

    if len(ranked_families) >= 2:
        fam2 = ranked_families[:2]
        fixed_65_35 = {fam2[0]: 0.65, fam2[1]: 0.35}
        fixed_50_50 = {fam2[0]: 0.50, fam2[1]: 0.50}
        blend_variants[f"blend_top2_fixed_65_35__{normalize_model_id(fam2[0])}__{normalize_model_id(fam2[1])}"] = fixed_65_35
        blend_variants[f"blend_top2_fixed_50_50__{normalize_model_id(fam2[0])}__{normalize_model_id(fam2[1])}"] = fixed_50_50
        best_w2, tested_w2, best_m2 = evaluate_blend_weights(
            family_ids=fam2,
            candidate_weights=deterministic_weight_grid_for_count(2),
            family_probs_by_model=family_probs_by_model,
            targets=targets,
        )
        blend_variants[f"blend_top2_validated__{normalize_model_id(fam2[0])}__{normalize_model_id(fam2[1])}"] = best_w2
        casted = list(diagnostics["validated_weight_selection"])
        casted.append(
            {
                "blend_scope": "top2",
                "families": fam2,
                "best_weights": best_w2,
                "best_metrics": best_m2,
                "tested_candidates": tested_w2,
            }
        )
        diagnostics["validated_weight_selection"] = casted

    if len(ranked_families) >= 3:
        fam3 = ranked_families[:3]
        fixed_50_30_20 = {fam3[0]: 0.50, fam3[1]: 0.30, fam3[2]: 0.20}
        blend_variants[
            f"blend_top3_fixed_50_30_20__{normalize_model_id(fam3[0])}__{normalize_model_id(fam3[1])}__{normalize_model_id(fam3[2])}"
        ] = fixed_50_30_20
        best_w3, tested_w3, best_m3 = evaluate_blend_weights(
            family_ids=fam3,
            candidate_weights=deterministic_weight_grid_for_count(3),
            family_probs_by_model=family_probs_by_model,
            targets=targets,
        )
        blend_variants[
            f"blend_top3_validated__{normalize_model_id(fam3[0])}__{normalize_model_id(fam3[1])}__{normalize_model_id(fam3[2])}"
        ] = best_w3
        casted = list(diagnostics["validated_weight_selection"])
        casted.append(
            {
                "blend_scope": "top3",
                "families": fam3,
                "best_weights": best_w3,
                "best_metrics": best_m3,
                "tested_candidates": tested_w3,
            }
        )
        diagnostics["validated_weight_selection"] = casted

    diagnostics["blend_model_ids"] = sorted(blend_variants.keys())
    return blend_variants, diagnostics


def blend_probabilities(component_probs: Dict[str, float], weights: Dict[str, float]) -> float:
    p_home = 0.0
    total_weight = 0.0
    for model_id, weight in weights.items():
        p_home += float(weight) * float(component_probs[model_id])
        total_weight += float(weight)
    if total_weight <= 0.0:
        raise ValueError("Blend weights must sum to a positive value.")
    return clamp_probability(p_home / total_weight)


def compute_metrics_from_arrays(y_true: Sequence[int], p_home: Sequence[float]) -> Dict[str, float]:
    n = len(y_true)
    if n == 0:
        return {"games": 0.0, "accuracy": 0.0, "log_loss": 0.0, "brier_score": 0.0}
    correct = 0
    ll = 0.0
    brier = 0.0
    for y, p in zip(y_true, p_home):
        p_safe = clamp_probability(float(p))
        pick = 1 if p_safe >= 0.5 else 0
        if pick == int(y):
            correct += 1
        ll += -(int(y) * math.log(p_safe) + (1 - int(y)) * math.log(1.0 - p_safe))
        brier += (p_safe - int(y)) ** 2
    return {
        "games": float(n),
        "accuracy": correct / n,
        "log_loss": ll / n,
        "brier_score": brier / n,
    }


def summarize_logistic_importance(
    weights: Sequence[float],
    feature_names: Sequence[str],
    top_n: int = 20,
) -> List[Dict[str, float]]:
    rows = [
        {
            "feature": str(name),
            "abs_weight": float(abs(weight)),
            "weight": float(weight),
        }
        for name, weight in zip(feature_names, weights)
    ]
    rows.sort(key=lambda r: float(r["abs_weight"]), reverse=True)
    return rows[: max(1, top_n)]


def summarize_predictions(rows: Sequence[Dict[str, object]]) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = {}
    grouped_by_season: Dict[Tuple[str, str, int], List[Dict[str, object]]] = {}
    meta_columns = [
        "recency_candidate_id",
        "recency_selector_mode",
        "recency_mode",
        "recency_season_half_life",
        "recency_game_half_life",
        "recency_min_weight",
        "recency_normalize_mean_one",
        "recency_base_mode",
        "recency_base_season_half_life",
        "recency_base_game_half_life",
        "recency_base_min_weight",
        "recency_base_normalize_mean_one",
        "nonlinear_model_backend",
        "nonlinear_model_style",
    ]
    for row in rows:
        candidate_id = str(row.get("recency_candidate_id", "single"))
        model_id = str(row["model_id"])
        season = int(row["season"])
        grouped.setdefault((candidate_id, model_id), []).append(row)
        grouped_by_season.setdefault((candidate_id, model_id, season), []).append(row)

    overall_rows: List[Dict[str, object]] = []
    by_season_rows: List[Dict[str, object]] = []

    for candidate_id, model_id in sorted(grouped.keys()):
        model_rows = grouped[(candidate_id, model_id)]
        first = model_rows[0]
        m = compute_metrics_from_arrays(
            [int(r["actual_home_win"]) for r in model_rows],
            [float(r["home_win_probability"]) for r in model_rows],
        )
        out = {
            "recency_candidate_id": candidate_id,
            "model_id": model_id,
            "games": int(m["games"]),
            "accuracy": round(m["accuracy"], 6),
            "log_loss": round(m["log_loss"], 6),
            "brier_score": round(m["brier_score"], 6),
        }
        for col in meta_columns:
            out[col] = first.get(col)
        overall_rows.append(out)

    for (candidate_id, model_id, season), season_rows in sorted(
        grouped_by_season.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])
    ):
        first = season_rows[0]
        m = compute_metrics_from_arrays(
            [int(r["actual_home_win"]) for r in season_rows],
            [float(r["home_win_probability"]) for r in season_rows],
        )
        out = {
            "recency_candidate_id": candidate_id,
            "model_id": model_id,
            "season": season,
            "season_label": season_label(season),
            "games": int(m["games"]),
            "accuracy": round(m["accuracy"], 6),
            "log_loss": round(m["log_loss"], 6),
            "brier_score": round(m["brier_score"], 6),
        }
        for col in meta_columns:
            out[col] = first.get(col)
        by_season_rows.append(out)
    return overall_rows, by_season_rows


def write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_sqlite(
    sqlite_db: Path,
    predictions: Sequence[Dict[str, object]],
    overall_rows: Sequence[Dict[str, object]],
    by_season_rows: Sequence[Dict[str, object]],
) -> None:
    with sqlite3.connect(sqlite_db) as con:
        con.execute("DROP TABLE IF EXISTS walk_forward_experiment_predictions")
        con.execute(
            """
            CREATE TABLE walk_forward_experiment_predictions (
                model_id TEXT,
                fold_train_end_season INTEGER,
                fold_test_season INTEGER,
                season INTEGER,
                game_id INTEGER,
                game_date TEXT,
                home_team_abbrev TEXT,
                away_team_abbrev TEXT,
                actual_home_win INTEGER,
                home_win_probability REAL,
                away_win_probability REAL,
                predicted_winner_abbrev TEXT,
                is_correct_pick INTEGER,
                recency_candidate_id TEXT,
                recency_selector_mode TEXT,
                recency_selector_regime TEXT,
                recency_mode TEXT,
                recency_season_half_life REAL,
                recency_game_half_life REAL,
                recency_min_weight REAL,
                recency_normalize_mean_one INTEGER,
                recency_base_mode TEXT,
                recency_base_season_half_life REAL,
                recency_base_game_half_life REAL,
                recency_base_min_weight REAL,
                recency_base_normalize_mean_one INTEGER,
                nonlinear_model_backend TEXT,
                nonlinear_model_style TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO walk_forward_experiment_predictions
            (model_id, fold_train_end_season, fold_test_season, season, game_id, game_date, home_team_abbrev, away_team_abbrev,
             actual_home_win, home_win_probability, away_win_probability, predicted_winner_abbrev, is_correct_pick,
             recency_candidate_id, recency_selector_mode, recency_selector_regime, recency_mode, recency_season_half_life,
             recency_game_half_life, recency_min_weight, recency_normalize_mean_one, recency_base_mode,
             recency_base_season_half_life, recency_base_game_half_life, recency_base_min_weight, recency_base_normalize_mean_one,
             nonlinear_model_backend, nonlinear_model_style)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(r["model_id"]),
                    int(r["fold_train_end_season"]),
                    int(r["fold_test_season"]),
                    int(r["season"]),
                    int(r["game_id"]),
                    str(r["game_date"]),
                    str(r["home_team_abbrev"]),
                    str(r["away_team_abbrev"]),
                    int(r["actual_home_win"]),
                    float(r["home_win_probability"]),
                    float(r["away_win_probability"]),
                    str(r["predicted_winner_abbrev"]),
                    int(r["is_correct_pick"]),
                    str(r.get("recency_candidate_id", "single")),
                    str(r.get("recency_selector_mode", "static")),
                    str(r.get("recency_selector_regime", "static")),
                    str(r.get("recency_mode", "none")),
                    float(r.get("recency_season_half_life", 1.0)),
                    float(r.get("recency_game_half_life", 1.0)),
                    float(r.get("recency_min_weight", 1.0)),
                    1 if bool(r.get("recency_normalize_mean_one", True)) else 0,
                    str(r.get("recency_base_mode", "none")),
                    float(r.get("recency_base_season_half_life", 1.0)),
                    float(r.get("recency_base_game_half_life", 1.0)),
                    float(r.get("recency_base_min_weight", 1.0)),
                    1 if bool(r.get("recency_base_normalize_mean_one", True)) else 0,
                    str(r.get("nonlinear_model_backend", "")),
                    str(r.get("nonlinear_model_style", "")),
                )
                for r in predictions
            ],
        )

        con.execute("DROP TABLE IF EXISTS walk_forward_experiment_metrics_overall")
        con.execute(
            """
            CREATE TABLE walk_forward_experiment_metrics_overall (
                recency_candidate_id TEXT,
                model_id TEXT,
                games INTEGER,
                accuracy REAL,
                log_loss REAL,
                brier_score REAL,
                recency_selector_mode TEXT,
                recency_mode TEXT,
                recency_season_half_life REAL,
                recency_game_half_life REAL,
                recency_min_weight REAL,
                recency_normalize_mean_one INTEGER,
                recency_base_mode TEXT,
                recency_base_season_half_life REAL,
                recency_base_game_half_life REAL,
                recency_base_min_weight REAL,
                recency_base_normalize_mean_one INTEGER,
                nonlinear_model_backend TEXT,
                nonlinear_model_style TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO walk_forward_experiment_metrics_overall
            (recency_candidate_id, model_id, games, accuracy, log_loss, brier_score,
             recency_selector_mode, recency_mode, recency_season_half_life, recency_game_half_life, recency_min_weight,
             recency_normalize_mean_one, recency_base_mode, recency_base_season_half_life, recency_base_game_half_life,
             recency_base_min_weight, recency_base_normalize_mean_one, nonlinear_model_backend, nonlinear_model_style)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(r.get("recency_candidate_id", "single")),
                    str(r["model_id"]),
                    int(r["games"]),
                    float(r["accuracy"]),
                    float(r["log_loss"]),
                    float(r["brier_score"]),
                    str(r.get("recency_selector_mode", "static")),
                    str(r.get("recency_mode", "none")),
                    float(r.get("recency_season_half_life", 1.0)),
                    float(r.get("recency_game_half_life", 1.0)),
                    float(r.get("recency_min_weight", 1.0)),
                    1 if bool(r.get("recency_normalize_mean_one", True)) else 0,
                    str(r.get("recency_base_mode", "none")),
                    float(r.get("recency_base_season_half_life", 1.0)),
                    float(r.get("recency_base_game_half_life", 1.0)),
                    float(r.get("recency_base_min_weight", 1.0)),
                    1 if bool(r.get("recency_base_normalize_mean_one", True)) else 0,
                    str(r.get("nonlinear_model_backend", "")),
                    str(r.get("nonlinear_model_style", "")),
                )
                for r in overall_rows
            ],
        )

        con.execute("DROP TABLE IF EXISTS walk_forward_experiment_metrics_by_season")
        con.execute(
            """
            CREATE TABLE walk_forward_experiment_metrics_by_season (
                recency_candidate_id TEXT,
                model_id TEXT,
                season INTEGER,
                season_label TEXT,
                games INTEGER,
                accuracy REAL,
                log_loss REAL,
                brier_score REAL,
                recency_selector_mode TEXT,
                recency_mode TEXT,
                recency_season_half_life REAL,
                recency_game_half_life REAL,
                recency_min_weight REAL,
                recency_normalize_mean_one INTEGER,
                recency_base_mode TEXT,
                recency_base_season_half_life REAL,
                recency_base_game_half_life REAL,
                recency_base_min_weight REAL,
                recency_base_normalize_mean_one INTEGER,
                nonlinear_model_backend TEXT,
                nonlinear_model_style TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO walk_forward_experiment_metrics_by_season
            (recency_candidate_id, model_id, season, season_label, games, accuracy, log_loss, brier_score,
             recency_selector_mode, recency_mode, recency_season_half_life, recency_game_half_life, recency_min_weight,
             recency_normalize_mean_one, recency_base_mode, recency_base_season_half_life, recency_base_game_half_life,
             recency_base_min_weight, recency_base_normalize_mean_one, nonlinear_model_backend, nonlinear_model_style)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(r.get("recency_candidate_id", "single")),
                    str(r["model_id"]),
                    int(r["season"]),
                    str(r["season_label"]),
                    int(r["games"]),
                    float(r["accuracy"]),
                    float(r["log_loss"]),
                    float(r["brier_score"]),
                    str(r.get("recency_selector_mode", "static")),
                    str(r.get("recency_mode", "none")),
                    float(r.get("recency_season_half_life", 1.0)),
                    float(r.get("recency_game_half_life", 1.0)),
                    float(r.get("recency_min_weight", 1.0)),
                    1 if bool(r.get("recency_normalize_mean_one", True)) else 0,
                    str(r.get("recency_base_mode", "none")),
                    float(r.get("recency_base_season_half_life", 1.0)),
                    float(r.get("recency_base_game_half_life", 1.0)),
                    float(r.get("recency_base_min_weight", 1.0)),
                    1 if bool(r.get("recency_base_normalize_mean_one", True)) else 0,
                    str(r.get("nonlinear_model_backend", "")),
                    str(r.get("nonlinear_model_style", "")),
                )
                for r in by_season_rows
            ],
        )
        con.commit()


def load_historical_games(con: sqlite3.Connection) -> List[HistoricalGame]:
    query = """
    SELECT
        season, game_id, game_date, home_team_abbrev, away_team_abbrev, home_goals, away_goals
    FROM historical_games_last5
    WHERE is_final = 1 AND game_type = '2'
    ORDER BY game_date ASC, game_id ASC
    """
    rows: List[HistoricalGame] = []
    for season, game_id, game_date, home_team, away_team, home_goals, away_goals in con.execute(query).fetchall():
        h_goals = int(home_goals)
        a_goals = int(away_goals)
        rows.append(
            HistoricalGame(
                season=int(season),
                game_id=int(game_id),
                game_date=str(game_date),
                home_team=str(home_team).upper(),
                away_team=str(away_team).upper(),
                home_goals=h_goals,
                away_goals=a_goals,
                home_win=1 if h_goals > a_goals else 0,
            )
        )
    return rows


def choose_feature_table(
    con: sqlite3.Connection,
    preferred_table: Optional[str],
    require_roster: bool,
    dependency_retries: int,
    dependency_wait_seconds: int,
) -> Tuple[str, str]:
    if preferred_table:
        if table_exists(con, preferred_table):
            return preferred_table, "preferred_table_available"
        return preferred_table, "preferred_table_missing"

    for _ in range(max(0, dependency_retries) + 1):
        if table_exists(con, "backtest_features_last5_roster"):
            return "backtest_features_last5_roster", "roster_features_available"
        if not require_roster and table_exists(con, "backtest_features_last5"):
            return "backtest_features_last5", "base_features_available"
        if not require_roster and table_exists(con, "historical_games_features_last5"):
            return "historical_games_features_last5", "historical_features_available"
        if dependency_wait_seconds > 0:
            time.sleep(max(0, dependency_wait_seconds))

    if require_roster:
        return "backtest_features_last5_roster", "roster_features_missing"
    return "backtest_features_last5", "feature_tables_missing"


def maybe_build_base_features(
    repo_root: Path,
    sqlite_db: Path,
    should_build: bool,
) -> None:
    if not should_build:
        return
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "build_last5_backtest_features.py"),
        "--repo-root",
        str(repo_root),
        "--sqlite-db",
        str(sqlite_db),
    ]
    subprocess.run(cmd, check=True)


def load_feature_rows(
    con: sqlite3.Connection,
    table_name: str,
    exclude_synthetic_data: bool = False,
    exclude_market_features: bool = False,
) -> Tuple[List[FeatureRow], List[str]]:
    cur = con.execute(f'PRAGMA table_info("{table_name}")')
    columns = [str(row[1]) for row in cur.fetchall()]
    required = {"season", "game_id", "game_date", "home_team_abbrev", "away_team_abbrev", "home_win"}
    missing = sorted([c for c in required if c not in columns])
    if missing:
        raise ValueError(f"Feature table '{table_name}' missing required columns: {', '.join(missing)}")

    derived_inputs = list(dict.fromkeys(BASE_FEATURE_CANDIDATES + ROSTER_FEATURE_CANDIDATES))
    feature_columns = [c for c in derived_inputs if c in columns]
    if not feature_columns:
        raise ValueError(f"No usable feature columns found in table '{table_name}'.")

    select_columns = ["season", "game_id", "game_date", "home_team_abbrev", "away_team_abbrev", "home_win"] + feature_columns
    where_clauses = []
    if exclude_synthetic_data:
        if "is_synthetic" in columns:
            where_clauses.append("COALESCE(is_synthetic, 0) = 0")
        else:
            where_clauses.append("CAST(season AS TEXT) NOT IN ('20152016', '20162017', '20172018')")
    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    query = (
        f'SELECT {", ".join([f"""\"{c}\"""" for c in select_columns])} '
        f'FROM "{table_name}"{where_sql} ORDER BY game_date ASC, game_id ASC'
    )
    rows: List[FeatureRow] = []
    for raw in con.execute(query).fetchall():
        row_dict = dict(zip(select_columns, raw))
        features = {name: parse_float(row_dict.get(name), 0.0) for name in feature_columns}
        if "home_prior_prev_season_points_pct" in features and "away_prior_prev_season_points_pct" in features:
            features["delta_prev_season_points_pct"] = (
                features["home_prior_prev_season_points_pct"] - features["away_prior_prev_season_points_pct"]
            )
        if "home_prior_prev_season_goal_diff_pg" in features and "away_prior_prev_season_goal_diff_pg" in features:
            features["delta_prev_season_goal_diff_pg"] = (
                features["home_prior_prev_season_goal_diff_pg"] - features["away_prior_prev_season_goal_diff_pg"]
            )
        if "home_pregame_roster_data_coverage_pct" in features and "away_pregame_roster_data_coverage_pct" in features:
            features["delta_roster_coverage_pct"] = (
                features["home_pregame_roster_data_coverage_pct"] - features["away_pregame_roster_data_coverage_pct"]
            )
        if "home_pregame_roster_games_covered" in features and "away_pregame_roster_games_covered" in features:
            features["delta_roster_games_covered"] = (
                features["home_pregame_roster_games_covered"] - features["away_pregame_roster_games_covered"]
            )

        rows.append(
            FeatureRow(
                season=int(row_dict["season"]),
                game_id=int(row_dict["game_id"]),
                game_date=str(row_dict["game_date"]),
                home_team=str(row_dict["home_team_abbrev"]).upper(),
                away_team=str(row_dict["away_team_abbrev"]).upper(),
                home_win=int(float(row_dict["home_win"])),
                features=features,
            )
        )

    if not exclude_market_features and table_exists(con, "market_signals"):
        market_cols = [
            "game_id",
            "market_consensus_home_prob",
            "market_opening_home_implied_prob",
            "market_spread_magnitude",
            "market_public_vs_sharp_agreement",
            "market_consensus_spread",
            "market_opening_spread",
        ]
        market_map: Dict[int, Dict[str, float]] = {}
        market_query = (
            "SELECT game_id, "
            "market_consensus_home_prob, market_opening_home_implied_prob, "
            "ABS(market_consensus_spread) AS market_spread_magnitude, "
            "market_public_vs_sharp_agreement, market_consensus_spread, market_opening_spread "
            "FROM market_signals"
        )
        for raw in con.execute(market_query).fetchall():
            raw_dict = dict(zip(market_cols, raw))
            game_id = int(raw_dict["game_id"])
            market_map[game_id] = {
                "market_consensus_home_prob": parse_float(raw_dict.get("market_consensus_home_prob"), 0.5),
                "market_opening_home_implied_prob": parse_float(raw_dict.get("market_opening_home_implied_prob"), 0.5),
                "market_spread_magnitude": abs(parse_float(raw_dict.get("market_spread_magnitude"), 0.0)),
                "market_public_vs_sharp_agreement": parse_float(raw_dict.get("market_public_vs_sharp_agreement"), 0.0),
                "market_consensus_spread": parse_float(raw_dict.get("market_consensus_spread"), 0.0),
                "market_opening_spread": parse_float(raw_dict.get("market_opening_spread"), 0.0),
            }
        for row in rows:
            market_row = market_map.get(row.game_id)
            if not market_row:
                continue
            row.features.update(market_row)

    attach_interaction_features(rows)
    if not exclude_market_features:
        attach_v3_interaction_features(rows)
    else:
        for row in rows:
            f = row.features
            roster_continuity = parse_float(f.get("delta_pregame_key_contributor_continuity_pct_home_minus_away", 0.0))
            roster_quality = parse_float(f.get("delta_pregame_roster_quality_idx_home_minus_away", 0.0))
            special_teams = parse_float(f.get("delta_pregame_special_teams_contributor_share_last5_home_minus_away", 0.0))
            rest_fatigue = parse_float(f.get("rest_days_delta_home_minus_away", 0.0))
            home_edge = parse_float(f.get("home_location_edge_points_pct", 0.0))
            travel = parse_float(f.get("delta_travel_miles_home_minus_away", 0.0))
            time_shift = parse_float(f.get("delta_timezone_shift_hours_home_minus_away", 0.0))
            goalie_fidelity = parse_float(f.get("delta_pregame_goalie_starter_certainty_home_minus_away", 0.0))
            goalie_quality_gap = parse_float(f.get("delta_pregame_goalie_starter_quality_gap_last10_home_minus_away", 0.0))
            b2b_gap = parse_float(f.get("away_back_to_back", 0.0)) - parse_float(f.get("home_back_to_back", 0.0))
            f["roster_continuity_x_opponent_quality"] = roster_continuity * roster_quality
            f["special_teams_x_rest_fatigue"] = special_teams * rest_fatigue
            f["home_away_x_travel_schedule"] = home_edge * (travel / 1000.0 + 0.5 * time_shift)
            f["goalie_fidelity_x_back_to_back"] = goalie_fidelity * b2b_gap
            f["goalie_quality_gap_x_back_to_back"] = goalie_quality_gap * b2b_gap
    attach_v4_interaction_features(rows)

    rows.sort(key=lambda r: (r.game_date, r.game_id))
    all_feature_names = sorted({k for r in rows for k in r.features.keys()})
    return rows, all_feature_names


@dataclass
class EloParams:
    home_advantage: float
    k_factor: float
    form_win_weight: float
    form_goal_weight: float
    season_regression: float = 0.75
    elo_mean: float = 1500.0


@dataclass
class EloTeamSeason:
    games: int = 0
    wins: int = 0
    goal_diff: int = 0


class EloState:
    def __init__(self, params: EloParams) -> None:
        self.params = params
        self.ratings: Dict[str, float] = {}
        self.season_stats: Dict[str, EloTeamSeason] = {}
        self.current_season: Optional[int] = None

    def _new_season(self, season: int) -> None:
        if self.current_season is not None:
            for team in list(self.ratings.keys()):
                self.ratings[team] = self.params.elo_mean + self.params.season_regression * (
                    self.ratings[team] - self.params.elo_mean
                )
        self.season_stats = {}
        self.current_season = season

    def _team_state(self, team: str) -> EloTeamSeason:
        if team not in self.season_stats:
            self.season_stats[team] = EloTeamSeason()
        return self.season_stats[team]

    def predict_update(self, game: HistoricalGame, do_update: bool = True) -> float:
        if self.current_season != game.season:
            self._new_season(game.season)

        home_elo = self.ratings.get(game.home_team, self.params.elo_mean)
        away_elo = self.ratings.get(game.away_team, self.params.elo_mean)
        home_state = self._team_state(game.home_team)
        away_state = self._team_state(game.away_team)

        home_win_pct = home_state.wins / home_state.games if home_state.games > 0 else 0.5
        away_win_pct = away_state.wins / away_state.games if away_state.games > 0 else 0.5
        home_goal_diff_pg = home_state.goal_diff / home_state.games if home_state.games > 0 else 0.0
        away_goal_diff_pg = away_state.goal_diff / away_state.games if away_state.games > 0 else 0.0

        rating_diff = (
            (home_elo - away_elo)
            + self.params.home_advantage
            + self.params.form_win_weight * (home_win_pct - away_win_pct)
            + self.params.form_goal_weight * (home_goal_diff_pg - away_goal_diff_pg)
        )
        prob = clamp_probability(1.0 / (1.0 + math.pow(10.0, -rating_diff / 400.0)))

        if do_update:
            margin = abs(game.home_goals - game.away_goals)
            k_adj = self.params.k_factor * (1.0 + min(margin, 5) * 0.1)
            delta = k_adj * (game.home_win - prob)
            self.ratings[game.home_team] = home_elo + delta
            self.ratings[game.away_team] = away_elo - delta

            home_state.games += 1
            away_state.games += 1
            home_state.wins += game.home_win
            away_state.wins += 1 - game.home_win
            home_state.goal_diff += game.home_goals - game.away_goals
            away_state.goal_diff += game.away_goals - game.home_goals

        return prob


def tune_elo_params(train_games: Sequence[HistoricalGame]) -> EloParams:
    grid: List[EloParams] = []
    for home_adv in (35.0, 55.0, 75.0):
        for k_factor in (14.0, 18.0, 22.0):
            for form_win in (80.0, 120.0, 160.0):
                for form_goal in (20.0, 35.0, 50.0):
                    grid.append(EloParams(home_adv, k_factor, form_win, form_goal))

    best_params = grid[0]
    best_log_loss = float("inf")
    best_accuracy = -1.0
    for params in grid:
        state = EloState(params)
        y_true: List[int] = []
        probs: List[float] = []
        for game in train_games:
            probs.append(state.predict_update(game, do_update=True))
            y_true.append(game.home_win)
        m = compute_metrics_from_arrays(y_true, probs)
        if m["log_loss"] < best_log_loss - 1e-12:
            best_log_loss = m["log_loss"]
            best_accuracy = m["accuracy"]
            best_params = params
        elif abs(m["log_loss"] - best_log_loss) <= 1e-12 and m["accuracy"] > best_accuracy:
            best_log_loss = m["log_loss"]
            best_accuracy = m["accuracy"]
            best_params = params
    return best_params


def run_experiments(
    feature_rows: Sequence[FeatureRow],
    historical_map: Dict[Tuple[int, int], HistoricalGame],
    min_train_seasons: int,
    recency_candidate: RecencyCandidate,
    calibration_config: CalibrationConfig,
    model_scope: str = "full",
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    seasons = sorted({r.season for r in feature_rows})
    if len(seasons) <= min_train_seasons:
        raise ValueError("Not enough seasons for season-expanding walk-forward folds.")

    logistic_allowlist = set(
        BASE_FEATURE_CANDIDATES
        + ROSTER_FEATURE_CANDIDATES
        + MARKET_FEATURE_CANDIDATES
        + [
            "delta_prev_season_points_pct",
            "delta_prev_season_goal_diff_pg",
            "delta_roster_coverage_pct",
            "delta_roster_games_covered",
        ]
        + INTERACTION_FEATURE_NAMES
        + V3_INTERACTION_FEATURE_NAMES
        + V4_INTERACTION_FEATURE_NAMES
    )
    logistic_features = sorted({name for name in feature_rows[0].features.keys() if name in logistic_allowlist})
    weighted_features = sorted([name for name in logistic_features if name in WEIGHTED_MODEL_WEIGHTS])

    all_predictions: List[Dict[str, object]] = []
    fold_summaries: List[Dict[str, object]] = []
    logistic_importance_rows: List[Dict[str, object]] = []
    calibration_diagnostics_rows: List[Dict[str, object]] = []

    for idx in range(min_train_seasons, len(seasons)):
        train_seasons = seasons[:idx]
        test_season = seasons[idx]
        train_rows = [r for r in feature_rows if r.season in train_seasons]
        test_rows = [r for r in feature_rows if r.season == test_season]
        if not train_rows or not test_rows:
            continue
        fold_recency_config, fold_regime = select_fold_recency_config(
            base_config=recency_candidate.base_config,
            selector_mode=recency_candidate.selector_mode,
            train_seasons=train_seasons,
        )
        train_weights = compute_recency_weights(train_rows, train_seasons, fold_recency_config)

        train_games: List[HistoricalGame] = []
        test_games: List[HistoricalGame] = []
        if model_scope != "logistic_only":
            train_games = [
                historical_map[(r.season, r.game_id)]
                for r in train_rows
                if (r.season, r.game_id) in historical_map
            ]
            test_games = [
                historical_map[(r.season, r.game_id)]
                for r in test_rows
                if (r.season, r.game_id) in historical_map
            ]
            if len(train_games) != len(train_rows) or len(test_games) != len(test_rows):
                raise ValueError("Missing historical_games_last5 rows required for Elo evaluation.")

        # Model A: tuned Elo-form blend.
        elo_params = tune_elo_params(train_games)
        elo_state = EloState(elo_params)
        for game in train_games:
            elo_state.predict_update(game, do_update=True)
        elo_probs: Dict[Tuple[int, int], float] = {}
        for game in test_games:
            p = elo_state.predict_update(game, do_update=True)
            elo_probs[(game.season, game.game_id)] = p

        # Model B: logistic model on engineered features.
        tuned_cfg = tune_logistic_hyperparameters(train_rows, logistic_features, train_row_weights=train_weights)
        med, sc = build_robust_scaler(train_rows, logistic_features)
        x_train = [build_feature_vector(r, logistic_features, med, sc) for r in train_rows]
        y_train = [r.home_win for r in train_rows]
        w, b = fit_logistic(
            x_train,
            y_train,
            learning_rate=float(tuned_cfg["lr"]),
            l2=float(tuned_cfg["l2"]),
            epochs=int(tuned_cfg["epochs"]),
            sample_weights=train_weights,
        )
        fold_importance_top = summarize_logistic_importance(w, logistic_features, top_n=20)
        for row in fold_importance_top:
            logistic_importance_rows.append(
                {
                    "fold_test_season": test_season,
                    "feature": str(row["feature"]),
                    "abs_weight": round(float(row["abs_weight"]), 10),
                    "weight": round(float(row["weight"]), 10),
                }
            )
        logistic_probs: Dict[Tuple[int, int], float] = {}
        for row in test_rows:
            x = build_feature_vector(row, logistic_features, med, sc)
            logistic_probs[(row.season, row.game_id)] = predict_logistic_probability(x, w, b)

        if model_scope == "logistic_only":
            for row in test_rows:
                key = (row.season, row.game_id)
                p_home = logistic_probs[key]
                pred_home = 1 if p_home >= 0.5 else 0
                predicted_winner = row.home_team if pred_home == 1 else row.away_team
                all_predictions.append(
                    {
                        "model_id": "logistic_engineered",
                        "fold_train_end_season": train_seasons[-1],
                        "fold_test_season": test_season,
                        "season": row.season,
                        "game_id": row.game_id,
                        "game_date": row.game_date,
                        "home_team_abbrev": row.home_team,
                        "away_team_abbrev": row.away_team,
                        "actual_home_win": row.home_win,
                        "home_win_probability": round(p_home, 6),
                        "away_win_probability": round(1.0 - p_home, 6),
                        "predicted_winner_abbrev": predicted_winner,
                        "is_correct_pick": 1 if pred_home == row.home_win else 0,
                        "recency_candidate_id": recency_candidate.candidate_id,
                        "recency_selector_mode": recency_candidate.selector_mode,
                        "recency_selector_regime": fold_regime,
                        "recency_mode": fold_recency_config.mode,
                        "recency_season_half_life": fold_recency_config.season_half_life,
                        "recency_game_half_life": fold_recency_config.game_half_life,
                        "recency_min_weight": fold_recency_config.min_weight,
                        "recency_normalize_mean_one": fold_recency_config.normalize_mean_one,
                        "recency_base_mode": recency_candidate.base_config.mode,
                        "recency_base_season_half_life": recency_candidate.base_config.season_half_life,
                        "recency_base_game_half_life": recency_candidate.base_config.game_half_life,
                        "recency_base_min_weight": recency_candidate.base_config.min_weight,
                        "recency_base_normalize_mean_one": recency_candidate.base_config.normalize_mean_one,
                        "nonlinear_model_backend": "skipped",
                        "nonlinear_model_style": "logistic_only",
                    }
                )
            fold_summaries.append(
                {
                    "fold_test_season": test_season,
                    "fold_train_start_season": train_seasons[0],
                    "fold_train_end_season": train_seasons[-1],
                    "train_games": len(train_rows),
                    "test_games": len(test_rows),
                    "recency": {
                        "candidate_id": recency_candidate.candidate_id,
                        "selector_mode": recency_candidate.selector_mode,
                        "selector_regime": fold_regime,
                        "mode": fold_recency_config.mode,
                        "season_half_life": fold_recency_config.season_half_life,
                        "game_half_life": fold_recency_config.game_half_life,
                        "min_weight": fold_recency_config.min_weight,
                        "normalize_mean_one": fold_recency_config.normalize_mean_one,
                    },
                    "logistic_tuning": tuned_cfg,
                    "execution_mode": "logistic_only",
                }
            )
            continue

        # Model D: nonlinear tree family (prefers LightGBM/XGBoost when available; deterministic fallback otherwise).
        nonlinear_predictor, nonlinear_model_info = build_nonlinear_predictor(
            train_rows=train_rows,
            feature_names=logistic_features,
            sample_weights=train_weights,
        )
        nonlinear_probs: Dict[Tuple[int, int], float] = {}
        for row in test_rows:
            nonlinear_probs[(row.season, row.game_id)] = nonlinear_predictor(row)

        # Model C: fold-local calibration with deterministic season/regime-aware method selection.
        calibration_train_seasons = sorted({r.season for r in train_rows})
        requested_validation_seasons = max(1, int(calibration_config.validation_seasons))
        selected_validation_seasons = calibration_train_seasons[-requested_validation_seasons:]
        if len(calibration_train_seasons) > requested_validation_seasons:
            fit_season_set = set(calibration_train_seasons[:-requested_validation_seasons])
        else:
            fit_season_set = set(calibration_train_seasons)
        calibration_fit_rows: List[FeatureRow] = []
        calibration_fit_weights: List[float] = []
        calibration_val_rows: List[FeatureRow] = []
        for row, row_weight in zip(train_rows, train_weights):
            if row.season in fit_season_set:
                calibration_fit_rows.append(row)
                calibration_fit_weights.append(row_weight)
            if row.season in set(selected_validation_seasons):
                calibration_val_rows.append(row)
        if not calibration_fit_rows or not calibration_val_rows:
            calibration_fit_rows = list(train_rows)
            calibration_fit_weights = list(train_weights)
            calibration_val_rows = list(train_rows)
            selected_validation_seasons = [calibration_train_seasons[-1]] if calibration_train_seasons else []
        calibration_fit_games = [
            historical_map[(r.season, r.game_id)]
            for r in calibration_fit_rows
            if (r.season, r.game_id) in historical_map
        ]
        calibration_val_games = [
            historical_map[(r.season, r.game_id)]
            for r in calibration_val_rows
            if (r.season, r.game_id) in historical_map
        ]
        if len(calibration_fit_games) != len(calibration_fit_rows) or len(calibration_val_games) != len(calibration_val_rows):
            raise ValueError("Missing historical rows in calibration split for fold-safe blend selection.")

        fit_med, fit_sc = build_robust_scaler(calibration_fit_rows, weighted_features)
        fit_scores = [weighted_score(r, weighted_features, fit_med, fit_sc) for r in calibration_fit_rows]
        fit_targets = [r.home_win for r in calibration_fit_rows]
        val_scores = [weighted_score(r, weighted_features, fit_med, fit_sc) for r in calibration_val_rows]
        val_targets = [r.home_win for r in calibration_val_rows]

        method_probs_on_val: Dict[str, List[float]] = {}
        val_metrics_by_method: Dict[str, Dict[str, float]] = {}
        platt_fit_a, platt_fit_b = fit_platt_scaler(
            fit_scores,
            fit_targets,
            sample_weights=calibration_fit_weights,
        )
        method_probs_on_val["platt"] = [apply_platt(s, platt_fit_a, platt_fit_b) for s in val_scores]
        val_metrics_by_method["platt"] = compute_metrics_from_arrays(val_targets, method_probs_on_val["platt"])
        isotonic_fit = fit_isotonic_calibrator(fit_scores, fit_targets, sample_weights=calibration_fit_weights)
        method_probs_on_val["isotonic"] = [apply_isotonic(s, isotonic_fit["breakpoints"], isotonic_fit["values"]) for s in val_scores]
        val_metrics_by_method["isotonic"] = compute_metrics_from_arrays(val_targets, method_probs_on_val["isotonic"])

        val_idx_by_season: Dict[int, List[int]] = {}
        val_idx_by_regime: Dict[str, List[int]] = {}
        ordered_val_seasons = sorted({r.season for r in calibration_val_rows})
        for idx_val, row in enumerate(calibration_val_rows):
            val_idx_by_season.setdefault(row.season, []).append(idx_val)
            regime_bucket = calibration_validation_regime_label(row.season, ordered_val_seasons)
            val_idx_by_regime.setdefault(regime_bucket, []).append(idx_val)

        view_metrics_by_method: Dict[str, Dict[str, Dict[str, float]]] = {"overall": val_metrics_by_method}
        for season in sorted(val_idx_by_season.keys()):
            idxs = val_idx_by_season[season]
            y_view = [val_targets[i] for i in idxs]
            view_name = f"season_{season}"
            view_metrics_by_method[view_name] = {
                method_name: compute_metrics_from_arrays(y_view, [method_probs_on_val[method_name][i] for i in idxs])
                for method_name in sorted(method_probs_on_val.keys())
            }
        for regime_name in sorted(val_idx_by_regime.keys()):
            idxs = val_idx_by_regime[regime_name]
            y_view = [val_targets[i] for i in idxs]
            view_name = f"regime_{regime_name}"
            view_metrics_by_method[view_name] = {
                method_name: compute_metrics_from_arrays(y_view, [method_probs_on_val[method_name][i] for i in idxs])
                for method_name in sorted(method_probs_on_val.keys())
            }

        selector_mode = str(calibration_config.selector_mode)
        selector_view = "overall"
        selector_notes = "aggregate_validation"
        selector_metrics_by_method = val_metrics_by_method
        if selector_mode == "season_aware":
            latest_val_season = ordered_val_seasons[-1] if ordered_val_seasons else None
            weighted_method_metrics: Dict[str, Dict[str, float]] = {}
            for method_name in sorted(method_probs_on_val.keys()):
                weighted_rows: List[Tuple[float, Dict[str, float]]] = []
                for season in ordered_val_seasons:
                    season_metrics = view_metrics_by_method.get(f"season_{season}", {}).get(method_name)
                    if season_metrics is None:
                        continue
                    age = 0 if latest_val_season is None else max(0, ordered_val_seasons.index(latest_val_season) - ordered_val_seasons.index(season))
                    season_w = math.pow(0.5, age / max(float(calibration_config.season_half_life), 1e-6))
                    weighted_rows.append((season_w, season_metrics))
                weighted_method_metrics[method_name] = aggregate_weighted_metrics(weighted_rows)
            selector_view = "season_aware_weighted"
            selector_notes = "recency_weighted_over_validation_seasons"
            selector_metrics_by_method = weighted_method_metrics
            view_metrics_by_method[selector_view] = weighted_method_metrics
        elif selector_mode == "season_regime":
            regime_to_view = {
                "early": "regime_early_window",
                "middle": "regime_middle_window",
                "late": "regime_late_window",
            }
            preferred_view = regime_to_view.get(fold_regime, "regime_late_window")
            if preferred_view in view_metrics_by_method:
                selector_view = preferred_view
                selector_notes = f"regime_matched_{fold_regime}"
                selector_metrics_by_method = view_metrics_by_method[preferred_view]
            else:
                selector_view = "overall"
                selector_notes = f"regime_fallback_overall_{fold_regime}"
                selector_metrics_by_method = val_metrics_by_method

        selected_calibration_method = choose_calibration_method(
            selector_metrics_by_method,
            objective=str(calibration_config.selection_objective),
            objective_margin=float(calibration_config.objective_margin),
        )

        # Fold-safe family ranking for blend construction (fit on calibration-train, rank on calibration-validation).
        calibration_elo_params = tune_elo_params(calibration_fit_games)
        calibration_elo_state = EloState(calibration_elo_params)
        for game in calibration_fit_games:
            calibration_elo_state.predict_update(game, do_update=True)
        calibration_elo_val_probs: List[float] = []
        for game in calibration_val_games:
            calibration_elo_val_probs.append(calibration_elo_state.predict_update(game, do_update=True))

        calibration_logistic_cfg = tune_logistic_hyperparameters(
            calibration_fit_rows,
            logistic_features,
            train_row_weights=calibration_fit_weights,
        )
        calibration_log_med, calibration_log_sc = build_robust_scaler(calibration_fit_rows, logistic_features)
        calibration_x_train = [
            build_feature_vector(r, logistic_features, calibration_log_med, calibration_log_sc)
            for r in calibration_fit_rows
        ]
        calibration_y_train = [r.home_win for r in calibration_fit_rows]
        calibration_log_w, calibration_log_b = fit_logistic(
            calibration_x_train,
            calibration_y_train,
            learning_rate=float(calibration_logistic_cfg["lr"]),
            l2=float(calibration_logistic_cfg["l2"]),
            epochs=int(calibration_logistic_cfg["epochs"]),
            sample_weights=calibration_fit_weights,
        )
        calibration_logistic_val_probs = [
            predict_logistic_probability(
                build_feature_vector(r, logistic_features, calibration_log_med, calibration_log_sc),
                calibration_log_w,
                calibration_log_b,
            )
            for r in calibration_val_rows
        ]
        calibration_nonlinear_predictor, _ = build_nonlinear_predictor(
            train_rows=calibration_fit_rows,
            feature_names=logistic_features,
            sample_weights=calibration_fit_weights,
        )
        calibration_nonlinear_val_probs = [calibration_nonlinear_predictor(r) for r in calibration_val_rows]
        calibration_weighted_val_probs = method_probs_on_val[selected_calibration_method]
        family_probs_by_model = {
            "elo_form_tuned": calibration_elo_val_probs,
            "logistic_engineered": calibration_logistic_val_probs,
            "weighted_calibrated": calibration_weighted_val_probs,
            "nonlinear_tree": calibration_nonlinear_val_probs,
        }
        family_metrics = {
            model_id: compute_metrics_from_arrays(val_targets, probs)
            for model_id, probs in family_probs_by_model.items()
        }
        fold_blend_variants, fold_blend_diagnostics = build_fold_blend_variants(
            family_metrics=family_metrics,
            family_probs_by_model=family_probs_by_model,
            targets=val_targets,
        )
        fold_blend_diagnostics["validation_seasons"] = selected_validation_seasons
        fold_blend_diagnostics["validation_games"] = len(val_targets)

        w_med, w_sc = build_robust_scaler(train_rows, weighted_features)
        train_scores = [weighted_score(r, weighted_features, w_med, w_sc) for r in train_rows]
        train_targets = [r.home_win for r in train_rows]
        full_platt_a, full_platt_b = fit_platt_scaler(train_scores, train_targets, sample_weights=train_weights)
        full_isotonic = fit_isotonic_calibrator(train_scores, train_targets, sample_weights=train_weights)

        weighted_probs_selected: Dict[Tuple[int, int], float] = {}
        weighted_probs_platt: Dict[Tuple[int, int], float] = {}
        weighted_probs_isotonic: Dict[Tuple[int, int], float] = {}
        for row in test_rows:
            score = weighted_score(row, weighted_features, w_med, w_sc)
            key = (row.season, row.game_id)
            platt_prob = apply_platt(score, full_platt_a, full_platt_b)
            isotonic_prob = apply_isotonic(score, full_isotonic["breakpoints"], full_isotonic["values"])
            weighted_probs_platt[key] = platt_prob
            weighted_probs_isotonic[key] = isotonic_prob
            weighted_probs_selected[key] = platt_prob if selected_calibration_method == "platt" else isotonic_prob

        for row in test_rows:
            key = (row.season, row.game_id)
            base_model_probs = {
                "elo_form_tuned": elo_probs[key],
                "logistic_engineered": logistic_probs[key],
                "weighted_calibrated": weighted_probs_selected[key],
                "weighted_calibrated_platt": weighted_probs_platt[key],
                "weighted_calibrated_isotonic": weighted_probs_isotonic[key],
                "nonlinear_tree": nonlinear_probs[key],
            }
            model_probs = dict(base_model_probs)
            for blend_model_id, blend_weights in fold_blend_variants.items():
                model_probs[blend_model_id] = blend_probabilities(base_model_probs, blend_weights)
            for model_id, p_home in model_probs.items():
                pred_home = 1 if p_home >= 0.5 else 0
                predicted_winner = row.home_team if pred_home == 1 else row.away_team
                all_predictions.append(
                    {
                        "model_id": model_id,
                        "fold_train_end_season": train_seasons[-1],
                        "fold_test_season": test_season,
                        "season": row.season,
                        "game_id": row.game_id,
                        "game_date": row.game_date,
                        "home_team_abbrev": row.home_team,
                        "away_team_abbrev": row.away_team,
                        "actual_home_win": row.home_win,
                        "home_win_probability": round(p_home, 6),
                        "away_win_probability": round(1.0 - p_home, 6),
                        "predicted_winner_abbrev": predicted_winner,
                        "is_correct_pick": 1 if pred_home == row.home_win else 0,
                        "recency_candidate_id": recency_candidate.candidate_id,
                        "recency_selector_mode": recency_candidate.selector_mode,
                        "recency_selector_regime": fold_regime,
                        "recency_mode": fold_recency_config.mode,
                        "recency_season_half_life": fold_recency_config.season_half_life,
                        "recency_game_half_life": fold_recency_config.game_half_life,
                        "recency_min_weight": fold_recency_config.min_weight,
                        "recency_normalize_mean_one": fold_recency_config.normalize_mean_one,
                        "recency_base_mode": recency_candidate.base_config.mode,
                        "recency_base_season_half_life": recency_candidate.base_config.season_half_life,
                        "recency_base_game_half_life": recency_candidate.base_config.game_half_life,
                        "recency_base_min_weight": recency_candidate.base_config.min_weight,
                        "recency_base_normalize_mean_one": recency_candidate.base_config.normalize_mean_one,
                        "nonlinear_model_backend": str(nonlinear_model_info.get("backend", "unknown")),
                        "nonlinear_model_style": str(nonlinear_model_info.get("style", "tree")),
                    }
                )

        fold_summaries.append(
            {
                "fold_test_season": test_season,
                "fold_train_start_season": train_seasons[0],
                "fold_train_end_season": train_seasons[-1],
                "train_games": len(train_rows),
                "test_games": len(test_rows),
                "elo_params": {
                    "home_advantage": elo_params.home_advantage,
                    "k_factor": elo_params.k_factor,
                    "form_win_weight": elo_params.form_win_weight,
                    "form_goal_weight": elo_params.form_goal_weight,
                },
                "logistic_params": {
                    "learning_rate": tuned_cfg["lr"],
                    "l2": tuned_cfg["l2"],
                    "epochs": int(tuned_cfg["epochs"]),
                },
                "nonlinear_model": nonlinear_model_info,
                "logistic_feature_importance_top": [
                    {
                        "feature": str(row["feature"]),
                        "abs_weight": round(float(row["abs_weight"]), 8),
                        "weight": round(float(row["weight"]), 8),
                    }
                    for row in fold_importance_top
                ],
                "interaction_feature_importance": [
                    {
                        "feature": str(row["feature"]),
                        "abs_weight": round(float(row["abs_weight"]), 8),
                        "weight": round(float(row["weight"]), 8),
                    }
                    for row in fold_importance_top
                    if str(row["feature"]) in INTERACTION_FEATURE_NAMES
                ],
                "recency_weighting": {
                    "candidate_id": recency_candidate.candidate_id,
                    "selector_mode": recency_candidate.selector_mode,
                    "selector_regime": fold_regime,
                    "mode": fold_recency_config.mode,
                    "season_half_life": fold_recency_config.season_half_life,
                    "game_half_life": fold_recency_config.game_half_life,
                    "min_weight": fold_recency_config.min_weight,
                    "normalize_mean_one": fold_recency_config.normalize_mean_one,
                    "base_mode": recency_candidate.base_config.mode,
                    "base_season_half_life": recency_candidate.base_config.season_half_life,
                    "base_game_half_life": recency_candidate.base_config.game_half_life,
                    "base_min_weight": recency_candidate.base_config.min_weight,
                    "base_normalize_mean_one": recency_candidate.base_config.normalize_mean_one,
                    "train_weight_min": min(train_weights) if train_weights else 1.0,
                    "train_weight_max": max(train_weights) if train_weights else 1.0,
                    "train_weight_mean": (sum(train_weights) / len(train_weights)) if train_weights else 1.0,
                },
                "weighted_calibration": {
                    "selected_method": selected_calibration_method,
                    "selector_mode": selector_mode,
                    "selector_view": selector_view,
                    "selector_notes": selector_notes,
                    "selection_objective": calibration_config.selection_objective,
                    "selection_objective_margin": calibration_config.objective_margin,
                    "validation_seasons": selected_validation_seasons,
                    "selection_fit_games": len(calibration_fit_rows),
                    "selection_validation_games": len(calibration_val_rows),
                    "selection_metrics": {
                        method: {
                            "games": int(m["games"]),
                            "accuracy": round(m["accuracy"], 6),
                            "log_loss": round(m["log_loss"], 6),
                            "brier_score": round(m["brier_score"], 6),
                        }
                        for method, m in sorted(selector_metrics_by_method.items())
                    },
                    "overall_validation_metrics": {
                        method: {
                            "games": int(m["games"]),
                            "accuracy": round(m["accuracy"], 6),
                            "log_loss": round(m["log_loss"], 6),
                            "brier_score": round(m["brier_score"], 6),
                        }
                        for method, m in sorted(val_metrics_by_method.items())
                    },
                    "diagnostic_views": {
                        view_name: {
                            method: {
                                "games": int(m["games"]),
                                "accuracy": round(m["accuracy"], 6),
                                "log_loss": round(m["log_loss"], 6),
                                "brier_score": round(m["brier_score"], 6),
                            }
                            for method, m in sorted(view_metrics.items())
                        }
                        for view_name, view_metrics in sorted(view_metrics_by_method.items())
                    },
                    "calibration_methods_by_variant": {
                        "weighted_calibrated": selected_calibration_method,
                        "weighted_calibrated_platt": "platt",
                        "weighted_calibrated_isotonic": "isotonic",
                    },
                    "selected_fit_parameters": (
                        {"a": full_platt_a, "b": full_platt_b}
                        if selected_calibration_method == "platt"
                        else {
                            "breakpoints": full_isotonic["breakpoints"],
                            "values": full_isotonic["values"],
                        }
                    ),
                },
                "blend_weights": fold_blend_variants,
                "blend_diagnostics": fold_blend_diagnostics,
            }
        )
        for method_name, metrics in sorted(val_metrics_by_method.items()):
            calibration_diagnostics_rows.append(
                {
                    "fold_test_season": test_season,
                    "fold_train_start_season": train_seasons[0],
                    "fold_train_end_season": train_seasons[-1],
                    "recency_candidate_id": recency_candidate.candidate_id,
                    "recency_selector_mode": recency_candidate.selector_mode,
                    "recency_selector_regime": fold_regime,
                    "calibration_selector_mode": selector_mode,
                    "calibration_selector_view": selector_view,
                    "calibration_selector_notes": selector_notes,
                    "calibration_selection_objective": calibration_config.selection_objective,
                    "calibration_objective_margin": round(float(calibration_config.objective_margin), 6),
                    "calibration_validation_seasons": ",".join([str(s) for s in selected_validation_seasons]),
                    "selection_fit_games": len(calibration_fit_rows),
                    "selection_validation_games": len(calibration_val_rows),
                    "calibration_method": method_name,
                    "is_selected_method": 1 if method_name == selected_calibration_method else 0,
                    "accuracy": round(float(metrics["accuracy"]), 6),
                    "log_loss": round(float(metrics["log_loss"]), 6),
                    "brier_score": round(float(metrics["brier_score"]), 6),
                }
            )

    return all_predictions, fold_summaries, logistic_importance_rows, calibration_diagnostics_rows


def build_recency_candidates(args: argparse.Namespace) -> List[RecencyCandidate]:
    base_single = RecencyCandidate(
        candidate_id="single",
        selector_mode=str(args.recency_selector_mode),
        base_config=RecencyConfig(
            mode=str(args.recency_decay_mode),
            season_half_life=max(1e-6, float(args.recency_season_half_life)),
            game_half_life=max(1e-6, float(args.recency_game_half_life)),
            min_weight=max(0.0, float(args.recency_min_weight)),
            normalize_mean_one=not bool(args.recency_disable_normalize),
        ),
    )
    if not bool(args.recency_sweep):
        return [base_single]

    if str(args.recency_grid_profile) == "drift_2025_2026":
        max_candidates = max(1, int(args.recency_sweep_max_candidates))
        return [
            RecencyCandidate(
                candidate_id=f"sweep_{idx:03d}",
                selector_mode=str(args.recency_selector_mode),
                base_config=cfg,
            )
            for idx, cfg in enumerate(DRIFT_2025_2026_RECENCY_GRID[:max_candidates], start=1)
        ]

    sweep_modes = parse_comma_list(str(args.recency_sweep_modes))
    if not sweep_modes:
        raise ValueError("recency_sweep_modes must include at least one mode.")
    valid_modes = {"none", "season_exponential", "game_exponential", "hybrid_exponential"}
    unknown_modes = sorted([m for m in sweep_modes if m not in valid_modes])
    if unknown_modes:
        raise ValueError(f"Unsupported recency_sweep_modes: {','.join(unknown_modes)}")

    season_half_lives = [max(1e-6, x) for x in parse_float_list(str(args.recency_sweep_season_half_lives))]
    game_half_lives = [max(1e-6, x) for x in parse_float_list(str(args.recency_sweep_game_half_lives))]
    normalize_options = parse_bool_list(str(args.recency_sweep_normalize_options))

    min_lower = max(0.0, float(args.recency_sweep_min_weight_lower))
    min_upper = max(min_lower, float(args.recency_sweep_min_weight_upper))
    raw_min_weights = parse_float_list(str(args.recency_sweep_min_weights))
    min_weights = [w for w in sorted(set(raw_min_weights)) if min_lower <= w <= min_upper]
    if not min_weights:
        raise ValueError("No recency_sweep_min_weights remain after applying min-weight guardrails.")

    configs: List[RecencyConfig] = []
    for mode in sweep_modes:
        if mode == "none":
            configs.append(
                RecencyConfig(
                    mode="none",
                    season_half_life=1.0,
                    game_half_life=1.0,
                    min_weight=1.0,
                    normalize_mean_one=True,
                )
            )
            continue

        if mode == "season_exponential":
            iterator = itertools.product(season_half_lives, min_weights, normalize_options)
            for season_hl, min_weight, normalize_mean_one in iterator:
                configs.append(
                    RecencyConfig(
                        mode=mode,
                        season_half_life=float(season_hl),
                        game_half_life=max(game_half_lives),
                        min_weight=float(min_weight),
                        normalize_mean_one=bool(normalize_mean_one),
                    )
                )
            continue

        if mode == "game_exponential":
            iterator = itertools.product(game_half_lives, min_weights, normalize_options)
            for game_hl, min_weight, normalize_mean_one in iterator:
                configs.append(
                    RecencyConfig(
                        mode=mode,
                        season_half_life=max(season_half_lives),
                        game_half_life=float(game_hl),
                        min_weight=float(min_weight),
                        normalize_mean_one=bool(normalize_mean_one),
                    )
                )
            continue

        iterator = itertools.product(season_half_lives, game_half_lives, min_weights, normalize_options)
        for season_hl, game_hl, min_weight, normalize_mean_one in iterator:
            configs.append(
                RecencyConfig(
                    mode=mode,
                    season_half_life=float(season_hl),
                    game_half_life=float(game_hl),
                    min_weight=float(min_weight),
                    normalize_mean_one=bool(normalize_mean_one),
                )
            )

    dedup: List[RecencyConfig] = []
    seen = set()
    for cfg in configs:
        key = (
            cfg.mode,
            round(cfg.season_half_life, 10),
            round(cfg.game_half_life, 10),
            round(cfg.min_weight, 10),
            cfg.normalize_mean_one,
        )
        if key in seen:
            continue
        seen.add(key)
        dedup.append(cfg)

    max_candidates = max(1, int(args.recency_sweep_max_candidates))
    dedup = dedup[:max_candidates]

    candidates: List[RecencyCandidate] = []
    for idx, cfg in enumerate(dedup, start=1):
        candidates.append(
            RecencyCandidate(
                candidate_id=f"sweep_{idx:03d}",
                selector_mode=str(args.recency_selector_mode),
                base_config=cfg,
            )
        )
    return candidates


def build_recency_comparison_rows(overall_rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    ranked = sorted(
        list(overall_rows),
        key=lambda r: (
            -float(r["accuracy"]),
            float(r["log_loss"]),
            float(r["brier_score"]),
            str(r.get("model_id", "")),
            str(r.get("recency_candidate_id", "")),
        ),
    )
    out: List[Dict[str, object]] = []
    for rank, row in enumerate(ranked, start=1):
        out.append({"rank": rank, **row})
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deterministic season-expanding walk-forward harness for multi-model NHL experiments."
    )
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--sqlite-db", default=None, help="Defaults to data\\processed\\nhl_research.db")
    parser.add_argument("--features-table", default=None, help="Auto: backtest_features_last5_roster -> backtest_features_last5")
    parser.add_argument("--require-roster-features", action="store_true")
    parser.add_argument("--auto-build-base-features", action="store_true")
    parser.add_argument("--dependency-retries", type=int, default=2)
    parser.add_argument("--dependency-wait-seconds", type=int, default=5)
    parser.add_argument("--min-train-seasons", type=int, default=2)
    parser.add_argument(
        "--recency-decay-mode",
        default="none",
        choices=["none", "season_exponential", "game_exponential", "hybrid_exponential"],
        help="Deterministic training sample weighting for recency emphasis.",
    )
    parser.add_argument(
        "--recency-season-half-life",
        type=float,
        default=1.5,
        help="Half-life in seasons for season/hybrid recency decay.",
    )
    parser.add_argument(
        "--recency-game-half-life",
        type=float,
        default=800.0,
        help="Half-life in games for game/hybrid recency decay.",
    )
    parser.add_argument(
        "--recency-min-weight",
        type=float,
        default=0.2,
        help="Floor for decay weights before optional normalization.",
    )
    parser.add_argument(
        "--recency-disable-normalize",
        action="store_true",
        help="Disable normalization that rescales each fold's recency weights to mean=1.",
    )
    parser.add_argument(
        "--recency-selector-mode",
        default="static",
        choices=["static", "season_regime", "season_regime_drift"],
        help="Fold-local deterministic selector for adapting recency settings by train-season regime.",
    )
    parser.add_argument(
        "--calibration-selector-mode",
        default="season_aware",
        choices=["static", "season_aware", "season_regime"],
        help="Fold-local calibration selector for choosing between Platt and isotonic.",
    )
    parser.add_argument(
        "--calibration-validation-seasons",
        type=int,
        default=2,
        help="Number of latest train seasons reserved for calibration method selection.",
    )
    parser.add_argument(
        "--calibration-season-half-life",
        type=float,
        default=1.0,
        help="Half-life in seasons for season-aware calibration selector weighting.",
    )
    parser.add_argument(
        "--calibration-selection-objective",
        default="joint",
        choices=["joint", "log_loss", "brier"],
        help="Primary objective for calibration selection.",
    )
    parser.add_argument(
        "--calibration-objective-margin",
        type=float,
        default=0.0005,
        help="Prefer Platt when objective gap to best method is within this margin.",
    )
    parser.add_argument(
        "--recency-grid-profile",
        default="default",
        choices=["default", "drift_2025_2026"],
        help="Deterministic recency candidate profile used when --recency-sweep is enabled.",
    )
    parser.add_argument("--recency-sweep", action="store_true", help="Run deterministic broad recency sweep.")
    parser.add_argument(
        "--recency-sweep-modes",
        default="none,season_exponential,game_exponential,hybrid_exponential",
        help="Comma list of recency modes included in sweep.",
    )
    parser.add_argument(
        "--recency-sweep-season-half-lives",
        default="0.75,1.0,1.5,2.0,3.0",
        help="Comma list of season half-lives for sweep combinations.",
    )
    parser.add_argument(
        "--recency-sweep-game-half-lives",
        default="300,450,650,900,1200",
        help="Comma list of game half-lives for sweep combinations.",
    )
    parser.add_argument(
        "--recency-sweep-min-weights",
        default="0.05,0.1,0.15,0.2,0.3",
        help="Comma list of min-weight values for sweep combinations.",
    )
    parser.add_argument(
        "--recency-sweep-min-weight-lower",
        type=float,
        default=0.05,
        help="Lower guardrail applied to recency-sweep min-weight values.",
    )
    parser.add_argument(
        "--recency-sweep-min-weight-upper",
        type=float,
        default=0.35,
        help="Upper guardrail applied to recency-sweep min-weight values.",
    )
    parser.add_argument(
        "--recency-sweep-normalize-options",
        default="true,false",
        help="Comma list of normalize options for sweep (true/false).",
    )
    parser.add_argument(
        "--recency-sweep-max-candidates",
        type=int,
        default=120,
        help="Deterministic cap on generated recency sweep candidates.",
    )
    parser.add_argument(
        "--model-scope",
        default="full",
        choices=["full", "logistic_only"],
        help="Model families to evaluate. Use logistic_only for faster recency-grid retuning runs.",
    )
    parser.add_argument("--output-predictions-csv", default=None, help="Defaults to data\\processed\\walk_forward_experiment_predictions.csv")
    parser.add_argument("--output-overall-csv", default=None, help="Defaults to data\\processed\\walk_forward_experiment_metrics_overall.csv")
    parser.add_argument("--output-by-season-csv", default=None, help="Defaults to data\\processed\\walk_forward_experiment_metrics_by_season.csv")
    parser.add_argument(
        "--output-recency-comparison-csv",
        default=None,
        help="Defaults to data\\processed\\walk_forward_experiment_recency_comparison.csv",
    )
    parser.add_argument(
        "--output-logistic-importance-csv",
        default=None,
        help="Defaults to data\\processed\\walk_forward_experiment_logistic_feature_importance.csv",
    )
    parser.add_argument(
        "--output-calibration-diagnostics-csv",
        default=None,
        help="Defaults to data\\processed\\walk_forward_experiment_calibration_diagnostics.csv",
    )
    parser.add_argument("--output-summary-json", default=None, help="Defaults to data\\processed\\walk_forward_experiment_summary.json")
    parser.add_argument("--skip-sqlite-write", action="store_true")
    parser.add_argument(
        "--exclude-synthetic-data",
        action="store_true",
        help="Exclude rows marked synthetic (or the known fabricated 2015-2018 seasons when provenance is absent).",
    )
    parser.add_argument(
        "--exclude-market-features",
        action="store_true",
        help="Do not load synthetic/circular market_signals features or derived market interactions.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    sqlite_db = Path(args.sqlite_db).resolve() if args.sqlite_db else repo_root / "data" / "processed" / "nhl_research.db"
    output_predictions_csv = (
        Path(args.output_predictions_csv).resolve()
        if args.output_predictions_csv
        else repo_root / "data" / "processed" / "walk_forward_experiment_predictions.csv"
    )
    output_overall_csv = (
        Path(args.output_overall_csv).resolve()
        if args.output_overall_csv
        else repo_root / "data" / "processed" / "walk_forward_experiment_metrics_overall.csv"
    )
    output_by_season_csv = (
        Path(args.output_by_season_csv).resolve()
        if args.output_by_season_csv
        else repo_root / "data" / "processed" / "walk_forward_experiment_metrics_by_season.csv"
    )
    output_recency_comparison_csv = (
        Path(args.output_recency_comparison_csv).resolve()
        if args.output_recency_comparison_csv
        else repo_root / "data" / "processed" / "walk_forward_experiment_recency_comparison.csv"
    )
    output_logistic_importance_csv = (
        Path(args.output_logistic_importance_csv).resolve()
        if args.output_logistic_importance_csv
        else repo_root / "data" / "processed" / "walk_forward_experiment_logistic_feature_importance.csv"
    )
    output_calibration_diagnostics_csv = (
        Path(args.output_calibration_diagnostics_csv).resolve()
        if args.output_calibration_diagnostics_csv
        else repo_root / "data" / "processed" / "walk_forward_experiment_calibration_diagnostics.csv"
    )
    output_summary_json = (
        Path(args.output_summary_json).resolve()
        if args.output_summary_json
        else repo_root / "data" / "processed" / "walk_forward_experiment_summary.json"
    )
    recency_candidates = build_recency_candidates(args)
    calibration_config = CalibrationConfig(
        selector_mode=str(args.calibration_selector_mode),
        validation_seasons=max(1, int(args.calibration_validation_seasons)),
        season_half_life=max(1e-6, float(args.calibration_season_half_life)),
        selection_objective=str(args.calibration_selection_objective),
        objective_margin=max(0.0, float(args.calibration_objective_margin)),
    )

    with sqlite3.connect(sqlite_db) as con:
        selected_table, dependency_status = choose_feature_table(
            con=con,
            preferred_table=args.features_table,
            require_roster=bool(args.require_roster_features),
            dependency_retries=max(0, int(args.dependency_retries)),
            dependency_wait_seconds=max(0, int(args.dependency_wait_seconds)),
        )

        if dependency_status in ("feature_tables_missing", "preferred_table_missing") and args.auto_build_base_features:
            maybe_build_base_features(repo_root, sqlite_db, should_build=True)
            selected_table, dependency_status = choose_feature_table(
                con=con,
                preferred_table=args.features_table,
                require_roster=bool(args.require_roster_features),
                dependency_retries=0,
                dependency_wait_seconds=0,
            )

        if dependency_status == "roster_features_missing":
            raise SystemExit(
                "Required roster features are not available yet. Re-run after backtest_features_last5_roster is built."
            )
        if dependency_status in ("feature_tables_missing", "preferred_table_missing"):
            raise SystemExit("No compatible feature table available for walk-forward experiments.")

        feature_rows, feature_names = load_feature_rows(
            con,
            selected_table,
            exclude_synthetic_data=bool(args.exclude_synthetic_data),
            exclude_market_features=bool(args.exclude_market_features),
        )
        attach_interaction_features(feature_rows)
        feature_names = sorted({k for r in feature_rows for k in r.features.keys()})
        historical_games = load_historical_games(con)

    historical_map = {(g.season, g.game_id): g for g in historical_games}
    predictions: List[Dict[str, object]] = []
    fold_summaries: List[Dict[str, object]] = []
    logistic_importance_rows: List[Dict[str, object]] = []
    calibration_diagnostics_rows: List[Dict[str, object]] = []
    for candidate in recency_candidates:
        candidate_predictions, candidate_folds, candidate_importance, candidate_calibration = run_experiments(
            feature_rows=feature_rows,
            historical_map=historical_map,
            min_train_seasons=max(1, int(args.min_train_seasons)),
            recency_candidate=candidate,
            calibration_config=calibration_config,
            model_scope=str(args.model_scope),
        )
        for fold in candidate_folds:
            fold["recency_candidate_id"] = candidate.candidate_id
            fold["recency_selector_mode"] = candidate.selector_mode
        for importance_row in candidate_importance:
            importance_row["recency_candidate_id"] = candidate.candidate_id
        for calibration_row in candidate_calibration:
            calibration_row["recency_candidate_id"] = candidate.candidate_id
            calibration_row["recency_selector_mode"] = candidate.selector_mode
        predictions.extend(candidate_predictions)
        fold_summaries.extend(candidate_folds)
        logistic_importance_rows.extend(candidate_importance)
        calibration_diagnostics_rows.extend(candidate_calibration)
    if not predictions:
        raise SystemExit("No predictions generated. Check season coverage and input data.")

    overall_rows, by_season_rows = summarize_predictions(predictions)
    recency_comparison_rows = build_recency_comparison_rows(overall_rows)
    model_ids = sorted({str(row["model_id"]) for row in predictions})
    blend_model_ids = sorted([model_id for model_id in model_ids if model_id.startswith("blend_")])
    calibrator_variant_ids = {"weighted_calibrated", "weighted_calibrated_platt", "weighted_calibrated_isotonic"}
    calibrator_impact_overall = [
        row for row in overall_rows if str(row.get("model_id")) in calibrator_variant_ids
    ]
    blend_impact_overall = [
        row for row in overall_rows if str(row.get("model_id")) in set(blend_model_ids)
    ]
    interaction_importance_rows = [
        row for row in logistic_importance_rows if str(row.get("feature")) in INTERACTION_FEATURE_NAMES
    ]
    nonlinear_backend_ids = sorted({str(row.get("nonlinear_model_backend", "")) for row in predictions if row.get("nonlinear_model_backend")})
    nonlinear_style_ids = sorted({str(row.get("nonlinear_model_style", "")) for row in predictions if row.get("nonlinear_model_style")})
    write_csv(output_predictions_csv, predictions)
    write_csv(output_overall_csv, overall_rows)
    write_csv(output_by_season_csv, by_season_rows)
    write_csv(output_recency_comparison_csv, recency_comparison_rows)
    write_csv(output_logistic_importance_csv, logistic_importance_rows)
    write_csv(output_calibration_diagnostics_csv, calibration_diagnostics_rows)

    best_row = recency_comparison_rows[0] if recency_comparison_rows else None
    summary_payload = {
        "deterministic": True,
        "leakage_controls": [
            "season-expanding folds with train seasons strictly before each test season",
            "robust scaling fit only on each fold's training rows",
            "logistic tuning uses training-only split (latest train season as validation)",
            "weighted calibration method selected from fold-local train/validation split and refit on fold training rows",
            "Elo parameters tuned on training games only and evaluated on next season",
            "blend family ranking and validated blend-weight selection performed only on fold-local calibration split",
            "nonlinear model family fit using fold-local training rows only and scored only on fold-local validation/test rows",
        ],
        "data_source": {
            "sqlite_db": str(sqlite_db),
            "feature_table": selected_table,
            "historical_table": "historical_games_last5",
            "dependency_status": dependency_status,
            "feature_count": len(feature_names),
            "row_count": len(feature_rows),
            "exclude_synthetic_data": bool(args.exclude_synthetic_data),
            "exclude_market_features": bool(args.exclude_market_features),
        },
        "interaction_features": INTERACTION_FEATURE_NAMES,
        "recency_sweep_enabled": bool(args.recency_sweep),
        "model_scope": str(args.model_scope),
        "calibration_selector_config": {
            "selector_mode": calibration_config.selector_mode,
            "validation_seasons": calibration_config.validation_seasons,
            "season_half_life": calibration_config.season_half_life,
            "selection_objective": calibration_config.selection_objective,
            "objective_margin": calibration_config.objective_margin,
        },
        "recency_candidate_count": len(recency_candidates),
        "recency_candidates": [
            {
                "candidate_id": c.candidate_id,
                "selector_mode": c.selector_mode,
                "base_mode": c.base_config.mode,
                "base_season_half_life": c.base_config.season_half_life,
                "base_game_half_life": c.base_config.game_half_life,
                "base_min_weight": c.base_config.min_weight,
                "base_normalize_mean_one": c.base_config.normalize_mean_one,
            }
            for c in recency_candidates
        ],
        "recency_comparison_best": best_row,
        "models": model_ids,
        "nonlinear_backend_ids": nonlinear_backend_ids,
        "nonlinear_style_ids": nonlinear_style_ids,
        "blend_variants_static": BLEND_VARIANTS,
        "blend_model_ids": blend_model_ids,
        "blend_impact_overall": blend_impact_overall,
        "calibrator_impact_overall": calibrator_impact_overall,
        "recency_comparison": recency_comparison_rows,
        "logistic_feature_importance_by_fold": logistic_importance_rows,
        "interaction_feature_importance_by_fold": interaction_importance_rows,
        "calibration_diagnostics": calibration_diagnostics_rows,
        "folds": fold_summaries,
        "overall_metrics": overall_rows,
        "metrics_by_season": by_season_rows,
        "artifacts": {
            "predictions_csv": str(output_predictions_csv),
            "overall_csv": str(output_overall_csv),
            "by_season_csv": str(output_by_season_csv),
            "recency_comparison_csv": str(output_recency_comparison_csv),
            "logistic_importance_csv": str(output_logistic_importance_csv),
            "calibration_diagnostics_csv": str(output_calibration_diagnostics_csv),
            "summary_json": str(output_summary_json),
        },
    }
    write_json(output_summary_json, summary_payload)

    if not args.skip_sqlite_write:
        write_sqlite(sqlite_db, predictions, overall_rows, by_season_rows)

    print(f"dependency_status={dependency_status}")
    print(f"feature_table={selected_table}")
    print(f"games_scored={len(predictions)}")
    print(f"recency_candidates={len(recency_candidates)}")
    print(f"models={','.join(model_ids)}")
    print(f"nonlinear_backends={','.join(nonlinear_backend_ids)}")
    print(f"blend_models={','.join(blend_model_ids)}")
    if calibrator_impact_overall:
        print("calibrator_impact_overall=" + ";".join(
            [
                f"{r['model_id']}:acc={r['accuracy']},ll={r['log_loss']},brier={r['brier_score']}"
                for r in calibrator_impact_overall
            ]
        ))
    if blend_impact_overall:
        print("blend_impact_overall=" + ";".join(
            [
                f"{r['model_id']}:acc={r['accuracy']},ll={r['log_loss']},brier={r['brier_score']}"
                for r in blend_impact_overall
            ]
        ))
    if best_row:
        print(
            "recency_best="
            f"{best_row.get('recency_candidate_id')}:{best_row.get('model_id')}"
            f"(acc={best_row.get('accuracy')},ll={best_row.get('log_loss')},brier={best_row.get('brier_score')})"
        )
    print(f"predictions_csv={output_predictions_csv}")
    print(f"overall_csv={output_overall_csv}")
    print(f"by_season_csv={output_by_season_csv}")
    print(f"recency_comparison_csv={output_recency_comparison_csv}")
    print(f"logistic_importance_csv={output_logistic_importance_csv}")
    print(f"calibration_diagnostics_csv={output_calibration_diagnostics_csv}")
    print(f"summary_json={output_summary_json}")
    if not args.skip_sqlite_write:
        print("sqlite_tables=walk_forward_experiment_predictions,walk_forward_experiment_metrics_overall,walk_forward_experiment_metrics_by_season")


if __name__ == "__main__":
    main()
