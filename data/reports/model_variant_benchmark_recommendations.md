# Model Variant Benchmark & Next Experiments

Date: 2026-08-03

## 1) Variant performance summary

### Overall (current 3-season walk-forward window: 2023-2024 to 2025-2026, n=3,936 per model)
| Model variant | Accuracy | Log loss | Brier | Notes |
|---|---:|---:|---:|---|
| logistic_engineered | 0.5950 | 0.6554 | 0.2322 | Best in current experiment |
| elo_form_tuned | 0.5671 | 0.6844 | 0.2453 | Weaker across all metrics |
| weighted_calibrated | 0.5460 | 0.6862 | 0.2465 | Calibration method hurt ranking quality |

Key deltas vs logistic_engineered (overall):
- elo_form_tuned: accuracy -0.0279, logloss +0.0290, brier +0.0131
- weighted_calibrated: accuracy -0.0490, logloss +0.0308, brier +0.0143

### By season (accuracy / logloss / brier)
| Season | logistic_engineered | elo_form_tuned | weighted_calibrated | baseline_elo_form_blend | improved_roster_aware |
|---|---|---|---|---|---|
| 2023-2024 | 0.6128 / 0.6501 / 0.2293 | 0.5877 / 0.6746 / 0.2405 | 0.5503 / 0.6836 / 0.2452 | 0.5854 / 0.6894 / 0.2464 | 0.6174 / 0.6497 / 0.2288 |
| 2024-2025 | 0.6082 / 0.6458 / 0.2280 | 0.5777 / 0.6777 / 0.2422 | 0.5549 / 0.6806 / 0.2439 | 0.5655 / 0.6883 / 0.2465 | 0.6067 / 0.6447 / 0.2276 |
| 2025-2026 | 0.5640 / 0.6702 / 0.2394 | 0.5358 / 0.7008 / 0.2533 | 0.5328 / 0.6944 / 0.2505 | 0.5358 / 0.7166 / 0.2597 | 0.5617 / 0.6715 / 0.2400 |

Observations:
- logistic_engineered and improved_roster_aware are effectively tied on the common 2023-2026 window (accuracy ~0.595).
- weighted_calibrated underperforms in every season and metric.
- All variants degrade materially in 2025-2026.

## 2) Overfit vs regime-shift diagnosis

Evidence points more to **data-regime shift** than pure model overfit:
1. Broad 2025-2026 drop across every variant (including deterministic baseline):
   - logistic_engineered: -0.0465 vs prior-2-season mean
   - elo_form_tuned: -0.0469
   - improved_roster_aware: -0.0503
   - baseline: -0.0396
2. Calibration drift in 2025-2026 for logistic_engineered:
   - mean confidence 0.606 vs realized accuracy 0.564 (overconfidence)
   - ECE(10 bins) rises to 0.0467 from ~0.03 in prior seasons.

Possible secondary overfit signal:
- Fold-specific hyperparameters vary materially (especially regularization), so some tuning may be season-specific; however the synchronized decline across models suggests regime change is dominant.

## 3) Ranked next experiments (expected value vs effort)

### E1. Time-decayed training + recency-weighted objective (High value, Low-Medium effort)
- Change: In logistic training, exponentially down-weight older seasons; tune decay half-life.
- Why: Directly targets 2025-2026 regime drift.
- Acceptance criteria:
  1) +0.007 absolute accuracy on 2025-2026 vs current logistic (>=0.5710).
  2) No worse than -0.002 absolute accuracy on combined 2023-2026.
  3) 2025-2026 logloss improves by >=0.010.

### E2. Season-aware calibration (isotonic + Platt, per fold; select by validation NLL) (High value, Medium effort)
- Change: Replace current weighted calibration with fold-time-safe isotonic/Platt comparison.
- Why: Current weighted calibration is consistently worse; miscalibration worsens in 2025-2026.
- Acceptance criteria:
  1) Improve ECE(10) on 2025-2026 by >=20% (<=0.0374).
  2) Do not reduce 2025-2026 accuracy.
  3) Improve 2025-2026 logloss by >=0.008.

### E3. Gradient-boosted trees with monotonic/interaction constraints (High value, Medium effort)
- Change: Train LightGBM/XGBoost on same walk-forward folds; tune with time-split CV.
- Why: Nonlinear interactions likely missed by linear logistic.
- Acceptance criteria:
  1) +0.006 absolute overall accuracy vs logistic on 2023-2026.
  2) Logloss <=0.648 on 2023-2026.
  3) 2025-2026 accuracy >=0.570.

### E4. Two-model blend: logistic_engineered + improved_roster_aware (Medium-High value, Low effort)
- Change: Blend probabilities (static and fold-learned weights).
- Why: Near-tied leaders may have complementary errors.
- Acceptance criteria:
  1) Accuracy gain >=0.004 vs best single model on 2023-2026.
  2) Logloss gain >=0.005.
  3) No season with accuracy drop >0.003 versus best single model for that season.

### E5. Confidence-aware decision policy (abstain/size by confidence) (Medium value, Low effort)
- Change: Evaluate thresholds on max(home/away prob): 0.55/0.60/0.65/0.70.
- Why: Current logistic already shows 0.682 accuracy at >=0.60 confidence (44.8% coverage).
- Acceptance criteria:
  1) At >=0.60 threshold: maintain coverage >=40% and accuracy >=0.67.
  2) At >=0.65 threshold: coverage >=25% and accuracy >=0.72.
  3) Improve thresholded logloss vs unthresholded by >=0.03.

### E6. Regime-gated ensemble (season-phase classifier + specialist models) (Medium value, Medium-High effort)
- Change: Train gate using pregame context (early-season, back-to-back intensity, roster volatility) to route between linear and tree specialists.
- Why: Explicitly handles shifting dynamics instead of single global mapping.
- Acceptance criteria:
  1) +0.008 accuracy on 2025-2026.
  2) +0.004 accuracy overall 2023-2026.
  3) Brier <=0.230 overall.

### E7. Feature refresh focused on roster volatility and goalie uncertainty (Medium value, Medium effort)
- Change: Add recent lineup churn, travel/rest compression, probable-goalie reliability indicators.
- Why: Likely regime-sensitive drivers behind latest-season drop.
- Acceptance criteria:
  1) Feature-augmented logistic improves 2025-2026 logloss by >=0.010.
  2) Overall accuracy gain >=0.004.
  3) Calibration gap (mean confidence - realized accuracy) in 2025-2026 reduced by >=30%.

## 4) Recommended execution order
1. E1 (fastest likely gain against regime shift)
2. E2 (repair calibration degradation)
3. E4 (cheap upside from complementary models)
4. E3 (larger modeling jump)
5. E5 (operational policy layer)
6. E7 then E6 (higher complexity follow-ons)

## Sources
- data\processed\walk_forward_experiment_summary.json
- data\processed\walk_forward_experiment_metrics_overall.csv
- data\processed\walk_forward_experiment_metrics_by_season.csv
- data\processed\walk_forward_selected_logistic_engineered_summary.json
- data\processed\last5seasons_evaluation_summary.json
- data\processed\improved_roster_aware_evaluation_summary.json
- data\reports\improved_learning_cycle_results.md
- data\reports\improved_roster_aware_evaluation_report.md
- data\reports\last5seasons_evaluation_report.md
