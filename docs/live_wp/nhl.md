# NHL live win probability

The NHL artifact is still the two-parameter analytic normal baseline, not a
learned model.  After the snapshot database was expanded to complete regular
seasons, learned models again looked better on a train-season validation split
but failed to beat the refit baseline on the untouched 2025-26 holdout.

## Data and split

- Database: `data\live_wp\nhl_snapshots.db`.
- Train: 2024-25, 1,312 games / 416,699 snapshots.
- Test: 2025-26, 1,312 games / 410,454 snapshots.
- Split is by game and season; train/test game overlap is 0.
- Model tuning used only a chronological game-level validation split carved
  from 2024-25: 1,049 fit games / 333,641 snapshots and 263 validation games /
  83,058 snapshots.
- ESPN NHL win probability benchmark remains unavailable: 0 snapshots carry
  `espn_home_wp`.

Labels use the final NHL result, including overtime/shootout. Regulation
`frac_remaining` is 0.0 in overtime; snapshots from period 4+ set
`is_overtime=1`.

## Full-season retrain result

The old published baseline parameters were `mu=0.3908`, `sigma=2.7339`. Refit
on the full 2024-25 training season by log loss, the baseline is:

```text
NormalBaselineModel(mu=0.4627, sigma=2.8187)
```

Held-out 2025-26:

| Method | Brier | Log loss | Max calibration gap | Shipped |
| --- | ---: | ---: | ---: | :---: |
| Old baseline params (`0.3908`, `2.7339`) | 0.174603 | 0.513313 | 0.0590 | no |
| **Refit analytic baseline (`0.4627`, `2.8187`)** | **0.174911** | **0.513699** | **0.0456** | **yes** |
| Best validation-selected learned blend | 0.175321 | 0.513911 | 0.0533 | no |

The old parameters happened to score slightly better on 2025-26, but the fair
baseline for this retrain is the model refit on the expanded 2024-25 training
season. No learned model beat that refit baseline on held-out log loss, so the
artifact remains analytic.

## Validation experiments

Validation baseline fit on the 1,049 fit games scored Brier **0.174529**, log
loss **0.512757** on the 263 validation games.

| Approach | Raw validation Brier | Raw validation log loss | Best simple baseline-blend log loss | Best monotone-envelope validation log loss |
| --- | ---: | ---: | ---: | ---: |
| Polynomial degree-2 logistic, C=0.05 | 0.174669 | 0.509588 | 0.508639 (alpha=0.55) | 0.508640 (alpha=0.60) |
| Polynomial degree-2 logistic, C=0.20 | 0.174594 | 0.509416 | 0.508858 (alpha=0.50) | 0.508884 (alpha=0.40) |
| HGB, leaf 200, l2=0.05 | 0.174110 | 0.508742 | 0.508605 (alpha=0.20) | 0.508822 (alpha=0.40) |
| **HGB, leaf 400, l2=0.20** | **0.174006** | **0.508545** | 0.508457 (alpha=0.20) | **0.508465 (alpha=0.20)** |
| ExtraTrees, leaf 300 | 0.174400 | 0.508903 | **0.508359 (alpha=0.40)** | rejected: non-monotone and >10 ms |

The selected shippable learned candidate was the HGB leaf-400 model with a 20%
normal-baseline blend and cumulative monotone envelope. It passed the shape and
latency gates on validation, but on 2025-26 scored Brier **0.175321**, log loss
**0.513911**, which is worse than the refit baseline's **0.513699** log loss.

## Monotonicity and latency

The final learned candidate, though not shipped, passed the requested shape
checks before the held-out comparison:

- Margin monotonicity: 0 drops over margins -10..10 at 41 time points.
- Time monotonicity: 0 wrong-way steps for margins ±1, ±2, ±3, ±4 over 40
  steps.
- Fresh-process candidate latency during training: 5.712 ms/call.

The shipped analytic baseline verified independently with:

```powershell
$env:PYTHONPATH="."; python scripts\live_wp\verify_artifacts.py nhl 2024-25 2025-26
```

Reproduced artifact metrics: Brier **0.174911**, log loss **0.513699**,
calibration gap **0.0456**, train/test game overlap **0**, margin monotone
`True`, and time monotone `True` for checked positive margins. Fresh serving
latency for the shipped baseline was about **0.04 ms/call**.

## Honest conclusion

The data-starvation hypothesis did not hold up. With 5.3x more NHL training
games, flexible learned models improved validation loss, but the best
shipping-eligible learned model still failed the held-out log-loss gate. NHL
continues to ship the analytic normal baseline and still has no external ESPN
benchmark.

Two caveats on the refit, stated plainly:

- The pre-expansion parameters score **better** on the held-out season
  (0.174603 vs 0.174911 Brier). A block bootstrap resampled by game puts the
  difference at `[-0.000565, -0.000036]`, so it is small but does not straddle
  zero. We shipped the refit anyway: the only way to learn that the old
  parameters won here was to look at the holdout, and picking parameters on
  that basis is selecting on the test set.
- Counting rounds 1-3 below, **eight** learned NHL models across four rounds
  have now failed to beat a two-line formula. At some point that stops being a
  tuning problem and starts being evidence that score and clock alone are
  close to sufficient for hockey.

## Earlier rounds (preserved history)

This history is kept deliberately. This repository has already had to retract
fabricated accuracy claims once, and the record of what failed is part of why
the current numbers can be trusted.

Rounds 1 and 2 were run on a much smaller harvest (497 games / 157,945
snapshots, `--max-games 500 --per-season 250`) and trained seven learned models
between them. Not one beat the baseline on held-out data.

**Round 3 found a second, worse problem in the round-1 artifact: it was not
monotone in margin.** At 75% of regulation remaining it rated a four-goal home
lead at 0.809, *below* the 0.821 it gave a three-goal lead. A win probability
display that says a team got worse by scoring is not shippable at any Brier
score. That defect is the direct ancestor of the margin-monotonicity gate that
every league must now pass.

Held-out 2025-26 on the old small sample:

| Method | Brier | Log loss | Monotone in margin |
| --- | ---: | ---: | :---: |
| Analytic baseline (`mu=0.3908`, `sigma=2.7339`) | 0.175316 | 0.515720 | yes |
| Round-1 logistic artifact | 0.175683 | 0.517337 | **no** |
| Round-2 isotonic-calibrated logistic | 0.176891 | 0.583302 | — |
| Leader baseline | 0.184228 | 0.551188 | yes |
| Constant 0.5 | 0.250000 | 0.693147 | — |

On tied states (28,838 snapshots) the baseline scored 0.248675 against round
1's 0.250887. Round 1 was *worse than a constant 0.5* on tied games, which is
the least a win probability model should clear.

The round-3 trade-off was accepted knowingly: the baseline's max calibration
gap (0.1064) was worse than the round-1 model's (0.0871), but the baseline won
both headline metrics and was monotone, while round 1's calibration edge came
attached to a defect that produced visibly absurd output.

Note that these numbers were measured on the old 248-game holdout and are
**not** comparable to the full-season figures above.
