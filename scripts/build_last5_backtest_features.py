import argparse
import csv
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional
from zoneinfo import ZoneInfo


TEAM_HOME_CONTEXT = {
    "ANA": {"city": "Anaheim", "lat": 33.8078, "lon": -117.8765, "tz": "America/Los_Angeles"},
    "BOS": {"city": "Boston", "lat": 42.3662, "lon": -71.0621, "tz": "America/New_York"},
    "BUF": {"city": "Buffalo", "lat": 42.8748, "lon": -78.8766, "tz": "America/New_York"},
    "CAR": {"city": "Raleigh", "lat": 35.8033, "lon": -78.7218, "tz": "America/New_York"},
    "CBJ": {"city": "Columbus", "lat": 39.9690, "lon": -83.0063, "tz": "America/New_York"},
    "CGY": {"city": "Calgary", "lat": 51.0374, "lon": -114.0519, "tz": "America/Edmonton"},
    "CHI": {"city": "Chicago", "lat": 41.8807, "lon": -87.6742, "tz": "America/Chicago"},
    "COL": {"city": "Denver", "lat": 39.7487, "lon": -105.0077, "tz": "America/Denver"},
    "DAL": {"city": "Dallas", "lat": 32.7905, "lon": -96.8103, "tz": "America/Chicago"},
    "DET": {"city": "Detroit", "lat": 42.3411, "lon": -83.0550, "tz": "America/New_York"},
    "EDM": {"city": "Edmonton", "lat": 53.5468, "lon": -113.4973, "tz": "America/Edmonton"},
    "FLA": {"city": "Sunrise", "lat": 26.1584, "lon": -80.3257, "tz": "America/New_York"},
    "LAK": {"city": "Los Angeles", "lat": 34.0430, "lon": -118.2673, "tz": "America/Los_Angeles"},
    "MIN": {"city": "St. Paul", "lat": 44.9448, "lon": -93.1012, "tz": "America/Chicago"},
    "MTL": {"city": "Montreal", "lat": 45.4960, "lon": -73.5693, "tz": "America/Toronto"},
    "NJD": {"city": "Newark", "lat": 40.7335, "lon": -74.1711, "tz": "America/New_York"},
    "NSH": {"city": "Nashville", "lat": 36.1592, "lon": -86.7785, "tz": "America/Chicago"},
    "NYI": {"city": "Elmont", "lat": 40.7229, "lon": -73.5908, "tz": "America/New_York"},
    "NYR": {"city": "New York", "lat": 40.7505, "lon": -73.9934, "tz": "America/New_York"},
    "OTT": {"city": "Ottawa", "lat": 45.2969, "lon": -75.9272, "tz": "America/Toronto"},
    "PHI": {"city": "Philadelphia", "lat": 39.9012, "lon": -75.1720, "tz": "America/New_York"},
    "PIT": {"city": "Pittsburgh", "lat": 40.4390, "lon": -79.9894, "tz": "America/New_York"},
    "SEA": {"city": "Seattle", "lat": 47.6221, "lon": -122.3540, "tz": "America/Los_Angeles"},
    "SJS": {"city": "San Jose", "lat": 37.3327, "lon": -121.9011, "tz": "America/Los_Angeles"},
    "STL": {"city": "St. Louis", "lat": 38.6268, "lon": -90.2026, "tz": "America/Chicago"},
    "TBL": {"city": "Tampa", "lat": 27.9427, "lon": -82.4518, "tz": "America/New_York"},
    "TOR": {"city": "Toronto", "lat": 43.6435, "lon": -79.3791, "tz": "America/Toronto"},
    "UTA": {"city": "Salt Lake City", "lat": 40.7683, "lon": -111.9012, "tz": "America/Denver"},
    "VAN": {"city": "Vancouver", "lat": 49.2777, "lon": -123.1088, "tz": "America/Vancouver"},
    "VGK": {"city": "Las Vegas", "lat": 36.1029, "lon": -115.1783, "tz": "America/Los_Angeles"},
    "WPG": {"city": "Winnipeg", "lat": 49.8927, "lon": -97.1436, "tz": "America/Winnipeg"},
    "WSH": {"city": "Washington", "lat": 38.8981, "lon": -77.0209, "tz": "America/New_York"},
}

UTA_LEGACY_CONTEXT = {"city": "Tempe", "lat": 33.4455, "lon": -112.0712, "tz": "America/Phoenix"}


@dataclass
class TeamState:
    prior_prev_season_points_pct: Optional[float] = None
    prior_prev_season_goal_diff_pg: Optional[float] = None
    prior_prev_season_games: int = 0
    games_played: int = 0
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0
    streak_signed: int = 0
    recent_points: Deque[int] = field(default_factory=lambda: deque(maxlen=10))
    recent_goal_diff: Deque[int] = field(default_factory=lambda: deque(maxlen=10))
    home_games: int = 0
    home_points: int = 0
    home_goal_diff: int = 0
    away_games: int = 0
    away_points: int = 0
    away_goal_diff: int = 0
    last_game_date: Optional[date] = None
    recent_game_dates: Deque[date] = field(default_factory=lambda: deque(maxlen=8))
    last_venue_lat: Optional[float] = None
    last_venue_lon: Optional[float] = None
    last_timezone_offset_hours: Optional[float] = None
    home_stand_streak: int = 0
    road_trip_streak: int = 0


COLUMNS = [
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


def safe_div(numerator: float, denominator: float) -> Optional[float]:
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def optional_subtract(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b


def haversine_miles(
    lat1: Optional[float], lon1: Optional[float], lat2: Optional[float], lon2: Optional[float]
) -> Optional[float]:
    if None in (lat1, lon1, lat2, lon2):
        return None
    from math import asin, cos, radians, sin, sqrt

    r_miles = 3958.7613
    d_lat = radians(float(lat2) - float(lat1))
    d_lon = radians(float(lon2) - float(lon1))
    a = sin(d_lat / 2.0) ** 2 + cos(radians(float(lat1))) * cos(radians(float(lat2))) * sin(d_lon / 2.0) ** 2
    c = 2.0 * asin(sqrt(a))
    return r_miles * c


def timezone_offset_hours(tz_name: Optional[str], game_date_obj: date) -> Optional[float]:
    if not tz_name:
        return None
    try:
        dt = datetime.combine(game_date_obj, time(hour=12), tzinfo=ZoneInfo(tz_name))
    except Exception:
        return None
    offset = dt.utcoffset()
    if offset is None:
        return None
    return offset.total_seconds() / 3600.0


def resolve_team_home_context(team_abbrev: str, season: int) -> Dict[str, Any]:
    team = (team_abbrev or "").upper()
    if team == "UTA" and season <= 20232024:
        return UTA_LEGACY_CONTEXT
    return TEAM_HOME_CONTEXT.get(team, {"city": None, "lat": None, "lon": None, "tz": None})


def count_games_in_last_days(recent_dates: Deque[date], game_date_obj: date, lookback_days: int) -> int:
    count = 0
    for prior in recent_dates:
        delta_days = (game_date_obj - prior).days
        if 1 <= delta_days <= lookback_days:
            count += 1
    return count


def load_alias_map(conn: sqlite3.Connection) -> Dict[str, str]:
    alias_to_canonical: Dict[str, str] = {}
    for canonical_abbrev, alias_abbrevs in conn.execute(
        "SELECT canonical_abbrev, alias_abbrevs FROM team_alias_map"
    ).fetchall():
        canonical = (canonical_abbrev or "").strip().upper()
        if not canonical:
            continue
        alias_to_canonical[canonical] = canonical
        for alias in (alias_abbrevs or "").split("|"):
            token = alias.strip().upper()
            if token:
                alias_to_canonical[token] = canonical
    return alias_to_canonical


def canonical_abbrev(team_abbrev: str, alias_map: Dict[str, str]) -> str:
    normalized = (team_abbrev or "").strip().upper()
    return alias_map.get(normalized, normalized)


def load_games(conn: sqlite3.Connection, alias_map: Dict[str, str]) -> List[Dict]:
    query = """
    SELECT
        season, game_id, game_date, home_team_abbrev, away_team_abbrev,
        home_goals, away_goals, winner_abbrev
    FROM historical_games_last5
    WHERE is_final = 1 AND game_type = '2'
    ORDER BY season, game_date, game_id
    """
    games = []
    for row in conn.execute(query).fetchall():
        season, game_id, game_date, home_abbrev, away_abbrev, home_goals, away_goals, winner = row
        home_canon = canonical_abbrev(home_abbrev, alias_map)
        away_canon = canonical_abbrev(away_abbrev, alias_map)
        winner_canon = canonical_abbrev(winner, alias_map)
        games.append(
            {
                "season": int(season),
                "game_id": int(game_id),
                "game_date": game_date,
                "game_date_obj": date.fromisoformat(game_date),
                "home_team_abbrev": home_canon,
                "away_team_abbrev": away_canon,
                "home_goals": int(home_goals),
                "away_goals": int(away_goals),
                "winner_abbrev": winner_canon,
            }
        )
    return games


def compute_prev_season_priors(games: List[Dict]) -> Dict[int, Dict[str, Dict[str, float]]]:
    season_team_totals: Dict[int, Dict[str, Dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"games": 0, "points": 0, "goal_diff": 0})
    )
    for game in games:
        season = game["season"]
        home = game["home_team_abbrev"]
        away = game["away_team_abbrev"]
        home_win = 1 if game["winner_abbrev"] == home else 0
        away_win = 1 if game["winner_abbrev"] == away else 0
        diff = game["home_goals"] - game["away_goals"]

        season_team_totals[season][home]["games"] += 1
        season_team_totals[season][home]["points"] += 2 * home_win
        season_team_totals[season][home]["goal_diff"] += diff

        season_team_totals[season][away]["games"] += 1
        season_team_totals[season][away]["points"] += 2 * away_win
        season_team_totals[season][away]["goal_diff"] -= diff

    priors_by_season: Dict[int, Dict[str, Dict[str, float]]] = {}
    ordered_seasons = sorted(season_team_totals.keys())
    for idx, season in enumerate(ordered_seasons):
        prev_totals = season_team_totals.get(ordered_seasons[idx - 1]) if idx > 0 else {}
        current_teams = season_team_totals[season].keys()
        season_priors: Dict[str, Dict[str, float]] = {}
        for team in current_teams:
            prev_team = prev_totals.get(team)
            if prev_team and prev_team["games"] > 0:
                points_pct = prev_team["points"] / (2.0 * prev_team["games"])
                goal_diff_pg = prev_team["goal_diff"] / float(prev_team["games"])
                season_priors[team] = {
                    "prior_prev_season_points_pct": points_pct,
                    "prior_prev_season_goal_diff_pg": goal_diff_pg,
                    "prior_prev_season_games": int(prev_team["games"]),
                }
            else:
                season_priors[team] = {
                    "prior_prev_season_points_pct": None,
                    "prior_prev_season_goal_diff_pg": None,
                    "prior_prev_season_games": 0,
                }
        priors_by_season[season] = season_priors
    return priors_by_season


def team_state_for(
    season_states: Dict[str, TeamState], team: str, season_priors: Dict[str, Dict[str, float]]
) -> TeamState:
    if team not in season_states:
        prior = season_priors.get(team, {})
        season_states[team] = TeamState(
            prior_prev_season_points_pct=prior.get("prior_prev_season_points_pct"),
            prior_prev_season_goal_diff_pg=prior.get("prior_prev_season_goal_diff_pg"),
            prior_prev_season_games=int(prior.get("prior_prev_season_games", 0)),
        )
    return season_states[team]


def pregame_rest_days(state: TeamState, game_date_obj: date) -> Optional[int]:
    if state.last_game_date is None:
        return None
    return max((game_date_obj - state.last_game_date).days - 1, 0)


def update_team_state(
    state: TeamState,
    *,
    is_win: bool,
    goals_for: int,
    goals_against: int,
    is_home: bool,
    game_date_obj: date,
    venue_lat: Optional[float],
    venue_lon: Optional[float],
    venue_timezone_offset_hours: Optional[float],
) -> None:
    state.games_played += 1
    state.points += 2 if is_win else 0
    state.goals_for += goals_for
    state.goals_against += goals_against

    game_diff = goals_for - goals_against
    state.recent_points.append(2 if is_win else 0)
    state.recent_goal_diff.append(game_diff)

    if is_win:
        state.streak_signed = state.streak_signed + 1 if state.streak_signed > 0 else 1
    else:
        state.streak_signed = state.streak_signed - 1 if state.streak_signed < 0 else -1

    if is_home:
        state.home_games += 1
        state.home_points += 2 if is_win else 0
        state.home_goal_diff += game_diff
        state.home_stand_streak += 1
        state.road_trip_streak = 0
    else:
        state.away_games += 1
        state.away_points += 2 if is_win else 0
        state.away_goal_diff += game_diff
        state.road_trip_streak += 1
        state.home_stand_streak = 0

    state.last_game_date = game_date_obj
    state.recent_game_dates.append(game_date_obj)
    state.last_venue_lat = venue_lat
    state.last_venue_lon = venue_lon
    state.last_timezone_offset_hours = venue_timezone_offset_hours


def build_backtest_rows(games: List[Dict]) -> List[Dict]:
    priors_by_season = compute_prev_season_priors(games)
    rows: List[Dict] = []

    for season in sorted({g["season"] for g in games}):
        season_games = [g for g in games if g["season"] == season]
        season_states: Dict[str, TeamState] = {}
        season_priors = priors_by_season.get(season, {})

        for game in season_games:
            home_team = game["home_team_abbrev"]
            away_team = game["away_team_abbrev"]
            home_state = team_state_for(season_states, home_team, season_priors)
            away_state = team_state_for(season_states, away_team, season_priors)
            venue_context = resolve_team_home_context(home_team, game["season"])
            venue_lat = venue_context.get("lat")
            venue_lon = venue_context.get("lon")
            venue_tz_offset = timezone_offset_hours(venue_context.get("tz"), game["game_date_obj"])

            home_last10_points_pct = safe_div(sum(home_state.recent_points), 2.0 * len(home_state.recent_points))
            away_last10_points_pct = safe_div(sum(away_state.recent_points), 2.0 * len(away_state.recent_points))
            home_last10_goal_diff_pg = safe_div(sum(home_state.recent_goal_diff), len(home_state.recent_goal_diff))
            away_last10_goal_diff_pg = safe_div(sum(away_state.recent_goal_diff), len(away_state.recent_goal_diff))

            home_season_points_pct = safe_div(home_state.points, 2.0 * home_state.games_played)
            away_season_points_pct = safe_div(away_state.points, 2.0 * away_state.games_played)
            home_season_goal_diff_pg = safe_div(
                home_state.goals_for - home_state.goals_against, home_state.games_played
            )
            away_season_goal_diff_pg = safe_div(
                away_state.goals_for - away_state.goals_against, away_state.games_played
            )

            home_home_points_pct = safe_div(home_state.home_points, 2.0 * home_state.home_games)
            away_road_points_pct = safe_div(away_state.away_points, 2.0 * away_state.away_games)

            home_rest_days = pregame_rest_days(home_state, game["game_date_obj"])
            away_rest_days = pregame_rest_days(away_state, game["game_date_obj"])
            home_b2b = 1 if home_rest_days == 0 else 0
            away_b2b = 1 if away_rest_days == 0 else 0
            home_three_in_four = 1 if count_games_in_last_days(home_state.recent_game_dates, game["game_date_obj"], 3) >= 2 else 0
            away_three_in_four = 1 if count_games_in_last_days(away_state.recent_game_dates, game["game_date_obj"], 3) >= 2 else 0
            home_four_in_six = 1 if count_games_in_last_days(home_state.recent_game_dates, game["game_date_obj"], 5) >= 3 else 0
            away_four_in_six = 1 if count_games_in_last_days(away_state.recent_game_dates, game["game_date_obj"], 5) >= 3 else 0
            home_travel_miles = haversine_miles(
                home_state.last_venue_lat,
                home_state.last_venue_lon,
                venue_lat,
                venue_lon,
            )
            away_travel_miles = haversine_miles(
                away_state.last_venue_lat,
                away_state.last_venue_lon,
                venue_lat,
                venue_lon,
            )
            home_timezone_shift = (
                optional_subtract(venue_tz_offset, home_state.last_timezone_offset_hours)
                if venue_tz_offset is not None and home_state.last_timezone_offset_hours is not None
                else None
            )
            away_timezone_shift = (
                optional_subtract(venue_tz_offset, away_state.last_timezone_offset_hours)
                if venue_tz_offset is not None and away_state.last_timezone_offset_hours is not None
                else None
            )
            home_home_stand_len = home_state.home_stand_streak + 1
            away_home_stand_len = 0
            home_road_trip_len = 0
            away_road_trip_len = away_state.road_trip_streak + 1

            home_win = 1 if game["winner_abbrev"] == home_team else 0
            row = {
                "season": game["season"],
                "game_id": game["game_id"],
                "game_date": game["game_date"],
                "home_team_abbrev": home_team,
                "away_team_abbrev": away_team,
                "home_pregame_streak_signed": home_state.streak_signed,
                "away_pregame_streak_signed": away_state.streak_signed,
                "home_pregame_last10_points_pct": home_last10_points_pct,
                "away_pregame_last10_points_pct": away_last10_points_pct,
                "home_pregame_last10_goal_diff_pg": home_last10_goal_diff_pg,
                "away_pregame_last10_goal_diff_pg": away_last10_goal_diff_pg,
                "home_pregame_season_points_pct": home_season_points_pct,
                "away_pregame_season_points_pct": away_season_points_pct,
                "home_pregame_season_goal_diff_pg": home_season_goal_diff_pg,
                "away_pregame_season_goal_diff_pg": away_season_goal_diff_pg,
                "home_pregame_home_points_pct": home_home_points_pct,
                "away_pregame_road_points_pct": away_road_points_pct,
                "home_pregame_rest_days": home_rest_days,
                "away_pregame_rest_days": away_rest_days,
                "home_back_to_back": home_b2b,
                "away_back_to_back": away_b2b,
                "home_three_in_four": home_three_in_four,
                "away_three_in_four": away_three_in_four,
                "home_four_in_six": home_four_in_six,
                "away_four_in_six": away_four_in_six,
                "home_pregame_travel_miles": home_travel_miles,
                "away_pregame_travel_miles": away_travel_miles,
                "delta_travel_miles_home_minus_away": optional_subtract(home_travel_miles, away_travel_miles),
                "home_timezone_shift_hours": home_timezone_shift,
                "away_timezone_shift_hours": away_timezone_shift,
                "delta_timezone_shift_hours_home_minus_away": optional_subtract(home_timezone_shift, away_timezone_shift),
                "home_pregame_home_stand_len": home_home_stand_len,
                "away_pregame_home_stand_len": away_home_stand_len,
                "home_pregame_road_trip_len": home_road_trip_len,
                "away_pregame_road_trip_len": away_road_trip_len,
                "delta_home_stand_len_home_minus_away": home_home_stand_len - away_home_stand_len,
                "delta_road_trip_len_home_minus_away": home_road_trip_len - away_road_trip_len,
                "rest_days_delta_home_minus_away": None
                if home_rest_days is None or away_rest_days is None
                else home_rest_days - away_rest_days,
                "home_location_edge_points_pct": optional_subtract(home_home_points_pct, away_road_points_pct),
                "home_prior_prev_season_points_pct": home_state.prior_prev_season_points_pct,
                "away_prior_prev_season_points_pct": away_state.prior_prev_season_points_pct,
                "home_prior_prev_season_goal_diff_pg": home_state.prior_prev_season_goal_diff_pg,
                "away_prior_prev_season_goal_diff_pg": away_state.prior_prev_season_goal_diff_pg,
                "home_prior_prev_season_games": home_state.prior_prev_season_games,
                "away_prior_prev_season_games": away_state.prior_prev_season_games,
                "delta_pregame_last10_points_pct_home_minus_away": optional_subtract(
                    home_last10_points_pct, away_last10_points_pct
                ),
                "delta_pregame_last10_goal_diff_pg_home_minus_away": optional_subtract(
                    home_last10_goal_diff_pg, away_last10_goal_diff_pg
                ),
                "delta_pregame_season_points_pct_home_minus_away": optional_subtract(
                    home_season_points_pct, away_season_points_pct
                ),
                "delta_pregame_season_goal_diff_pg_home_minus_away": optional_subtract(
                    home_season_goal_diff_pg, away_season_goal_diff_pg
                ),
                "home_win": home_win,
                "winner_abbrev": game["winner_abbrev"],
            }
            rows.append(row)

            update_team_state(
                home_state,
                is_win=home_win == 1,
                goals_for=game["home_goals"],
                goals_against=game["away_goals"],
                is_home=True,
                game_date_obj=game["game_date_obj"],
                venue_lat=venue_lat,
                venue_lon=venue_lon,
                venue_timezone_offset_hours=venue_tz_offset,
            )
            update_team_state(
                away_state,
                is_win=home_win == 0,
                goals_for=game["away_goals"],
                goals_against=game["home_goals"],
                is_home=False,
                game_date_obj=game["game_date_obj"],
                venue_lat=venue_lat,
                venue_lon=venue_lon,
                venue_timezone_offset_hours=venue_tz_offset,
            )

    return rows


def write_csv(rows: List[Dict], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [name for name, _ in COLUMNS]
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_sqlite(rows: List[Dict], sqlite_db: Path, table_name: str) -> None:
    sqlite_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(sqlite_db) as conn:
        conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        create_cols = ", ".join(f'"{name}" {sql_type}' for name, sql_type in COLUMNS)
        conn.execute(f'CREATE TABLE "{table_name}" ({create_cols})')
        col_names = [name for name, _ in COLUMNS]
        placeholders = ", ".join(["?"] * len(col_names))
        quoted_cols = ", ".join([f'"{col}"' for col in col_names])
        insert_sql = f'INSERT INTO "{table_name}" ({quoted_cols}) VALUES ({placeholders})'
        conn.executemany(insert_sql, [[row.get(col) for col in col_names] for row in rows])
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_season_date" ON "{table_name}" (season, game_date, game_id)'
        )
        conn.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build last-5-seasons NHL game-level backtest features with strict pregame no-leakage logic."
    )
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--sqlite-db", default=None, help="SQLite DB path (default: data\\processed\\nhl_research.db)")
    parser.add_argument(
        "--output-csv", default=None, help="Output CSV path (default: data\\processed\\backtest_features_last5.csv)"
    )
    parser.add_argument("--table-name", default="backtest_features_last5")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    sqlite_db = Path(args.sqlite_db).resolve() if args.sqlite_db else repo_root / "data" / "processed" / "nhl_research.db"
    output_csv = (
        Path(args.output_csv).resolve()
        if args.output_csv
        else repo_root / "data" / "processed" / "backtest_features_last5.csv"
    )

    with sqlite3.connect(sqlite_db) as conn:
        alias_map = load_alias_map(conn)
        games = load_games(conn, alias_map)

    if not games:
        raise RuntimeError("No completed regular-season games found in historical_games_last5.")

    rows = build_backtest_rows(games)
    write_csv(rows, output_csv)
    write_sqlite(rows, sqlite_db, args.table_name)

    seasons = sorted({row["season"] for row in rows})
    print(f"rows_built={len(rows)}")
    print(f"seasons={seasons}")
    print(f"csv={output_csv}")
    print(f"table={args.table_name}")


if __name__ == "__main__":
    main()
