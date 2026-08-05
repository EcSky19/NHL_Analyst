# NFL baselines and evaluation methodology

Generated: 2026-08-05

Source: nflverse `games.csv` loaded into `data\nfl\nfl_research.db` table `games`. Main numbers below use played regular-season games only: preseason is excluded, postseason is held out of the main benchmark because playoff fields and incentives differ from regular-season forecasting, and 2026/future or null-score rows are excluded.

Ties are not counted as wins or losses for straight-up winner accuracy; they are reported as skipped because the prediction target is a winner. Tied regular-season games skipped: **15**. Played postseason games excluded from these bars: **309**. Preseason rows excluded: **0**. Future/unplayed rows excluded: **272**.

## Reference bars

| Baseline | Games | Correct | Accuracy | Wilson 95% CI | Skipped |
|---|---:|---:|---:|---:|---:|
| Always pick home | 6,952 | 3,905 | 56.17% | 55.00%-57.33% | 15 |
| Vegas moneyline favorite | 5,025 | 3,346 | 66.59% | 65.27%-67.88% | 1,942 |
| Spread-implied favorite | 6,922 | 4,614 | 66.66% | 65.54%-67.76% | 45 |

The Vegas moneyline favorite is the critical bar: it is the market's own straight-up forecast. A future model must be compared to this, not to 50% or to a trivial no-skill reference.

### Per-season trend

| Season | Home acc. (Wilson 95% CI) | Home n | Vegas ML favorite acc. (Wilson 95% CI) | ML n / coverage | Spread favorite acc. (Wilson 95% CI) | Spread n / coverage |
|---:|---:|---:|---:|---:|---:|---:|
| 1999 | 59.68% (53.47%-65.59%) | 248 | NA (NA-NA) | 0 / 0.00% | 66.80% (60.67%-72.41%) | 244 / 98.39% |
| 2000 | 55.65% (49.42%-61.70%) | 248 | NA (NA-NA) | 0 / 0.00% | 65.02% (58.83%-70.74%) | 243 / 97.98% |
| 2001 | 54.84% (48.62%-60.91%) | 248 | NA (NA-NA) | 0 / 0.00% | 65.71% (59.57%-71.37%) | 245 / 98.79% |
| 2002 | 58.04% (51.91%-63.93%) | 255 | NA (NA-NA) | 0 / 0.00% | 62.85% (56.74%-68.57%) | 253 / 99.22% |
| 2003 | 61.33% (55.24%-67.08%) | 256 | NA (NA-NA) | 0 / 0.00% | 67.59% (61.60%-73.06%) | 253 / 98.83% |
| 2004 | 56.64% (50.52%-62.57%) | 256 | NA (NA-NA) | 0 / 0.00% | 66.27% (60.23%-71.82%) | 252 / 98.44% |
| 2005 | 58.98% (52.87%-64.83%) | 256 | NA (NA-NA) | 0 / 0.00% | 74.90% (69.19%-79.86%) | 251 / 98.05% |
| 2006 | 53.12% (47.01%-59.15%) | 256 | 58.17% (51.38%-64.67%) | 208 / 81.25% | 59.38% (53.26%-65.21%) | 256 / 100.00% |
| 2007 | 57.42% (51.30%-63.33%) | 256 | 68.90% (62.96%-74.27%) | 254 / 99.22% | 69.14% (63.23%-74.48%) | 256 / 100.00% |
| 2008 | 57.25% (51.12%-63.17%) | 255 | 66.48% (59.35%-72.94%) | 182 / 71.37% | 68.24% (62.29%-73.64%) | 255 / 100.00% |
| 2009 | 57.03% (50.91%-62.95%) | 256 | 70.54% (64.50%-75.94%) | 241 / 94.14% | 69.53% (63.64%-74.85%) | 256 / 100.00% |
| 2010 | 55.86% (49.73%-61.81%) | 256 | 66.02% (60.01%-71.54%) | 256 / 100.00% | 66.41% (60.42%-71.91%) | 256 / 100.00% |
| 2011 | 56.64% (50.52%-62.57%) | 256 | 67.45% (61.48%-72.91%) | 255 / 99.61% | 66.80% (60.82%-72.28%) | 256 / 100.00% |
| 2012 | 57.25% (51.12%-63.17%) | 255 | 64.31% (58.26%-69.94%) | 255 / 100.00% | 64.31% (58.26%-69.94%) | 255 / 100.00% |
| 2013 | 60.00% (53.88%-65.82%) | 255 | 71.94% (66.10%-77.11%) | 253 / 99.22% | 71.37% (65.54%-76.57%) | 255 / 100.00% |
| 2014 | 56.86% (50.73%-62.80%) | 255 | 66.40% (60.38%-71.94%) | 253 / 99.22% | 66.67% (60.67%-72.17%) | 255 / 100.00% |
| 2015 | 53.91% (47.79%-59.91%) | 256 | 62.06% (55.94%-67.81%) | 253 / 98.83% | 62.50% (56.43%-68.20%) | 256 / 100.00% |
| 2016 | 57.87% (51.73%-63.78%) | 254 | 64.29% (58.20%-69.95%) | 252 / 99.21% | 64.43% (58.35%-70.07%) | 253 / 99.61% |
| 2017 | 56.64% (50.52%-62.57%) | 256 | 71.54% (65.69%-76.75%) | 253 / 98.83% | 70.75% (64.87%-76.01%) | 253 / 98.83% |
| 2018 | 60.24% (54.11%-66.06%) | 254 | 66.67% (60.63%-72.20%) | 252 / 99.21% | 66.14% (60.12%-71.68%) | 254 / 100.00% |
| 2019 | 51.76% (45.65%-57.83%) | 255 | 64.43% (58.35%-70.07%) | 253 / 99.22% | 64.31% (58.26%-69.94%) | 255 / 100.00% |
| 2020 | 49.80% (43.72%-55.90%) | 255 | 67.84% (61.88%-73.27%) | 255 / 100.00% | 67.45% (61.48%-72.91%) | 255 / 100.00% |
| 2021 | 51.66% (45.73%-57.55%) | 271 | 62.36% (56.46%-67.92%) | 271 / 100.00% | 62.36% (56.46%-67.92%) | 271 / 100.00% |
| 2022 | 56.13% (50.16%-61.94%) | 269 | 65.67% (59.80%-71.10%) | 268 / 99.63% | 66.17% (60.32%-71.56%) | 269 / 100.00% |
| 2023 | 55.51% (49.57%-61.30%) | 272 | 68.15% (62.37%-73.42%) | 270 / 99.26% | 68.01% (62.25%-73.27%) | 272 / 100.00% |
| 2024 | 53.31% (47.38%-59.15%) | 272 | 71.59% (65.94%-76.63%) | 271 / 99.63% | 71.32% (65.68%-76.37%) | 272 / 100.00% |
| 2025 | 53.87% (47.93%-59.71%) | 271 | 65.56% (59.70%-70.97%) | 270 / 99.63% | 65.31% (59.47%-70.73%) | 271 / 100.00% |

Home-field accuracy declined from an average **57.30%** across the first 10 seasons in this file to **54.10%** across the latest five completed seasons. Treat home advantage as time-varying.

## Realistic ceiling

Published NFL models and the betting market usually land in the mid-to-high 60s for straight-up winner accuracy. Matching the closing moneyline favorite is already an excellent result; consistently beating it out of sample is very hard. A one-season result a point or two above Vegas is not a breakthrough unless it survives the holdout policy and the noise-floor thresholds below.

## Evaluation harness design

- Use expanding-window walk-forward validation by season: train on all prior eligible seasons and predict the next season.
- Main development folds use regular season only. Postseason can be evaluated as a separately labeled stress test, never mixed into headline regular-season accuracy.
- Preseason is always excluded.
- Future/unplayed games and any rows with null scores are always excluded.
- Ties are excluded from winner-accuracy denominators and counted as skipped.
- Strict holdout seasons are **2024, 2025**. The harness excludes them by default and only includes them if the caller passes the explicit unlock token `I_UNDERSTAND_THIS_TOUCHES_NFL_HOLDOUT_ONCE`.
- `data\nfl\walk_forward_folds.csv` records the currently available non-holdout folds.
- `scripts\nfl\evaluation_harness.py compare` reports accuracy, Wilson 95% intervals, and pairwise indistinguishability flags for future model variants.

## Noise floor

Approximate standard errors and minimum detectable differences below use p=67%, close to the NFL market/model ceiling. The minimum detectable difference is the 95% two-model difference threshold under an independent-proportion approximation; paired tests may be more efficient, but claims smaller than these values should be presumed noise unless independently replicated.

| Sample | Games | SE | Minimum detectable difference |
|---|---:|---:|---:|
| One recent regular season | 271 | 2.86 pp | 7.92 pp |
| Three recent regular seasons | 815 | 1.65 pp | 4.57 pp |
| Full 2002-present regular-season era | 6,208 | 0.60 pp | 1.65 pp |

Practical rule: a single modern NFL season needs roughly an eight-point accuracy gap before two variants are clearly separated. Three seasons still need roughly five points. Over the full 2002-present regular-season sample, differences around 1.6-1.7 pp are the smallest worth discussing statistically; smaller selected-on-test gains should be treated as noise.

## Current non-holdout walk-forward folds

| Test season | Train seasons | Holdout? |
|---:|---|---:|
| 2004 | 1999-2003 | False |
| 2005 | 1999-2004 | False |
| 2006 | 1999-2005 | False |
| 2007 | 1999-2006 | False |
| 2008 | 1999-2007 | False |
| 2009 | 1999-2008 | False |
| 2010 | 1999-2009 | False |
| 2011 | 1999-2010 | False |
| 2012 | 1999-2011 | False |
| 2013 | 1999-2012 | False |
| 2014 | 1999-2013 | False |
| 2015 | 1999-2014 | False |
| 2016 | 1999-2015 | False |
| 2017 | 1999-2016 | False |
| 2018 | 1999-2017 | False |
| 2019 | 1999-2018 | False |
| 2020 | 1999-2019 | False |
| 2021 | 1999-2020 | False |
| 2022 | 1999-2021 | False |
| 2023 | 1999-2022 | False |
