# MLB live win probability

Generated with:

```powershell
python scripts\live_wp\harvest_mlb.py
python scripts\live_wp\train_mlb.py
```

## Data and split

Snapshots are stored in `data\live_wp\mlb_snapshots.db`.

- Seasons: full 2024 and 2025 regular seasons in the harvested ESPN feed.
- Harvested games with snapshots: 4,859.
- Harvested snapshots: 2,773,343.
- ESPN win-probability coverage on held-out 2025: 183,206 / 1,387,627 snapshots.
- Outs coverage: 2,773,343 / 2,773,343 snapshots.

The validation split is by game, not by snapshot: all 2024 games train, all
2025 games test. Training uses an even deterministic subsample capped at 120
snapshots per game (291,480 training snapshots from 2,429 games) so unusually
long games do not dominate the fit. Evaluation uses all 1,387,627 snapshots
from the 2,430 held-out 2025 games.

## Model

The artifact is `models\live_wp\mlb_live_wp.joblib`. It contains a
`GradientBoostingClassifier` wrapped in 3-fold sigmoid calibration, trained only
on the frozen core `app.services.live_winprob.build_features` fields:
`margin`, `margin_scaled`, `frac_remaining`, `pregame_logit`,
`pregame_logit_decay`, and `is_overtime`.

No pregame probabilities were available in these harvested snapshots, so the two
pregame features are zero.

The current artifact blends the learned probability with the analytic normal
baseline (`mu=0.25`, `sigma=4.5`) using a time-varying normal weight
`0.5 * sqrt(frac_remaining)`, then applies time and margin monotone envelopes.
The time envelope uses a 401-point precomputed surface and does not include an
off-grid `blend(frac_remaining)` term, so the surface is monotone between grid
points as well as on the grid. The blend schedule was selected on a
deterministic 2024 validation slice split by game; 2025 was reserved for the
final holdout.

MLB can transiently report `outs=3` between half-innings. Training maps that
state to "outs unknown", matching live serving, rather than treating it as a
fourth active-half-inning ordinal value. The shipped artifact does not consume
outs because validation did not require it.

## Held-out 2025 results

| Predictor | Brier | Log loss | Notes |
| --- | ---: | ---: | --- |
| MLB model current | 0.155322 | 0.463994 | All held-out snapshots |
| Previously shipped artifact re-scored on expanded 2025 | 0.157857 | 0.470732 | All held-out snapshots |
| Leader baseline | 0.171609 | 0.523497 | 0.85 if home leads, 0.15 if trails |
| Constant 0.5 | 0.250000 | 0.693147 | All held-out snapshots |
| Normal baseline (`mu=0.25`, `sigma=4.5`) | 0.158119 | 0.501975 | All held-out snapshots |
| Independent normal baseline fit by Brier on 2024 (`mu=0.420`, `sigma=3.530`) | 0.156060 | 0.498600 | From `verify_artifacts.py` |
| Independent normal baseline fit by log loss on 2024 (`mu=0.478`, `sigma=3.976`) | 0.156431 | 0.497973 | From `verify_artifacts.py` |
| ESPN home WP | 0.151983 | 0.453902 | Only 183,206 / 1,387,627 held-out snapshots where ESPN published WP |

The model beat the previously shipped artifact when both were re-scored on the
same expanded 2025 holdout, and it beat the analytic normal baselines on both
Brier and log loss. It did not beat ESPN on the ESPN-published subset; ESPN
coverage was 13.2% of held-out snapshots, so that comparison is subset-only.

## Calibration

Max calibration gap over 10 bins with at least 30 rows: **0.0339**.

| Bin | N | Mean prediction | Actual home win rate | Gap |
| --- | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 193,127 | 0.0396 | 0.0383 | -0.0013 |
| 0.1-0.2 | 77,998 | 0.1488 | 0.1463 | -0.0025 |
| 0.2-0.3 | 108,266 | 0.2504 | 0.2399 | -0.0105 |
| 0.3-0.4 | 147,661 | 0.3725 | 0.3926 | 0.0201 |
| 0.4-0.5 | 20,292 | 0.4309 | 0.4453 | 0.0144 |
| 0.5-0.6 | 346,344 | 0.5462 | 0.5731 | 0.0270 |
| 0.6-0.7 | 114,701 | 0.6572 | 0.6743 | 0.0171 |
| 0.7-0.8 | 77,346 | 0.7606 | 0.7945 | 0.0339 |
| 0.8-0.9 | 116,635 | 0.8509 | 0.8827 | 0.0319 |
| 0.9-1.0 | 185,257 | 0.9614 | 0.9763 | 0.0149 |

The expanded-data re-score showed that more data alone did not fully fix the
old late-game underconfidence. The previously shipped artifact re-scored on the
new 2025 holdout had mean prediction 0.4881 vs actual 0.5282, bin 0.7-0.8 at
0.7669 vs 0.8430, and late one-run leads (`frac_remaining < 0.15`) at 0.8041
vs 0.9204 (n=8,827). The validation-selected time-varying blend improved but
did not eliminate it: mean prediction 0.5123 vs actual 0.5282, bin 0.7-0.8 at
0.7606 vs 0.7945, and late one-run leads at 0.8598 vs 0.9204.
The exact monotone envelope changed the final scores slightly from the first
time-varying blend candidate (0.155303 / 0.463914 to 0.155322 / 0.463994).

## Phase breakdown

| Phase | N | Model Brier | Model log loss | Normal Brier | ESPN Brier (coverage) |
| --- | ---: | ---: | ---: | ---: | --- |
| Innings 1-3 | 534,595 | 0.213190 | 0.611637 | 0.214580 | 0.209350 (72,031/534,595) |
| Innings 4-6 | 466,829 | 0.146026 | 0.445656 | 0.148518 | 0.142356 (62,019/466,829) |
| Innings 7-9 | 367,725 | 0.081469 | 0.268508 | 0.085474 | 0.076260 (46,792/367,725) |
| Extra/no regulation left | 18,478 | 0.184290 | 0.540032 | 0.212861 | 0.155400 (2,364/18,478) |

Early-game skill remains the weakest phase; the normal baseline was slightly
better in innings 1-3 by Brier and log loss.

## MLB-specific handling and limitations

Baseball has no game clock. ESPN play `period.number` is the inning and
`period.type` is Top/Bottom; the shared harvester converts that into
`frac_remaining` in half-inning steps over nine regulation innings. That means
top/bottom asymmetry is represented only by the remaining half-inning count.
Outs are harvested and the live router passes active-half-inning values 0-2 to
the shared `GameState`, but the published artifact still does not consume them
because the held-out shipping gate above did not improve. MLB can transiently
report `outs=3` at middle/end-of-inning boundaries; serving treats that and
middle/end labels as unknown rather than extrapolating beyond the 0-2 active
half-inning range.

Extra innings use `is_overtime=True` and `frac_remaining=0.0`. The model remains
finite at those states, but it cannot distinguish top vs bottom of an extra
inning through the current frozen feature map.

If the home team is leading after the top of the 9th, MLB simply ends the game;
live serving should normally see that game as final rather than as an in-game
state with a missing bottom half.

## Sanity checks

Measured from the saved artifact:

- Tied top 1st proxy: 0.539741.
- Home +1 early: 0.648054.
- Home +1 late: 0.860049.
- Home -1 late: 0.212800.
- Tied bottom 9th proxy: 0.580569.
- Home +1 bottom 9th proxy: 0.914887.
- Tied extra-inning state: 0.605688.

These pass the intended directionality checks: home win probability rises with
lead, the same lead is worth more later, and bottom-9 proxies favor the home
team.

## Time monotonicity fix

Before the monotone-envelope post-processor, walking `frac_remaining` from 1.0 to 0.0 in 40 steps had wrong-way ticks: +1 had 6 drops, +2 had 2, +3 had 5, +5 had 4, and the mirror trailing margins had 3 to 9 wrong-way increases. The current artifact has **0 / 400** wrong-way steps for each checked margin
(`±1`, `±2`, `±3` in `verify_artifacts.py`, plus manual checks for `±5`), and
a manual 1600-step sweep also has 0 wrong-way steps for `±1`, `±2`, `±3`, and
`±5`. The margin-monotonic grid check has 0 drops.
