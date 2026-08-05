# Real Historical NHL Ingestion Results

Generated at: 2026-08-05T19:20:24Z

## Data sources

- Season metadata: `https://api.nhle.com/stats/rest/en/season`
- Game schedules/results: `https://api-web.nhle.com/v1/schedule/{date}`
- Boxscore rosters/player stats: `https://api-web.nhle.com/v1/gamecenter/{gameId}/boxscore`

All ingested rows use `data_source='real_nhl_api_web'` and include `source_url`, `raw_json_path`, and `fetched_at_utc` provenance columns.

## Historical team handling

- Team membership is derived from teams that actually appear in each season's API games.
- Pre-2024 Arizona/Phoenix aliases are stored as `ARI`; Utah (`UTA`) is not used for these historical seasons.
- Vegas (`VGK`) appears beginning in 20172018; Seattle (`SEA`) is absent from these seasons.

## Tables updated

- Source-specific: `real_historical_games_api`, `real_historical_game_rosters_api`, `real_historical_player_game_stats_api`.
- Canonical compatibility: replaced matching seasons in `historical_games_last5`, `historical_game_rosters`, and `historical_player_game_stats` with the same real API rows.

## Games by season

| Season | Real games | Teams | First date | Last date | Home win rate |
| --- | ---: | ---: | --- | --- | ---: |
| 20152016 | 1230 | 30 | 2015-10-07 | 2016-04-10 | 0.5293 |
| 20162017 | 1230 | 30 | 2016-10-12 | 2017-04-09 | 0.5593 |
| 20172018 | 1271 | 31 | 2017-10-04 | 2018-04-08 | 0.5633 |
| 20182019 | 1271 | 31 | 2018-10-03 | 2019-04-06 | 0.5366 |
| 20192020 | 1082 | 31 | 2019-10-02 | 2020-03-11 | 0.5333 |

## Roster ingestion

| Season | Games with roster rows | Roster rows |
| --- | ---: | ---: |
| 20152016 | 1230 | 49200 |
| 20162017 | 1230 | 49197 |
| 20172018 | 1271 | 50840 |

## Spot checks

| Game ID | Date | Result | Winner |
| ---: | --- | --- | --- |
| 2015020001 | 2015-10-07 | MTL 3 @ TOR 1 | MTL |
| 2016020001 | 2016-10-12 | TOR 4 @ OTT 5 | OTT |
| 2017020015 | 2017-10-06 | VGK 2 @ DAL 1 | VGK |
| 2018020001 | 2018-10-03 | MTL 2 @ TOR 3 | TOR |
| 2019020001 | 2019-10-02 | OTT 3 @ TOR 5 | TOR |

## Gaps and failures

- Boxscore rosters were not fetched for optional seasons: [20182019, 20192020].
- No schedule-result gaps or boxscore failures for the fetched roster seasons.
