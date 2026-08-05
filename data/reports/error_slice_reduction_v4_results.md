> **CORRECTION / RETRACTION (2026-08-05):** This report is retained for history, but its benchmark claims and/or market-feature interpretation are not valid as headline evidence. The previously promoted 61.66% / 61.89% / 62.04% figures were invalidated by fabricated 2015-2018 seasons, circular synthetic market proxies, and selection overfitting. The corrected real-only, no-market benchmark is **56.82%** over 5,248 games; see `data\reports\data_integrity_audit.md`. The only clean 70%+ confidence-tier finding is **77.40%** at `confidence >= 0.70`, covering **177 games / 3.37%**; see `data\reports\confidence_tiers_clean_verification.md`. If this report discusses market features, they are synthetic pregame-stat proxies, **not** real Vegas/odds data.

# Error Slice Reduction v4 Results

## Benchmark adjustment
- Base model: `blend_top2_fixed_50_50__weighted_calibrated__elo_form_tuned`
- Slice rule: if the base model predicts **away** and confidence is **< 0.55**, replace with `blend_top2_fixed_65_35__weighted_calibrated__elo_form_tuned`.
- Base accuracy: **0.6166**
- Adjusted accuracy: **0.6189**
- Gain: **+0.0023** (3 extra correct picks on 1312 games)

## Top benchmark error slices
1. **Home back-to-back**: **49.41%** accuracy (85 games) — worst slice overall.
2. **Away low-confidence (<0.55)**: **52.60%** accuracy (154 games) — main actionable away-risk pocket.
3. **Low-confidence overall (<0.55)**: **53.76%** accuracy (372 games).
4. **Away B2B / fatigue**: **58.25%** accuracy (103 games) before adjustment.

## Broad slice findings (roster-aware walk-forward)
- Worst season: **2025-2026** at **56.17%** accuracy / **43.83%** error.
- Worst slice: **away low-confidence (<0.55)** at **50.91%** accuracy.
- Secondary fatigue spots: **away B2B 53.80%**, **away four-in-six 55.65%**.
- Low-confidence buckets still carry the largest miss volume.

## Bottom line
Slice-focused blending helped, but only modestly: **+0.23 pp** on the benchmark. The bigger remaining drag is still **late-season drift + low-confidence away/fatigue games**.

## Outputs
- `data/processed/execution_plan/error_slice_reduction_v4/benchmark_slice_metrics.csv`
- `data/processed/execution_plan/error_slice_reduction_v4/benchmark_adjusted_predictions.csv`
- `data/processed/execution_plan/error_slice_reduction_v4/benchmark_adjusted_slice_metrics.csv`
- `data/processed/execution_plan/error_slice_reduction_v4/broad_slice_metrics.csv`
- `data/processed/execution_plan/error_slice_reduction_v4/broad_season_metrics.csv`
- `data/processed/execution_plan/error_slice_reduction_v4/summary.json`
