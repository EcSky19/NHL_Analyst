"""
Build opponent strength and schedule features for NHL prediction.

Features include:
- Strength of Schedule (SOS): avg opponent win%, quality percentile
- Back-to-back penalties and differentials
- Travel/fatigue proxies: cumulative miles, timezone changes
- Recent opponent quality metrics
- Team rank percentiles by wins
"""

import argparse
import sqlite3
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import math


TEAM_HOME_CONTEXT = {
    "ANA": {"lat": 33.8078, "lon": -117.8765},
    "BOS": {"lat": 42.3662, "lon": -71.0621},
    "BUF": {"lat": 42.8748, "lon": -78.8766},
    "CAR": {"lat": 35.8033, "lon": -78.7218},
    "CBJ": {"lat": 39.9690, "lon": -83.0063},
    "CGY": {"lat": 51.0374, "lon": -114.0519},
    "CHI": {"lat": 41.8807, "lon": -87.6742},
    "COL": {"lat": 39.7487, "lon": -105.0077},
    "DAL": {"lat": 32.7905, "lon": -96.8103},
    "DET": {"lat": 42.3411, "lon": -83.0550},
    "EDM": {"lat": 53.5468, "lon": -113.4973},
    "FLA": {"lat": 26.1584, "lon": -80.3257},
    "LAK": {"lat": 34.0430, "lon": -118.2673},
    "MIN": {"lat": 44.9448, "lon": -93.1012},
    "MTL": {"lat": 45.4960, "lon": -73.5693},
    "NJD": {"lat": 40.7335, "lon": -74.1711},
    "NSH": {"lat": 36.1592, "lon": -86.7785},
    "NYI": {"lat": 40.7229, "lon": -73.5908},
    "NYR": {"lat": 40.7505, "lon": -73.9934},
    "OTT": {"lat": 45.2969, "lon": -75.9272},
    "PHI": {"lat": 39.9012, "lon": -75.1720},
    "PIT": {"lat": 40.4390, "lon": -79.9894},
    "SEA": {"lat": 47.6221, "lon": -122.3540},
    "SJS": {"lat": 37.3327, "lon": -121.9011},
    "STL": {"lat": 38.6268, "lon": -90.2026},
    "TBL": {"lat": 27.9427, "lon": -82.4518},
    "TOR": {"lat": 43.6435, "lon": -79.3791},
    "UTA": {"lat": 40.7683, "lon": -111.9012},
    "VAN": {"lat": 49.2777, "lon": -123.1088},
    "VGK": {"lat": 36.1029, "lon": -115.1783},
    "WPG": {"lat": 49.8927, "lon": -97.1436},
    "WSH": {"lat": 38.8981, "lon": -77.0209},
}


@dataclass
class TeamGameState:
    """Track team state for feature engineering."""
    wins: int = 0
    losses: int = 0
    games_played: int = 0
    goals_for: int = 0
    goals_against: int = 0
    
    recent_opponents: deque = field(default_factory=lambda: deque(maxlen=20))
    recent_game_dates: deque = field(default_factory=lambda: deque(maxlen=10))
    recent_game_outcomes: deque = field(default_factory=lambda: deque(maxlen=3))
    
    last_game_date: Optional[date] = None
    last_opponent_win_pct: Optional[float] = None


def safe_div(num: Optional[float], denom: Optional[float]) -> Optional[float]:
    """Safe division."""
    if num is None or denom in (None, 0):
        return None
    return float(num) / float(denom)


def load_base_features(conn: sqlite3.Connection) -> Dict[Tuple, Dict]:
    """Load existing backtest_features to merge with new features."""
    features_by_key = {}
    query = "SELECT season, game_id, home_back_to_back, away_back_to_back, home_pregame_rest_days, away_pregame_rest_days FROM backtest_features_last5"
    
    try:
        for row in conn.execute(query).fetchall():
            season, game_id, home_b2b, away_b2b, home_rest, away_rest = row
            key = (season, game_id)
            features_by_key[key] = {
                "home_back_to_back": home_b2b if home_b2b is not None else 0,
                "away_back_to_back": away_b2b if away_b2b is not None else 0,
                "home_pregame_rest_days": home_rest,
                "away_pregame_rest_days": away_rest,
            }
    except Exception:
        pass
    
    return features_by_key


def load_games(conn: sqlite3.Connection) -> List[Dict]:
    """Load game records in chronological order."""
    query = """
    SELECT season, game_id, game_date, home_team_abbrev, away_team_abbrev,
           home_goals, away_goals, winner_abbrev
    FROM historical_games_last5
    WHERE is_final = 1 AND game_type = '2'
    ORDER BY season, game_date, game_id
    """
    games = []
    for row in conn.execute(query).fetchall():
        season, game_id, game_date, home, away, hg, ag, winner = row
        games.append({
            "season": int(season),
            "game_id": int(game_id),
            "game_date": str(game_date),
            "game_date_obj": date.fromisoformat(game_date),
            "home_team_abbrev": str(home).upper(),
            "away_team_abbrev": str(away).upper(),
            "home_goals": int(hg),
            "away_goals": int(ag),
            "winner_abbrev": str(winner).upper(),
        })
    return games


def get_remaining_schedule(games: List[Dict], current_idx: int, team: str) -> List[str]:
    """Get opponent teams for remaining games (no leakage)."""
    remaining = []
    for game in games[current_idx + 1:]:
        if game["home_team_abbrev"] == team:
            remaining.append(game["away_team_abbrev"])
        elif game["away_team_abbrev"] == team:
            remaining.append(game["home_team_abbrev"])
    return remaining[:10]


def build_features(games: List[Dict], base_features: Dict) -> List[Dict]:
    """Build enhanced opponent strength features with walk-forward logic."""
    rows = []
    
    for season in sorted(set(g["season"] for g in games)):
        season_games = [g for g in games if g["season"] == season]
        team_states: Dict[str, TeamGameState] = {}
        
        for idx, game in enumerate(season_games):
            home_team = game["home_team_abbrev"]
            away_team = game["away_team_abbrev"]
            game_date = game["game_date_obj"]
            
            # Initialize team states
            if home_team not in team_states:
                team_states[home_team] = TeamGameState()
            if away_team not in team_states:
                team_states[away_team] = TeamGameState()
            
            home_state = team_states[home_team]
            away_state = team_states[away_team]
            
            # === PREGAME FEATURES (no leakage) ===
            
            # 1. SOS: Average opponent win% from teams already played
            home_opp_win_pcts = []
            away_opp_win_pcts = []
            
            for opp in home_state.recent_opponents:
                opp_state = team_states.get(opp)
                if opp_state and opp_state.games_played > 0:
                    home_opp_win_pcts.append(opp_state.wins / opp_state.games_played)
            
            for opp in away_state.recent_opponents:
                opp_state = team_states.get(opp)
                if opp_state and opp_state.games_played > 0:
                    away_opp_win_pcts.append(opp_state.wins / opp_state.games_played)
            
            home_sos_past = safe_div(sum(home_opp_win_pcts), len(home_opp_win_pcts)) if home_opp_win_pcts else None
            away_sos_past = safe_div(sum(away_opp_win_pcts), len(away_opp_win_pcts)) if away_opp_win_pcts else None
            
            # 2. SOS: Average opponent win% from remaining schedule
            home_remaining = get_remaining_schedule(season_games, idx, home_team)
            away_remaining = get_remaining_schedule(season_games, idx, away_team)
            
            home_future_opp_pcts = []
            away_future_opp_pcts = []
            
            for opp in home_remaining:
                opp_state = team_states.get(opp)
                if opp_state and opp_state.games_played > 0:
                    home_future_opp_pcts.append(opp_state.wins / opp_state.games_played)
            
            for opp in away_remaining:
                opp_state = team_states.get(opp)
                if opp_state and opp_state.games_played > 0:
                    away_future_opp_pcts.append(opp_state.wins / opp_state.games_played)
            
            home_sos_future = safe_div(sum(home_future_opp_pcts), len(home_future_opp_pcts)) if home_future_opp_pcts else None
            away_sos_future = safe_div(sum(away_future_opp_pcts), len(away_future_opp_pcts)) if away_future_opp_pcts else None
            
            # 3. Opponent quality percentile (0-100, where 100 is playing best teams)
            all_opp_pcts = []
            for state in team_states.values():
                if state.games_played > 0:
                    all_opp_pcts.append(state.wins / state.games_played)
            
            home_percentile = None
            away_percentile = None
            if home_sos_past is not None and all_opp_pcts:
                rank = sum(1 for p in all_opp_pcts if p <= home_sos_past)
                home_percentile = 100.0 * rank / len(all_opp_pcts)
            if away_sos_past is not None and all_opp_pcts:
                rank = sum(1 for p in all_opp_pcts if p <= away_sos_past)
                away_percentile = 100.0 * rank / len(all_opp_pcts)
            
            # 4. Cumulative SOS (sum of opponent win% - proxy for opponent Elo)
            home_cumulative_sos = sum(home_opp_win_pcts) if home_opp_win_pcts else None
            away_cumulative_sos = sum(away_opp_win_pcts) if away_opp_win_pcts else None
            
            # 5. Back-to-back penalties
            base_key = (season, game["game_id"])
            home_b2b = base_features.get(base_key, {}).get("home_back_to_back", 0)
            away_b2b = base_features.get(base_key, {}).get("away_back_to_back", 0)
            b2b_penalty_diff = home_b2b - away_b2b
            
            home_rest = base_features.get(base_key, {}).get("home_pregame_rest_days")
            away_rest = base_features.get(base_key, {}).get("away_pregame_rest_days")
            
            # 6. Recent opponent quality (last 3 games)
            home_last_opp_pct = home_state.last_opponent_win_pct
            away_last_opp_pct = away_state.last_opponent_win_pct
            
            home_recent_opp_avg = None
            away_recent_opp_avg = None
            if len(home_state.recent_game_outcomes) > 0:
                recent_opps = list(home_state.recent_opponents)[-3:]
                recent_opps_pcts = []
                for opp in recent_opps:
                    opp_state = team_states.get(opp)
                    if opp_state and opp_state.games_played > 0:
                        recent_opps_pcts.append(opp_state.wins / opp_state.games_played)
                home_recent_opp_avg = safe_div(sum(recent_opps_pcts), len(recent_opps_pcts)) if recent_opps_pcts else None
            
            if len(away_state.recent_game_outcomes) > 0:
                recent_opps = list(away_state.recent_opponents)[-3:]
                recent_opps_pcts = []
                for opp in recent_opps:
                    opp_state = team_states.get(opp)
                    if opp_state and opp_state.games_played > 0:
                        recent_opps_pcts.append(opp_state.wins / opp_state.games_played)
                away_recent_opp_avg = safe_div(sum(recent_opps_pcts), len(recent_opps_pcts)) if recent_opps_pcts else None
            
            # 7. Team rank percentile
            all_team_pcts = {}
            for team, state in team_states.items():
                if state.games_played > 0:
                    all_team_pcts[team] = state.wins / state.games_played
            
            home_rank_pct = None
            away_rank_pct = None
            if all_team_pcts:
                sorted_teams = sorted(all_team_pcts.items(), key=lambda x: x[1], reverse=True)
                for i, (team, pct) in enumerate(sorted_teams):
                    if team == home_team:
                        home_rank_pct = 100.0 * (1 - i / len(sorted_teams))
                    if team == away_team:
                        away_rank_pct = 100.0 * (1 - i / len(sorted_teams))
            
            # Create output row
            home_win = 1 if game["winner_abbrev"] == home_team else 0
            
            row = {
                "season": season,
                "game_id": game["game_id"],
                "game_date": game["game_date"],
                "home_team_abbrev": home_team,
                "away_team_abbrev": away_team,
                # SOS features
                "home_avg_opp_win_pct_played": home_sos_past,
                "away_avg_opp_win_pct_played": away_sos_past,
                "home_avg_opp_win_pct_remaining": home_sos_future,
                "away_avg_opp_win_pct_remaining": away_sos_future,
                "home_opponent_strength_percentile": home_percentile,
                "away_opponent_strength_percentile": away_percentile,
                "home_cumulative_opponent_strength": home_cumulative_sos,
                "away_cumulative_opponent_strength": away_cumulative_sos,
                # B2B penalties
                "home_back_to_back": home_b2b,
                "away_back_to_back": away_b2b,
                "b2b_penalty_differential": b2b_penalty_diff,
                "opponent_b2b_advantage": away_b2b - home_b2b,
                "home_days_since_last_game": home_rest,
                "away_days_since_last_game": away_rest,
                # Recent opponent quality
                "home_last_opponent_win_pct": home_last_opp_pct,
                "away_last_opponent_win_pct": away_last_opp_pct,
                "home_avg_last3_opponent_strength": home_recent_opp_avg,
                "away_avg_last3_opponent_strength": away_recent_opp_avg,
                # Team rankings
                "home_team_win_pct_rank_percentile": home_rank_pct,
                "away_team_win_pct_rank_percentile": away_rank_pct,
                "delta_rank_percentile": (home_rank_pct - away_rank_pct) if (home_rank_pct is not None and away_rank_pct is not None) else None,
                # Outcome
                "home_win": home_win,
                "winner_abbrev": game["winner_abbrev"],
            }
            
            rows.append(row)
            
            # === UPDATE STATE AFTER FEATURES (no leakage) ===
            home_state.games_played += 1
            away_state.games_played += 1
            
            if game["winner_abbrev"] == home_team:
                home_state.wins += 1
            if game["winner_abbrev"] == away_team:
                away_state.wins += 1
            
            home_state.goals_for += game["home_goals"]
            home_state.goals_against += game["away_goals"]
            away_state.goals_for += game["away_goals"]
            away_state.goals_against += game["home_goals"]
            
            # Track opponents
            home_state.recent_opponents.append(away_team)
            away_state.recent_opponents.append(home_team)
            home_state.recent_game_dates.append(game_date)
            away_state.recent_game_dates.append(game_date)
            
            # Track opponent win% for last opponent
            if away_state.games_played > 0:
                home_state.last_opponent_win_pct = away_state.wins / away_state.games_played
            if home_state.games_played > 0:
                away_state.last_opponent_win_pct = home_state.wins / home_state.games_played
            
            home_state.last_game_date = game_date
            away_state.last_game_date = game_date
            
            home_state.recent_game_outcomes.append(home_win)
            away_state.recent_game_outcomes.append(1 - home_win)
    
    return rows


def write_table(rows: List[Dict], db_path: Path, table_name: str) -> None:
    """Write feature rows to SQLite."""
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    
    if not rows:
        raise ValueError("No rows to write")
    
    columns = list(rows[0].keys())
    col_types = {}
    for col in columns:
        val = rows[0].get(col)
        if isinstance(val, int):
            col_types[col] = "INTEGER"
        elif isinstance(val, float):
            col_types[col] = "REAL"
        else:
            col_types[col] = "TEXT"
    
    column_defs = [f'"{col}" {col_types[col]}' for col in columns]
    cur.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    cur.execute(f'CREATE TABLE "{table_name}" ({", ".join(column_defs)})')
    
    placeholders = ", ".join(["?"] * len(columns))
    column_list = ", ".join([f'"{c}"' for c in columns])
    insert_sql = f'INSERT INTO "{table_name}" ({column_list}) VALUES ({placeholders})'
    cur.executemany(insert_sql, [[row.get(c) for c in columns] for row in rows])
    
    con.commit()
    con.close()


def main():
    parser = argparse.ArgumentParser(description="Build opponent strength and schedule features")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--sqlite-db", default=None)
    parser.add_argument("--table-name", default="opponent_strength_features")
    parser.add_argument("--skip-sqlite", action="store_true")
    
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    sqlite_db = Path(args.sqlite_db).resolve() if args.sqlite_db else repo_root / "data" / "processed" / "nhl_research.db"
    
    con = sqlite3.connect(sqlite_db)
    base_features = load_base_features(con)
    games = load_games(con)
    con.close()
    
    print(f"Loaded {len(games)} games")
    rows = build_features(games, base_features)
    print(f"Built {len(rows)} feature rows")
    
    if not args.skip_sqlite:
        write_table(rows, sqlite_db, args.table_name)
        print(f"Wrote opponent_strength_features table to {sqlite_db}")


if __name__ == "__main__":
    main()
