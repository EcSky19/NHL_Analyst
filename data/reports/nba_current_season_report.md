# NBA current-season data source report

Generated at: 2026-08-05T22:55:15Z

## Scope and coverage

- Real source only; no synthetic or placeholder-filled NBA rows were generated.
- Basketball-Reference current/gap coverage captured: 2023-24, 2024-25, and 2025-26.
- hoopR-data still ends at season 2023; this script closes the 2023-24 and 2024-25 standings/team-stat gap with Basketball-Reference `/leagues/` pages and covers the most recently completed 2025-26 season.
- 2025-26 final last-10 and streak were computed from permitted Basketball-Reference `/leagues/NBA_2026_games-<month>.html` regular-season schedule pages through April 12, excluding the non-standings NBA Cup championship game.

## Robots and crawl-delay compliance

- Basketball-Reference `/leagues/` pages are robots-permitted for `User-agent: *`; disallowed gamelog/splits/on-off/lineups/shooting paths were not requested.
- Implemented per-host crawl delay of at least 3.1 seconds before uncached Basketball-Reference requests.
- Raw HTML is cached under `data\nba\raw\`; cached files are reused on rerun with no network request.

## URLs fetched this run

- None; all source pages were served from local cache.

## URLs served from cache

- https://en.wikipedia.org/api/rest_v1/page/html/2025%E2%80%9326_NBA_season
- https://www.basketball-reference.com/leagues/NBA_2024.html
- https://www.basketball-reference.com/leagues/NBA_2024_standings.html
- https://www.basketball-reference.com/leagues/NBA_2025.html
- https://www.basketball-reference.com/leagues/NBA_2025_standings.html
- https://www.basketball-reference.com/leagues/NBA_2026.html
- https://www.basketball-reference.com/leagues/NBA_2026_games-april.html
- https://www.basketball-reference.com/leagues/NBA_2026_games-december.html
- https://www.basketball-reference.com/leagues/NBA_2026_games-february.html
- https://www.basketball-reference.com/leagues/NBA_2026_games-january.html
- https://www.basketball-reference.com/leagues/NBA_2026_games-march.html
- https://www.basketball-reference.com/leagues/NBA_2026_games-november.html
- https://www.basketball-reference.com/leagues/NBA_2026_games-october.html
- https://www.basketball-reference.com/leagues/NBA_2026_per_game.html
- https://www.basketball-reference.com/leagues/NBA_2026_standings.html

## Validation

- Standings row counts by season: [('2023-24', 30), ('2024-25', 30), ('2025-26', 30)]
- Team-stat row counts by season: [('2023-24', 30), ('2024-25', 30), ('2025-26', 30)]
- 2025-26 player leader rows: 75
- 2025-26 conference counts: [('Eastern', 15), ('Western', 15)]
- 2025-26 teams with wins+losses != 82: []
- 2025-26 league win/loss totals: (1230, 1230)
- 2025-26 top teams: [('Oklahoma City Thunder', 64, 18, 'Western'), ('San Antonio Spurs', 62, 20, 'Western'), ('Detroit Pistons', 60, 22, 'Eastern'), ('Boston Celtics', 56, 26, 'Eastern'), ('Denver Nuggets', 54, 28, 'Western')]

## Wikipedia cross-check

- Wikipedia REST page cached/fetched at 2026-08-05T22:55:13Z; parsed 30 team win totals.
- Result: PASS
  - All 30 parsed Wikipedia win totals matched Basketball-Reference.
