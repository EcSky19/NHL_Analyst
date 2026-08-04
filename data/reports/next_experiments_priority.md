# Next Experiments Priority (Post-Wave1 SOTA)

Date: 2026-08-04  
Target to beat: Wave1 SOTA accuracy **0.597561** (`data\reports\wave1_improvement_results.md`)

## Ranked experiments (highest expected value first)

| Rank | Experiment | Rationale | Expected lift (accuracy, pp) | Effort | Exact scripts/tables to change | Go / No-Go acceptance criteria |
|---|---|---|---|---|---|---|
| 1 | Recency-weighted retraining + regime selector retune | All variants degrade in 2025-26; strongest low-effort lever for regime shift. | **+0.2 to +0.8** overall; **+0.4 to +1.0** on 2025-26 | Low-Med | **Scripts:** `scripts\train_roster_aware_model.py`, `scripts\run_walk_forward_experiments.py`  **Tables/artifacts:** `data\processed\walk_forward_experiment_recency_*.csv/json`, `data\processed\walk_forward_experiment_summary.json` | **Go:** overall >= **0.5985** and 2025-26 >= **0.5710**, with log loss not worse than +0.003. **No-Go:** < +0.002 overall in 2 consecutive retunes. |
| 2 | Fold-safe season-aware calibration (Platt vs isotonic) | 2025-26 overconfidence is material; prior weighted calibration underperformed. | **+0.0 to +0.4** overall; log loss improvement likely larger than accuracy | Med | **Scripts:** `scripts\run_walk_forward_experiments.py`  **Tables/artifacts:** `data\processed\walk_forward_experiment_metrics_overall.csv`, `data\processed\walk_forward_experiment_metrics_by_season.csv`, `data\processed\walk_forward_experiment_summary.json` | **Go:** 2025-26 log loss improves by >= **0.008** and accuracy does not decline; ECE improves >=20%. **No-Go:** any season accuracy drop >0.003 with no compensating log-loss gain. |
| 3 | OOS probability blend: `logistic_engineered` + `improved_roster_aware` | Near-tied leaders suggest complementary errors; cheapest path to >0.600. | **+0.2 to +0.6** overall | Low | **Scripts:** `scripts\run_walk_forward_experiments.py`  **Tables/artifacts:** `data\processed\walk_forward_selected_logistic_engineered_predictions.csv`, `data\processed\roster_aware_walk_forward_predictions.csv`, new blended outputs in `data\processed\walk_forward_experiment_*.csv/json` | **Go:** overall >= **0.5990** and no season drop >0.003 vs best single model. **No-Go:** gain <0.002 after static + fold-learned blend tests. |
| 4 | Nonlinear model variant on same folds (LightGBM/XGBoost) | Linear logistic may miss interaction structure in upset/away contexts. | **+0.3 to +0.9** overall | Med | **Scripts:** `scripts\run_walk_forward_experiments.py` (variant wiring), optional new trainer script if needed; keep same fold protocol.  **Tables/artifacts:** `data\processed\walk_forward_experiment_metrics_*.csv`, `data\processed\walk_forward_experiment_summary.json` | **Go:** overall >= **0.6000**, log loss <= **0.648**, and 2025-26 >= **0.570**. **No-Go:** fails to beat logistic by >=0.003 overall. |
| 5 | Confirmed starting-goalie fidelity + goalie quality differential | Audit flags missing true starter signal as highest-fidelity feature gap. | **+0.3 to +0.9** overall | Med | **Scripts:** `scripts\ingest_last5_rosters.py`, `scripts\build_last5_backtest_features_roster.py`, `scripts\train_roster_aware_model.py`  **Tables/artifacts:** `data\processed\backtest_features_last5_roster.csv`, `data\processed\roster_aware_feature_importance.csv`, `data\processed\roster_aware_walk_forward_predictions.csv` | **Go:** new goalie fields >=98% coverage on scored rows and >=+0.003 overall lift. **No-Go:** coverage <95% or net lift <+0.001 after fallback logic tuning. |
| 6 | Special-teams strength family (PP/PK/net ST) | Explicitly missing in audit; likely explains matchup variance not in current feature set. | **+0.2 to +0.6** overall | Med | **Scripts:** `scripts\build_last5_backtest_features_roster.py`, `scripts\train_roster_aware_model.py`  **Tables/artifacts:** `data\processed\backtest_features_last5_roster.csv`, `data\processed\roster_aware_feature_importance.csv` | **Go:** PP/PK/ST columns >=97% coverage and >=+0.0025 overall lift, especially in 0.50-0.60 confidence bucket. **No-Go:** high collinearity with no measurable lift. |
| 7 | Replace inferred injury proxy with official injury-status features | Current injury feature is proxy/noisy and may drift by season. | **+0.2 to +0.7** overall | Med-High | **Scripts:** `scripts\ingest_last5_rosters.py`, `scripts\build_last5_backtest_features_roster.py`, `scripts\train_roster_aware_model.py`  **Tables/artifacts:** `data\processed\backtest_features_last5_roster.csv`, `data\processed\roster_aware_walk_forward_predictions.csv` | **Go:** role-based injury features >=95% coverage, 2025-26 accuracy +>=0.003, and no overall log-loss regression >0.003. **No-Go:** unstable historical backfill or inconsistent season definitions. |

## Execution sequence
1. Ranks **1-3 first** (fastest loop, lowest engineering overhead, highest chance to clear 0.600 quickly).  
2. Then rank **4** (model-class jump) if still below target.  
3. Execute ranks **5-7** as feature-fidelity upgrades if model-only gains plateau.

## Promotion gate (final)
Promote only if all are true on comparable walk-forward window:
1. Overall accuracy **> 0.597561** (strict Wave1 SOTA beat), target **>= 0.600**.
2. 2025-2026 accuracy **>= 0.571**.
3. Log loss improves by **>= 0.005** vs current selected run.
