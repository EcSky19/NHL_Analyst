# NFL feature engineering

Generated: 2026-08-05T20:12:10+00:00

## Scope and integrity

- Built table: `nfl_features` in `data\nfl\nfl_research.db`.
- Rows: 4,363 played, non-preseason games from 2010 onward; unplayed/future rows excluded.
- Non-tie binary outcome rows: 4,350. Ties are retained with `target_home_win` NULL.
- Source rows available: games=4,363, team EPA=8,726, QB weekly=9,874.
- No synthetic, simulated, randomly generated, or silently imputed data was created. Missing values remain NULL.
- Week 1/cold starts: trailing 3/5/8 features carry prior-season games when available; season-to-date features are NULL until a team has played earlier in the same season.
- Opponent adjustment: not applied in this version. Implementing it leakage-safely would require a second pass of opponent pregame rolling baselines; raw rolling EPA is stored instead.

## Rows by season

| season | rows |
| --- | ---: |
| 2010 | 267 |
| 2011 | 267 |
| 2012 | 267 |
| 2013 | 267 |
| 2014 | 267 |
| 2015 | 267 |
| 2016 | 267 |
| 2017 | 267 |
| 2018 | 267 |
| 2019 | 267 |
| 2020 | 269 |
| 2021 | 285 |
| 2022 | 284 |
| 2023 | 285 |
| 2024 | 285 |
| 2025 | 285 |

## Selected feature coverage

| feature | non-null coverage | null rate |
| --- | ---: | ---: |
| `home_moneyline_implied_no_vig` | 99.98% | 0.02% |
| `spread_line` | 100.00% | 0.00% |
| `home_offensive_epa_per_play_last5` | 99.63% | 0.37% |
| `away_offensive_epa_per_play_last5` | 99.63% | 0.37% |
| `home_offensive_epa_per_play_season_to_date` | 94.13% | 5.87% |
| `home_qb_passing_epa_per_dropback_last5` | 98.53% | 1.47% |
| `home_qb_changed_from_previous_game` | 99.63% | 0.37% |
| `temp` | 67.93% | 32.07% |
| `wind` | 67.93% | 32.07% |
| `away_travel_timezone_abs` | 100.00% | 0.00% |

## Features with >50% missingness

| feature | null rate |
| --- | ---: |
| None | 0.00% |

## Leakage verification

- Source-date columns checked: 4.
- Rolling/QB source-date violations (`source_date >= gameday`): 0.
- Forbidden score columns in feature table: [].
- Linear holdout score-margin reconstruction check (train <=2022, test 2023-2025): R²=0.165, exact rounded-margin reconstruction=3.04%.
- Result: PASSED.

## Key correlations with home win

| rank | feature | Pearson r | n |
| ---: | --- | ---: | ---: |
| 1 | `home_moneyline_implied_no_vig` | 0.381 | 4,349 |
| 2 | `spread_line` | 0.380 | 4,350 |
| 3 | `elo_diff_with_hfa` | 0.296 | 4,350 |
| 4 | `diff_offensive_epa_per_play_last5` | 0.250 | 4,334 |
| 5 | `diff_pass_epa_per_play_last5` | 0.239 | 4,334 |
| 6 | `home_elo_pregame` | 0.212 | 4,350 |
| 7 | `diff_qb_passing_epa_per_dropback_last5` | 0.197 | 4,246 |
| 8 | `diff_qb_passing_cpoe_last5` | 0.163 | 4,246 |
| 9 | `diff_defensive_epa_per_play_allowed_last5` | -0.130 | 4,334 |
| 10 | `diff_qb_prior_starts` | 0.120 | 4,350 |
| 11 | `temp` | -0.035 | 2,955 |
| 12 | `rest_diff_home_minus_away` | 0.035 | 4,350 |
| 13 | `division_game` | -0.013 | 4,350 |
| 14 | `wind` | -0.006 | 2,955 |

## Feature families

- Team strength: pregame Elo, Elo differential, neutral-site-aware home-field adjustment.
- Rolling EPA form: trailing 3/5/8 and season-to-date offense/defense EPA, pass/rush splits, success, third-down/red-zone, turnovers, and home-minus-away differentials.
- Quarterback: listed starter rolling EPA/CPOE, starter-change flags, and prior-starts proxy.
- Situational: rest, short week, post-bye, Thursday, division, neutral site, roof/weather, and timezone travel burden.
- Market: spread, total, moneylines, raw and no-vig implied probabilities. These columns are explicitly named and can be excluded for non-market model runs.
