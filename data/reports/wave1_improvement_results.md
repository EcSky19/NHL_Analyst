# Wave-1 Improvement Results

## Selected winner (Wave-1)
- **Variant:** `hybrid_exponential + logistic_engineered`
- **Selection rule:** maximize accuracy (tie-breakers: min log loss, min brier score, model_id ascending)
- **Games evaluated:** 3,936

## Overall metrics (selected variant)
- **Accuracy:** 0.597561
- **Log loss:** 0.655001
- **Brier score:** 0.23206

## Accuracy deltas
- **vs baseline (0.578811):** +0.018750 (+1.8750 percentage points)
- **vs previous best roster-aware (0.597180):** +0.000381 (+0.0381 percentage points)

## Per-season accuracy
- **2023-2024:** 0.612805 (1,312 games)
- **2024-2025:** 0.612043 (1,312 games)
- **2025-2026:** 0.567835 (1,312 games)

## Conclusion
Wave-1 **does improve SOTA** in this repository: the selected winner reaches **0.597561** accuracy, which is above both the baseline and the prior best roster-aware benchmark.
