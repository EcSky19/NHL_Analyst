# Next Accuracy Actions (Ranked) — Beyond Wave-1 Best

Date: 2026-08-03  
Baseline to beat: Wave-1 selected variant (`logistic_engineered`, `hybrid_exponential`) accuracy **0.597561** on 3,936 games (`data\processed\quickwin_wave1\wave1_selected_variant_summary.json`).

## 1) Expand recency-weight sweep + season-aware selection (Top priority)
- **Why this should lift accuracy:** Wave-1 already showed recency helps (`0.597561` vs `0.595020` no-recency); deeper tuning should improve 2025-2026 drift handling.
- **Expected lift:** **+0.10 to +0.35 pp** overall.
- **Effort/complexity:** **Low–Medium**
- **Exact scripts/tables to change:**
  - `scripts\run_walk_forward_experiments.py` (add grid over `season_half_life`, `game_half_life`, `min_weight`, optional season-specific selector).
  - `scripts\train_roster_aware_model.py` (if mirrored weighting path is needed).
  - Artifacts: `data\processed\walk_forward_experiment_summary.json`, `data\processed\quickwin_wave1\wave1_variant_comparison.csv`.
- **Acceptance criteria:**
  - At least one tuned variant reaches accuracy **>= 0.5985** with no log-loss regression >0.003 vs current wave-1 best.

## 2) Add fold-safe blend with improved roster-aware signal
- **Why this should lift accuracy:** `improved_roster_aware` (0.5972) and wave-1 logistic (0.597561) are near-tied and likely have complementary errors.
- **Expected lift:** **+0.15 to +0.45 pp** overall.
- **Effort/complexity:** **Medium**
- **Exact scripts/tables to change:**
  - `scripts\run_walk_forward_experiments.py` (add blend variants using fold-safe out-of-sample probabilities).
  - Inputs: `data\processed\roster_aware_walk_forward_predictions.csv`, wave-forward prediction outputs.
  - Outputs: `data\processed\quickwin_wave1\wave1_variant_comparison.csv`, selected summary JSON/CSV files.
- **Acceptance criteria:**
  - New blend variant accuracy **>= 0.5990**, and by-season 2025-2026 accuracy not worse than current best by >0.002.

## 3) Upgrade goalie-starter fidelity (true confirmed starter + quality delta)
- **Why this should lift accuracy:** Audit found no true pregame confirmed starter signal; goalie quality is high-impact in close games.
- **Expected lift:** **+0.30 to +0.90 pp** overall.
- **Effort/complexity:** **Medium**
- **Exact scripts/tables to change:**
  - `scripts\ingest_last5_rosters.py` (store starter-confidence/state features).
  - `scripts\build_last5_backtest_features_roster.py` (add starter-specific pregame columns + deltas).
  - `scripts\train_roster_aware_model.py`, `scripts\run_walk_forward_experiments.py`.
  - Tables: `historical_game_rosters`, `roster_team_pregame_features_last5`, `backtest_features_last5_roster`.
- **Acceptance criteria:**
  - New goalie starter features >=95% populated in scored rows and produce **>= +0.20 pp** lift in full walk-forward evaluation.

## 4) Replace inferred injury proxy with official status + role-weighted impact
- **Why this should lift accuracy:** Current injury feature is inferred/noisy and likely drifting; role-aware availability should reduce matchup misses.
- **Expected lift:** **+0.20 to +0.70 pp** overall.
- **Effort/complexity:** **Medium–High**
- **Exact scripts/tables to change:**
  - `scripts\ingest_last5_rosters.py` (ingest official OUT/IR/day-to-day tags when available).
  - `scripts\build_last5_backtest_features_roster.py` (derive role-weighted injury features).
  - `scripts\train_roster_aware_model.py`.
  - Tables: `historical_game_rosters`, `roster_player_pregame_stats_last5`, `roster_team_pregame_features_last5`, `backtest_features_last5_roster`.
- **Acceptance criteria:**
  - Injury features coverage >=95% with stable season distribution and **>= +0.15 pp** lift over pre-change retrain baseline.

## 5) Add special-teams feature family (PP/PK/net ST strength)
- **Why this should lift accuracy:** Feature audit identified PP/PK as missing high-value matchup signal, especially for upset-prone contexts.
- **Expected lift:** **+0.20 to +0.60 pp** overall.
- **Effort/complexity:** **Medium**
- **Exact scripts/tables to change:**
  - `scripts\build_last5_backtest_features_roster.py` (new rolling PP%, PK%, net special-teams deltas).
  - `scripts\train_roster_aware_model.py`, `scripts\run_walk_forward_experiments.py`.
  - Table/file: `backtest_features_last5_roster`, `data\processed\backtest_features_last5_roster.csv`.
- **Acceptance criteria:**
  - Added ST columns have >=98% coverage and improve accuracy by **>= +0.10 pp** or improve both log loss (>=0.004) and Brier (>=0.002).

## 6) Add travel/circadian burden features for away-pick weakness
- **Why this should lift accuracy:** Error slicing shows away contexts underperform; current features only capture rest/B2B, not travel load/time-zone shifts.
- **Expected lift:** **+0.10 to +0.45 pp** overall.
- **Effort/complexity:** **Medium**
- **Exact scripts/tables to change:**
  - `scripts\build_matchup_context_features.py` (distance/time-zone/nights-in-city).
  - `scripts\build_last5_backtest_features_roster.py` (join travel features into final rows).
  - `scripts\train_roster_aware_model.py`.
  - Tables/files: `backtest_features_last5`, `backtest_features_last5_roster`, `data\processed\backtest_features_last5_roster.csv`.
- **Acceptance criteria:**
  - Away-pick accuracy improves by **>= +0.30 pp** and overall accuracy by **>= +0.10 pp** on comparable walk-forward window.

## 7) Add team/opponent residual interaction features for concentrated miss pockets
- **Why this should lift accuracy:** Repeated miss concentration (e.g., ANA picks, picks against CAR) suggests systematic matchup residuals not captured by global coefficients.
- **Expected lift:** **+0.10 to +0.35 pp** overall.
- **Effort/complexity:** **Low–Medium**
- **Exact scripts/tables to change:**
  - `scripts\train_roster_aware_model.py` (team/opponent interaction terms with regularization).
  - `scripts\run_walk_forward_experiments.py` (evaluate interaction-enabled model IDs).
  - Input/output tables/files: `backtest_features_last5_roster`, `data\processed\quickwin_wave1\wave1_variant_comparison.csv`.
- **Acceptance criteria:**
  - Worst-team/opponent slice error rates improve by >=1.5 pp without degrading global log loss by >0.003.

---

## Recommended execution order
1. Actions **1 → 2** (fastest chance to clear 0.600).  
2. Then **3 → 5 → 6** (highest structural feature lifts).  
3. Finish with **7** (targeted residual cleanup).

## Promotion gate (for any candidate)
- Promote only if:
  - Overall accuracy **> 0.597561** (strictly beats wave-1 best), and
  - 2025-2026 accuracy does not drop by >0.002 vs current best seasonal result, and
  - Log loss does not worsen by >0.003.
