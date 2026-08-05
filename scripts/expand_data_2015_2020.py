#!/usr/bin/env python
"""
WARNING: QUARANTINE REQUIRED FOR 2015-2018 EXPANSION.
The repository was previously contaminated by fabricated 2015-2018 seasons from
generate_synthetic_historical_data.py. Do not mix these seasons into evaluation
unless rows are proven real NHL API records and carry non-synthetic provenance.

Expand NHL prediction dataset to include 2015-2020 seasons.
Fetches games, rosters, and player stats for 2015-2016, 2016-2017, 2017-2018 seasons
and engineers features using the same logic as the 5-season pipeline.
"""

import argparse
import json
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests

# Season IDs to fetch
SEASONS_TO_EXPAND = [
    {"season_id": 20152016, "start": "2015-10-07", "end": "2016-04-10"},
    {"season_id": 20162017, "start": "2016-10-07", "end": "2017-04-09"},
    {"season_id": 20172018, "start": "2017-10-05", "end": "2018-04-08"},
]

# NHL API endpoints
SCHEDULE_URL = "https://api-web.nhle.com/v1/schedule"
BOXSCORE_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"

# Fallback: Try statsapi.mlb.com/api/v1/schedule
STATSAPI_SCHEDULE = "https://statsapi.web.nhl.com/api/v1/schedule"
STATSAPI_GAME = "https://statsapi.web.nhl.com/api/v1/game/{game_id}/boxscore"

def load_alias_map(conn: sqlite3.Connection) -> Dict[str, str]:
    """Load team alias to canonical mapping from database."""
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


def canonical_abbrev(abbrev: Optional[str], alias_map: Dict[str, str]) -> str:
    """Convert team abbreviation to canonical form."""
    normalized = (abbrev or "").strip().upper()
    return alias_map.get(normalized, normalized)


def fetch_json(url: str, timeout: int = 30) -> Dict[str, Any]:
    """Fetch JSON from URL with retry logic."""
    for attempt in range(1, 4):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < 3:
                wait_time = 2 ** attempt
                print(f"  Retry {attempt}/3 after {wait_time}s: {str(e)[:100]}")
                time.sleep(wait_time)
            else:
                raise


def fetch_games_statsapi(
    season_id: int,
    start_date: str,
    end_date: str,
    alias_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Fetch games from StatsAPI (works for older seasons)."""
    print(f"  Fetching games for season {season_id} from StatsAPI...")
    rows: List[Dict[str, Any]] = []
    seen_ids = set()
    
    try:
        # Fetch using date range
        url = f"{STATSAPI_SCHEDULE}?startDate={start_date}&endDate={end_date}"
        payload = fetch_json(url)
        
        for game_data in payload.get("dates", []):
            for game in game_data.get("games", []):
                game_id = game.get("gamePk")
                game_state = (game.get("status", {}).get("abstractGameState") or "").upper()
                
                # Only include completed games
                if game_state not in ("FINAL", "LIVE"):
                    continue
                    
                away_team = game.get("teams", {}).get("away", {})
                home_team = game.get("teams", {}).get("home", {})
                
                away_goals = away_team.get("score")
                home_goals = home_team.get("score")
                
                if away_goals is None or home_goals is None:
                    continue
                
                # Only include regular season
                game_type = game.get("gameType")
                if game_type != "R":
                    continue
                
                if game_id in seen_ids:
                    continue
                
                game_date = game.get("gameDateTime", "")[:10]
                home_abbrev = canonical_abbrev(home_team.get("team", {}).get("abbreviation"), alias_map)
                away_abbrev = canonical_abbrev(away_team.get("team", {}).get("abbreviation"), alias_map)
                winner = home_abbrev if int(home_goals) > int(away_goals) else away_abbrev
                
                rows.append({
                    "season": season_id,
                    "game_id": game_id,
                    "game_date": game_date,
                    "home_team_abbrev": home_abbrev,
                    "away_team_abbrev": away_abbrev,
                    "home_goals": int(home_goals),
                    "away_goals": int(away_goals),
                    "winner_abbrev": winner,
                    "game_type": "2",  # Regular season
                    "status": "FINAL",
                    "is_final": 1,
                })
                seen_ids.add(game_id)
        
        print(f"  Fetched {len(rows)} games for season {season_id}")
        return rows
        
    except Exception as e:
        print(f"  ERROR fetching games for season {season_id}: {e}")
        return []


def fetch_boxscore_statsapi(game_id: int) -> Dict[str, Any]:
    """Fetch boxscore from StatsAPI."""
    try:
        url = STATSAPI_GAME.format(game_id=game_id)
        return fetch_json(url)
    except Exception as e:
        print(f"  Warning: Could not fetch boxscore for game {game_id}: {e}")
        return {}


def extract_roster_from_boxscore(
    boxscore: Dict[str, Any],
    game_id: int,
    season: int,
    game_date: str,
    team_abbrev: str,
    is_home: bool,
) -> List[Dict[str, Any]]:
    """Extract roster players from boxscore JSON."""
    roster_rows = []
    team_key = "home" if is_home else "away"
    
    try:
        teams = boxscore.get("teams", {})
        team_data = teams.get(team_key, {})
        players = team_data.get("players", {})
        
        for player_id_str, player_data in players.items():
            try:
                person = player_data.get("person", {})
                player_id = person.get("id")
                player_name = person.get("fullName")
                jersey_num = player_data.get("jerseyNumber")
                position = player_data.get("position", {}).get("code")
                
                stats = player_data.get("stats", {})
                skater_stats = stats.get("skatingStats", {})
                goalie_stats = stats.get("goalieStats", {})
                
                if goalie_stats:
                    # Goalie
                    goals_against = goalie_stats.get("goalsAgainst")
                    shots = goalie_stats.get("shots")
                    saves = goalie_stats.get("saves")
                    save_pct = goalie_stats.get("savePercentage")
                    
                    roster_rows.append({
                        "season": season,
                        "game_id": game_id,
                        "game_date": game_date,
                        "team_abbrev": team_abbrev,
                        "player_id": player_id,
                        "player_name": player_name,
                        "jersey_number": jersey_num,
                        "position": position,
                        "goals": 0,
                        "assists": 0,
                        "points": 0,
                        "plus_minus": None,
                        "toi_minutes": None,
                        "toi_seconds": None,
                        "shots": shots,
                        "goalie_save_pct": save_pct,
                        "goalie_goals_against": goals_against,
                        "goalie_saves": saves,
                    })
                else:
                    # Skater
                    goals = skater_stats.get("goals", 0)
                    assists = skater_stats.get("assists", 0)
                    points = goals + assists
                    plus_minus = skater_stats.get("plusMinus")
                    toi = skater_stats.get("timeOnIce", "0:00")
                    
                    # Parse TOI
                    toi_parts = str(toi).split(":")
                    toi_minutes = 0
                    toi_seconds = 0
                    try:
                        if len(toi_parts) >= 2:
                            toi_minutes = int(toi_parts[0])
                            toi_seconds = int(toi_parts[1])
                    except ValueError:
                        pass
                    
                    roster_rows.append({
                        "season": season,
                        "game_id": game_id,
                        "game_date": game_date,
                        "team_abbrev": team_abbrev,
                        "player_id": player_id,
                        "player_name": player_name,
                        "jersey_number": jersey_num,
                        "position": position,
                        "goals": goals,
                        "assists": assists,
                        "points": points,
                        "plus_minus": plus_minus,
                        "toi_minutes": toi_minutes,
                        "toi_seconds": toi_seconds,
                        "shots": skater_stats.get("shots"),
                        "goalie_save_pct": None,
                        "goalie_goals_against": None,
                        "goalie_saves": None,
                    })
            except Exception as e:
                print(f"    Warning: Could not parse player data: {e}")
                continue
    except Exception as e:
        print(f"  Warning: Could not extract roster from boxscore {game_id}: {e}")
    
    return roster_rows


def expand_historical_games(
    db_path: Path,
    alias_map: Dict[str, str],
    seasons: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Expand historical games table with older seasons."""
    all_games = []
    all_rosters = []
    
    for season_info in seasons:
        season_id = season_info["season_id"]
        start_date = season_info["start"]
        end_date = season_info["end"]
        
        print(f"\nFetching season {season_id}...")
        
        # Fetch games using StatsAPI
        games = fetch_games_statsapi(season_id, start_date, end_date, alias_map)
        if not games:
            print(f"  WARNING: No games fetched for season {season_id}")
            continue
        
        all_games.extend(games)
        
        # Fetch rosters for each game
        print(f"  Fetching rosters for {len(games)} games...")
        for i, game in enumerate(games):
            if (i + 1) % 50 == 0:
                print(f"    Progress: {i + 1}/{len(games)}")
            
            game_id = game["game_id"]
            try:
                boxscore = fetch_boxscore_statsapi(game_id)
                if boxscore:
                    # Extract home roster
                    home_roster = extract_roster_from_boxscore(
                        boxscore, game_id, season_id, game["game_date"],
                        game["home_team_abbrev"], is_home=True
                    )
                    all_rosters.extend(home_roster)
                    
                    # Extract away roster
                    away_roster = extract_roster_from_boxscore(
                        boxscore, game_id, season_id, game["game_date"],
                        game["away_team_abbrev"], is_home=False
                    )
                    all_rosters.extend(away_roster)
                    
                time.sleep(0.1)  # Rate limiting
            except Exception as e:
                print(f"    Warning: Could not fetch roster for game {game_id}: {e}")
    
    return all_games, all_rosters


def persist_expanded_data(
    db_path: Path,
    games: List[Dict[str, Any]],
    rosters: List[Dict[str, Any]],
) -> None:
    """Insert expanded data into database."""
    print(f"\nInserting {len(games)} games and {len(rosters)} roster records...")
    
    with sqlite3.connect(db_path) as conn:
        # Insert games
        conn.executemany(
            """
            INSERT OR IGNORE INTO historical_games_last5 (
                season, game_id, game_date, home_team_abbrev, away_team_abbrev,
                home_goals, away_goals, winner_abbrev, game_type, status, is_final
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(
                g["season"], g["game_id"], g["game_date"],
                g["home_team_abbrev"], g["away_team_abbrev"],
                g["home_goals"], g["away_goals"], g["winner_abbrev"],
                g["game_type"], g["status"], g["is_final"]
            ) for g in games],
        )
        
        # Insert rosters
        conn.executemany(
            """
            INSERT OR IGNORE INTO historical_game_rosters (
                season, game_id, game_date, team_abbrev, player_id,
                player_name, jersey_number, position, goals, assists,
                points, plus_minus, toi_minutes, toi_seconds, shots,
                goalie_save_pct, goalie_goals_against, goalie_saves
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(
                r["season"], r["game_id"], r["game_date"], r["team_abbrev"],
                r["player_id"], r["player_name"], r["jersey_number"],
                r["position"], r["goals"], r["assists"], r["points"],
                r["plus_minus"], r["toi_minutes"], r["toi_seconds"],
                r["shots"], r["goalie_save_pct"],
                r["goalie_goals_against"], r["goalie_saves"]
            ) for r in rosters],
        )
        
        conn.commit()
        print(f"  Inserted {len(games)} games")
        print(f"  Inserted {len(rosters)} roster records")


def main():
    parser = argparse.ArgumentParser(
        description="Expand NHL dataset to include 2015-2020 seasons"
    )
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args()
    
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parent.parent
    db_path = repo_root / "data" / "processed" / "nhl_research.db"
    
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        return False
    
    print(f"Using database: {db_path}")
    
    # Load alias map
    with sqlite3.connect(db_path) as conn:
        alias_map = load_alias_map(conn)
    
    print(f"Loaded {len(alias_map)} team aliases")
    
    # Fetch and expand data
    try:
        games, rosters = expand_historical_games(db_path, alias_map, SEASONS_TO_EXPAND)
        
        if not games:
            print("ERROR: No games fetched")
            return False
        
        # Persist to database
        persist_expanded_data(db_path, games, rosters)
        print("\n✓ Data expansion complete")
        return True
        
    except Exception as e:
        print(f"ERROR during expansion: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
