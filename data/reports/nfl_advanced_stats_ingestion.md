# NFL advanced stats ingestion

Generated: 2026-08-05T20:06:29+00:00

## Data integrity rule

No synthetic, simulated, randomly generated, or imputed data was created. Unavailable sources/seasons were recorded as gaps only.

## Sources discovered

### Worked

- nflverse-data releases api: https://api.github.com/repos/nflverse/nflverse-data/releases?per_page=100 (ok)
- nfldata contents api: https://api.github.com/repos/nflverse/nfldata/contents/data?ref=master (ok)
- nfldata github tree html: https://github.com/nflverse/nfldata/tree/master/data (ok)
- nfldata games csv: https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv (ok)
- release:pbp: https://api.github.com/repos/nflverse/nflverse-data/releases/tags/pbp (160 assets)
- release:stats_team: https://api.github.com/repos/nflverse/nflverse-data/releases/tags/stats_team (542 assets)
- release:stats_player: https://api.github.com/repos/nflverse/nflverse-data/releases/tags/stats_player (542 assets)
- release:player_stats: https://api.github.com/repos/nflverse/nflverse-data/releases/tags/player_stats (1822 assets)
- release:pfr_advstats: https://api.github.com/repos/nflverse/nflverse-data/releases/tags/pfr_advstats (190 assets)
- release:nextgen_stats: https://api.github.com/repos/nflverse/nflverse-data/releases/tags/nextgen_stats (95 assets)

### Did not work or was not listable

- nfldata raw directory: https://raw.githubusercontent.com/nflverse/nfldata/master/data/ (status=404, Not Found)

## Ingested assets

- pbp: 2010-2025 (16 seasons)
  - sample URL: https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2010.parquet
  - sample URL: https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2011.parquet
  - sample URL: https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2012.parquet
- stats_player_week: 2010-2025 (16 seasons)
  - sample URL: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2010.parquet
  - sample URL: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2011.parquet
  - sample URL: https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2012.parquet
- stats_team_week: 2010-2025 (16 seasons)
  - sample URL: https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2010.parquet
  - sample URL: https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2011.parquet
  - sample URL: https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2012.parquet

## Tables and metrics

- `nfl_team_week_advanced`: per-(season, week, normalized team) observations from play-by-play EPA. Metrics include offensive/defensive EPA per play, pass/rush EPA splits, positive-EPA success rates, third-down/red-zone positive-EPA rates, giveaways, takeaways, and play counts.
- `nfl_team_week_box_stats`: nflverse team-week box/summary stats including passing/rushing EPA, CPOE, yardage, touchdowns, sacks, interceptions, penalties, and kicking/punting fields.
- `nfl_qb_week_stats`: QB weekly passing/rushing production from nflverse player-week stats, including passing EPA, CPOE, sacks, interceptions, rushing EPA, and derived passing EPA per dropback.

## Coverage summary

- `nfl_team_week_advanced`: 8,726 rows, seasons 2010-2025.
- `nfl_team_week_box_stats`: 8,726 rows.
- `nfl_qb_week_stats`: 9,874 rows.
- Overall null rates for key EPA metrics: `{"defensive_epa_per_play_allowed": 0.0, "giveaway_rate": 0.0, "offensive_epa_per_play": 0.0, "pass_epa_per_play": 0.0, "red_zone_success_rate": 0.0209, "rush_epa_per_play": 0.0, "takeaway_rate": 0.0, "third_down_success_rate": 0.0}`

### Rows/teams by season

| table_name | season | rows | teams | expected_teams_from_games | missing_teams |
| --- | --- | --- | --- | --- | --- |
| nfl_team_week_advanced | 2010 | 534 | 32 | 32 |  |
| nfl_team_week_advanced | 2011 | 534 | 32 | 32 |  |
| nfl_team_week_advanced | 2012 | 534 | 32 | 32 |  |
| nfl_team_week_advanced | 2013 | 534 | 32 | 32 |  |
| nfl_team_week_advanced | 2014 | 534 | 32 | 32 |  |
| nfl_team_week_advanced | 2015 | 534 | 32 | 32 |  |
| nfl_team_week_advanced | 2016 | 534 | 32 | 32 |  |
| nfl_team_week_advanced | 2017 | 534 | 32 | 32 |  |
| nfl_team_week_advanced | 2018 | 534 | 32 | 32 |  |
| nfl_team_week_advanced | 2019 | 534 | 32 | 32 |  |
| nfl_team_week_advanced | 2020 | 538 | 32 | 32 |  |
| nfl_team_week_advanced | 2021 | 570 | 32 | 32 |  |
| nfl_team_week_advanced | 2022 | 568 | 32 | 32 |  |
| nfl_team_week_advanced | 2023 | 570 | 32 | 32 |  |
| nfl_team_week_advanced | 2024 | 570 | 32 | 32 |  |
| nfl_team_week_advanced | 2025 | 570 | 32 | 32 |  |
| nfl_team_week_box_stats | 2010 | 534 | 32 | 32 |  |
| nfl_team_week_box_stats | 2011 | 534 | 32 | 32 |  |
| nfl_team_week_box_stats | 2012 | 534 | 32 | 32 |  |
| nfl_team_week_box_stats | 2013 | 534 | 32 | 32 |  |
| nfl_team_week_box_stats | 2014 | 534 | 32 | 32 |  |
| nfl_team_week_box_stats | 2015 | 534 | 32 | 32 |  |
| nfl_team_week_box_stats | 2016 | 534 | 32 | 32 |  |
| nfl_team_week_box_stats | 2017 | 534 | 32 | 32 |  |
| nfl_team_week_box_stats | 2018 | 534 | 32 | 32 |  |
| nfl_team_week_box_stats | 2019 | 534 | 32 | 32 |  |
| nfl_team_week_box_stats | 2020 | 538 | 32 | 32 |  |
| nfl_team_week_box_stats | 2021 | 570 | 32 | 32 |  |
| nfl_team_week_box_stats | 2022 | 568 | 32 | 32 |  |
| nfl_team_week_box_stats | 2023 | 570 | 32 | 32 |  |
| nfl_team_week_box_stats | 2024 | 570 | 32 | 32 |  |
| nfl_team_week_box_stats | 2025 | 570 | 32 | 32 |  |
| nfl_qb_week_stats | 2010 | 613 | 32 | 32 |  |
| nfl_qb_week_stats | 2011 | 608 | 32 | 32 |  |
| nfl_qb_week_stats | 2012 | 601 | 32 | 32 |  |
| nfl_qb_week_stats | 2013 | 582 | 32 | 32 |  |
| nfl_qb_week_stats | 2014 | 602 | 32 | 32 |  |
| nfl_qb_week_stats | 2015 | 595 | 32 | 32 |  |
| nfl_qb_week_stats | 2016 | 602 | 32 | 32 |  |
| nfl_qb_week_stats | 2017 | 596 | 32 | 32 |  |
| nfl_qb_week_stats | 2018 | 596 | 32 | 32 |  |
| nfl_qb_week_stats | 2019 | 588 | 32 | 32 |  |
| nfl_qb_week_stats | 2020 | 619 | 32 | 32 |  |
| nfl_qb_week_stats | 2021 | 642 | 32 | 32 |  |
| nfl_qb_week_stats | 2022 | 646 | 32 | 32 |  |
| nfl_qb_week_stats | 2023 | 663 | 32 | 32 |  |
| nfl_qb_week_stats | 2024 | 663 | 32 | 32 |  |
| nfl_qb_week_stats | 2025 | 658 | 32 | 32 |  |

## Honest gaps/blockers

- No missing teams versus the local `games` table for ingested seasons were detected.
- Coverage intentionally starts at 2010 to keep play-by-play ingestion pragmatic while covering modern NFL data. nflverse publishes older play-by-play assets back to 1999, but they were not ingested in this run.
- ESPN API was not used because the task reported 403 responses; all ingested data came from nflverse/GitHub.
