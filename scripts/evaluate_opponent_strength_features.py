"""
Advanced walk-forward evaluation using scikit-learn models.
Compares prediction accuracy with and without opponent strength features.
"""

import sqlite3
from pathlib import Path
import sys
from typing import List, Dict, Tuple
import numpy as np

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
except ImportError:
    print("ERROR: scikit-learn not found. Installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "scikit-learn", "-q"])
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler


def safe_float(val):
    """Safely convert value to float, returning None if not convertible."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def load_backtest_data(conn: sqlite3.Connection) -> List[Dict]:
    """Load backtest features and merge with opponent strength features."""
    query = """
    SELECT
        b.season, b.game_id, b.game_date,
        b.home_team_abbrev, b.away_team_abbrev,
        b.home_pregame_last10_points_pct,
        b.away_pregame_last10_points_pct,
        b.home_pregame_season_points_pct,
        b.away_pregame_season_points_pct,
        b.home_back_to_back,
        b.away_back_to_back,
        b.home_pregame_rest_days,
        b.away_pregame_rest_days,
        b.home_pregame_travel_miles,
        b.away_pregame_travel_miles,
        o.home_avg_opp_win_pct_played,
        o.away_avg_opp_win_pct_played,
        o.home_opponent_strength_percentile,
        o.away_opponent_strength_percentile,
        o.home_cumulative_opponent_strength,
        o.away_cumulative_opponent_strength,
        o.home_last_opponent_win_pct,
        o.away_last_opponent_win_pct,
        o.home_avg_last3_opponent_strength,
        o.away_avg_last3_opponent_strength,
        o.home_team_win_pct_rank_percentile,
        o.away_team_win_pct_rank_percentile,
        b.home_win
    FROM backtest_features_last5 b
    LEFT JOIN opponent_strength_features o 
        ON b.season = o.season AND b.game_id = o.game_id
    ORDER BY b.season, b.game_date, b.game_id
    """
    
    data = []
    for row in conn.execute(query).fetchall():
        data.append({
            "season": row[0],
            "game_id": row[1],
            "game_date": row[2],
            "home_team": row[3],
            "away_team": row[4],
            "home_last10_pct": safe_float(row[5]),
            "away_last10_pct": safe_float(row[6]),
            "home_season_pct": safe_float(row[7]),
            "away_season_pct": safe_float(row[8]),
            "home_b2b": safe_float(row[9]),
            "away_b2b": safe_float(row[10]),
            "home_rest": safe_float(row[11]),
            "away_rest": safe_float(row[12]),
            "home_travel": safe_float(row[13]),
            "away_travel": safe_float(row[14]),
            "home_opp_sos": safe_float(row[15]),
            "away_opp_sos": safe_float(row[16]),
            "home_opp_percentile": safe_float(row[17]),
            "away_opp_percentile": safe_float(row[18]),
            "home_cumul_sos": safe_float(row[19]),
            "away_cumul_sos": safe_float(row[20]),
            "home_last_opp_pct": safe_float(row[21]),
            "away_last_opp_pct": safe_float(row[22]),
            "home_last3_opp": safe_float(row[23]),
            "away_last3_opp": safe_float(row[24]),
            "home_rank_pct": safe_float(row[25]),
            "away_rank_pct": safe_float(row[26]),
            "home_win": safe_float(row[27]),
        })
    
    return data


def compute_feature_matrix_baseline(games: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
    """Compute baseline feature matrix (10 features)."""
    features_list = []
    targets = []
    
    for game in games:
        features = [
            game.get("home_last10_pct") or 0.5,
            game.get("away_last10_pct") or 0.5,
            game.get("home_season_pct") or 0.5,
            game.get("away_season_pct") or 0.5,
            float(game.get("home_b2b") or 0),
            float(game.get("away_b2b") or 0),
            float(game.get("home_rest") or 1),
            float(game.get("away_rest") or 1),
            (game.get("home_last10_pct") or 0.5) - (game.get("away_last10_pct") or 0.5),
            (game.get("home_season_pct") or 0.5) - (game.get("away_season_pct") or 0.5),
        ]
        targets.append(game.get("home_win") or 0)
        features_list.append(features)
    
    return np.array(features_list), np.array(targets)


def compute_feature_matrix_enhanced(games: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
    """Compute enhanced feature matrix with opponent strength features."""
    features_list = []
    targets = []
    
    for game in games:
        features = [
            game.get("home_last10_pct") or 0.5,
            game.get("away_last10_pct") or 0.5,
            game.get("home_season_pct") or 0.5,
            game.get("away_season_pct") or 0.5,
            float(game.get("home_b2b") or 0),
            float(game.get("away_b2b") or 0),
            float(game.get("home_rest") or 1),
            float(game.get("away_rest") or 1),
            (game.get("home_last10_pct") or 0.5) - (game.get("away_last10_pct") or 0.5),
            (game.get("home_season_pct") or 0.5) - (game.get("away_season_pct") or 0.5),
            # New opponent strength features
            game.get("home_opp_sos") or 0.5,
            game.get("away_opp_sos") or 0.5,
            game.get("home_opp_percentile") or 50.0,
            game.get("away_opp_percentile") or 50.0,
            game.get("home_last_opp_pct") or 0.5,
            game.get("away_last_opp_pct") or 0.5,
            game.get("home_last3_opp") or 0.5,
            game.get("away_last3_opp") or 0.5,
            game.get("home_rank_pct") or 50.0,
            game.get("away_rank_pct") or 50.0,
            (game.get("home_opp_sos") or 0.5) - (game.get("away_opp_sos") or 0.5),
            (game.get("home_rank_pct") or 50.0) - (game.get("away_rank_pct") or 50.0),
        ]
        targets.append(game.get("home_win") or 0)
        features_list.append(features)
    
    return np.array(features_list), np.array(targets)


def walk_forward_evaluation(all_data: List[Dict]) -> Dict:
    """Perform walk-forward evaluation with proper ML models."""
    results_baseline = []
    results_enhanced = []
    
    seasons = sorted(set(g["season"] for g in all_data))
    
    # Group by season
    data_by_season = {}
    for season in seasons:
        data_by_season[season] = [g for g in all_data if g["season"] == season]
    
    # Walk forward: train on historical, test on next season
    all_seasons = sorted(data_by_season.keys())
    for test_season_idx in range(1, len(all_seasons)):
        test_season = all_seasons[test_season_idx]
        
        # Collect training data from previous seasons (2-year window)
        train_data = []
        for i in range(max(0, test_season_idx - 2), test_season_idx):
            train_data.extend(data_by_season[all_seasons[i]])
        
        test_data = data_by_season[test_season]
        
        if len(train_data) < 100 or len(test_data) < 50:
            continue
        
        print(f"\nSeason {test_season}: train={len(train_data)}, test={len(test_data)}")
        
        # Train baseline model (Random Forest)
        try:
            X_train_base, y_train = compute_feature_matrix_baseline(train_data)
            X_test_base, y_test = compute_feature_matrix_baseline(test_data)
            
            # Handle NaN values
            X_train_base = np.nan_to_num(X_train_base, nan=0.5, posinf=1.0, neginf=0.0)
            X_test_base = np.nan_to_num(X_test_base, nan=0.5, posinf=1.0, neginf=0.0)
            
            scaler_base = StandardScaler()
            X_train_base = scaler_base.fit_transform(X_train_base)
            X_test_base = scaler_base.transform(X_test_base)
            
            model_base = RandomForestClassifier(n_estimators=100, max_depth=8, random_state=42)
            model_base.fit(X_train_base, y_train)
            accuracy_base = model_base.score(X_test_base, y_test)
            results_baseline.append(accuracy_base)
            print(f"  Baseline: {accuracy_base:.4f}")
        except Exception as e:
            print(f"  Baseline error: {e}")
            results_baseline.append(0.5)
        
        # Train enhanced model
        try:
            X_train_enh, y_train = compute_feature_matrix_enhanced(train_data)
            X_test_enh, y_test = compute_feature_matrix_enhanced(test_data)
            
            # Handle NaN values
            X_train_enh = np.nan_to_num(X_train_enh, nan=0.5, posinf=1.0, neginf=0.0)
            X_test_enh = np.nan_to_num(X_test_enh, nan=0.5, posinf=1.0, neginf=0.0)
            
            scaler_enh = StandardScaler()
            X_train_enh = scaler_enh.fit_transform(X_train_enh)
            X_test_enh = scaler_enh.transform(X_test_enh)
            
            model_enh = RandomForestClassifier(n_estimators=100, max_depth=8, random_state=42)
            model_enh.fit(X_train_enh, y_train)
            accuracy_enh = model_enh.score(X_test_enh, y_test)
            results_enhanced.append(accuracy_enh)
            print(f"  Enhanced: {accuracy_enh:.4f}")
        except Exception as e:
            print(f"  Enhanced error: {e}")
            results_enhanced.append(0.5)
    
    # Aggregate results
    if results_baseline:
        avg_baseline = np.mean(results_baseline)
        avg_enhanced = np.mean(results_enhanced)
        improvement = avg_enhanced - avg_baseline
        improvement_pct = 100.0 * improvement / avg_baseline if avg_baseline > 0 else 0
        
        return {
            "baseline_accuracy": avg_baseline,
            "enhanced_accuracy": avg_enhanced,
            "improvement": improvement,
            "improvement_pct": improvement_pct,
            "n_folds": len(results_baseline),
            "baseline_folds": results_baseline,
            "enhanced_folds": results_enhanced,
        }
    
    return {"baseline_accuracy": 0, "enhanced_accuracy": 0, "improvement": 0, 
            "improvement_pct": 0, "n_folds": 0, "baseline_folds": [], "enhanced_folds": []}


def main():
    db_path = Path("data/processed/nhl_research.db")
    
    con = sqlite3.connect(db_path)
    all_data = load_backtest_data(con)
    con.close()
    
    print(f"Loaded {len(all_data)} games")
    
    print("\nRunning advanced walk-forward evaluation with Random Forest...")
    results = walk_forward_evaluation(all_data)
    
    print("\n" + "="*70)
    print("ADVANCED WALK-FORWARD EVALUATION RESULTS (Random Forest)")
    print("="*70)
    print(f"Baseline (10 features):  {results['baseline_accuracy']:.4f} ({results['baseline_accuracy']*100:.2f}%)")
    print(f"Enhanced (22 features):  {results['enhanced_accuracy']:.4f} ({results['enhanced_accuracy']*100:.2f}%)")
    print(f"Improvement:             {results['improvement']:+.4f} ({results['improvement_pct']:+.2f}%)")
    print(f"Evaluation folds:        {results['n_folds']}")
    print("="*70)
    
    # Save results
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS opponent_strength_eval_results (
            baseline_accuracy REAL,
            enhanced_accuracy REAL,
            improvement REAL,
            improvement_pct REAL,
            n_folds INTEGER,
            evaluation_date TEXT
        )
    """)
    cur.execute("DELETE FROM opponent_strength_eval_results")
    
    from datetime import datetime
    cur.execute("""
        INSERT INTO opponent_strength_eval_results 
        VALUES (?, ?, ?, ?, ?, ?)
    """, (results['baseline_accuracy'], results['enhanced_accuracy'], 
          results['improvement'], results['improvement_pct'], results['n_folds'],
          datetime.now().isoformat()))
    con.commit()
    con.close()
    
    print("\nResults saved to opponent_strength_eval_results table")


if __name__ == "__main__":
    main()
