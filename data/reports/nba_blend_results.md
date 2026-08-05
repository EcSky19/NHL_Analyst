# NBA blend/stacking experiment

Date: 2026-08-05T23:30:55.948862+00:00

## Headline

The pre-registered blend **did not beat pure Elo** on the frozen 2023 holdout: logistic stacking reached **62.78%** accuracy on **1,174** games, Wilson 95% CI **59.97%-65.50%**, versus pure Elo at **62.95%**. The margin is **-0.17%**, which is inside the 2-3 point noise floor and is not strong evidence of a truly superior classifier.

## Non-negotiable holdout protocol

- The final holdout season was **2023**.
- All blend selection used only development predictions from seasons **2007-2022**.
- Candidate blends were evaluated with an expanding nested walk-forward meta-test: fit the blend on development seasons before the test season, then test seasons **2009-2022**.
- The selected configuration was written to `data\nba\nba_blend_config.json` before loading/scoring the 2023 holdout rows.
- The selected method was **logistic_stack**, chosen because it had the best nested-development accuracy among the blend candidates, with log loss as the tie-breaker.

## Approaches tried on development folds

All methods below used only two pre-existing out-of-sample probabilities: `elo_prob_home` and `model_prob_home`.

| Model | Games | Accuracy | Wilson 95% CI | Log loss | Brier |
|---|---:|---:|---:|---:|---:|
| always_home | 16,640 | 58.24% | 57.49%-58.99% | 0.6795 | 0.2432 |
| pure_elo | 16,640 | 65.97% | 65.24%-66.68% | 0.6144 | 0.2130 |
| nba_model | 16,640 | 66.42% | 65.70%-67.14% | 0.6123 | 0.2121 |
| prob_weight_logloss | 16,640 | 66.38% | 65.66%-67.10% | 0.6096 | 0.2110 |
| prob_weight_accuracy | 16,640 | 66.14% | 65.42%-66.86% | 0.6106 | 0.2115 |
| logit_weight_logloss | 16,640 | 66.42% | 65.70%-67.14% | 0.6095 | 0.2110 |
| logit_weight_accuracy | 16,640 | 66.24% | 65.52%-66.95% | 0.6101 | 0.2113 |
| logistic_stack | 16,640 | 66.46% | 65.74%-67.17% | 0.6096 | 0.2111 |
| logistic_stack_no_intercept | 16,640 | 66.39% | 65.67%-67.11% | 0.6095 | 0.2110 |

Interpretation: logistic stacking was the best nested-development accuracy candidate. Log-odds weighted blends improved log loss, but did not win the selection criterion.

## Frozen 2023 holdout result

| Model | Games | Accuracy | Wilson 95% CI | Log loss | Brier |
|---|---:|---:|---:|---:|---:|
| always_home | 1,174 | 58.43% | 55.59%-61.22% | 0.6789 | 0.2429 |
| pure_elo | 1,174 | 62.95% | 60.15%-65.66% | 0.6499 | 0.2280 |
| nba_model | 1,174 | 62.52% | 59.72%-65.25% | 0.6487 | 0.2285 |
| logistic_stack | 1,174 | 62.78% | 59.97%-65.50% | 0.6440 | 0.2261 |

The blend did not improve accuracy versus pure Elo on this holdout. It did improve log loss and Brier, so the combination appears to add probability-quality value without a defensible accuracy win.

## Final blend configuration

```json
{
  "selected_method": "logistic_stack",
  "final_fit_config": {
    "coef_logit_elo": 0.4747907957244573,
    "coef_logit_model": 0.48785484580948324,
    "intercept": 0.018867366975671356,
    "C": 1.0,
    "solver": "lbfgs",
    "fit_intercept": "True"
  },
  "input_columns": [
    "elo_prob_home",
    "model_prob_home"
  ]
}
```

No serving artifact was written because the selected blend did not beat Elo on accuracy.

## Calibration reliability table: final holdout

Bucket-weighted absolute calibration error is **3.48%** on the final holdout.

| Predicted bucket | Games | Avg predicted home win | Actual home win |
|---|---:|---:|---:|
| 0.0-0.1 | 0 | n/a | n/a |
| 0.1-0.2 | 2 | 18.47% | 0.00% |
| 0.2-0.3 | 50 | 26.65% | 36.00% |
| 0.3-0.4 | 123 | 35.59% | 37.40% |
| 0.4-0.5 | 242 | 45.58% | 49.17% |
| 0.5-0.6 | 294 | 55.10% | 58.50% |
| 0.6-0.7 | 240 | 64.75% | 68.75% |
| 0.7-0.8 | 161 | 74.29% | 72.05% |
| 0.8-0.9 | 62 | 83.28% | 80.65% |
| 0.9-1.0 | 0 | n/a | n/a |

Buckets include counts; small buckets should not be over-interpreted.

## What did not get refit

The prior frozen NBA model already includes `elo_prob_home`, Elo differences, rest, back-to-back, road-trip, rolling form, and opponent-strength features. This experiment therefore focused on the highest-value, lowest-leakage question: whether the existing model probability and pure Elo probability can be combined honestly. No injury feed or new per-game data source was available in the listed database tables, and no additional classifier family was tuned on the holdout.

## Candid verdict

This is a legitimate incremental probability-quality result, not proof that NBA Elo has been decisively beaten. The selected stack trailed Elo by **0.17%** on the frozen holdout while improving log loss/Brier; the small accuracy difference is inside sampling noise for 1,174 games.
