# Current Accuracy State Snapshot (2026-08-03)

## Current best accuracy and benchmark deltas
- **Best latest variant (Wave-1 selected):** `hybrid_exponential + logistic_engineered` at **0.597561** accuracy (3,936 games), log loss **0.655001**, Brier **0.232060**.
- **Delta vs baseline (0.578811):** **+0.018750** (**+1.875 pp**).
- **Delta vs previous best roster-aware (0.597180):** **+0.000381** (**+0.038 pp**) on the 3,936-game comparable window.
- **Stability note:** full-window best in prior slice report is still `improved_roster_aware` at **0.5972** over 5,248 games; gains are currently narrow and context-sensitive.

## Biggest remaining failure slices
- **Season drift (largest):** 2025-2026 is worst at **56.17%** accuracy / **43.83%** error (1,312 games).
- **Low-confidence mass errors:** 0.50-0.55 bucket has **47.80%** error over **1,408** games (largest miss volume).
- **Away-pick weakness:** predicted-away accuracy **57.56%** vs predicted-home **61.14%**.
- **Opponent upset pocket:** picks against **CAR** fail **57.65%** of the time (85 games).

## Which recent changes helped most
1. **Hybrid recency weighting** was the most effective recent change: logistic_engineered improved from **0.595020** (`none`) to **0.597561** (`hybrid_exponential`) = **+0.002541** (+0.254 pp).
2. **Game exponential recency** also helped (to **0.596037**), but less than hybrid.
3. **Weighted-calibrated and isotonic variants hurt accuracy materially** (down to ~0.542-0.547), so calibration approach as implemented is not helping win-rate.

## Top 3 evidence-based bottlenecks now
1. **Regime drift into 2025-2026** (largest seasonal degradation vs earlier seasons and baseline-relative underperformance).
2. **Weak edge in near-coinflip games (0.50-0.60)**, which contain high volume and near-47% error.
3. **Context bias on away/upset scenarios** (lower away-pick accuracy and strong upset-prone opponents like CAR/FLA).

## Bottom line
Performance is at a **marginal new high (~59.76%)**, but only slightly above prior SOTA and still constrained by **2025-2026 drift**, **low-confidence miss density**, and **away/upset context errors**.
