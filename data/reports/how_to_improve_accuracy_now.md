# How to Improve Accuracy Now (Practical Guide)

## Current performance context
Current best is **59.76% accuracy** (Wave-1 winner: `logistic_engineered + hybrid_exponential`, n=3,936; log loss 0.6550, Brier 0.2321). Gains over prior best are small, and misses are concentrated in **2025-2026 drift** (56.78% in wave-1 artifacts / 56.17% in broader slice), **0.50-0.55 confidence games**, and **away/upset contexts**.

## Top actionable next steps (implementable now)
1. **Run a wider recency-weight sweep + season-aware selector** in `scripts\run_walk_forward_experiments.py`.
2. **Add fold-safe blend variants** combining wave-1 logistic and `improved_roster_aware` OOS predictions in `scripts\run_walk_forward_experiments.py`.
3. **Upgrade goalie starter fidelity** (confirmed starter state + quality deltas) via `scripts\ingest_last5_rosters.py` and `scripts\build_last5_backtest_features_roster.py`.
4. **Add special-teams features** (rolling PP%, PK%, net ST deltas) in `scripts\build_last5_backtest_features_roster.py`.
5. **Add travel/circadian burden features** (distance, time-zone shift, nights-in-city) in `scripts\build_matchup_context_features.py`, then join into roster backtest features.
6. **Add team-opponent interaction terms** (regularized residual matchup effects) in `scripts\train_roster_aware_model.py`.

## What to do first this week vs next
### This week (fastest lift to >60%)
- Steps **1-2** first (lowest effort, quickest rerun loop).
- Then step **6** to reduce concentrated miss pockets with minimal pipeline changes.

### Next (structural feature lift)
- Steps **3-5** (data/feature engineering work that targets drift and away-game weakness).

## Success thresholds (use these to judge progress)
- **Promotion gate (must pass all):**
  - Accuracy **> 0.597561** (strictly beats wave-1 best).
  - 2025-2026 accuracy does **not** drop by more than **0.002** vs current best.
  - Log loss does **not** worsen by more than **0.003**.
- **Interim targets by workstream:**
  - Recency sweep finds a variant at **>= 0.5985**.
  - Blend variant reaches **>= 0.5990**.
  - Away-pick accuracy improves by **>= 0.30 pp**.
  - New goalie/ST/travel features achieve **>=95-98% coverage** and at least **+0.10 to +0.20 pp** lift in comparable walk-forward runs.
