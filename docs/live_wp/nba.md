# NBA live win probability

Round 2 generated 2026-08-06 from `data/live_wp/nba_snapshots.db` by
`scripts/live_wp/train_nba.py`.

## Data and fixed split

- Harvested 500 completed NBA games, 239,153 labelled snapshots.
- Split is by whole game, not by snapshot, and was kept identical to round 1:
  - Train/model-selection pool: `season_start_year == 2023`, 250 games, 119,349 snapshots.
  - Final held-out test: `season_start_year == 2024`, 250 games, 119,804 snapshots.
  - Game id overlap: 0.
- Model selection used only a stratified game-level validation split carved from
  2023: 200 fit games / 50 validation games. The 2024 season was scored once
  after selecting the winner.

The serving artifact still uses only features produced by
`app.services.live_winprob.build_features`. The round-2 artifact feature list is
`margin`, `margin_scaled`, `frac_remaining`, and `is_overtime`.

## Round-2 validation experiments

Selection criterion: lowest validation log loss, with Brier as tie-breaker.

| approach | features | validation Brier | validation log loss | max calibration gap |
|---|---|---:|---:|---:|
| round-1 logistic regression | `margin`, `margin_scaled` | 0.137913 | 0.425276 | 0.1522 |
| polynomial logistic regression, degree 3 | all six frozen features | 0.139611 | 0.425676 | 0.1491 |
| spline logistic regression | core margin/time features | 0.138543 | 0.427120 | 0.1589 |
| **monotone histogram gradient boosting** | core margin/time features | 0.138831 | **0.422870** | 0.1545 |
| classical gradient boosting | core margin/time features | 0.139783 | 0.427094 | 0.1557 |

The monotone histogram gradient boosting model won on validation log loss. It
was then refit on all 2023 games and evaluated once on the 2024 holdout.

## Held-out 2024 test comparison

| predictor | n | Brier | log loss |
|---|---:|---:|---:|
| **round-2 selected model** | 119,804 | **0.167947** | **0.491963** |
| round-1 current artifact | 119,804 | 0.171201 | 0.507814 |
| analytic normal baseline reported in round 1 | 119,804 | 0.171684 | — |
| normal baseline recomputed by this script | 119,804 | 0.166073 | 0.508698 |
| ESPN published WP | 119,803 | 0.157319 | 0.462902 |
| leader baseline | 119,804 | 0.200021 | 0.600738 |
| constant 0.5 | 119,804 | 0.250000 | 0.693147 |

Honest summary: round 2 improves the round-1 artifact on both Brier and log
loss, so `models/live_wp/nba_live_wp.joblib` was overwritten. It still does not
beat ESPN's published curve. It also does not beat the recomputed normal
baseline on Brier, although it has materially better log loss than that normal
baseline.

## Calibration

Max calibration gap over deciles with at least 100 examples: 0.0656.

| bin | n | predicted | actual | gap |
|---|---:|---:|---:|---:|
| 0.0-0.1 | 6,915 | 0.0222 | 0.0068 | -0.0154 |
| 0.1-0.2 | 10,572 | 0.1805 | 0.2460 | 0.0656 |
| 0.2-0.3 | 8,275 | 0.2568 | 0.3193 | 0.0625 |
| 0.3-0.4 | 6,270 | 0.3425 | 0.3893 | 0.0468 |
| 0.4-0.5 | 9,648 | 0.4414 | 0.4899 | 0.0486 |
| 0.5-0.6 | 15,721 | 0.5476 | 0.5851 | 0.0375 |
| 0.6-0.7 | 22,509 | 0.6486 | 0.6851 | 0.0365 |
| 0.7-0.8 | 9,399 | 0.7494 | 0.7378 | -0.0115 |
| 0.8-0.9 | 14,665 | 0.8393 | 0.8653 | 0.0260 |
| 0.9-1.0 | 15,830 | 0.9861 | 0.9934 | 0.0073 |

## Phase breakdown

| regulation remaining | n | Brier | log loss |
|---|---:|---:|---:|
| 1.00-0.75 | 28,768 | 0.232184 | 0.659082 |
| 0.75-0.50 | 30,059 | 0.199930 | 0.583834 |
| 0.50-0.25 | 29,665 | 0.155939 | 0.466541 |
| 0.25-0.00 | 31,312 | 0.089604 | 0.274311 |

## Sanity checks

- Probability increases with home margin at 50% remaining: pass.
  - -20: 0.164274; -10: 0.196881; 0: 0.544303; +10: 0.817671; +20: 0.928386.
- Same +8 lead is worth more later: pass.
  - frac_remaining 0.8: 0.673305.
  - frac_remaining 0.2: 0.793167.
- Output stays strictly inside (0, 1): pass.
- Edge states are finite: pass.
  - tie at start: 0.542028; tie at end: 0.739611; +60 at end: 0.999965; -60 at end: 0.000074.
- Fresh-process serving check through
  `predict_home_win_prob(GameState(league='nba', margin=8, frac_remaining=0.2, period=4))`:
  available, probability 0.793167.
