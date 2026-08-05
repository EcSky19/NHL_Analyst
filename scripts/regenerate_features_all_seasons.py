#!/usr/bin/env python
"""
WARNING: QUARANTINE-AWARE ONLY.
This script can propagate fabricated 2015-2018 rows into feature tables if they
remain in historical_games_last5. Generated outputs must preserve is_synthetic /
data_source provenance and must not be used for benchmarks unless synthetic rows
are excluded.

Engineer features for all 8 seasons (including the newly added 2015-2018 data).
This generates features for the full expanded dataset.
"""

import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
import sys

def regenerate_backtest_features_for_all_seasons(db_path: Path) -> bool:
    """
    Regenerate backtest features table to include all seasons.
    This will drop and recreate the backtest_features_last5 table with all games.
    """
    print("Regenerating backtest features for all seasons...")
    
    with sqlite3.connect(db_path) as conn:
        # Get all unique games
        cursor = conn.execute("""
            SELECT season, game_id, game_date, home_team_abbrev, away_team_abbrev,
                   home_goals, away_goals, winner_abbrev
            FROM historical_games_last5
            ORDER BY season, game_date, game_id
        """)
        games = cursor.fetchall()
        
        print(f"Found {len(games)} total games across all seasons")
        
        if len(games) == 0:
            print("ERROR: No games found in historical_games_last5")
            return False
        
        # Drop the old backtest_features_last5 table
        print("Dropping existing backtest_features_last5 table...")
        conn.execute("DROP TABLE IF EXISTS backtest_features_last5")
        
        # Create the new table with the correct schema
        print("Creating new backtest_features_last5 table...")
        conn.execute("""
            CREATE TABLE backtest_features_last5 (
                season INTEGER NOT NULL,
                game_id INTEGER PRIMARY KEY,
                game_date TEXT NOT NULL,
                home_team_abbrev TEXT NOT NULL,
                away_team_abbrev TEXT NOT NULL,
                home_pregame_streak_signed INTEGER,
                away_pregame_streak_signed INTEGER,
                home_pregame_last10_points_pct REAL,
                away_pregame_last10_points_pct REAL,
                home_pregame_last10_goal_diff_pg REAL,
                away_pregame_last10_goal_diff_pg REAL,
                home_pregame_season_points_pct REAL,
                away_pregame_season_points_pct REAL,
                home_pregame_season_goal_diff_pg REAL,
                away_pregame_season_goal_diff_pg REAL,
                home_pregame_home_points_pct REAL,
                away_pregame_road_points_pct REAL,
                home_pregame_rest_days INTEGER,
                away_pregame_rest_days INTEGER,
                home_back_to_back INTEGER,
                away_back_to_back INTEGER,
                home_three_in_four INTEGER,
                away_three_in_four INTEGER,
                home_four_in_six INTEGER,
                away_four_in_six INTEGER,
                home_pregame_travel_miles REAL,
                away_pregame_travel_miles REAL,
                delta_travel_miles_home_minus_away REAL,
                home_timezone_shift_hours REAL,
                away_timezone_shift_hours REAL,
                delta_timezone_shift_hours_home_minus_away REAL,
                home_pregame_home_stand_len INTEGER,
                away_pregame_home_stand_len INTEGER,
                home_pregame_road_trip_len INTEGER,
                away_pregame_road_trip_len INTEGER,
                delta_home_stand_len_home_minus_away INTEGER,
                delta_road_trip_len_home_minus_away INTEGER,
                rest_days_delta_home_minus_away INTEGER,
                home_location_edge_points_pct REAL,
                home_prior_prev_season_points_pct REAL,
                away_prior_prev_season_points_pct REAL,
                home_prior_prev_season_goal_diff_pg REAL,
                away_prior_prev_season_goal_diff_pg REAL,
                home_prior_prev_season_games INTEGER,
                away_prior_prev_season_games INTEGER,
                delta_pregame_last10_points_pct_home_minus_away REAL,
                delta_pregame_last10_goal_diff_pg_home_minus_away REAL,
                delta_pregame_season_points_pct_home_minus_away REAL,
                delta_pregame_season_goal_diff_pg_home_minus_away REAL,
                home_win INTEGER,
                winner_abbrev TEXT,
                is_synthetic INTEGER NOT NULL DEFAULT 0,
                data_source TEXT
            )
        """)
        
        # Insert base features - for now, just insert the game info
        # The rest of the features will be computed by the existing pipeline
        print("Inserting base game data...")
        conn.executemany("""
            INSERT INTO backtest_features_last5 (
                season, game_id, game_date, home_team_abbrev, away_team_abbrev,
                home_win, winner_abbrev, is_synthetic, data_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                g[0], g[1], g[2], g[3], g[4],
                1 if g[3] == g[7] else 0,  # home_win
                g[7],  # winner_abbrev
                1 if str(g[0]) in {"20152016", "20162017", "20172018"} else 0,
                "FABRICATED_SYNTHETIC_RANDOM_SEED_42"
                if str(g[0]) in {"20152016", "20162017", "20172018"}
                else "REAL_NHL_API_OR_DERIVED_FROM_REAL",
            )
            for g in games
        ])
        
        conn.commit()
        print(f"[OK] Created backtest_features_last5 with {len(games)} games")
        return True


def verify_feature_table(db_path: Path) -> bool:
    """Verify the feature table has been created with all games."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM backtest_features_last5")
        count = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT COUNT(DISTINCT season) FROM backtest_features_last5")
        season_count = cursor.fetchone()[0]
        
        cursor = conn.execute("""
            SELECT season, COUNT(*) 
            FROM backtest_features_last5 
            GROUP BY season 
            ORDER BY season
        """)
        
        print("\nFeature table verification:")
        print(f"Total rows: {count}")
        print(f"Distinct seasons: {season_count}")
        print("\nGames per season:")
        for season, cnt in cursor.fetchall():
            print(f"  Season {season}: {cnt} games")
        
        return count > 6560  # Should be > 6560 now that we've added 1406 games


def main():
    parser = argparse.ArgumentParser(description="Engineer features for expanded 8-season dataset")
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args()
    
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parent.parent
    db_path = repo_root / "data" / "processed" / "nhl_research.db"
    
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        return False
    
    print(f"Using database: {db_path}\n")
    
    # Regenerate features for all seasons
    if not regenerate_backtest_features_for_all_seasons(db_path):
        print("ERROR: Failed to regenerate backtest features")
        return False
    
    # Verify
    if not verify_feature_table(db_path):
        print("WARNING: Feature table may not include all expanded data")
    
    print("\n[OK] Feature table regenerated for all 8 seasons")
    print("\nNOTE: Run build_last5_backtest_features_roster.py next to compute advanced roster features")
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
