# NFL ingestion report
Generated: 2026-08-05T20:01:43+00:00
## Source and provenance
- Source URL: `https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv`
- Downloaded at (UTC): `2026-08-05T20:01:43+00:00`
- Raw file: `C:\Users\t-ecoskay\Sports_analytics\data\nfl\games.csv` (2,172,887 bytes)
- SQLite database: `C:\Users\t-ecoskay\Sports_analytics\data\nfl\nfl_research.db`
- Rows ingested: 7,548
- Seasons covered: 1999-2026 (28 seasons)
Every `games` row includes `source_url` and `downloaded_at_utc`; no synthetic, simulated, randomized, or imputed game rows were created.
## Schema
The `games` table preserves every nflverse source column exactly by name and adds explicit derived data-quality/provenance columns. Numeric source columns are stored with SQLite numeric affinity where appropriate; blanks are stored as NULL.

Derived columns:
- `source_url`, `downloaded_at_utc`: row-level provenance.
- `played` / `unplayed`: score/result completeness flags. Future or scheduled rows with NULL scores are `unplayed=1` and must be excluded from training/evaluation.
- `tie_game`: `1` when `result == 0` on a played game.
- `home_win`: binary label for non-tie played games only (`1` if `result > 0`, `0` if `result < 0`, NULL for ties/unplayed).
- `season_phase`: `REG`, `POST`, or `PRE`; `is_preseason`, `is_regular_season`, and `is_postseason` are one-hot flags.
- `away_team_normalized`, `home_team_normalized`, `unknown_team_alias`, `data_quality_notes`: team-alias and row-quality fields.
Additional tables: `team_alias_map`, `season_team_validation`, `season_quality`, and `ingestion_metadata`.

## Tie handling decision
NFL regular-season games can end tied. Ties are explicitly flagged and **excluded from binary win/loss modeling** by setting `home_win=NULL`; they are not coerced to home wins/losses. Current tied played games: 15.

## Overall data quality
| rows | played | unplayed | ties | binary_games | home_win_rate | away_moneyline_coverage | home_moneyline_coverage | spread_line_coverage | total_line_coverage | qb_id_pair_coverage | qb_name_pair_coverage | temp_coverage | wind_coverage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 7548 | 7276 | 272 | 15 | 7261 | 56.42% | 72.77% | 72.77% | 100.00% | 100.00% | 100.00% | 100.00% | 71.55% | 71.55% |

## Game phase counts
| season_phase | rows | played | unplayed |
|---|---|---|---|
| POST | 309 | 309 | 0 |
| REG | 7239 | 6967 | 272 |

## Per-season coverage and home win rate
| season | games | reg_games | post_games | pre_games | played_games | unplayed_games | ties | binary_model_games | home_win_rate | away_moneyline_coverage | home_moneyline_coverage | spread_line_coverage | total_line_coverage | qb_id_pair_coverage | qb_name_pair_coverage | temp_coverage | wind_coverage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1999 | 259 | 248 | 11 | 0 | 259 | 0 | 0 | 259 | 59.85% | 0.00% | 0.00% | 100.00% | 100.00% | 100.00% | 100.00% | 76.06% | 76.06% |
| 2000 | 259 | 248 | 11 | 0 | 259 | 0 | 0 | 259 | 56.37% | 0.00% | 0.00% | 100.00% | 100.00% | 100.00% | 100.00% | 79.92% | 79.92% |
| 2001 | 259 | 248 | 11 | 0 | 259 | 0 | 0 | 259 | 55.60% | 0.00% | 0.00% | 100.00% | 100.00% | 100.00% | 100.00% | 80.31% | 80.31% |
| 2002 | 267 | 256 | 11 | 0 | 267 | 0 | 1 | 266 | 59.02% | 0.00% | 0.00% | 100.00% | 100.00% | 100.00% | 100.00% | 79.03% | 79.03% |
| 2003 | 267 | 256 | 11 | 0 | 267 | 0 | 0 | 267 | 61.42% | 0.00% | 0.00% | 100.00% | 100.00% | 100.00% | 100.00% | 77.90% | 77.90% |
| 2004 | 267 | 256 | 11 | 0 | 267 | 0 | 0 | 267 | 56.55% | 0.00% | 0.00% | 100.00% | 100.00% | 100.00% | 100.00% | 78.28% | 78.28% |
| 2005 | 267 | 256 | 11 | 0 | 267 | 0 | 0 | 267 | 58.43% | 0.00% | 0.00% | 100.00% | 100.00% | 100.00% | 100.00% | 80.15% | 80.15% |
| 2006 | 267 | 256 | 11 | 0 | 267 | 0 | 0 | 267 | 53.93% | 82.40% | 82.40% | 100.00% | 100.00% | 100.00% | 100.00% | 74.91% | 74.91% |
| 2007 | 267 | 256 | 11 | 0 | 267 | 0 | 0 | 267 | 56.93% | 99.63% | 99.63% | 100.00% | 100.00% | 100.00% | 100.00% | 75.28% | 75.28% |
| 2008 | 267 | 256 | 11 | 0 | 267 | 0 | 1 | 266 | 56.77% | 72.66% | 72.66% | 100.00% | 100.00% | 100.00% | 100.00% | 74.91% | 74.91% |
| 2009 | 267 | 256 | 11 | 0 | 267 | 0 | 0 | 267 | 57.30% | 94.76% | 94.76% | 100.00% | 100.00% | 100.00% | 100.00% | 70.04% | 70.04% |
| 2010 | 267 | 256 | 11 | 0 | 267 | 0 | 0 | 267 | 55.43% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 71.91% | 71.91% |
| 2011 | 267 | 256 | 11 | 0 | 267 | 0 | 0 | 267 | 57.30% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 71.54% | 71.54% |
| 2012 | 267 | 256 | 11 | 0 | 267 | 0 | 1 | 266 | 57.14% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 71.54% | 71.54% |
| 2013 | 267 | 256 | 11 | 0 | 267 | 0 | 1 | 266 | 59.77% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 72.66% | 72.66% |
| 2014 | 267 | 256 | 11 | 0 | 267 | 0 | 1 | 266 | 57.52% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 74.91% | 74.91% |
| 2015 | 267 | 256 | 11 | 0 | 267 | 0 | 0 | 267 | 54.31% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 75.28% | 75.28% |
| 2016 | 267 | 256 | 11 | 0 | 267 | 0 | 2 | 265 | 58.49% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 74.16% | 74.16% |
| 2017 | 267 | 256 | 11 | 0 | 267 | 0 | 0 | 267 | 56.93% | 99.63% | 99.63% | 100.00% | 100.00% | 100.00% | 100.00% | 74.91% | 74.91% |
| 2018 | 267 | 256 | 11 | 0 | 267 | 0 | 2 | 265 | 59.62% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 73.78% | 73.78% |
| 2019 | 267 | 256 | 11 | 0 | 267 | 0 | 1 | 266 | 52.26% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 73.41% | 73.41% |
| 2020 | 269 | 256 | 13 | 0 | 269 | 0 | 1 | 268 | 50.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 65.43% | 65.43% |
| 2021 | 285 | 272 | 13 | 0 | 285 | 0 | 1 | 284 | 51.76% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 67.02% | 67.02% |
| 2022 | 284 | 271 | 13 | 0 | 284 | 0 | 2 | 282 | 56.74% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 37.68% | 37.68% |
| 2023 | 285 | 272 | 13 | 0 | 285 | 0 | 0 | 285 | 56.49% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 55.44% | 55.44% |
| 2024 | 285 | 272 | 13 | 0 | 285 | 0 | 0 | 285 | 54.74% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 63.86% | 63.86% |
| 2025 | 285 | 272 | 13 | 0 | 285 | 0 | 1 | 284 | 53.52% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 66.67% | 66.67% |
| 2026 | 272 | 272 | 0 | 0 | 0 | 272 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## Team normalization and validation
Teams are normalized to stable current franchise-style codes before joining. Relocation/rebrand aliases are explicit, including STL/LA/LAR -> LAR, SD/LAC -> LAC, OAK/LV -> LV, WSH/WAS -> WAS, and JAC/JAX -> JAX.

| season | normalized_distinct_teams | expected_distinct_teams | team_count_ok |
|---|---|---|---|
| 1999 | 31 | 31 | 1 |
| 2000 | 31 | 31 | 1 |
| 2001 | 31 | 31 | 1 |
| 2002 | 32 | 32 | 1 |
| 2003 | 32 | 32 | 1 |
| 2004 | 32 | 32 | 1 |
| 2005 | 32 | 32 | 1 |
| 2006 | 32 | 32 | 1 |
| 2007 | 32 | 32 | 1 |
| 2008 | 32 | 32 | 1 |
| 2009 | 32 | 32 | 1 |
| 2010 | 32 | 32 | 1 |
| 2011 | 32 | 32 | 1 |
| 2012 | 32 | 32 | 1 |
| 2013 | 32 | 32 | 1 |
| 2014 | 32 | 32 | 1 |
| 2015 | 32 | 32 | 1 |
| 2016 | 32 | 32 | 1 |
| 2017 | 32 | 32 | 1 |
| 2018 | 32 | 32 | 1 |
| 2019 | 32 | 32 | 1 |
| 2020 | 32 | 32 | 1 |
| 2021 | 32 | 32 | 1 |
| 2022 | 32 | 32 | 1 |
| 2023 | 32 | 32 | 1 |
| 2024 | 32 | 32 | 1 |
| 2025 | 32 | 32 | 1 |
| 2026 | 32 | 32 | 1 |

### Alias map
| source_team | normalized_team | description |
|---|---|---|
| ARI | ARI | Arizona Cardinals |
| ATL | ATL | Atlanta Falcons |
| BAL | BAL | Baltimore Ravens |
| BUF | BUF | Buffalo Bills |
| CAR | CAR | Carolina Panthers |
| CHI | CHI | Chicago Bears |
| CIN | CIN | Cincinnati Bengals |
| CLE | CLE | Cleveland Browns |
| DAL | DAL | Dallas Cowboys |
| DEN | DEN | Denver Broncos |
| DET | DET | Detroit Lions |
| GB | GB | Green Bay Packers |
| HOU | HOU | Houston Texans |
| IND | IND | Indianapolis Colts |
| JAC | JAX | Jacksonville Jaguars alias |
| JAX | JAX | Jacksonville Jaguars |
| KC | KC | Kansas City Chiefs |
| LAC | LAC | Los Angeles Chargers |
| SD | LAC | San Diego Chargers historical alias |
| LA | LAR | Los Angeles Rams alias |
| LAR | LAR | Los Angeles Rams |
| STL | LAR | St. Louis Rams historical alias |
| LV | LV | Las Vegas Raiders |
| OAK | LV | Oakland Raiders historical alias |
| MIA | MIA | Miami Dolphins |
| MIN | MIN | Minnesota Vikings |
| NE | NE | New England Patriots |
| NO | NO | New Orleans Saints |
| NYG | NYG | New York Giants |
| NYJ | NYJ | New York Jets |
| PHI | PHI | Philadelphia Eagles |
| PIT | PIT | Pittsburgh Steelers |
| SEA | SEA | Seattle Seahawks |
| SF | SF | San Francisco 49ers |
| TB | TB | Tampa Bay Buccaneers |
| TEN | TEN | Tennessee Titans |
| WAS | WAS | Washington historical/source code |
| WSH | WAS | Washington alias |

## Known gaps and modeling cautions
- Betting columns are real nflverse market data and are legitimate pregame predictors, but they are very strong; keep them separated from post-game/in-game fields to avoid leakage.
- Older seasons have lower betting/QB/weather coverage; use the per-season table above to choose model cutoffs rather than filling gaps.
- Unplayed/future rows are retained for schedule awareness but must never enter training or evaluation.
- Preseason rows, if present, are flagged as `PRE`/`is_preseason=1` and should be excluded from outcome modeling unless intentionally analyzed separately.
