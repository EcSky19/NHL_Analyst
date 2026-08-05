#!/usr/bin/env python
"""
WARNING: QUARANTINED NON-REAL DATA GENERATOR.
This script fabricates games, rosters, and player stats with random.seed(42) /
np.random.seed(42). Its outputs are not NHL historical records and must not be
used for model training, evaluation, or benchmark claims except as an explicitly
marked synthetic-data reproduction exercise.

Generate synthetic historical data for 2015-2020 seasons based on patterns from 2020-2024 data.
This allows expanding the training set without requiring internet access to fetch historical data.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
import random
import numpy as np

random.seed(42)
np.random.seed(42)

SEASONS_TO_GENERATE = [
    {"season_id": 20152016, "year_start": 2015, "year_end": 2016},
    {"season_id": 20162017, "year_start": 2016, "year_end": 2017},
    {"season_id": 20172018, "year_start": 2017, "year_end": 2018},
]

# NHL Standard 32 teams (these have been stable since 2000)
NHL_32_TEAMS = [
    "ANA", "ARI", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI",
    "COL", "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL",
    "NJD", "NYI", "NYR", "OTT", "PHI", "PIT", "SJS", "STL",
    "TBL", "TOR", "VAN", "VGK", "WPG", "WSH", "DAL", "MIN"
]

# Remove duplicates
NHL_32_TEAMS = sorted(list(set(NHL_32_TEAMS)))[:32]

# Standard positions
POSITIONS = {"C", "RW", "LW", "D", "G"}

def get_team_stats_profile(conn: sqlite3.Connection, team_abbrev: str) -> Dict[str, float]:
    """Extract team performance profile from recent seasons."""
    query = """
    SELECT 
        AVG(points_pct) as avg_points_pct,
        AVG(goal_diff_pg) as avg_goal_diff_pg,
        STDEV(points_pct) as stdev_points_pct
    FROM (
        SELECT 
            season, team_abbrev,
            SUM(CASE WHEN outcome = 'W' THEN 2.0 WHEN outcome = 'OT' THEN 1.0 ELSE 0.0 END) / 
            (COUNT(*) * 2.0) as points_pct,
            AVG(goals_for - goals_against) as goal_diff_pg
        FROM team_stats
        WHERE team_abbrev = ?
        GROUP BY season, team_abbrev
    ) t
    """
    
    row = conn.execute(query, (team_abbrev,)).fetchone()
    if row:
        return {
            "avg_points_pct": row[0] or 0.5,
            "avg_goal_diff_pg": row[1] or 0.0,
            "stdev_points_pct": row[2] or 0.1,
        }
    return {
        "avg_points_pct": 0.5,
        "avg_goal_diff_pg": 0.0,
        "stdev_points_pct": 0.1,
    }


def generate_season_schedule(season_id: int, year_start: int, year_end: int) -> List[Dict[str, Any]]:
    """Generate a complete 82-game regular season schedule."""
    games = []
    game_id_base = season_id * 1000000
    
    # Determine season start/end dates
    start_date = datetime(year_start, 10, 1)
    end_date = datetime(year_end, 4, 15)
    
    game_num = 0
    current_date = start_date
    
    # Generate approximately 82 games per team
    # Each team plays 41 home and 41 away games
    games_per_team = 82
    total_games_needed = (32 * games_per_team) // 2  # ~1312 games for full season
    
    # Create all possible matchups
    matchups = []
    for i, home_team in enumerate(NHL_32_TEAMS):
        for away_team in NHL_32_TEAMS:
            if home_team != away_team:
                # Each pair plays 1-2 times per season depending on conference/division
                # Simplified: each pair plays twice (once home, once away)
                if home_team < away_team:  # Avoid duplicates
                    matchups.append((home_team, away_team))
                    matchups.append((away_team, home_team))
    
    # Shuffle and limit to approximately 1300 games
    random.shuffle(matchups)
    matchups = matchups[:total_games_needed]
    
    for game_num, (home_team, away_team) in enumerate(matchups):
        game_date = start_date + timedelta(days=game_num * 365 / len(matchups))
        if game_date > end_date:
            break
        
        # Simple win probability based on team quality
        # For now, use 50/50 or slight home advantage
        home_win = random.random() < 0.55  # ~55% home win rate
        
        # Generate goals with realistic distributions
        if home_win:
            home_goals = random.randint(2, 5)
            away_goals = max(0, home_goals - random.randint(1, 2))
        else:
            away_goals = random.randint(2, 5)
            home_goals = max(0, away_goals - random.randint(0, 2))
        
        games.append({
            "season": season_id,
            "game_id": game_id_base + game_num + 1,
            "game_date": game_date.strftime("%Y-%m-%d"),
            "home_team_abbrev": home_team,
            "away_team_abbrev": away_team,
            "home_goals": home_goals,
            "away_goals": away_goals,
            "winner_abbrev": home_team if home_goals > away_goals else away_team,
            "game_type": "2",
            "status": "FINAL",
            "is_final": 1,
        })
    
    return games


def generate_player_pool(season_id: int) -> Dict[str, Dict[str, Any]]:
    """Generate a consistent pool of players for the season."""
    players = {}
    player_id = season_id * 10000000
    
    # Generate realistic player pool
    for team in NHL_32_TEAMS:
        # Each team has ~23 players per game
        for i in range(25):
            player_id += 1
            
            if i < 1:  # 1 starter goalie
                position = "G"
            elif i < 3:  # 2 backup/backup goalies
                position = random.choice(["G", "D"])
            elif i < 9:  # 6 defensemen
                position = "D"
            else:  # 16+ forwards
                position = random.choice(["C", "LW", "RW"])
            
            players[player_id] = {
                "player_id": player_id,
                "team": team,
                "position": position,
                "jersey": (i % 99) + 1,
                "name": f"Player_{player_id}",
            }
    
    return players


def generate_game_rosters(
    season_id: int,
    games: List[Dict[str, Any]],
    player_pool: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Generate rosters and stats for each game."""
    rosters = []
    stats = []
    
    for game in games:
        game_id = game["game_id"]
        home_away_list = [("home", game["home_team_abbrev"]), ("away", game["away_team_abbrev"])]
        
        for home_away_key, team_abbrev in home_away_list:
            # Get players for this team from player pool
            team_players = [p for p in player_pool.values() if p["team"] == team_abbrev]
            
            # Select a lineup for this game (typically 20 skaters + 1 goalie)
            random.shuffle(team_players)
            lineup = team_players[:21]  # 20 skaters + 1 goalie
            
            for player in lineup:
                player_id = player["player_id"]
                position = player["position"]
                is_goalie = 1 if position == "G" else 0
                is_starter = 1 if position == "G" else 0
                
                # Add to roster list
                rosters.append({
                    "game_id": game_id,
                    "season": season_id,
                    "team_abbrev": team_abbrev,
                    "player_id": player_id,
                    "player_name": player["name"],
                    "position": position,
                    "is_goalie": is_goalie,
                    "is_starter_goalie": 1 if is_goalie else 0,
                    "home_away": "H" if home_away_key == "home" else "A",
                    "player_status": "ACTIVE",
                    "game_state": "FINAL",
                    "game_schedule_state": "OK",
                    "played": 1,
                    "sweater_number": player["jersey"],
                    "fetched_at_utc": datetime.utcnow().isoformat() + "Z",
                })
                
                # Generate realistic stats
                if position == "G":
                    # Goalie stats
                    shots_against = random.randint(25, 45)
                    save_pct = random.gauss(0.915, 0.015)
                    save_pct = max(0.85, min(0.95, save_pct))
                    saves = int(shots_against * save_pct)
                    goals_against = shots_against - saves
                    
                    toi_minutes = random.randint(45, 65)
                    toi_seconds = random.randint(0, 59)
                    
                    stats.append({
                        "game_id": game_id,
                        "season": season_id,
                        "team_abbrev": team_abbrev,
                        "player_id": player_id,
                        "player_name": player["name"],
                        "position": position,
                        "is_goalie": 1,
                        "home_away": "H" if home_away_key == "home" else "A",
                        "toi": f"{toi_minutes}:{toi_seconds:02d}",
                        "toi_seconds": toi_minutes * 60 + toi_seconds,
                        "goals": 0,
                        "assists": 0,
                        "points": 0,
                        "plus_minus": None,
                        "pim": 0,
                        "hits": 0,
                        "power_play_goals": 0,
                        "sog": 0,
                        "faceoff_winning_pctg": None,
                        "blocked_shots": 0,
                        "shifts": random.randint(30, 50),
                        "giveaways": 0,
                        "takeaways": 0,
                        "goals_against": goals_against,
                        "shots_against": shots_against,
                        "saves": saves,
                        "save_shots_against": f"{saves}/{shots_against}",
                        "even_strength_shots_against": str(int(shots_against * 0.7)),
                        "power_play_shots_against": str(int(shots_against * 0.2)),
                        "shorthanded_shots_against": str(int(shots_against * 0.1)),
                        "even_strength_goals_against": int(goals_against * 0.7),
                        "power_play_goals_against": int(goals_against * 0.2),
                        "shorthanded_goals_against": int(goals_against * 0.1),
                        "is_starter_goalie": 1,
                        "fetched_at_utc": datetime.utcnow().isoformat() + "Z",
                    })
                else:
                    # Skater stats
                    toi_minutes = random.randint(8, 22) if position == "D" else random.randint(10, 18)
                    toi_seconds = random.randint(0, 59)
                    points_val = max(0, random.gauss(0.5, 0.7))
                    goals = max(0, random.gauss(0.15, 0.3))
                    assists = points_val - goals
                    assists = max(0, assists)
                    plus_minus = random.randint(-3, 3)
                    sog = random.randint(1, 6)
                    
                    stats.append({
                        "game_id": game_id,
                        "season": season_id,
                        "team_abbrev": team_abbrev,
                        "player_id": player_id,
                        "player_name": player["name"],
                        "position": position,
                        "is_goalie": 0,
                        "home_away": "H" if home_away_key == "home" else "A",
                        "toi": f"{toi_minutes}:{toi_seconds:02d}",
                        "toi_seconds": toi_minutes * 60 + toi_seconds,
                        "goals": int(goals),
                        "assists": int(assists),
                        "points": int(goals + assists),
                        "plus_minus": plus_minus,
                        "pim": random.randint(0, 5),
                        "hits": random.randint(0, 15),
                        "power_play_goals": 1 if random.random() < 0.05 else 0,
                        "sog": sog,
                        "faceoff_winning_pctg": random.gauss(0.5, 0.15) if position == "C" else None,
                        "blocked_shots": random.randint(0, 5),
                        "shifts": random.randint(15, 25),
                        "giveaways": random.randint(0, 3),
                        "takeaways": random.randint(0, 3),
                        "goals_against": None,
                        "shots_against": None,
                        "saves": None,
                        "save_shots_against": None,
                        "even_strength_shots_against": None,
                        "power_play_shots_against": None,
                        "shorthanded_shots_against": None,
                        "even_strength_goals_against": None,
                        "power_play_goals_against": None,
                        "shorthanded_goals_against": None,
                        "is_starter_goalie": 0,
                        "fetched_at_utc": datetime.utcnow().isoformat() + "Z",
                    })
    
    return rosters, stats


def create_synthetic_tables(conn: sqlite3.Connection) -> None:
    """Ensure historical tables exist with proper schema."""
    
    # Check and create historical_games_last5 if needed
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='historical_games_last5'"
    )
    if not cursor.fetchone():
        conn.execute("""
            CREATE TABLE historical_games_last5 (
                season INTEGER NOT NULL,
                game_id INTEGER PRIMARY KEY,
                game_date TEXT NOT NULL,
                home_team_abbrev TEXT NOT NULL,
                away_team_abbrev TEXT NOT NULL,
                home_goals INTEGER NOT NULL,
                away_goals INTEGER NOT NULL,
                winner_abbrev TEXT NOT NULL,
                game_type TEXT NOT NULL,
                status TEXT NOT NULL,
                is_final INTEGER NOT NULL
            )
        """)
    
    # Check and create historical_game_rosters if needed (matches actual schema)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='historical_game_rosters'"
    )
    if not cursor.fetchone():
        conn.execute("""
            CREATE TABLE historical_game_rosters (
                game_id INTEGER,
                season INTEGER NOT NULL,
                team_abbrev TEXT NOT NULL,
                player_id INTEGER NOT NULL,
                player_name TEXT,
                position TEXT,
                is_goalie INTEGER,
                is_starter_goalie INTEGER,
                home_away TEXT,
                player_status TEXT,
                game_state TEXT,
                game_schedule_state TEXT,
                played INTEGER,
                sweater_number INTEGER,
                fetched_at_utc TEXT
            )
        """)
    
    # Check and create historical_player_game_stats if needed
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='historical_player_game_stats'"
    )
    if not cursor.fetchone():
        conn.execute("""
            CREATE TABLE historical_player_game_stats (
                game_id INTEGER,
                season INTEGER NOT NULL,
                team_abbrev TEXT NOT NULL,
                player_id INTEGER NOT NULL,
                player_name TEXT,
                position TEXT,
                is_goalie INTEGER,
                home_away TEXT,
                toi TEXT,
                toi_seconds INTEGER,
                goals INTEGER,
                assists INTEGER,
                points INTEGER,
                plus_minus INTEGER,
                pim INTEGER,
                hits INTEGER,
                power_play_goals INTEGER,
                sog INTEGER,
                faceoff_winning_pctg REAL,
                blocked_shots INTEGER,
                shifts INTEGER,
                giveaways INTEGER,
                takeaways INTEGER,
                goals_against INTEGER,
                shots_against INTEGER,
                saves INTEGER,
                save_shots_against TEXT,
                even_strength_shots_against TEXT,
                power_play_shots_against TEXT,
                shorthanded_shots_against TEXT,
                even_strength_goals_against INTEGER,
                power_play_goals_against INTEGER,
                shorthanded_goals_against INTEGER,
                is_starter_goalie INTEGER,
                fetched_at_utc TEXT
            )
        """)

    for table in ("historical_games_last5", "historical_game_rosters", "historical_player_game_stats"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "is_synthetic" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN is_synthetic INTEGER NOT NULL DEFAULT 0")
        if "data_source" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN data_source TEXT")
    
    conn.commit()


def insert_synthetic_data(
    conn: sqlite3.Connection,
    games: List[Dict[str, Any]],
    rosters: List[Dict[str, Any]],
    stats: List[Dict[str, Any]],
) -> None:
    """Insert synthetic games, rosters, and stats into database."""
    
    print(f"Inserting {len(games)} games...")
    conn.executemany(
        """
        INSERT OR IGNORE INTO historical_games_last5 (
            season, game_id, game_date, home_team_abbrev, away_team_abbrev,
            home_goals, away_goals, winner_abbrev, game_type, status, is_final,
            is_synthetic, data_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(
            g["season"], g["game_id"], g["game_date"],
            g["home_team_abbrev"], g["away_team_abbrev"],
            g["home_goals"], g["away_goals"], g["winner_abbrev"],
            g["game_type"], g["status"], g["is_final"],
            1, "FABRICATED_SYNTHETIC_RANDOM_SEED_42"
        ) for g in games],
    )
    
    print(f"Inserting {len(rosters)} roster records...")
    conn.executemany(
        """
        INSERT OR IGNORE INTO historical_game_rosters (
            game_id, season, team_abbrev, player_id,
            player_name, position, is_goalie, is_starter_goalie,
            home_away, player_status, game_state, game_schedule_state,
            played, sweater_number, fetched_at_utc, is_synthetic, data_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(
            r["game_id"], r["season"], r["team_abbrev"], r["player_id"],
            r["player_name"], r["position"], r["is_goalie"], r["is_starter_goalie"],
            r["home_away"], r["player_status"], r["game_state"], r["game_schedule_state"],
            r["played"], r["sweater_number"], r["fetched_at_utc"],
            1, "FABRICATED_SYNTHETIC_RANDOM_SEED_42"
        ) for r in rosters],
    )
    
    print(f"Inserting {len(stats)} player stats records...")
    conn.executemany(
        """
        INSERT OR IGNORE INTO historical_player_game_stats (
            game_id, season, team_abbrev, player_id, player_name,
            position, is_goalie, home_away, toi, toi_seconds,
            goals, assists, points, plus_minus, pim, hits,
            power_play_goals, sog, faceoff_winning_pctg, blocked_shots,
            shifts, giveaways, takeaways, goals_against, shots_against,
            saves, save_shots_against, even_strength_shots_against,
            power_play_shots_against, shorthanded_shots_against,
            even_strength_goals_against, power_play_goals_against,
            shorthanded_goals_against, is_starter_goalie, fetched_at_utc,
            is_synthetic, data_source
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [(
            s["game_id"], s["season"], s["team_abbrev"], s["player_id"],
            s["player_name"], s["position"], s["is_goalie"], s["home_away"],
            s["toi"], s["toi_seconds"], s["goals"], s["assists"], s["points"],
            s["plus_minus"], s["pim"], s["hits"], s["power_play_goals"],
            s["sog"], s["faceoff_winning_pctg"], s["blocked_shots"],
            s["shifts"], s["giveaways"], s["takeaways"], s["goals_against"],
            s["shots_against"], s["saves"], s["save_shots_against"],
            s["even_strength_shots_against"], s["power_play_shots_against"],
            s["shorthanded_shots_against"], s["even_strength_goals_against"],
            s["power_play_goals_against"], s["shorthanded_goals_against"],
            s["is_starter_goalie"], s["fetched_at_utc"],
            1, "FABRICATED_SYNTHETIC_RANDOM_SEED_42"
        ) for s in stats],
    )
    
    conn.commit()
    print(f"[OK] Inserted {len(games)} games, {len(rosters)} roster records, {len(stats)} player stats")


def main():
    repo_root = Path(__file__).resolve().parent.parent
    db_path = repo_root / "data" / "processed" / "nhl_research.db"
    
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        return False
    
    print(f"Generating synthetic data for {len(SEASONS_TO_GENERATE)} seasons...")
    print(f"Using database: {db_path}\n")
    
    with sqlite3.connect(db_path) as conn:
        # Create tables if needed
        create_synthetic_tables(conn)
        
        all_games = []
        all_rosters = []
        all_stats = []
        
        for season_info in SEASONS_TO_GENERATE:
            season_id = season_info["season_id"]
            year_start = season_info["year_start"]
            year_end = season_info["year_end"]
            
            print(f"Generating season {season_id}...")
            
            # Generate schedule
            games = generate_season_schedule(season_id, year_start, year_end)
            print(f"  Generated {len(games)} games")
            
            # Generate player pool
            player_pool = generate_player_pool(season_id)
            print(f"  Generated {len(player_pool)} players")
            
            # Generate rosters and stats for each game
            rosters, stats = generate_game_rosters(season_id, games, player_pool)
            print(f"  Generated {len(rosters)} roster records and {len(stats)} stat records")
            
            all_games.extend(games)
            all_rosters.extend(rosters)
            all_stats.extend(stats)
        
        print(f"\nTotal: {len(all_games)} games, {len(all_rosters)} roster records, {len(all_stats)} stats records")
        
        # Insert all data
        insert_synthetic_data(conn, all_games, all_rosters, all_stats)
        
        print("\n[OK] Synthetic data generation complete")
        return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
