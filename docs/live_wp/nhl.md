# NHL live win probability

Harvested with `scripts\live_wp\harvest_nhl.py --max-games 500 --per-season 250`.

**The published artifact is the two-parameter analytic baseline, not a learned
model.** Rounds 1 and 2 trained seven learned models between them and not one
beat the baseline on held-out data, so shipping any of them would have meant
serving a worse predictor than a two-line formula. Fit with
`scripts\live_wp\fit_nhl_baseline.py`; the learned-model experiments remain in
`scripts\live_wp\train_nhl.py` and are documented below.

## Data and split

- Harvested: 497 games / 157,945 snapshots in `data/live_wp/nhl_snapshots.db`.
- Seasons: 2024-25 and 2025-26.
- Split: game-level season holdout, never snapshot-random.
  - Train: 2024-25, 249 games / 78,979 snapshots.
  - Test: 2025-26, 248 games / 78,966 snapshots.
  - Game overlap: 0.
- ESPN NHL win probability benchmark: unavailable in this harvest; 0 snapshots
  had `espn_home_wp`.

Labels use the final NHL result, including overtime/shootout. Regulation
`frac_remaining` is 0.0 in overtime; snapshots from period 4+ set
`is_overtime=1`.

## Round 3: ship the analytic baseline (published)

After round 2 failed, the round-1 artifact was re-audited independently and a
second, worse problem surfaced: **it was not monotone in margin.** At 75% of
regulation remaining it rated a four-goal home lead at 0.809, *below* the 0.821
it gave a three-goal lead. A win-probability display that says a team got worse
by scoring is not shippable regardless of its Brier score.

Since no learned model beat the baseline anyway, the baseline is now what we
serve (`app/services/live_wp_baseline.py`, `model_kind="analytic_normal_baseline"`).
It treats the remaining margin as `Normal(mu*f, sigma^2*f)` and asks for
`P(final margin > 0)`. `mu` and `sigma` are fit by log loss on the 2024-25
training season only: **`mu=0.3908`, `sigma=2.7339`**.

Held-out 2025-26 (independently reproduced from the snapshot DB):

| Method | Brier | Log loss | Monotone in margin |
| --- | ---: | ---: | :---: |
| **Published analytic baseline** | **0.175316** | **0.515720** | **yes** |
| Round-1 logistic artifact | 0.175683 | 0.517337 | **no** |
| Round-2 isotonic-calibrated logistic | 0.176891 | 0.583302 | — |
| Leader baseline | 0.184228 | 0.551188 | yes |
| Constant 0.5 | 0.250000 | 0.693147 | — |

Tied states (28,838 snapshots): Brier **0.248675**, versus 0.250887 for round 1.
Round 1 was *worse than a constant 0.5* on tied states; the baseline is now
better than a coin flip, which is the least you should expect.

**The honest trade-off:** the baseline's max calibration gap is **0.1064**,
which is *worse* than the round-1 model's 0.0871. We accepted that because the
baseline wins on both headline metrics (Brier and log loss) and is monotone,
whereas the round-1 model's calibration edge came attached to a defect that
would produce visibly absurd output.

Serving sanity checks through the frozen interface:

| State | Home win prob |
| --- | ---: |
| Puck drop, tied | 0.5568 |
| Tied, 5 minutes left | 0.5164 |
| Home +1, late | 0.9523 |
| Home -1, late | 0.0544 |
| Home +3 at 75% remaining | 0.9179 |
| Home +4 at 75% remaining | 0.9651 (correctly above +3) |
| Tied, overtime | 0.5000 |

Puck drop at 0.5568 sits at the NHL home-win base rate, and overtime is treated
as the coin flip it effectively is.

**There is still no external benchmark for NHL.** ESPN publishes a win
probability curve for NBA, NFL and MLB but not for hockey: 0 of 157,945
harvested snapshots carried `espn_home_wp`. Every NHL number above is measured
against our own baselines only.

## Round 2 experiment (not published)

Round 2 kept the fixed split and used only a chronological, game-level
validation carve-out from 2024-25 for model selection:

- Fit inside train: first 199 2024-25 games / 63,200 snapshots.
- Validation inside train: last 50 2024-25 games / 15,779 snapshots.
- Final test: 2025-26, still untouched until selecting the validation winner.

Validation results:

| Approach | Validation Brier | Validation log loss | Tied Brier | Tied log loss |
| --- | ---: | ---: | ---: | ---: |
| degree-2 logistic regression | 0.152634 | 0.456909 | 0.247962 | 0.689152 |
| degree-3 logistic regression | 0.154223 | 0.460938 | 0.249253 | 0.691886 |
| spline + interaction logistic regression | 0.154452 | 0.461947 | 0.252170 | 0.698600 |
| monotone HistGradientBoosting depth 3 | 0.153907 | 0.459612 | 0.249929 | 0.693376 |
| ExtraTrees | 0.155760 | 0.464920 | 0.252919 | 0.700097 |
| degree-2 logistic + isotonic calibration on validation | **0.147456** | **0.439195** | **0.245723** | **0.684500** |

The validation-selected model was degree-2 logistic regression with isotonic
calibration fit only on the 2024-25 validation games. Its held-out 2025-26
score was:

| Method | Brier | Log loss |
| --- | ---: | ---: |
| Round-2 selected model | 0.176891 | 0.583302 |
| Round-1 published artifact | 0.175683 | 0.517337 |
| Normal baseline (`mu=0.4`, `sigma=2.75`) | **0.175363** | **0.516340** |
| Leader baseline | 0.184228 | 0.551188 |
| Constant 0.5 | 0.250000 | 0.693147 |

Honest bottom line: round 2 fixed some of the tied-state defect but made the
overall held-out model worse, especially log loss, so
`models\live_wp\nhl_live_wp.joblib` was **not overwritten**.

Round-2 tied states: 28,838 snapshots, Brier 0.249711, log loss 0.692611
(round 1: Brier 0.250887, log loss 0.695005). This is a small improvement over
both round 1 and a constant 0.5 Brier, but not enough to justify publishing the
artifact.

Round-2 calibration max gap: 0.0766. ESPN NHL win probability remains
unavailable in this harvest; 0 snapshots had `espn_home_wp`, so there is no ESPN
benchmark.

Round-2 phase breakdown:

| Regulation remaining | Snapshots | Brier | Log loss |
| --- | ---: | ---: | ---: |
| 1.00-0.75 | 19,535 | 0.246321 | 0.688263 |
| 0.75-0.50 | 19,824 | 0.205934 | 0.672497 |
| 0.50-0.25 | 19,843 | 0.150487 | 0.637237 |
| 0.25-0.00 | 19,764 | 0.105646 | 0.335941 |

Round-2 sanity checks:

- Puck drop tied: 0.5331, near the 2025-26 tied-state/home base rate.
- Mid-game: home down 1 = 0.1711, tied = 0.5638, home up 1 = 0.8057.
- One-goal home lead: early = 0.8057, late = 0.9730. This is strong but below
  the explicit "not near 99%" guard.
- Tied OT state: 0.5638.
- Edge states were finite and strictly inside (0, 1).
- Fresh serving check for the unchanged published artifact:
  `predict_home_win_prob(GameState(league='nhl', margin=1, frac_remaining=0.2))`
  returned 0.852593.

## Round 1 held-out 2025-26 results (superseded)

| Method | Brier | Log loss |
| --- | ---: | ---: |
| Model | 0.175683 | 0.517337 |
| Normal baseline (`mu=0.4`, `sigma=2.75`) | 0.175363 | 0.516340 |
| Leader baseline | 0.184228 | 0.551188 |
| Constant 0.5 | 0.250000 | 0.693147 |

The model beats the leader and constant baselines, but it did **not** beat the
normal baseline on this holdout.

Calibration: max calibration gap = 0.0871. Largest bucket miss was 0.2-0.3:
predicted 0.2559, actual 0.1688 over 4,164 snapshots.

## Phase breakdown for the model

| Regulation remaining | Snapshots | Brier | Log loss |
| --- | ---: | ---: | ---: |
| 1.00-0.75 | 19,535 | 0.240329 | 0.672596 |
| 0.75-0.50 | 19,824 | 0.205455 | 0.601825 |
| 0.50-0.25 | 19,843 | 0.151251 | 0.468373 |
| 0.25-0.00 | 19,764 | 0.106454 | 0.328291 |

Tied states: 28,838 snapshots, Brier 0.250887, log loss 0.695005. The model
does not add useful signal on tied states beyond the home/team base rate.

## Sanity checks

- Puck drop tied: 0.5451 (train-season home win rate was 0.5502).
- Mid-game: home down 1 = 0.3141, tied = 0.5966, home up 1 = 0.7895.
- One-goal home lead: early = 0.7100, late = 0.8911.
- Tied OT state: 0.6051.
- Serving check for margin +1, `frac_remaining=0.2`: 0.8526.

A late one-goal lead is strong but not treated as certain.
