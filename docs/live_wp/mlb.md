# MLB live win probability

Generated with:

```powershell
python scripts\live_wp\harvest_mlb.py
python scripts\live_wp\train_mlb.py
```

## Data and split

Snapshots are stored in `data\live_wp\mlb_snapshots.db`.

- Seasons: 2024 and 2025 regular-season mid-summer windows, 2024-07-20 through
  2024-08-08 and 2025-07-20 through 2025-08-08.
- Harvested games with snapshots: 528.
- Harvested snapshots: 302,994.
- ESPN win-probability coverage: 40,054 / 302,994 snapshots.
- Outs coverage: 302,994 / 302,994 snapshots.
- Extra-inning rows: 3,697 snapshots from 43 games.

The validation split is by game, not by snapshot: all 2024 games train, all
2025 games test. Training uses an even deterministic subsample capped at 120
snapshots per game (31,680 training snapshots from 264 games) so unusually long
games do not dominate the fit. Evaluation uses all 150,575 snapshots from the
264 held-out 2025 games.

## Model

The artifact is `models\live_wp\mlb_live_wp.joblib`. It contains a
`GradientBoostingClassifier` wrapped in 3-fold sigmoid calibration, trained only
on the frozen `app.services.live_winprob.build_features` fields:
`margin`, `margin_scaled`, `frac_remaining`, `pregame_logit`,
`pregame_logit_decay`, and `is_overtime`.

No pregame probabilities were available in these harvested snapshots, so the two
pregame features are zero.

The round-3 artifact then blends the learned probability 70/30 with the analytic
normal baseline (`mu=0.25`, `sigma=4.5`) and applies time and margin monotone
envelopes. This was selected because a direct monotone HGB over
`margin`/`margin_scaled` fixed the wobble but missed the shipping gate
(held-out log loss 0.469488).

## Held-out 2025 results

| Predictor | Brier | Log loss | Notes |
| --- | ---: | ---: | --- |
| MLB model round 3 | 0.154305 | 0.462951 | All held-out snapshots |
| MLB model previous | 0.154604 | 0.463933 | All held-out snapshots |
| Leader baseline | 0.168118 | 0.515082 | 0.85 if home leads, 0.15 if trails |
| Constant 0.5 | 0.250000 | 0.693147 | All held-out snapshots |
| Normal baseline (`mu=0.25`, `sigma=4.5`) | 0.154822 | 0.484393 | All held-out snapshots |
| ESPN home WP | 0.153735 | 0.461687 | Only 19,963 / 150,575 held-out snapshots where ESPN published WP |

The model narrowly beat the previous artifact and the normal baseline on Brier
and more clearly on log loss. It did not beat ESPN on the ESPN-published subset; ESPN coverage was only
13.3% of held-out snapshots, so that comparison is subset-only.

## Calibration

Max calibration gap over 10 bins with at least 30 rows: **0.0755**.

| Bin | N | Mean prediction | Actual home win rate | Gap |
| --- | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 24,173 | 0.0444 | 0.0611 | 0.0166 |
| 0.1-0.2 | 12,817 | 0.1529 | 0.1507 | -0.0023 |
| 0.2-0.3 | 5,491 | 0.2461 | 0.2114 | -0.0346 |
| 0.3-0.4 | 16,558 | 0.3552 | 0.3700 | 0.0147 |
| 0.4-0.5 | 3,465 | 0.4509 | 0.5175 | 0.0666 |
| 0.5-0.6 | 38,126 | 0.5139 | 0.5278 | 0.0139 |
| 0.6-0.7 | 13,389 | 0.6293 | 0.6957 | 0.0664 |
| 0.7-0.8 | 9,163 | 0.7631 | 0.8386 | 0.0755 |
| 0.8-0.9 | 8,260 | 0.8342 | 0.9068 | 0.0726 |
| 0.9-1.0 | 19,133 | 0.9579 | 0.9869 | 0.0290 |

## Phase breakdown

| Phase | N | Model Brier | Model log loss | Normal Brier | ESPN Brier (coverage) |
| --- | ---: | ---: | ---: | ---: | --- |
| Innings 1-3 | 58,253 | 0.218410 | 0.627200 | 0.217619 | 0.220282 (7,870/58,253) |
| Innings 4-6 | 50,649 | 0.144529 | 0.445875 | 0.145586 | 0.141665 (6,774/50,649) |
| Innings 7-9 | 40,051 | 0.073033 | 0.244572 | 0.074183 | 0.068029 (5,114/40,051) |
| Extra/no regulation left | 1,622 | 0.164093 | 0.489563 | 0.179100 | 0.135891 (205/1,622) |

Early-game skill remains the weakest phase; the normal baseline was slightly
better in innings 1-3 by Brier and log loss.

## MLB-specific handling and limitations

Baseball has no game clock. ESPN play `period.number` is the inning and
`period.type` is Top/Bottom; the shared harvester converts that into
`frac_remaining` in half-inning steps over nine regulation innings. That means
top/bottom asymmetry is represented only by the remaining half-inning count.
Outs were harvested but are not used because the frozen serving interface has no
outs feature.

Extra innings use `is_overtime=True` and `frac_remaining=0.0`. The model remains
finite at those states, but it cannot distinguish top vs bottom of an extra
inning through the current frozen feature map.

If the home team is leading after the top of the 9th, MLB simply ends the game;
live serving should normally see that game as final rather than as an in-game
state with a missing bottom half.

## Sanity checks

Measured from the saved artifact:

- Tied top 1st proxy: 0.503353.
- Home +1 early: 0.607626.
- Home +1 late: 0.798177.
- Home -1 late: 0.189094.
- Tied bottom 9th proxy: 0.521888.
- Home +1 bottom 9th proxy: 0.837307.
- Tied extra-inning state: 0.557623.

These pass the intended directionality checks: home win probability rises with
lead, the same lead is worth more later, and bottom-9 proxies favor the home
team.

## Time monotonicity fix

Before round 3, walking `frac_remaining` from 1.0 to 0.0 in 40 steps had wrong-way ticks: +1 had 6 drops, +2 had 2, +3 had 5, +5 had 4, and the mirror trailing margins had 3 to 9 wrong-way increases. After round 3, all checked margins (`±1`, `±2`, `±3`, `±5`) have **0 / 40** wrong-way steps, and the margin-monotonic grid check has 0 drops.

## Known limitation: home-field bias in the training sample

At a 0-0 start of game the model now returns **0.5034** for the home team. Real
MLB home teams win about 53% of the time, so that intercept remains too low even
though the round-3 blend no longer slightly favours the away side.

It is, however, faithful to what the model was shown. The harvest covers 264
games per season, not a full 2,430-game slate, and in the 2024 training sample
the home team won only **46.2%** of games. The 2025 test sample came in at
51.9%, and among tied snapshots with >95% of regulation remaining the home side
actually won 51.1%. So the model inherited a home-field disadvantage that exists
in the sample but not in the sport.

The practical effect is confined to the earliest, least informative part of a
game, where the margin term carries almost no signal and the intercept dominates;
by the middle innings the score difference swamps it. It is nonetheless a real
defect, and the honest fix is a larger harvest rather than hand-patching the
intercept. Recorded here rather than silently corrected.
