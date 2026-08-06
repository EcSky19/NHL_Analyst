# NBA live win probability

Late-game calibration experiment generated 2026-08-06 from
`data/live_wp/nba_snapshots.db` by `scripts/live_wp/train_nba.py`.

## Data and fixed split

- Harvested 500 completed NBA games, 239,153 labelled snapshots.
- Split is by whole game, not by snapshot:
  - Train/model-selection pool: `season_start_year == 2023`, 250 games, 119,349 snapshots.
  - Final held-out test: `season_start_year == 2024`, 250 games, 119,804 snapshots.
  - Game id overlap: 0.
- Model selection used only a stratified game-level validation split carved from
  2023: 200 fit games / 50 validation games. The 2024 season was scored only
  after choosing the validation winner.

## Correction: the "overconfidence defect" was not a defect

**This investigation was launched on a premise that turned out to be wrong, and
the premise came from intuition rather than measurement.** Everything below was
written while chasing a supposed overconfidence bug at "home +10 with 2:00
left", where the published model returns `0.9980` and that was assumed to be
too high.

Measuring the held-out 2024 season settled it. Of the 193 snapshots with a home
margin of +9..+11 and roughly 1:26-2:38 remaining:

| Source | Home win probability |
|---|---:|
| **Actually observed outcome** | **0.9948** (192 of 193) |
| Published model | 0.9980 |
| ESPN's published curve | 0.9865 |

A 10-point lead with two minutes left really is very nearly decided. The
published model is the **closest of the three to the observed rate**, and ESPN
is slightly *under*-confident in this state. The proposed "fix" would have moved
the number to `0.968`, i.e. further from reality, and it independently failed
the shipping gate by making held-out log loss worse (`0.494886` vs `0.491963`).

So the artifact was correctly left alone, for a better reason than the one
originally recorded. The sections below are kept as an honest record of the
experiment, but read "defect" in them as "hypothesised defect, since
disproved".

## Problem targeted (as originally hypothesised — see correction above)

The published monotone `HistGradientBoostingClassifier` is overconfident in
late blowouts: home +10 with 2:00 left in regulation scores about `0.9980`.
That is too close to certain and looks unreasonable beside ESPN. Comparable
2024 ESPN states in this harvest (margin exactly +10 and within ±30 seconds of
2:00) averaged `0.987962` with range `0.960` to `0.999`.

Shipping rule remains unchanged: ship only if held-out 2024 log loss beats the
published artifact (`0.491963`) and the model is monotone non-decreasing in home
margin on an explicit grid.

## 2023 validation experiments

Selection among defect-fixing candidates required monotonicity and home +10 at
2:00 <= `0.98`, then lowest validation log loss.

| approach | validation Brier | validation log loss | +10 / 2:00 | monotone grid | defect gate |
|---|---:|---:|---:|---|---|
| round-1 two-feature logistic | 0.137913 | 0.425276 | 0.809556 | pass | pass |
| **40% HGB / 60% smooth logistic logit blend** | **0.136415** | **0.416763** | **0.967664** | pass | pass |
| 50% HGB / 50% smooth logistic logit blend | 0.136617 | 0.416848 | 0.979890 | pass | pass |
| 70% HGB / 30% smooth logistic logit blend | 0.137290 | 0.418355 | 0.992319 | pass | fail |
| polynomial logistic degree 3 | 0.139611 | 0.425676 | 0.964282 | fail | pass |
| spline logistic | 0.138543 | 0.427120 | 0.786502 | fail | pass |
| published-style monotone HGB | 0.138831 | 0.422870 | 0.998210 | pass | fail |
| classical gradient boosting | 0.139783 | 0.427094 | 0.987707 | fail | fail |

I also checked validation-only calibration transforms during exploration:
isotonic calibration of the 80%-fit HGB had validation log loss `0.390269` but
still scored +10/2:00 at `0.9958`; sigmoid calibration had validation log loss
`0.406716` and rounded to `1.0000` for the defect state. Neither was a credible
fix for this defect.

## Held-out 2024 result for the validation winner

The validation winner fixed the target state and passed monotonicity, but it did
**not** beat the published model on held-out log loss. Therefore
`models/live_wp/nba_live_wp.joblib` was **not overwritten**.

| predictor | n | Brier | log loss | max calibration gap |
|---|---:|---:|---:|---:|
| validation winner: 40/60 logit blend | 119,804 | 0.168327 | 0.494886 | 0.0711 |
| **published NBA artifact** | 119,804 | **0.167947** | **0.491963** | **0.0656** |
| analytic normal baseline | 119,804 | 0.166237 | 0.509335 | — |
| normal baseline recomputed in script | 119,804 | 0.166073 | 0.508698 | — |
| ESPN published WP | 119,803 | 0.157319 | 0.462902 | — |

Honest bottom line: the smooth blend fixes the visual absurdity but gives up too
much held-out log loss, so it fails the repo shipping rule. ESPN still beats both
our published artifact and the attempted replacement.

## Held-out phase breakdown for the validation winner

| regulation remaining | n | Brier | log loss |
|---|---:|---:|---:|
| 1.00-0.75 | 28,768 | 0.232652 | 0.660937 |
| 0.75-0.50 | 30,059 | 0.200372 | 0.585188 |
| 0.50-0.25 | 29,665 | 0.154850 | 0.463149 |
| 0.25-0.00 | 31,312 | 0.091235 | 0.285704 |

Late-game direct comparison (`frac_remaining <= 0.25`):

| predictor | n | Brier | log loss |
|---|---:|---:|---:|
| validation winner | 32,551 | 0.092191 | 0.288530 |
| ESPN | 32,550 | 0.089219 | 0.268831 |

## Defect and tail sanity for the validation winner

Before/after target state:

| state | published artifact | validation winner | comparable ESPN mean |
|---|---:|---:|---:|
| home +10, 2:00 left | 0.9980 | 0.968486 | 0.987962 |

Late-tail table for the validation winner:

| margin | 2:00 left | 0:30 left |
|---:|---:|---:|
| +5 | 0.742681 | 0.943209 |
| +10 | 0.968486 | 0.970440 |
| +15 | 0.982639 | 0.983548 |
| +20 | 0.989417 | 0.990155 |

## Monotonicity and edge states

The validation winner passed the explicit monotone grid: 3,840 adjacent margin
pairs checked across `frac_remaining` values `1.0, 0.75, 0.5, 0.25, 0.10,
120/2880, 30/2880, 0.0` and periods `1, 2, 4, 5`; failures: 0.

Edge outputs were finite and strictly inside `(0, 1)` before serving clamp:

- tie at start: 0.532738
- tie at end: 0.618059
- +60 at end: 0.999996
- -60 at end: 0.000006

Because the held-out log-loss gate failed, these checks are documentation of the
rejected candidate, not the shipped artifact.
