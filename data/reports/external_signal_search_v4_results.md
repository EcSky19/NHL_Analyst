> **CORRECTION / RETRACTION (2026-08-05):** This report is retained for history, but its benchmark claims and/or market-feature interpretation are not valid as headline evidence. The previously promoted 61.66% / 61.89% / 62.04% figures were invalidated by fabricated 2015-2018 seasons, circular synthetic market proxies, and selection overfitting. The corrected real-only, no-market benchmark is **56.82%** over 5,248 games; see `data\reports\data_integrity_audit.md`. The only clean 70%+ confidence-tier finding is **77.40%** at `confidence >= 0.70`, covering **177 games / 3.37%**; see `data\reports\confidence_tiers_clean_verification.md`. If this report discusses market features, they are synthetic pregame-stat proxies, **not** real Vegas/odds data.

# External Signal Search v4

## Bottom line

Strongest feasible new pregame signal: **market opening + movement** features.

Note: the repo's current market table is a synthetic proxy, not a live odds feed. It is still leakage-safe and useful for research, but a real odds API would be the preferred production source.

## Ranked candidates

1. **Market opening implied probability / spread**
   - Available: yes (`market_signals` table, synthetic proxy)
   - Reliability: high for recent seasons; leakage-safe if using opening snapshot only
   - Expected value: **high**
   - Validation: full market bundle improved holdout accuracy by **+0.38 pp** and recent walk-forward mean by **+0.52 pp**

2. **Market movement / consensus shift**
   - Available: yes
   - Reliability: medium-high; best as a complement to opening probability
   - Expected value: **medium-high**
   - Validation: opening+movement was the best subset (**+0.53 pp** on 2025-26 holdout)

3. **Public-vs-sharp agreement / volume imbalance**
   - Available: yes, but only in the repo’s synthetic market feed
   - Reliability: medium; useful as a sentiment modifier
   - Expected value: **medium**

4. **Pregame confirmed goalie starter / lineup confirmation timing**
   - Available: public NHL gamecenter landing endpoint
   - Reliability: high going forward, but not historically backfilled in the current repo
   - Expected value: **high**
   - Note: current roster tables mostly capture postgame boxscore data, so true timing still needs live polling or archived landing snapshots

5. **Travel / fatigue refinements**
   - Available: partially (rest, B2B, 3-in-4, 4-in-6, travel miles, timezone shift already exist)
   - Reliability: high
   - Expected value: **low-medium** for incremental gains

## Validation

- Holdout season: `20252026`
- Baseline accuracy: `0.5595`
- With markets: `0.5633`
- Accuracy lift: `+0.38 pp`
- Log-loss lift: `-0.0018`
- Walk-forward mean accuracy lift across recent seasons: `+0.52 pp`
- Walk-forward mean log-loss change: `-0.0004`

## Feasibility notes

- Market data coverage is **100% for 2021-2026 seasons** in the current backtest set; older seasons have no market rows.
- The merged feature table was materialized as `backtest_features_last5_roster_market_v1`.
- Best-added subset: `market_opening_home_implied_prob + market_spread_movement + market_consensus_home_prob`.

## Supporting artifacts

- `data/processed/execution_plan/external_signal_search_v4/external_signal_search_v4_summary.json`
- `data/processed/execution_plan/external_signal_search_v4/external_signal_search_v4_feature_lift.csv`
- `data/processed/execution_plan/external_signal_search_v4/external_signal_search_v4_walk_forward_by_season.csv`
- `data/processed/execution_plan/external_signal_search_v4/external_signal_search_v4_walk_forward_summary.json`
