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

## Held-out 2025 results

| Predictor | Brier | Log loss | Notes |
| --- | ---: | ---: | --- |
| MLB model | 0.154604 | 0.463933 | All held-out snapshots |
| Leader baseline | 0.168118 | 0.515082 | 0.85 if home leads, 0.15 if trails |
| Constant 0.5 | 0.250000 | 0.693147 | All held-out snapshots |
| Normal baseline (`mu=0.25`, `sigma=4.5`) | 0.154822 | 0.484393 | All held-out snapshots |
| ESPN home WP | 0.153735 | 0.461687 | Only 19,963 / 150,575 held-out snapshots where ESPN published WP |

The model narrowly beat the normal baseline on Brier and more clearly on log
loss. It did not beat ESPN on the ESPN-published subset; ESPN coverage was only
13.3% of held-out snapshots, so that comparison is subset-only.

## Calibration

Max calibration gap over 10 bins with at least 30 rows: **0.0793**.

| Bin | N | Mean prediction | Actual home win rate | Gap |
| --- | ---: | ---: | ---: | ---: |
| 0.0-0.1 | 24,874 | 0.0481 | 0.0642 | 0.0161 |
| 0.1-0.2 | 14,113 | 0.1509 | 0.1564 | 0.0055 |
| 0.2-0.3 | 4,395 | 0.2599 | 0.2228 | -0.0372 |
| 0.3-0.4 | 16,640 | 0.3488 | 0.3885 | 0.0396 |
| 0.4-0.5 | 25,096 | 0.4932 | 0.5100 | 0.0169 |
| 0.5-0.6 | 16,710 | 0.5342 | 0.5555 | 0.0213 |
| 0.6-0.7 | 12,191 | 0.6255 | 0.7049 | 0.0793 |
| 0.7-0.8 | 6,092 | 0.7595 | 0.8119 | 0.0524 |
| 0.8-0.9 | 10,835 | 0.8259 | 0.8982 | 0.0723 |
| 0.9-1.0 | 19,629 | 0.9585 | 0.9872 | 0.0287 |

## Phase breakdown

| Phase | N | Model Brier | Model log loss | Normal Brier | ESPN Brier (coverage) |
| --- | ---: | ---: | ---: | ---: | --- |
| Innings 1-3 | 58,253 | 0.219132 | 0.628564 | 0.217619 | 0.220282 (7,870/58,253) |
| Innings 4-6 | 50,649 | 0.144650 | 0.445824 | 0.145586 | 0.141665 (6,774/50,649) |
| Innings 7-9 | 40,051 | 0.072924 | 0.246031 | 0.074183 | 0.068029 (5,114/40,051) |
| Extra/no regulation left | 1,622 | 0.164837 | 0.497317 | 0.179100 | 0.135891 (205/1,622) |

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

- Tied top 1st proxy: 0.495296.
- Home +1 early: 0.604486.
- Home +1 late: 0.812684.
- Home -1 late: 0.164439.
- Tied bottom 9th proxy: 0.529029.
- Home +1 bottom 9th proxy: 0.840250.
- Tied extra-inning state: 0.582319.

These pass the intended directionality checks: home win probability rises with
lead, the same lead is worth more later, and bottom-9 proxies favor the home
team. The tied top-1st proxy is slightly below 0.500 in this sample.

## Known limitation: home-field bias in the training sample

At a 0-0 start of game the model returns **0.4953** for the home team, i.e. it
very slightly favours the *away* side. Real MLB home teams win about 53% of the
time, so that intercept is wrong in direction.

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
