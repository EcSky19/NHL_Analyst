# Accuracy Improvement Plan (Decision-Ready)

Date: 2026-08-03  
Scope: Improve out-of-sample NHL winner prediction accuracy using existing Sports_analytics pipeline.

## 1) Benchmark context

| Benchmark | Accuracy | Log loss | Brier | Games | Source |
|---|---:|---:|---:|---:|---|
| Baseline (last5 deterministic blend) | 0.5788 | 0.6883 | 0.2462 | 6560 | `last5seasons_evaluation_summary.json` |
| Previous best (improved_roster_aware) | 0.5972 | 0.6588 | 0.2334 | 5248 | `improved_roster_aware_evaluation_summary.json` |
| Current cycle best (logistic_engineered) | 0.5950 | 0.6554 | 0.2322 | 3936 | `walk_forward_selected_logistic_engineered_summary.json` |

Key context:
- Current cycle did **not** beat previous best accuracy (0.5950 vs 0.5972).
- 2025-2026 is the main failure regime (0.5617 roster-aware; 0.5640 logistic).
- Largest miss volume is low-confidence games (0.50-0.60 buckets).

## 2) Prioritized actions (top 8)

| Priority | Action | Why it helps | Implementation in this repo | Expected lift | Complexity | Risk |
|---|---|---|---|---|---|---|
| P1 | Add recency-weighted training (time decay) | Directly targets 2025-2026 regime drift seen across all variants | Update weighting in `scripts\train_roster_aware_model.py` and experiment wiring in `scripts\run_walk_forward_experiments.py`; emit deltas in `walk_forward_experiment_summary.json` | +0.4 to +1.0 pp on 2025-2026; +0.1 to +0.4 pp overall | Low-Med | Overfitting to latest season |
| P2 | Season-aware calibration (Platt vs isotonic, fold-safe) | Reduces overconfidence (notably 0.55-0.60 and 0.70+ buckets) and improves probability quality | Add fold-time-safe calibrator selection in `scripts\run_walk_forward_experiments.py`; write calibrated metrics into existing `walk_forward_*summary*.json/csv` artifacts | +0.0 to +0.4 pp accuracy; -0.008 to -0.020 log loss | Med | Accuracy can stagnate while calibration improves |
| P3 | Blend `logistic_engineered` + `improved_roster_aware` | Near-tied leaders likely have complementary errors | Add probability blend stage in `scripts\run_walk_forward_experiments.py`; persist blended predictions/summary alongside existing outputs | +0.2 to +0.6 pp overall | Low | Minimal gain if errors are highly correlated |
| P4 | Confidence-gated decision policy | Removes low-edge 0.50-0.60 picks that drive error concentration | Add threshold evaluation (0.55/0.60/0.65/0.70) using `data\processed\roster_aware_walk_forward_predictions.csv` and logistic predictions; publish threshold KPIs in report | +8 to +15 pp on acted subset accuracy (coverage tradeoff) | Low | Lower coverage; not a pure model lift |
| P5 | True pregame confirmed goalie starter features | Highest-fidelity missing signal from audit; current proxy is weak | Extend `scripts\ingest_last5_rosters.py` + `scripts\build_last5_backtest_features_roster.py` to add starter-confirmed flags and goalie quality differential columns; retrain via `train_roster_aware_model.py` | +0.3 to +0.9 pp | Med | External lineup signal availability/latency |
| P6 | Replace inferred injury proxy with official injury status features | Current injury feature is noisy proxy and likely drifting | Modify roster ingestion + feature build to include OUT/IR/day-to-day by role and projected TOI impact in `backtest_features_last5_roster.csv` | +0.2 to +0.7 pp | Med-High | Data consistency across seasons |
| P7 | Add special-teams strength family (PP/PK/net ST) | Missing matchup-critical variance identified in audit | Add PP/PK and net ST rolling features in `scripts\build_last5_backtest_features_roster.py`; include deltas in training matrix | +0.2 to +0.6 pp | Med | Collinearity with existing team-strength terms |
| P8 | Add travel/fatigue + coverage-quality refinements | Addresses away-pick asymmetry and coarse coverage-delta saturation | Add distance/time-zone/rest compression + staleness confidence features in feature builder; down-weight stale/low-fidelity rows | +0.1 to +0.5 pp | Med | Feature noise if schedule joins are wrong |

## 3) Staged execution roadmap

### Quick wins (<=1 day)
1. P1 recency weighting experiment.
2. P2 calibration experiment (Platt vs isotonic, fold-safe).
3. P3 two-model blend.
4. P4 confidence-threshold policy report.

### Mid-term (2-5 days)
1. P5 confirmed goalie starter feature integration.
2. P7 special-teams feature family.
3. P8 travel/fatigue and staleness-confidence features.

### Longer-term (>5 days)
1. P6 official injury pipeline replacement and validation across seasons.
2. If plateau persists: add regime-gated ensemble/tree variant within `run_walk_forward_experiments.py` using same walk-forward evaluation contracts.

## 4) Success criteria and stopping rules

### Success criteria
Ship the first model/policy package that satisfies all:
1. Overall accuracy >= **0.600** on the comparable evaluation window.
2. 2025-2026 accuracy >= **0.571**.
3. Log loss improvement >= **0.008** vs current cycle best.
4. No season drops by more than **0.003** vs that season’s best existing benchmark.

### Stopping/rollback rules
- Stop a feature line if two consecutive iterations deliver <+0.002 overall accuracy lift.
- Roll back any candidate that worsens log loss by >0.005 or increases calibration error materially.
- Do not promote features with <95% coverage or severe saturation (e.g., >85% zero-delta) unless paired with demonstrable lift.
- Freeze and publish when criteria are met; otherwise continue by priority order (P1→P8).
