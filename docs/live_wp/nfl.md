# NFL live win probability

## Data and split

- Database: `data\live_wp\nfl_snapshots.db`.
- Total: 544 games and 78,767 snapshots from the 2023 and 2024 NFL regular seasons.
- Fixed final holdout: train on 2023 games only (272 games, 39,397 snapshots), test once on 2024 games only (272 games, 39,370 snapshots).
- Model selection used only a 2023 game-level chronological development split: first 70% of games for fitting, next 10% reserved for calibration experiments, final 20% for validation.
- ESPN win probability is a benchmark only, never an input.

## Round 2 model

The saved artifact is `models\live_wp\nfl_live_wp.joblib`.

Selected model: `PolynomialFeatures(degree=3)` over:

- `margin`
- `margin_scaled`
- `frac_remaining`

followed by standardized logistic regression (`C=0.1`). This keeps the frozen serving interface intact while allowing nonlinear lead/time interactions.

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

## Held-out 2024 metrics

| Predictor | Brier | Log loss |
| --- | ---: | ---: |
| **NFL live WP round 2** | **0.164048** | **0.480777** |
| NFL live WP round 1 | 0.166640 | 0.490719 |
| ESPN published WP | 0.145762 | 0.437000 |
| Normal baseline (`mu=0`, `sigma=13.5`, script) | 0.164627 | 0.496034 |
| Leader baseline | 0.189586 | 0.570677 |
| Constant 0.5 | 0.250000 | 0.693147 |

Round 2 honestly improves over round 1 and narrowly beats the fixed normal baseline on Brier, but it still does **not** close the full gap to ESPN.

## Calibration

Max calibration gap over 10 bins with at least 30 samples: **0.0686** (round 1: 0.0875).

## Phase breakdown

| Fraction remaining | N | Model Brier | Model log loss | ESPN Brier | ESPN log loss | Normal Brier | Normal log loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.00-0.75 | 8,510 | 0.237781 | 0.668588 | 0.206101 | 0.599037 | 0.237928 | 0.668002 |
| 0.75-0.50 | 10,740 | 0.194928 | 0.566716 | 0.171548 | 0.511954 | 0.194100 | 0.563171 |
| 0.50-0.25 | 8,978 | 0.144488 | 0.434443 | 0.134699 | 0.410570 | 0.144856 | 0.433939 |
| 0.25-0.00 | 11,142 | 0.093727 | 0.291826 | 0.083698 | 0.262185 | 0.096163 | 0.350009 |

The gain is concentrated late, where the cubic interaction gives the model a much better terminal-game shape. ESPN remains better in every phase.

## Sanity checks

Measured from the saved artifact:

- Margin monotonic at 50% remaining: -14 = 0.105269, -7 = 0.279044, 0 = 0.535869, +7 = 0.764329, +14 = 0.899084.
- Same +7 lead is worth more late: 80% remaining = 0.760118; 20% remaining = 0.848184.
- Edge states are finite and strictly inside (0, 1): tied kickoff = 0.563613, tied at regulation end = 0.478833, +14 at regulation end = 0.999978, -14 at regulation end = 0.000093.

