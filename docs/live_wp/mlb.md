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
For extra innings (`is_overtime=True`, `frac_remaining=0.0`) the regulation
normal baseline is not used; those states use a monotone empirical margin table
fit from 2024 extra-inning snapshots only. This avoids treating every
`frac_remaining=0.0` MLB row as a completed game.
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
| MLB model current | 0.155257 | 0.463758 | All held-out snapshots; includes bounded walk-off handling for home leads after the top of the 9th |
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
| Extra/no regulation left | 18,478 | 0.180725 | 0.529009 | 0.212861 | 0.155400 (2,364/18,478) |

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
inning through the current frozen feature map. A 2024 empirical margin table is
therefore used only at the extra-inning endpoint; it materially fixes the
average home-trailing-by-one extra-inning state, but it still cannot resolve
top/bottom-specific extra-inning context.

How much of that is demonstrable, measured independently: **almost none of the
aggregate movement is statistically significant, and the per-cell claim is.**
Extra-inning snapshots are extremely clustered -- 18,478 rows come from only 209
games, and the whole `margin=0` cell is those same 209 games -- so the effective
sample is far smaller than the row counts suggest. Game-level cluster bootstraps
on held-out 2025 give:

| Quantity | Change | 95% CI | Verdict |
| --- | ---: | ---: | --- |
| Full-season Brier | -0.000057 | [-0.000137, +0.000015] | not significant |
| Extras-only Brier | -0.004282 | [-0.010252, +0.001359] | not significant |
| Extras-only log loss | -0.014038 | [-0.033667, +0.004440] | not significant (better in 93.3% of resamples) |

The one defensible claim is per-cell falsifiability, the same standard applied to
the NBA overtime fix: for `margin=-1` in extras (128 games) the observed rate is
0.2887 with a cluster CI of [0.2068, 0.3767]. The old model predicted 0.1425,
which is **outside** that interval and therefore measurably wrong; the new model
predicts 0.2929, which is inside it. No aggregate metric regressed, so the change
ships on that basis rather than on the aggregate numbers.

Two things this measurement retracted:

- The `margin=0` extras cell was originally diagnosed as a defect (0.6057
  predicted against 0.6664 observed). On 209 games the cluster CI is
  [0.5859, 0.7441], which **contains** the prediction. That "defect" was largely
  an artifact of counting correlated snapshots as independent, and it correctly
  did not move.
- The sparse negative cells that appear to regress (`margin=-2`: 0.0526 to
  0.1181; `margin=-4`: 0.0280 to 0.0577) rest on 49 and 21 games. `margin=-2`
  stays inside its CI both before and after; `margin=-4` has a degenerate CI
  (no home wins at all), so neither the regression nor the improvement there is
  measurable.

Known latent risk: the empirical table lets predictions reach the 1e-6 clip,
where the old artifact floored at 0.0126. Across both seasons (2.77M snapshots)
**no** prediction within 1e-3 of 0 or 1 was contradicted by the outcome, so this
is not an observed defect -- but a single contradicted 1e-6 prediction would cost
13.8 nats, so the floor is worth revisiting if extras data ever grows.

If the home team is leading after the top of the 9th, MLB simply ends the game.
The artifact therefore returns bounded near-certainty (`1.0 - 1e-9`) for
regulation states with `margin > 0`, `is_overtime=False`, and
`frac_remaining <= 1/18 + 1e-12`. This is a rule of the sport rather than a
fitted estimate: the bottom of the 9th is not played when the home team already
leads. The `1e-12` tolerance is intentional because production bottom-9
encoding can land a few ULP above exact `1/18`. The bound is also intentional:
confidence in a rule of baseball is not worth an unbounded log-loss penalty for
unforeseen data quirks such as suspended games, scoring corrections, or a
mislabeled outcome.

The harvested data verified the rule with zero counterexamples: 2024 had 438
firing rows over 101 games, 2025 had 468 rows over 112 games, and the combined
906 rows over 213 games were all home wins. The analogous positive-margin
`frac_remaining=0.0` extra-inning rows in 2024 also had zero exceptions
(464/464 rows, 107 games), but extras continue to use the separate empirical
table because extra innings are encoded separately.

The walk-off rule specifically fixes the repeated bottom-9, home +1 defect: a
state that is certain by the rules of the sport was being rated 0.9149. It does
not fix the other three replicated late-inning cells, which remain open and
measured below. With a 3000-resample cluster bootstrap by `game_id` on 2024:

| Cell | Games | Rows | Old pred | New pred | Actual (95% CI) | Verdict |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Bottom 9, home +1 | 84 | 369 | 0.914887 | 0.999999999 | 1.000000 [1.000000, 1.000000] | fixed by bounded rule certainty |
| Bottom 8, home +1 | 330 | 8,173 | 0.833516 | 0.833516 | 0.873975 [0.835074, 0.910132] | open; unchanged and still outside |
| Bottom 8, home +2 | 304 | 7,313 | 0.925872 | 0.925872 | 0.954328 [0.928550, 0.977302] | open; unchanged and still outside |
| Top 9, home -1 | 294 | 6,970 | 0.215398 | 0.215398 | 0.165136 [0.116814, 0.213444] | open; unchanged and still outside |

Full-season cluster-bootstrap deltas (old minus new) are tiny but positive:

| Season | Brier delta (95% CI) | Log-loss delta (95% CI) | Interpretation |
| --- | ---: | ---: | --- |
| 2024 train season | +0.000001942 [+0.000001531, +0.000002417] | +0.000024480 [+0.000019414, +0.000030369] | statistically positive but practically tiny |
| 2025 held-out season | +0.000002284 [+0.000001854, +0.000002724] | +0.000028371 [+0.000023070, +0.000033760] | statistically positive but practically tiny |

These aggregate movements are statistically detectable because the rule fires
on rows that were previously badly underrated, but they are practically
negligible -- roughly four orders of magnitude smaller than the model/baseline
differences discussed elsewhere on this page. The change is justified by the
per-cell correctness argument, not by a meaningful aggregate accuracy gain.

## Sanity checks

Measured from the saved artifact:

- Tied top 1st proxy: 0.539741.
- Home +1 early: 0.648054.
- Home +1 late: 0.860049.
- Home -1 late: 0.212800.
- Tied bottom 9th proxy: 0.580569.
- Home +1 bottom 9th proxy: 0.999999999.
- Tied extra-inning state: 0.602595.

These pass the intended directionality checks: home win probability rises with
lead, the same lead is worth more later, and bottom-9 proxies favor the home
team.

## Time monotonicity fix

Before the monotone-envelope post-processor, walking `frac_remaining` from 1.0 to 0.0 in 40 steps had wrong-way ticks: +1 had 6 drops, +2 had 2, +3 had 5, +5 had 4, and the mirror trailing margins had 3 to 9 wrong-way increases. The current artifact has **0 / 400** wrong-way steps for each checked margin
(`±1`, `±2`, `±3` in `verify_artifacts.py`, plus manual checks for `±5`), and
a manual 1600-step sweep also has 0 wrong-way steps for `±1`, `±2`, `±3`, and
`±5`. The margin-monotonic grid check has 0 drops.
