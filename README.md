# NHL Analyst

This repository builds and evaluates pregame NHL win-probability models from historical game, team, roster, goalie, schedule, and matchup features. It is useful for researching modest predictive edges, calibration, confidence tiers, and model failure modes in a high-variance sport.

## Honest current benchmark

Previous headline accuracy claims of **61.66%**, **61.89%**, and **62.04%** are retracted. They should not be used as evidence of model quality.

The corrected benchmark is a real-only, no-market expanding walk-forward evaluation over 5,248 games:

| Test season | Games | Accuracy |
|---|---:|---:|
| 2022-23 | 1,312 | 59.07% |
| 2023-24 | 1,312 | 58.23% |
| 2024-25 | 1,312 | 56.78% |
| 2025-26 | 1,312 | 53.20% |
| **Overall** | **5,248** | **56.82%** |

This is a real but modest edge over an always-pick-home baseline of roughly 52-54%, not a 60%+ all-games system.

Primary audit: `data\reports\data_integrity_audit.md`.

## Confidence tiers

Clean pooled verification found that 70%+ accuracy survives only at very high model confidence and very low coverage:

| Minimum confidence | Games | Coverage | Accuracy | Wilson 95% CI |
|---|---:|---:|---:|---:|
| >=0.65 | 698 | 13.30% | 70.06% | 66.56%-73.34% |
| >=0.70 | 177 | 3.37% | 77.40% | 70.70%-82.94% |

The `>=0.65` tier has a 70% point estimate, but its confidence interval lower bound is below 70%. The only statistically defensible 70%+ finding is `confidence >= 0.70`, and it covers just 177 games.

Primary verification: `data\reports\confidence_tiers_clean_verification.md`.

## Data integrity incident

A 2026-08-05 audit found two major contamination sources:

1. `scripts\generate_synthetic_historical_data.py` fabricated the 2015-16, 2016-17, and 2017-18 seasons using seeded random generation. Quarantine scope: 1,406 fabricated game/feature rows, 59,052 roster/stat rows, and 2,812 team pregame rows.
2. `scripts\fetch_market_signals.py` did not fetch real betting odds. It synthesized "market" and "Vegas" features from pregame statistics already available to the model, including season points percentage, last-10 percentage, goal differential, and home/road splits. Any measured "market lift" was circular.

The contaminated rows and artifacts were marked rather than deleted. Honest evaluation must exclude synthetic rows and market proxy features.

## What is genuinely true

- Honest all-games accuracy is about **56.8%** on the current clean benchmark.
- The model beats simple baselines, but the edge is modest.
- The confidence-tier result is real only at `confidence >= 0.70`, with **3.37%** coverage.
- About **6,084 genuinely real historical games from 2015-2020** have now been ingested from the NHL API with era-correct team handling: Arizona present, Utah/Seattle absent, and Vegas beginning in 2017-18.
- Expanded real-data retraining is in progress and can be appended later, for example in `data\reports\real_expanded_retrain_results.md`.

## What is not true

- This repo does **not** currently demonstrate 61.66%, 61.89%, or 62.04% honest all-games accuracy.
- This repo does **not** contain real historical Vegas odds in the synthetic market artifacts.
- This repo does **not** show that 70% accuracy is attainable across all NHL games.

Realistic context: published NHL prediction models and market favorites typically land around the low 60s at best, with Vegas closing favorites around 60%. NHL outcomes have high game-to-game variance, so 70% all-games accuracy is not a realistic target for a pregame model.

## Reading old reports

Older reports are retained for history. Reports with invalidated accuracy claims or market-feature interpretations now carry correction notices at the top. When in doubt, prefer:

- `data\reports\data_integrity_audit.md`
- `data\reports\confidence_tiers_clean_verification.md`
