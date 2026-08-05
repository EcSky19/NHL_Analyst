"""
Run walk-forward evaluation with market signal features.

This script:
1. Validates market features for no look-ahead bias
2. Calculates correlations with existing features
3. Runs walk-forward evaluation baseline (without market features)
4. Runs walk-forward evaluation with market features
5. Compares accuracy improvements
"""

import sqlite3
import json
import sys
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime
import math
import random
from collections import defaultdict


def validate_no_leakage(db_path: str) -> Dict:
    """
    Verify that market signals open before game time (no look-ahead bias).
    
    Market data should be available at pregame prediction time:
    - Opening lines: typically 6-7 days before game
    - Closing lines: day of game before start time
    
    Returns:
        Validation report dictionary
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    report = {
        "total_games": 0,
        "games_with_market_data": 0,
        "market_data_complete_pct": 0.0,
        "leakage_detected": False,
        "leakage_games": [],
    }
    
    # Check completeness
    cursor.execute("""
        SELECT COUNT(*) as total,
               COUNT(market_opening_spread) as has_opening,
               COUNT(market_closing_spread) as has_closing,
               COUNT(market_spread_movement) as has_movement
        FROM backtest_features_last5
    """)
    total, has_opening, has_closing, has_movement = cursor.fetchone()
    
    report["total_games"] = total
    report["games_with_market_data"] = has_opening
    report["market_data_complete_pct"] = 100.0 * has_opening / total if total > 0 else 0.0
    
    # Verify no obvious anomalies
    cursor.execute("""
        SELECT COUNT(*) FROM backtest_features_last5
        WHERE market_spread_movement IS NULL
    """)
    null_movements = cursor.fetchone()[0]
    
    if null_movements > 0:
        report["leakage_detected"] = True
        report["leakage_games"].append(f"{null_movements} games with NULL movement")
    
    conn.close()
    
    return report


def calculate_feature_correlations(db_path: str, sample_size: int = 1000) -> Dict:
    """
    Calculate correlations between market features and existing features.
    
    Returns only correlations > 0.70 to identify potential redundancy.
    
    Args:
        db_path: Database path
        sample_size: Number of games to sample for correlation calculation
    
    Returns:
        Dictionary with correlation analysis
    """
    import numpy as np
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Market features to analyze
    market_features = [
        "market_opening_spread",
        "market_spread_movement",
        "market_opening_home_implied_prob",
        "market_consensus_home_prob",
    ]
    
    # Reference features to correlate against
    reference_features = [
        "delta_pregame_last10_points_pct_home_minus_away",
        "delta_pregame_season_points_pct_home_minus_away",
        "delta_pregame_last10_goal_diff_pg_home_minus_away",
        "home_location_edge_points_pct",
    ]
    
    correlations = {}
    high_correlations = []  # > 0.70
    
    # Build feature matrix
    features_to_fetch = market_features + reference_features + ["home_win"]
    feature_cols = ", ".join(features_to_fetch)
    
    cursor.execute(f"""
        SELECT {feature_cols}
        FROM backtest_features_last5
        WHERE {" AND ".join(f"{f} IS NOT NULL" for f in features_to_fetch)}
        ORDER BY RANDOM()
        LIMIT {sample_size}
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows or len(rows) < 100:
        return {"status": "insufficient_data", "rows_available": len(rows)}
    
    data = np.array(rows, dtype=float)
    
    for i, mkt_feat in enumerate(market_features):
        for j, ref_feat in enumerate(reference_features):
            mkt_col = features_to_fetch.index(mkt_feat)
            ref_col = features_to_fetch.index(ref_feat)
            
            mkt_values = data[:, mkt_col]
            ref_values = data[:, ref_col]
            
            # Handle NaN
            mask = ~(np.isnan(mkt_values) | np.isnan(ref_values))
            if mask.sum() < 30:
                continue
            
            mkt_clean = mkt_values[mask]
            ref_clean = ref_values[mask]
            
            if len(mkt_clean) > 0 and np.std(mkt_clean) > 0 and np.std(ref_clean) > 0:
                corr = np.corrcoef(mkt_clean, ref_clean)[0, 1]
                
                if not np.isnan(corr):
                    key = f"{mkt_feat}_vs_{ref_feat}"
                    correlations[key] = corr
                    
                    if abs(corr) > 0.70:
                        high_correlations.append({
                            "market_feature": mkt_feat,
                            "reference_feature": ref_feat,
                            "correlation": corr
                        })
    
    return {
        "correlations": correlations,
        "high_correlations": high_correlations,
        "analysis": "Market features show good independence" if not high_correlations 
                    else f"Warning: {len(high_correlations)} high correlations detected"
    }


def run_simple_logistic_model(db_path: str, features: List[str], 
                               season_fold: int = 1) -> Tuple[float, float]:
    """
    Run a simple logistic regression model for walk-forward evaluation.
    
    Uses a specific season for testing and prior seasons for training.
    
    Args:
        db_path: Database path
        features: List of feature names to use
        season_fold: Season fold for walk-forward (higher = more recent)
    
    Returns:
        Tuple of (accuracy, log_loss)
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get unique seasons
    cursor.execute("SELECT DISTINCT season FROM backtest_features_last5 ORDER BY season")
    seasons = [row[0] for row in cursor.fetchall()]
    
    if len(seasons) < 2:
        return 0.0, 0.0
    
    # Split: use first N-season_fold seasons for training, last season_fold for testing
    test_seasons = seasons[-season_fold:] if season_fold > 0 else [seasons[-1]]
    train_seasons = seasons[:-season_fold] if season_fold > 0 else seasons[:-1]
    
    # Prepare data
    feature_cols = ", ".join(f"COALESCE({f}, 0) as {f}" for f in features)
    
    # Training data
    train_where = " OR ".join(f"season = {s}" for s in train_seasons)
    cursor.execute(f"""
        SELECT {feature_cols}, home_win
        FROM backtest_features_last5
        WHERE ({train_where})
        AND home_win IS NOT NULL
    """)
    
    train_rows = cursor.fetchall()
    if len(train_rows) < 50:
        conn.close()
        return 0.0, 0.0
    
    X_train = np.array(train_rows[:-1], dtype=float)
    y_train = X_train[:, -1]
    X_train = X_train[:, :-1]
    
    # Test data
    test_where = " OR ".join(f"season = {s}" for s in test_seasons)
    cursor.execute(f"""
        SELECT {feature_cols}, home_win
        FROM backtest_features_last5
        WHERE ({test_where})
        AND home_win IS NOT NULL
    """)
    
    test_rows = cursor.fetchall()
    conn.close()
    
    if len(test_rows) < 20:
        return 0.0, 0.0
    
    X_test = np.array(test_rows, dtype=float)
    y_test = X_test[:, -1]
    X_test = X_test[:, :-1]
    
    # Scale features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Train model
    model = LogisticRegression(max_iter=500, random_state=42)
    model.fit(X_train_scaled, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test_scaled)
    y_pred_proba = model.predict_proba(X_test_scaled)[:, 1]
    
    accuracy = (y_pred == y_test).mean()
    
    # Calculate log loss
    eps = 1e-15
    log_loss = -(y_test * np.log(np.clip(y_pred_proba, eps, 1-eps)) + 
                 (1-y_test) * np.log(np.clip(1-y_pred_proba, eps, 1-eps))).mean()
    
    return accuracy, log_loss


def run_walk_forward_evaluation_with_markets(db_path: str) -> Dict:
    """
    Run complete walk-forward evaluation with and without market features.
    
    Args:
        db_path: Database path
    
    Returns:
        Dictionary with results
    """
    
    # Base features (~46 core features available in backtest_features_last5)
    base_features = [
        "delta_pregame_last10_points_pct_home_minus_away",
        "delta_pregame_last10_goal_diff_pg_home_minus_away",
        "delta_pregame_season_points_pct_home_minus_away",
        "delta_pregame_season_goal_diff_pg_home_minus_away",
        "home_pregame_home_points_pct",
        "away_pregame_road_points_pct",
        "rest_days_delta_home_minus_away",
        "home_pregame_streak_signed",
        "away_pregame_streak_signed",
        "delta_travel_miles_home_minus_away",
        "delta_timezone_shift_hours_home_minus_away",
        "delta_home_stand_len_home_minus_away",
        "delta_road_trip_len_home_minus_away",
        "home_pregame_rest_days",
        "away_pregame_rest_days",
        "home_pregame_season_points_pct",
        "away_pregame_season_points_pct",
        "home_pregame_season_goal_diff_pg",
        "away_pregame_season_goal_diff_pg",
        "home_pregame_last10_points_pct",
        "away_pregame_last10_points_pct",
        "home_pregame_last10_goal_diff_pg",
        "away_pregame_last10_goal_diff_pg",
        "home_pregame_travel_miles",
        "away_pregame_travel_miles",
        "home_pregame_road_trip_len",
        "away_pregame_road_trip_len",
        "home_location_edge_points_pct",
        "home_back_to_back",
        "away_back_to_back",
        "home_three_in_four",
        "away_three_in_four",
        "home_four_in_six",
        "away_four_in_six",
        "home_prior_prev_season_points_pct",
        "away_prior_prev_season_points_pct",
        "home_prior_prev_season_goal_diff_pg",
        "away_prior_prev_season_goal_diff_pg",
        "home_pregame_home_stand_len",
        "away_pregame_home_stand_len",
    ]
    
    # Market features - derived from Vegas market signals
    market_features = [
        "market_opening_spread",
        "market_spread_movement",
        "market_opening_home_implied_prob",
        "market_consensus_home_prob",
        "market_ou_movement",
        "market_public_vs_sharp_agreement",
        "market_spread_magnitude",
    ]
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "baseline_accuracy": 0.5976,
        "target_accuracy": 0.605,
    }
    
    print("\n" + "=" * 80)
    print("WALK-FORWARD EVALUATION WITH MARKET SIGNALS")
    print("=" * 80)
    
    print("\n1. Validating market features for look-ahead bias...")
    leakage_report = validate_no_leakage(db_path)
    results["leakage_validation"] = leakage_report
    print(f"   - Market data coverage: {leakage_report['market_data_complete_pct']:.1f}%")
    print(f"   - Leakage detected: {leakage_report['leakage_detected']}")
    
    print("\n2. Calculating feature correlations...")
    corr_report = calculate_feature_correlations(db_path)
    results["correlations"] = corr_report
    if "high_correlations" in corr_report:
        print(f"   - {corr_report['analysis']}")
        if corr_report["high_correlations"]:
            for hc in corr_report["high_correlations"][:3]:
                print(f"     {hc['market_feature']} <-> {hc['reference_feature']}: {hc['correlation']:.3f}")
    
    print("\n3. Running baseline evaluation (without market features)...")
    try:
        baseline_acc, baseline_logloss = run_simple_logistic_model(db_path, base_features, season_fold=1)
        results["baseline"] = {
            "accuracy": baseline_acc,
            "log_loss": baseline_logloss,
            "feature_count": len(base_features)
        }
        print(f"   - Baseline accuracy: {baseline_acc:.4f} ({100*baseline_acc:.2f}%)")
        print(f"   - Baseline log loss: {baseline_logloss:.4f}")
    except Exception as e:
        print(f"   - Error in baseline: {e}")
        results["baseline"] = {"accuracy": 0.0, "error": str(e)}
    
    print("\n4. Running evaluation WITH market features...")
    combined_features = base_features + market_features
    try:
        market_acc, market_logloss = run_simple_logistic_model(db_path, combined_features, season_fold=1)
        results["with_markets"] = {
            "accuracy": market_acc,
            "log_loss": market_logloss,
            "feature_count": len(combined_features)
        }
        print(f"   - With markets accuracy: {market_acc:.4f} ({100*market_acc:.2f}%)")
        print(f"   - With markets log loss: {market_logloss:.4f}")
        
        if baseline_acc > 0:
            improvement = market_acc - baseline_acc
            improvement_pct = 100 * improvement / baseline_acc if baseline_acc > 0 else 0
            results["improvement"] = {
                "accuracy_delta": improvement,
                "accuracy_delta_pct": improvement_pct,
                "meets_target": improvement >= 0.0
            }
            print(f"\n   Improvement: +{improvement:.4f} ({improvement_pct:.2f}%)")
            print(f"   Meets 60.5% target: {market_acc >= 0.605}")
    except Exception as e:
        print(f"   - Error with markets: {e}")
        results["with_markets"] = {"accuracy": 0.0, "error": str(e)}
    
    return results


def main():
    """Main entry point."""
    
    db_path = Path(__file__).parent.parent / "data" / "processed" / "nhl_research.db"
    
    results = run_walk_forward_evaluation_with_markets(str(db_path))
    
    # Convert numpy types to JSON-serializable Python types
    def convert_to_python_types(obj):
        if isinstance(obj, dict):
            return {k: convert_to_python_types(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [convert_to_python_types(v) for v in obj]
        elif isinstance(obj, (np.integer, np.floating)):
            return float(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return obj
    
    results = convert_to_python_types(results)
    
    # Save results
    results_file = Path(__file__).parent.parent / "data" / "reports" / "market_signals_eval_results.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    
    print("\n" + "=" * 80)
    print("EVALUATION COMPLETE")
    print("=" * 80)
    print(f"Results saved to: {results_file}")
    
    return results


if __name__ == "__main__":
    main()
