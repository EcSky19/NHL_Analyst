# Live win probability

Live game rows expose a `win_probability` field: the modelled chance that the
**home** team wins, given the current score and time remaining. These are model
estimates, not betting lines, and they are not accurate enough to bet on.

## Candidate predictors

Each league has two candidate live win-probability predictors:

1. a learned model, either logistic or gradient-boosted, trained on in-game
   snapshots; and
2. a two-parameter analytic baseline implemented as `NormalBaselineModel` in
   `app/services/live_wp_baseline.py`.

The analytic baseline treats the remaining scoring margin as
`Normal(mu*f, sigma^2*f)`, where `f` is the fraction of regulation remaining,
and returns `P(final margin > 0)`.

## Selection policy

Ship whichever candidate wins held-out **log loss**, subject to one hard gate:
the predicted probability must be monotone non-decreasing in home margin at
every time point. A candidate that fails the monotonicity gate is disqualified
regardless of its aggregate score.

Log loss is the tiebreaking metric because it is a proper scoring rule and is
far more sensitive than Brier to overconfident tail predictions. That is exactly
the failure mode that matters when displaying a probability to a user. Brier is
reported too, and honestly, but it is not the tiebreaker.

Monotonicity is a hard gate because a model that says a team got worse by
scoring is indefensible to show a user. This is not hypothetical: the NHL
round-1 learned model rated a 4-goal lead at 0.809, below the 0.821 it gave a
3-goal lead, at 75% of regulation remaining.

## Current shipped predictors

Held-out log loss as of this commit:

| League | Learned model log loss | Analytic baseline log loss | Monotone? | **Ships** |
|---|---:|---:|:---:|---|
| NBA | **0.491963** | 0.509335 | yes | learned model |
| NFL | **0.480777** | 0.489634 | yes | learned model |
| MLB | **0.463933** | 0.487293 | yes | learned model |
| NHL | 0.517337 | **0.515720** | learned model was NOT monotone | **analytic baseline** |

Corresponding Brier scores:

| League | Ours (Brier) | Analytic baseline (Brier) | ESPN (Brier) |
|---|---:|---:|---:|
| NBA | 0.167947 | **0.166237** | **0.157319** |
| NFL | 0.164048 | **0.163775** | **0.145762** |
| MLB | **0.154604** | 0.155233 | 0.153735 (partial coverage) |
| NHL | 0.175316 (is the baseline) | — | none published |

Read those tables plainly:

- ESPN's published win-probability model beats ours in every league where ESPN
  publishes one. We do not claim parity. The gap is largest in the NFL.
- Under Brier, NBA and NFL lose to the two-parameter analytic baseline. They
  ship anyway because the policy tiebreaker is log loss, where they win. That is
  a deliberate, documented choice, not an oversight.
- MLB is the only league that beats the analytic baseline on both metrics.
- NHL ships the analytic baseline because it wins log loss and the learned model
  failed the monotonicity gate.
- ESPN publishes no win-probability curve for NHL at all: 0 of 157,945
  harvested NHL snapshots carried an ESPN value, so NHL has no external
  benchmark.

## Methodology

The models are trained on in-game snapshots harvested from ESPN play-by-play:
about 780k snapshots over 2,069 games. Splits are **by game, never by
snapshot**. Snapshots within a game share one final label and are heavily
correlated, so a snapshot-level split leaks and yields meaningless scores.

To re-verify a league's published claims, run:

```powershell
$env:PYTHONPATH="."; python scripts\live_wp\verify_artifacts.py <league> <train_season> <test_season>
```

Examples:

```powershell
$env:PYTHONPATH="."; python scripts\live_wp\verify_artifacts.py nba 2023 2024
$env:PYTHONPATH="."; python scripts\live_wp\verify_artifacts.py nhl 2024-25 2025-26
$env:PYTHONPATH="."; python scripts\live_wp\verify_artifacts.py nfl 2023 2024
$env:PYTHONPATH="."; python scripts\live_wp\verify_artifacts.py mlb 2024 2025
```

The verification script deliberately re-derives every metric from the snapshot
database instead of trusting numbers stored in the artifact.

## Per-league details

- [NHL](nhl.md)
- [NFL](nfl.md)
- [NBA](nba.md)
- [MLB](mlb.md)
