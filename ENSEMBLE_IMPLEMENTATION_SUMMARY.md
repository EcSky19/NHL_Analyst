# Ensemble Nonlinear Models Implementation - Summary

## Task Completion Status

### Requirements Met:
1. ✅ **Installed gradient boosting libraries**: lightgbm, xgboost, scikit-learn
2. ✅ **Created script**: `scripts/train_ensemble_models.py`
3. ✅ **Implemented deterministic nonlinear models**:
   - LightGBM regressor with seed=0 (deterministic)
   - XGBoost regressor with seed=0 (deterministic)
   - Logistic regression baseline for comparison
4. ✅ **Implemented ensemble variants**:
   - Soft voting: 40% LightGBM + 40% XGBoost + 20% Logistic
   - Stacking: K-fold cross-validation meta-learner (logistic regression)
5. ✅ **Ran walk-forward evaluation** on recent seasons (2022-2026)
6. ✅ **Generated report**: `data/reports/ensemble_nonlinear_results.md`

## Results Summary

### Overall Accuracy (Walk-Forward on Seasons 2022-2026)

| Model | Accuracy | Improvement |
|-------|----------|-------------|
| Logistic Baseline | 58.12% | - |
| LightGBM Solo | 56.12% | -2.00% |
| XGBoost Solo | 56.14% | -1.98% |
| Soft Voting Ensemble | 56.57% | -1.55% |
| **Stacking Ensemble** | **58.31%** | **+0.19%** |

### Per-Season Performance

| Season | Logistic | LGB | XGB | Voting | Stacking |
|--------|----------|-----|-----|--------|----------|
| 2022-23 | 57.85% | 55.72% | 55.34% | 56.71% | 59.07% |
| 2023-24 | 58.77% | 57.01% | 55.03% | 56.86% | 58.46% |
| 2024-25 | 58.99% | 57.47% | 58.77% | 58.77% | 59.30% |
| 2025-26 | 56.86% | 54.27% | 55.41% | 53.96% | 56.40% |

## Ensemble Strategy Details

### LightGBM Configuration
- **Objective**: binary:logistic
- **Learning Rate**: 0.05 (conservative)
- **Num Leaves**: 127 (aggressive)
- **Max Depth**: 10
- **Iterations**: 1,000
- **Regularization**: L1=0.01, L2=0.01
- **Seed**: 0 (deterministic)

### XGBoost Configuration
- **Objective**: binary:logistic
- **Learning Rate (eta)**: 0.05
- **Max Depth**: 8
- **Iterations**: 1,000
- **Regularization**: L1=0.01, L2=0.01
- **Subsample**: 0.9
- **Column Sample**: 0.9
- **Seed**: 0 (deterministic)

### Stacking Ensemble
- **Fold Strategy**: 5-fold cross-validation
- **Meta-Learner**: Logistic Regression (L-BFGS)
- **Training Data**: Out-of-fold predictions from base models
- **Advantages**:
  - Prevents overfitting by using OOS predictions
  - Learns optimal weight combination
  - Generalizes better than simple voting

## Key Findings

1. **Logistic Regression Strength**: The logistic regression baseline (58.12%) is already quite strong for this feature set, making it difficult for tree-based models to improve upon.

2. **Stacking Outperforms Voting**: The k-fold stacking ensemble (+0.19%) beats simple soft voting (-1.55%), demonstrating the value of learning optimal weight combinations.

3. **Consistency by Season**: Stacking shows strong performance in most seasons, particularly 2022-23 (59.07%) and 2024-25 (59.30%).

4. **Individual Tree Models Underperform**: Both LightGBM and XGBoost alone perform worse than logistic regression, likely because the linear separability is already captured by the hand-engineered features.

## Path to 61% Target

To reach the 61% target, consider:
1. **Feature Engineering**: Create interaction terms that tree models can better exploit
2. **Ensemble Diversity**: Include other model types (neural networks, gradient boosting variants)
3. **Hyperparameter Tuning**: Use automated tuning (Bayesian optimization, random search)
4. **Model Blending**: Combine multiple ensemble approaches with learned weights
5. **Feature Scaling**: Ensure proper preprocessing for all model types
6. **Cross-Validation**: Use nested cross-validation for more reliable meta-learner training

## Files Generated

1. **Script**: `scripts/train_ensemble_models.py`
   - Runnable with: `python scripts/train_ensemble_models.py`
   - Performs deterministic walk-forward evaluation
   - Generates results report

2. **Report**: `data/reports/ensemble_nonlinear_results.md`
   - Overall accuracy summary
   - Per-season breakdown
   - Ensemble variant analysis

## Reproducibility

The implementation is fully deterministic with:
- Fixed random seeds (seed=0) for LightGBM and XGBoost
- Deterministic sklearn models (random_state=0)
- Sorted feature lists and reproducible walk-forward splits
- Consistent k-fold cross-validation seeds

Running the script multiple times will produce identical results.
