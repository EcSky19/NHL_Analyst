# Wave 2 Results (Quick Win)

## Selected winner
- **Variant:** `single + blend_logistic_weighted_70_30`
- **Selection rule:** highest accuracy, then lower log_loss, then lower brier_score
- **Recency settings (selected):**
  - selector_mode: `season_regime`
  - mode: `hybrid_exponential`
  - season_half_life: `0.85`
  - game_half_life: `552.5`
  - min_weight: `0.09000000000000001`

## Overall metrics (3936 games)
- **Accuracy:** `0.590447`
- **Log loss:** `0.662053`
- **Brier score:** `0.23512`

## Accuracy delta vs references
- vs baseline (`0.578811`): **`+0.011636`**
- vs previous best roster-aware (`0.597180`): **`-0.006733`**
- vs wave1 best (`0.597561`): **`-0.007114`**

## Per-season accuracy
- `2023-2024`: `0.606707` (1312 games)
- `2024-2025`: `0.603659` (1312 games)
- `2025-2026`: `0.560976` (1312 games)

## Conclusion
Wave 2 improves over the baseline, but **does not beat** the previous best roster-aware model or the wave1 best. Therefore, wave 2 **did not set a new SOTA** on accuracy.
