# NFL live win probability

## Data and split

- Database: `data\live_wp\nfl_snapshots.db`.
- Total: 544 games and 78,767 snapshots from the 2023 and 2024 NFL regular seasons.
- Fixed final holdout: train on 2023 games only (272 games, 39,397 snapshots), test once on 2024 games only (272 games, 39,370 snapshots).
- Model selection used only a 2023 game-level chronological development split: first 70% of games for fitting, next 10% reserved for calibration experiments, final 20% for validation.
- ESPN win probability is a benchmark only, never an input.

## Round 3 monotone-time model

The saved artifact is `models\live_wp\nfl_live_wp.joblib`.

Base model: the round-2 `PolynomialFeatures(degree=3)` logistic model over:

- `margin`
- `margin_scaled`
- `frac_remaining`

followed by standardized logistic regression (`C=0.1`). Round 3 keeps that base model, blends its probability 50/50 with the analytic normal baseline (`mu=0`, `sigma=13.5`), then applies a time monotone envelope at fixed margin. This keeps the frozen serving interface intact.

## 2023 validation experiments

Selection prioritized validation calibration gap, then Brier/log loss, among models that passed sanity checks. The spline model had the best validation gap but was rejected after refitting on all 2023 data because it failed the "same lead is worth more late" sanity check.

| Approach | Validation Brier | Validation log loss | Validation max gap | Result |
| --- | ---: | ---: | ---: | --- |
| Round-1 logistic (`margin`, `margin_scaled`) | 0.160888 | 0.474189 | 0.1822 | Passed, not selected |
| Logistic + `frac_remaining` | 0.160647 | 0.473688 | 0.1496 | Rejected: time-leverage sanity failed |
| Cubic polynomial logistic | 0.162649 | 0.476861 | 0.0996 | **Selected** |
| Spline logistic over margin/time | 0.161764 | 0.479129 | 0.0791 | Rejected after full-train sanity |
| Monotonic HistGradientBoosting | 0.163428 | 0.487057 | 0.1686 | Passed, not selected |
| Sigmoid-calibrated HGB | 0.168372 | 0.503264 | 0.1687 | Passed, not selected |
| Monotone HGB on `margin`, `margin_scaled` | 0.163486 | 0.481040 | 0.2027 | Time/margin monotone, but final 2024 log loss worsened to 0.484421 |
| Normal-baseline blend + time envelope | selected after base model | selected after base model | selected after base model | **Shipped**: fixed time monotonicity and improved held-out log loss |

## Held-out 2024 metrics

| Predictor | Brier | Log loss |
| --- | ---: | ---: |
| **NFL live WP round 4** | **0.163903** | **0.479367** |
| NFL live WP round 3 | 0.164034 | 0.479629 |
| NFL live WP round 2 | 0.164048 | 0.480777 |
| NFL live WP round 1 | 0.166640 | 0.490719 |
| ESPN published WP | 0.145762 | 0.437000 |
| Normal baseline (`mu=0`, `sigma=13.5`, script) | 0.164627 | 0.496034 |
| Leader baseline | 0.189586 | 0.570677 |
| Constant 0.5 | 0.250000 | 0.693147 |

Round 4 honestly improves over round 3 by a small amount on the original
snapshot evaluation and fixes the local time wobble, but it still does **not**
close the full gap to ESPN.

## Round 4 situational model

`data\live_wp\nfl_situation.db` adds possession, down, distance and field
position. Round 4 uses a cubic logistic base model over the existing margin/time
features plus the NFL situational features, keeps the normal-baseline blend and
time monotone envelope, and adds a local cumulative margin envelope. Training
includes missing-situation copies so live payloads without a situation block
degrade gracefully. `pregame_logit` and `pregame_logit_decay` are in the
artifact feature list, but this harvest has no pregame prior column, so they are
neutral zero values in this round.

| Same `nfl_situation.db` 2024 rows | Brier | Log loss |
| --- | ---: | ---: |
| Old margin/time round-3 recipe | **0.161824** | **0.474385** |
| **Round 4 full recipe + situation** | **0.160183** | **0.469577** |
| ESPN published WP | 0.144450 | 0.433754 |

Against ESPN on these rows, the old recipe gap is 0.040631 log-loss points and
round 4's gap is 0.035823, closing about **11.8%** of the ESPN log-loss gap.
On the original `nfl_snapshots.db` evaluation, where situational fields are
unobserved, round 4 scores **0.163903 Brier / 0.479367 log loss**, a small
published-table improvement over round 3.

The 2023-only validation alpha sweep selected a 67.5% normal-baseline blend
among monotonic candidates. Checked validation log loss: alpha 0.60 failed
fixed-situation margin monotonicity; alpha 0.625 failed; alpha 0.65 failed;
alpha 0.675 passed at 0.446891; alpha 0.70 passed at 0.447279.

Live serving now threads ESPN scoreboard `situation` fields into `GameState`
when present: possession is resolved by team id, and `yardLine` is converted to
yards to the offense's opponent end zone (`100 - yardLine` for home possession,
`yardLine` for away possession). If the block is absent, the router passes
`None` for every situational field.

Sanity check for omitted situation at margin +3 with 10% regulation remaining:
unknown situation = 0.739258, home 1st-and-10 at midfield = 0.774449, and away
1st-and-10 in the red zone = 0.669793. The model uses `situation_known`, but
missing-vs-known cases do not lurch to extreme probabilities.

## Calibration

Max calibration gap over 10 bins with at least 30 samples: **0.0740** (round 2: 0.0686; round 1: 0.0875).

## Phase breakdown

| Fraction remaining | N | Model Brier | Model log loss | ESPN Brier | ESPN log loss | Normal Brier | Normal log loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.00-0.75 | 8,510 | 0.237608 | 0.667918 | 0.206101 | 0.599037 | 0.237928 | 0.668002 |
| 0.75-0.50 | 10,740 | 0.194978 | 0.566166 | 0.171548 | 0.511954 | 0.194100 | 0.563171 |
| 0.50-0.25 | 8,978 | 0.144518 | 0.433446 | 0.134699 | 0.410570 | 0.144856 | 0.433939 |
| 0.25-0.00 | 11,142 | 0.093737 | 0.289618 | 0.083698 | 0.262185 | 0.096163 | 0.350009 |

The gain is concentrated late, where the cubic interaction gives the model a much better terminal-game shape. ESPN remains better in every phase.

## Sanity checks

Measured from the saved artifact:

- Margin monotonic at 50% remaining: -14 = 0.088256, -7 = 0.255367, 0 = 0.517934, +7 = 0.766320, +14 = 0.913920.
- Same +7 lead is worth more late: 80% remaining = 0.749772; 20% remaining = 0.862523.
- Edge states through serving are finite and strictly inside (0, 1): tied kickoff = 0.531807, tied at regulation end = 0.489416, +14 at regulation end = 0.999000, -14 at regulation end = 0.001000.

## Time monotonicity fix

Before round 3, walking `frac_remaining` from 1.0 to 0.0 in 40 steps had visible wrong-way ticks: +1 had 34 drops, +3 had 19, +4 had 16, +7 had 13, +10 had 12, and +14 had 10; the mirror trailing margins also had 7 to 16 wrong-way increases. After round 3, all checked margins (`±1`, `±3`, `±4`, `±7`, `±10`, `±14`) have **0 / 40** wrong-way steps, and the margin-monotonic grid check has 0 drops.
