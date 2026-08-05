# Ensemble Nonlinear Models - Final Results

## Overall Accuracy

| Model | Accuracy |
|-------|----------|
| logistic | 0.5812 |
| lgb | 0.5612 |
| xgb | 0.5614 |
| voting | 0.5657 |
| stacking | 0.5831 |

## By Season

| Season | Logistic | LGB | XGB | Voting | Stacking |
|--------|----------|-----|-----|--------|----------|
| 20222023 | 0.5785 | 0.5572 | 0.5534 | 0.5671 | 0.5907 |
| 20232024 | 0.5877 | 0.5701 | 0.5503 | 0.5686 | 0.5846 |
| 20242025 | 0.5899 | 0.5747 | 0.5877 | 0.5877 | 0.5930 |
| 20252026 | 0.5686 | 0.5427 | 0.5541 | 0.5396 | 0.5640 |

## Ensemble Variants

### Soft Voting (40% LGB + 40% XGB + 20% Logistic)
- Accuracy: 0.5657
- Improvement: -0.0154

### Stacking (K-Fold Cross-Validation Meta-Learner)
- Accuracy: 0.5831
- Improvement: +0.0019

