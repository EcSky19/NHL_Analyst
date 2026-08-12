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

Ship whichever candidate wins held-out **log loss**, subject to two hard gates
on the shape of the predicted probability surface:

1. **Monotone in margin** — non-decreasing in home margin at every time point.
2. **Monotone in time** — at a fixed positive margin, non-decreasing as the
   clock runs out. A lead must gain value as the time available to overturn it
   disappears.

A candidate that fails either gate is disqualified regardless of its aggregate
score.

Gate 2 was added late, after gate 1 had already been used to select every
shipped model. Auditing against it retroactively found that **NFL and MLB had
been shipped in violation of it**: holding the lead fixed and running the clock
down in 40 steps, NFL fell on 19 of 40 steps (worst single drop 0.00397 at +3)
and MLB on 6 of 40 (worst 0.00299 at +1). NHL and NBA were clean at 0 of 40.
The reversals were small and the overall trend was correct in both leagues, but
they were user-visible: the live view could tick a leading team downward when
nothing had happened to them.

Both were then refit to satisfy gate 2, and both came out *better* on held-out
log loss than the models they replaced, so nothing was traded away to get the
correct shape. See the per-league docs.

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
| NBA | 0.167947 | 0.166237 (not a significant difference) | **0.157319** |
| NFL | 0.164048 | 0.163775 (not a significant difference) | **0.145762** |
| MLB | **0.154604** | 0.155233 | 0.153735 (partial coverage) |
| NHL | 0.175316 (is the baseline) | — | none published |

Read those tables plainly:

- ESPN's published win-probability model beats ours in every league where ESPN
  publishes one. We do not claim parity. The gap is largest in the NFL.
- Under Brier, NBA and NFL do **not** measurably differ from the two-parameter
  analytic baseline. An earlier version of this page said they "lose" to it, and
  that was an overstatement in the same family as the accuracy claims this repo
  has already retracted -- it read a difference off correlated snapshots without
  asking whether the difference was larger than noise. Re-measured with a
  game-level cluster bootstrap (3,000 resamples, resampling whole `game_id`s)
  on the current full-season artifacts, the Brier differences against a Brier-fit
  baseline are NFL +0.000128 [-0.001913, +0.002123] over 272 games and NBA
  -0.000133 [-0.000324, +0.000052] over 1,231 games. Both span zero. They ship
  because they win log loss, which is the policy tiebreaker, and because there
  is no measurable Brier cost to doing so -- not because we accept a known Brier
  loss.
- The log-loss wins are not all equally solid either. NBA's survives both
  baseline parameterisations comfortably (-0.026752 [-0.038032, -0.016583]
  against a log-loss-fit baseline). NFL's does not: against a log-loss-fit
  baseline, which is the fairer opponent on that metric, it is -0.008985
  [-0.017856, +0.000077], which touches zero. A 272-game NFL season is simply
  too small to settle it, and the table above should be read with that in mind.
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

### The artifacts are not self-contained

A `.joblib` here does **not** freeze the model's behaviour. Pickle stores a
*reference* to the model class, not its code, and these classes live in the
training scripts:

```python
>>> type(joblib.load("models/live_wp/mlb_live_wp.joblib")["model"]).__module__
'scripts.live_wp.train_mlb'
```

So the arrays are frozen but the logic is whatever `scripts/live_wp/train_*.py`
says **today**. Editing a training script can change what production serves
with no retrain, and checking out an old artifact does not give you the old
model.

That breaks the obvious way to measure a change:

```powershell
# WRONG - scores the OLD artifact with the NEW class code
git show HEAD:models/live_wp/mlb_live_wp.joblib > old.joblib
```

We used exactly that method and it silently reported a change of **zero** on
every one of 1.39M held-out snapshots, because both sides were running the new
rule. The correct method pins source and artifact together:

```powershell
git worktree add --detach $env:TEMP\old_tree <commit>
# score the old artifact inside the old worktree, the new one in the repo,
# feeding both an identical feature matrix, then compare
git worktree remove --force $env:TEMP\old_tree
```

Whether the shortcut happens to be safe depends on how much of a model's
behaviour is *data* versus *code*, which differs per league and is not
obvious:

- **NBA** (`GridBlendModel`) serves predictions by interpolating a grid that is
  pickled into the artifact. The class code mostly builds that grid at training
  time, so an old artifact keeps behaving like the old model. Re-checking the
  published overtime numbers with the pinned method reproduced them exactly
  (overtime log loss 0.570655 to 0.428562, overtime Brier 0.164774 to 0.142148,
  full season 0.164364 to 0.164083).
- **MLB** (`MonotoneBlendModel`) applies rules such as the walk-off case in
  live class code at predict time, so an old artifact adopts new behaviour
  immediately and the shortcut compares a model to itself.

You cannot tell which case you are in without looking, so always pin.

## Per-league details

- [NHL](nhl.md)
- [NFL](nfl.md)
- [NBA](nba.md)
- [MLB](mlb.md)
