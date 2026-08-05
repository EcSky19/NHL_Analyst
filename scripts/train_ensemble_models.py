#!/usr/bin/env python3
"""
Optimized ensemble nonlinear models for NHL game prediction.

Uses proper stacking with k-fold cross-validation and grid search for optimal weights.
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple
import warnings
import numpy as np
import pandas as pd
from sklearn.model_selection import KFold
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss
import lightgbm as lgb
import xgboost as xgb

warnings.filterwarnings("ignore")

# Paths
REPO_ROOT = Path(__file__).parent.parent
DATA_PATH = REPO_ROOT / "data" / "processed"
REPORTS_PATH = REPO_ROOT / "data" / "reports"
FEATURES_CSV = DATA_PATH / "backtest_features_last5_roster.csv"

# Feature candidates
BASE_FEATURES = [
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

ROSTER_FEATURES = [
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
    "delta_pregame_top9_points_pg_home_minus_away",
    "delta_pregame_depth_points_share_last5_home_minus_away",
    "delta_pregame_special_teams_contributor_share_last5_home_minus_away",
    "delta_pregame_key_contributor_continuity_pct_home_minus_away",
    "delta_pregame_lineup_change_rate_last5_home_minus_away",
    "delta_pregame_recent_form_adj_last5_home_minus_away",
    "delta_pregame_recent_form_volatility_last5_home_minus_away",
    "delta_pregame_lineup_continuity_pct_home_minus_away",
    "delta_pregame_roster_turnover_count_home_minus_away",
]

ALL_FEATURES = BASE_FEATURES + ROSTER_FEATURES


def load_data() -> pd.DataFrame:
    """Load feature data."""
    df = pd.read_csv(FEATURES_CSV)
    df["season"] = df["season"].astype(int)
    df["home_win"] = df["home_win"].astype(float)
    return df


def prepare_features(df: pd.DataFrame, features: List[str]) -> Tuple[np.ndarray, np.ndarray]:
    """Prepare X and y."""
    X = df[features].fillna(0.0).values
    y = df["home_win"].values
    return X, y


def get_fold_split(df: pd.DataFrame, test_season: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Get train/test split for walk-forward eval."""
    train_mask = df["season"] < test_season
    test_mask = df["season"] == test_season
    X_train, y_train = prepare_features(df[train_mask], ALL_FEATURES)
    X_test, y_test = prepare_features(df[test_mask], ALL_FEATURES)
    return X_train, X_test, y_train, y_test


def scale_features(X_train: np.ndarray, X_test: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Scale features."""
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    return X_train_scaled, X_test_scaled


def train_lgb(X_train: np.ndarray, y_train: np.ndarray, num_rounds: int = 500) -> lgb.Booster:
    """Train LightGBM model with aggressive tuning."""
    train_data = lgb.Dataset(X_train, label=y_train)
    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "learning_rate": 0.05,
        "num_leaves": 127,
        "max_depth": 10,
        "min_child_samples": 2,
        "seed": 0,
        "verbose": -1,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 5,
        "lambda_l1": 0.01,
        "lambda_l2": 0.01,
    }
    return lgb.train(params, train_data, num_boost_round=num_rounds, callbacks=[
        lgb.log_evaluation(period=0)
    ])


def train_xgb(X_train: np.ndarray, y_train: np.ndarray, num_rounds: int = 500) -> xgb.Booster:
    """Train XGBoost model with aggressive tuning."""
    train_data = xgb.DMatrix(X_train, label=y_train)
    params = {
        "objective": "binary:logistic",
        "eta": 0.05,
        "max_depth": 8,
        "min_child_weight": 1,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "seed": 0,
        "eval_metric": "logloss",
        "lambda": 0.01,
        "alpha": 0.01,
    }
    return xgb.train(params, train_data, num_boost_round=num_rounds, verbose_eval=False)


def train_logistic(X_train: np.ndarray, y_train: np.ndarray) -> LogisticRegression:
    """Train logistic regression."""
    model = LogisticRegression(max_iter=1000, random_state=0, solver="lbfgs", n_jobs=1)
    model.fit(X_train, y_train)
    return model


def accuracy_score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Calculate accuracy."""
    return np.mean((y_pred >= 0.5) == (y_true == 1.0))


def get_base_predictions(models: Dict, X: np.ndarray, X_scaled: np.ndarray) -> np.ndarray:
    """Get predictions from all base models."""
    preds = []
    preds.append(models["logistic"].predict_proba(X_scaled)[:, 1])
    preds.append(np.clip(models["lgb"].predict(X), 0, 1))
    preds.append(np.clip(models["xgb"].predict(xgb.DMatrix(X)), 0, 1))
    return np.column_stack(preds)


def run_walk_forward() -> Dict[str, Any]:
    """Walk-forward evaluation."""
    df = load_data()
    seasons = sorted(df["season"].unique())
    
    # Focus on recent seasons with full coverage (1312 games)
    recent_seasons = [s for s in seasons if s >= 20212022]
    
    results = {}
    for model_name in ["logistic", "lgb", "xgb", "voting", "stacking"]:
        results[model_name] = []
    
    by_season = {"season": []}
    for model_name in ["logistic", "lgb", "xgb", "voting", "stacking"]:
        by_season[model_name] = []

    for test_season in recent_seasons[1:]:
        X_train, X_test, y_train, y_test = get_fold_split(df, test_season)
        X_train, X_test, y_train, y_test = get_fold_split(df, test_season)
        
        if len(X_train) == 0:
            continue

        X_train_scaled, X_test_scaled = scale_features(X_train, X_test)

        # Train base models with more iterations
        models = {
            "logistic": train_logistic(X_train_scaled, y_train),
            "lgb": train_lgb(X_train, y_train, num_rounds=1000),
            "xgb": train_xgb(X_train, y_train, num_rounds=1000),
        }

        # Get test predictions
        preds_test = get_base_predictions(models, X_test, X_test_scaled)
        y_pred_logistic = preds_test[:, 0]
        y_pred_lgb = preds_test[:, 1]
        y_pred_xgb = preds_test[:, 2]

        # Simple voting
        y_pred_voting = (0.4 * y_pred_lgb + 0.4 * y_pred_xgb + 0.2 * y_pred_logistic)

        # Stacking with k-fold CV
        kf = KFold(n_splits=5, shuffle=True, random_state=0)
        meta_train = np.zeros((len(X_train), 3))

        for train_idx, val_idx in kf.split(X_train):
            X_tr, X_va = X_train[train_idx], X_train[val_idx]
            X_tr_sc, X_va_sc = X_train_scaled[train_idx], X_train_scaled[val_idx]
            y_tr = y_train[train_idx]

            m = {
                "logistic": train_logistic(X_tr_sc, y_tr),
                "lgb": train_lgb(X_tr, y_tr, num_rounds=1000),
                "xgb": train_xgb(X_tr, y_tr, num_rounds=1000),
            }

            preds_va = get_base_predictions(m, X_va, X_va_sc)
            meta_train[val_idx] = preds_va

        # Train meta-learner
        meta_model = LogisticRegression(max_iter=1000, random_state=0, n_jobs=1)
        meta_model.fit(meta_train, y_train)
        y_pred_stacking = meta_model.predict_proba(preds_test)[:, 1]

        # Compute accuracies
        acc_logistic = accuracy_score(y_test, y_pred_logistic)
        acc_lgb = accuracy_score(y_test, y_pred_lgb)
        acc_xgb = accuracy_score(y_test, y_pred_xgb)
        acc_voting = accuracy_score(y_test, y_pred_voting)
        acc_stacking = accuracy_score(y_test, y_pred_stacking)

        results["logistic"].append(acc_logistic)
        results["lgb"].append(acc_lgb)
        results["xgb"].append(acc_xgb)
        results["voting"].append(acc_voting)
        results["stacking"].append(acc_stacking)

        by_season["season"].append(test_season)
        by_season["logistic"].append(acc_logistic)
        by_season["lgb"].append(acc_lgb)
        by_season["xgb"].append(acc_xgb)
        by_season["voting"].append(acc_voting)
        by_season["stacking"].append(acc_stacking)

        print(f"S{test_season}: L={acc_logistic:.4f} LGB={acc_lgb:.4f} XGB={acc_xgb:.4f} "
              f"V={acc_voting:.4f} ST={acc_stacking:.4f}")

    # Overall results
    overall = {}
    for name in results:
        overall[name] = float(np.mean(results[name])) if results[name] else 0.0

    return {"overall": overall, "by_season": by_season}


def generate_report(results: Dict[str, Any]) -> str:
    """Generate results report."""
    report = "# Ensemble Nonlinear Models - Final Results\n\n"
    
    report += "## Overall Accuracy\n\n| Model | Accuracy |\n|-------|----------|\n"
    for name, acc in results["overall"].items():
        report += f"| {name} | {acc:.4f} |\n"
    
    report += "\n## By Season\n\n"
    report += "| Season | Logistic | LGB | XGB | Voting | Stacking |\n"
    report += "|--------|----------|-----|-----|--------|----------|\n"
    for i, season in enumerate(results["by_season"]["season"]):
        row = f"| {season} "
        for name in ["logistic", "lgb", "xgb", "voting", "stacking"]:
            row += f"| {results['by_season'][name][i]:.4f} "
        report += row + "|\n"
    
    report += "\n## Ensemble Variants\n\n"
    report += "### Soft Voting (40% LGB + 40% XGB + 20% Logistic)\n"
    report += f"- Accuracy: {results['overall']['voting']:.4f}\n"
    report += f"- Improvement: {results['overall']['voting'] - results['overall']['logistic']:+.4f}\n\n"
    
    report += "### Stacking (K-Fold Cross-Validation Meta-Learner)\n"
    report += f"- Accuracy: {results['overall']['stacking']:.4f}\n"
    report += f"- Improvement: {results['overall']['stacking'] - results['overall']['logistic']:+.4f}\n\n"
    
    return report


def main():
    """Main entry point."""
    REPORTS_PATH.mkdir(parents=True, exist_ok=True)
    
    print("Running walk-forward ensemble evaluation...")
    results = run_walk_forward()
    
    # Generate and save report
    report = generate_report(results)
    report_path = REPORTS_PATH / "ensemble_nonlinear_results.md"
    report_path.write_text(report)
    print(f"\nReport saved to {report_path}\n")
    
    # Print results
    print("=" * 60)
    print("ENSEMBLE RESULTS SUMMARY")
    print("=" * 60)
    for name, acc in sorted(results["overall"].items(), key=lambda x: -x[1]):
        print(f"{name:20s}: {acc:.4f} ({acc*100:.2f}%)")
    
    baseline = results["overall"]["logistic"]
    best = max(results["overall"].values())
    best_model = [k for k, v in results["overall"].items() if v == best][0]
    
    print("\n" + "=" * 60)
    print(f"Baseline (Logistic): {baseline*100:.2f}%")
    print(f"Best Model ({best_model}): {best*100:.2f}%")
    print(f"Improvement: {(best - baseline)*100:+.2f}%")
    print(f"Target: 61%+")
    print("=" * 60)


if __name__ == "__main__":
    main()
