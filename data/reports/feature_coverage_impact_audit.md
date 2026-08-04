# Feature Coverage & Data Quality Impact Audit

Date: 2026-08-03  
Scope: `backtest_features_last5_roster`, roster feature generation scripts, model importance/evaluation artifacts.

## 1) Coverage/missingness for high-impact feature families

Source files:  
- `data\processed\backtest_features_last5_roster.csv` (6,560 rows)  
- `data\processed\roster_aware_feature_importance.csv`  
- `data\processed\roster_aware_walk_forward_predictions.csv` (5,248 scored games)

Top weighted features (mean abs weight):
1. `delta_roster_games_covered` (0.224)
2. `delta_roster_coverage_pct` (0.187)
3. `delta_season_goal_diff_pg` (0.178)
4. `delta_season_points_pct` (0.125)
5. `home_back_to_back` (0.086)

Coverage quality summary (prediction window):
- **Roster coverage fields**: 100% non-null, but low variance in deltas:
  - `delta_roster_coverage_pct == 0` in **91.39%** of games
  - `delta_roster_games_covered == 0` in **81.48%** of games
- **Goalie fields**:
  - home goalie save% coverage: **99.83%** (9 missing in scored set)
  - away goalie save% coverage: **99.54%** (24 missing in scored set)
- **Skater form/two-way**: ~99.7%+ coverage
- **Lineup continuity/stability**: ~99.5%+ coverage
- **Injury + “confirmed starters”**:
  - 100% populated, but `confirmed_starters_count` is almost constant (mostly 19; mean ~19.05)

Data freshness (`game_date - roster_source_stats_through_date`):
- median lag: 2 days (home/away)
- 95th percentile lag: 4 days
- long-tail staleness up to **183-185 days**

## 2) Coverage quality vs prediction accuracy

Overall roster-aware accuracy: **0.5972**.

Observed relationships:
- Low min coverage (<0.9) is rare (35/5,248 games) and underperforms full-coverage games.
- Missing away goalie save% rows show lower accuracy (0.417 on 24 games vs 0.598 when present; small sample).
- Season-level decline in 2025-26 (accuracy 0.5617) does **not** coincide with a drop in roster coverage %, suggesting model suppression is not primarily null-rate driven.

Important caveat:
- `delta_roster_coverage_pct` and `delta_roster_games_covered` rank as strongest signals while being near-zero in most games. This pattern indicates high leverage from a small minority of rows (potential instability/overfit risk).

## 3) Highest-value feature gaps likely suppressing accuracy

1. **No true confirmed starting-goalie signal**
   - Current logic falls back to active-goalie aggregates unless `lineup_role == goalie_starter` is available.
   - Missing explicit pregame starter confirmation likely weakens goalie signal quality, especially close-moneyline games.

2. **Injury feature is inferred proxy, not real injury feed**
   - `pregame_injury_count` is derived from “expected core absent,” not official injury/availability status.
   - Rising average injury counts by season suggest possible drift/noise in proxy behavior.

3. **No special-teams strength family (PP/PK, net special teams)**
   - No PP/PK/power-play/penalty-kill columns in model feature tables.
   - Likely leaves matchup-critical variance unexplained.

4. **No travel/circadian fatigue effects beyond rest/back-to-back**
   - No distance/time-zone/travel-load features detected.
   - Likely hurts out-of-sample robustness for schedule-context edge cases.

5. **Roster coverage deltas are too coarse and mostly tied**
   - Existing coverage metrics saturate (near-identical home/away values in most games), limiting discrimination.

## 4) Prioritized recommendations (impact vs complexity)

1. **Add pregame confirmed goalie starter + goalie quality differential**  
   - Expected impact: **High** (directional + accuracy, +calibration)  
   - Complexity: **Medium** (new ingestion + join + fallback logic)

2. **Replace inferred injuries with official injury report features** (OUT/IR/day-to-day by role, projected TOI impact)  
   - Expected impact: **High**  
   - Complexity: **Medium-High**

3. **Add special-teams unit strength** (team PP%, PK%, xGF/60-xGA/60 special teams, top-unit availability)  
   - Expected impact: **Medium-High**  
   - Complexity: **Medium**

4. **Add travel burden features** (distance, timezone shift, nights-in-city, east/west penalty)  
   - Expected impact: **Medium**  
   - Complexity: **Medium**

5. **Refine coverage quality features** (staleness-aware confidence, role-weighted coverage, goalie-specific coverage completeness)  
   - Expected impact: **Medium**  
   - Complexity: **Low-Medium**

## 5) Implementation notes from scripts

- `scripts\build_last5_backtest_features_roster.py` sets:
  - `pregame_injury_count` from inferred missing core players
  - `pregame_confirmed_starters_count` from active row count (not true public pregame confirmations)
- `scripts\train_roster_aware_model.py` derives and consumes `delta_roster_coverage_pct` and `delta_roster_games_covered`, which currently have low variance but large learned weights.

---
Bottom line: raw missingness is already low; the larger accuracy limiter appears to be **feature fidelity and missing feature families** (true goalie confirmation, real injuries, special teams, travel context), plus over-reliance on coarse coverage deltas.
