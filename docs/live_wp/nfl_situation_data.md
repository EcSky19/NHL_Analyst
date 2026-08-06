# NFL situational live win-probability harvest

This document describes `data/live_wp/nfl_situation.db`, built by
`scripts/live_wp/harvest_nfl_situation.py`.

## Source and scope

- Source: ESPN summary endpoint through `app.services.espn_pbp.fetch_summary("nfl", game_id)`.
- Games: regular seasons matching `scripts/live_wp/harvest_nfl.py`:
  - 2023: 2023-09-07 through 2024-01-07
  - 2024: 2024-09-05 through 2025-01-05
- Game IDs are loaded from `data/live_wp/nfl_snapshots.db` in SQLite read-only mode when present, so the situational harvest targets the same 544 games.

## Tables

### `games`

One row per harvested game:

- `game_id TEXT PRIMARY KEY`
- `season INTEGER`
- `game_date TEXT`
- `home TEXT`, `away TEXT`
- `home_team_id TEXT`, `away_team_id TEXT`
- `home_score INTEGER`, `away_score INTEGER`
- `status TEXT`
- `harvested_at TEXT`
- `n_snapshots INTEGER`

### `snapshots`

One row per parsed ESPN play:

- `game_id TEXT`
- `season INTEGER`
- `play_index INTEGER`
- `play_id TEXT`
- `sequence_number INTEGER`
- `period INTEGER`
- `clock_seconds REAL`
- `frac_remaining REAL`
- `home_score INTEGER`, `away_score INTEGER`
- `margin INTEGER`
- `home_won INTEGER`
- `espn_home_wp REAL`
- `offense_is_home INTEGER`
- `offense_team_id TEXT`
- `down INTEGER`
- `distance INTEGER`
- `yard_line INTEGER`
- `yards_to_endzone INTEGER`
- `is_turnover INTEGER`
- `play_type TEXT`
- `down_distance_text TEXT`

Primary key: `(game_id, play_index)`.

### `failed_games`

Records games that could not be harvested after retries, without aborting the run.

## `frac_remaining` convention

`frac_remaining` is computed by importing and using the existing
`app.services.espn_pbp.frac_remaining_clock("nfl", period, clock_seconds)`.
This is the same convention used by `scripts/live_wp/harvest_nfl.py` via
`snapshots_from_summary`: share of regulation remaining in `[0, 1]`, with NFL
quarters treated as four 15-minute periods and overtime returning `0.0`.

## Coverage from the completed local harvest

- 2023: 50,226 rows, 272 games
- 2024: 49,994 rows, 272 games
- Failed games: 0
- Existing `nfl_snapshots.db` overlap: 544 game IDs
- Existing games lacking a situational harvest: 0

## Validation notes

- `espn_home_wp` is populated only when ESPN's `winprobability` entry has a
  matching `playId`. Local harvest: 100,110 non-null values out of 100,220 rows.
  No interpolation or guessing is used.
- `offense_is_home` is resolved per play from `start.team.id` against the home
  team ID in the ESPN summary header. Local mean: 0.5034.
- Distribution checks from the completed local harvest:
  - `down`: min 0, max 4, median 2.0, null rate 0.0000
  - `distance`: min 0, max 40, median 10.0, null rate 0.0000
  - `yards_to_endzone`: min 0, max 99, median 56.0, null rate 0.0000
- `frac_remaining` min 0.0, max 1.0, out-of-range count 0. The same ESPN clock
  convention as the old harvest is used; a small number of row-to-row increases
  remain because ESPN includes clock corrections and quarter-boundary
  administrative rows.
