# NBA live win probability

Retrain generated 2026-08-06 from full-season coverage in
`data/live_wp/nba_snapshots.db` by `scripts/live_wp/train_nba.py`.

## Data and fixed split

- Split is by whole game, not by snapshot.
- Train/model-selection pool: `games.season_start_year == 2023`, 1,231 games, 574,228 snapshots.
- Final held-out test: `games.season_start_year == 2024`, 1,231 games, 581,626 snapshots.
- Game id overlap: 0.
- NBA `snapshots` has no `season` column; training joins `games` and uses `games.season_start_year`.
- Model selection used only a stratified 2023 game-level validation split: 984 fit games / 247 validation games. The 2024 season was scored only after choosing the validation winner.

## Correction: the "overconfidence defect" was not a defect

**This investigation was launched on a premise that turned out to be wrong, and
the premise came from intuition rather than measurement.** Everything below was
written while chasing a supposed overconfidence bug at "home +10 with 2:00
left", where the earlier published model returned `0.9980` and that was assumed
to be too high.

Measuring the full held-out 2024 season settled it. Of the 796 snapshots with a
home margin of +9..+11 and roughly 1:24-2:36 remaining:

| Source | Home win probability |
|---|---:|
| **Actually observed outcome** | **0.9950** (792 of 796) |
| 2026-08-06 retrained model | 0.9954 |
| ESPN's published curve | 0.9870 |

A 10-point lead with two minutes left really is very nearly decided. The model
is closest to the observed rate in this state, and ESPN is slightly
under-confident. The disclosure is preserved here because the original
"overconfidence defect" premise was disproved by measurement, not silently
forgotten.

## Refit analytic baseline

The old two-parameter normal baseline was fit on the prior ~250-game sample. On
the expanded 2023 training season:

| baseline | mu | sigma | held-out Brier | held-out log loss |
|---|---:|---:|---:|---:|
| old OLS normal from prior artifact | 2.0988 | 18.8195 | 0.164166 | 0.492453 |
| new OLS normal on full 2023 | 1.8373 | 19.3191 | **0.164147** | **0.492408** |
| refit normal, optimized for Brier | 1.6604 | 18.2928 | 0.164216 | 0.492706 |
| refit normal, optimized for log loss | 1.6810 | 18.7406 | 0.164172 | 0.492512 |

The fair shipping gate used the refit log-loss baseline for log loss and the
refit Brier baseline for the known Brier weakness.

## 2023 validation experiments

Selection required both monotonicity checks to pass and validation log loss to
beat the refit validation baseline (`0.479885`). Among those, the known NBA
weakness made validation Brier the first tiebreaker.

| approach | validation Brier | validation log loss | margin monotone | time monotone |
|---|---:|---:|---|---|
| **HGB grid blend leaf7 alpha=0.2** | **0.158116** | 0.469330 | pass | pass |
| HGB grid blend leaf7 alpha=0.4 | 0.158121 | 0.469371 | pass | pass |
| HGB grid blend leaf15 alpha=0.4 | 0.158179 | 0.469149 | pass | pass |
| HGB grid blend leaf15 alpha=0.6 | 0.158184 | 0.469305 | pass | pass |
| HGB grid blend leaf31 alpha=0.4 | 0.158190 | 0.469115 | pass | pass |
| poly2 baseline correction alpha=0.4 diagnostic | 0.158283 | **0.468817** | fail | fail |

The poly2 diagnostic had the best validation log loss, but it was not shippable
because it violated monotonicity. The selected model is a regularized monotone
`HistGradientBoostingClassifier` blended with the refit normal baseline and
projected to a precomputed cumulative grid enforcing margin and time
monotonicity.

## Held-out 2024 result

| predictor | n | Brier | log loss | max calibration gap |
|---|---:|---:|---:|---:|
| **2026-08-06 shipped retrain** | 581,626 | 0.164364 | **0.484255** | 0.0448 |
| previous NBA artifact re-scored on new holdout | 581,626 | 0.165848 | 0.490248 | 0.0313 |
| refit normal, log-loss objective | 581,626 | 0.164172 | 0.492512 | — |
| refit normal, Brier objective | 581,626 | **0.164216** | 0.492706 | — |
| ESPN published WP | 581,625 | **0.149702** | **0.448265** | — |

Shipping decision: **artifact overwritten**. The retrain beats the refit
analytic baseline on held-out log loss and passes both monotonicity gates. It
does **not** beat the refit baseline on Brier (`0.164364` vs `0.164216`), so the
known Brier weakness was narrowed but not eliminated.

The previously published `0.167947 / 0.491963` came from the old evaluation set
and should not be presented as a modeling improvement. On the new 2024 holdout,
the previous artifact re-scores at `0.165848 / 0.490248`.

## Held-out phase breakdown for the shipped model

| regulation remaining | n | Brier | log loss |
|---|---:|---:|---:|
| 1.00-0.75 | 140,445 | 0.231465 | 0.654708 |
| 0.75-0.50 | 147,410 | 0.196722 | 0.572675 |
| 0.50-0.25 | 144,375 | 0.148107 | 0.449875 |
| 0.25-0.00 | 149,396 | 0.085069 | 0.269994 |

## Error concentration relative to ESPN

The ESPN gap is largest early and in close states:

| bucket | n | ours log loss | ESPN log loss | gap |
|---|---:|---:|---:|---:|
| time 1.00-0.75 | 140,445 | 0.654708 | 0.580189 | 0.074519 |
| time 0.75-0.50 | 147,410 | 0.572675 | 0.526597 | 0.046079 |
| margin 0 | 28,595 | 0.691994 | 0.632115 | 0.059879 |
| margin 1-3 | 136,492 | 0.669241 | 0.615247 | 0.053994 |
| margin 4-7 | 142,398 | 0.600164 | 0.559267 | 0.040898 |
| time 0.25-0.00 | 149,395 | 0.269993 | 0.263973 | 0.006021 |

This points to missing pregame/team-strength information and early-game state,
not a late-blowout overconfidence defect.

## Monotonicity, loading, and latency

- Margin monotonicity: pass, 4,800 adjacent margin pairs checked over 41 time steps.
- Time monotonicity: pass, margins ±3, ±5, ±8, ±12 over 40 steps each.
- Fresh-process serving check succeeded.
- Fresh-process NBA latency measured under the ~10 ms/call gate during verification.
