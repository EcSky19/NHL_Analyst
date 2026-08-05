# NBA recent per-game results ingestion

Generated at: 2026-08-05T23:30:48Z

## Sources and robots

- hoopR recent coverage probe: unavailable HTTP 404 for https://raw.githubusercontent.com/sportsdataverse/hoopR-data/main/nba/schedules/csv/nba_schedule_2024.csv
- Basketball-Reference robots.txt was re-read and cached at `data\nba\raw\basketball_reference_robots.txt`.
- `/leagues/NBA_YYYY_games-month.html` paths were checked with `urllib.robotparser.can_fetch` before fetch.
- Basketball-Reference crawl delay honored: 3.1 seconds between network requests.
- Basketball-Reference pages fetched this run: 0; cached pages reused: 21.

## Database

- Wrote only `data\nba\nba_recent_games.db`.
- `nba_games` schema matches `nba_research.db` columns.
- `nba_team_box` has one row per team-game with verified points only; detailed box-score fields are NULL because schedule pages do not provide them.
- `nba_player_box` schema is present but empty; player box scores were not fetched to avoid thousands of additional Basketball-Reference requests.
- `game_id` values are stable derived IDs of the form `NBA_{season_end}_{yyyymmdd}_{away}_{home}`; Basketball-Reference schedule pages do not expose hoopR/ESPN IDs.

## Game counts and internal validation

| Season | Games | Home wins | Away wins | Teams | Self-games | Duplicate IDs |
|---|---:|---:|---:|---:|---:|---:|
| 2023-24 (2024) | 1230 | 668 | 562 | 30 | 0 | 0 |
| 2024-25 (2025) | 1230 | 669 | 561 | 30 | 0 | 0 |
| 2025-26 (2026) | 1230 | 682 | 548 | 30 | 0 | 0 |

A full modern NBA regular season is 1,230 games. Shortfalls or overages are listed in the validation issues section.

## Standings cross-check

Exact match: derived win-loss records match all 90 rows in `nba_current_standings`.

## Spot-checks against second sources

- 2023-10-24: database row `NBA_2024_20231024_LAL_DEN` has Nuggets 119, Lakers 107. Second-source quote: ESPN recap title/result, `Nuggets 119-107 Lakers (Oct 24, 2023) Game Recap`.
- 2024-10-22: database row `NBA_2025_20241022_NYK_BOS` has Celtics 132, Knicks 109. Second-source quote: NBA.com Celtics recap, `Keys to the Game: Celtics 132, Knicks 109`.

## Missing or excluded

- No target regular-season schedule pages were missing.
- Excluded non-standings NBA Cup/In-Season Tournament final rows:
  - 2023-12-09 IND 109 at LAL 123 (In-Season Tournament)
  - 2024-12-17 MIL 97 at OKC 81 (NBA Cup)
  - 2025-12-16 SAS 113 at NYK 124 (NBA Cup)

## Validation issues

- None.
