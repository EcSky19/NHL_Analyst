# MLB live win-probability snapshot coverage

Harvest run: 2026-08-06.

## Scope

The harvest used the existing MLB snapshot feature path in `scripts/live_wp/harvest_mlb.py`
and `app.services.espn_pbp.snapshots_from_summary`; feature computation and the SQLite
schema were not changed. The season discovery was expanded from the former 20-day
midseason windows to the ESPN regular-season windows:

- 2024-03-20 through 2024-09-30
- 2025-03-18 through 2025-09-28

ESPN reported 2,429 final regular-season games for 2024 and 2,430 for 2025.
Postponed/non-final rows in those windows were not harvested: 37 in 2024 and 30 in 2025.

## Coverage

Counts are queried from `data/live_wp/mlb_snapshots.db`.

| Season | Before games | Before rows | After games | After rows | Home win rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2024 | 264 | 152,419 | 2,429 | 1,385,716 | 0.5216 |
| 2025 | 264 | 150,575 | 2,430 | 1,387,627 | 0.5428 |

The after-run game counts match all final regular-season games discovered from ESPN:
missing expected games: 0; extra games outside that expected set: 0.

## Failures and retries

The detached full run initially had 10 transient ESPN summary failures
(HTTP 502/504). A second idempotent retry run harvested all 10 successfully.

Permanent failed games after retry: 0.

## Verification

- Duplicate `(game_id, snapshot_index)` groups: 0.
- Empty harvested games (`n_snapshots = 0`): 0.
- `frac_remaining` outside `[0, 1]`: 0 rows.
- `margin != home_score - away_score`: 0 rows.
- Existing baseline games before the run: 528; missing after run: 0; changed after run: 0.

`outs` sanity note: 586,169 rows have `outs = 3`. This comes from the existing ESPN
play-by-play parsing path and was not changed for this data-harvest-only task.
Distribution after harvest: `NULL=0`, `0=531,673`, `1=839,023`, `2=816,478`,
`3=586,169`.

## Structural oddities

Maximum inning (`period`) distribution by game:

| Season | Max period | Games |
| --- | ---: | ---: |
| 2024 | 6 | 1 |
| 2024 | 7 | 1 |
| 2024 | 8 | 1 |
| 2024 | 9 | 2,210 |
| 2024 | 10 | 162 |
| 2024 | 11 | 31 |
| 2024 | 12 | 16 |
| 2024 | 13 | 5 |
| 2024 | 14 | 2 |
| 2025 | 6 | 2 |
| 2025 | 7 | 2 |
| 2025 | 8 | 1 |
| 2025 | 9 | 2,216 |
| 2025 | 10 | 134 |
| 2025 | 11 | 61 |
| 2025 | 12 | 11 |
| 2025 | 13 | 3 |

The short maximum-period games are final games where the play list ended before
period 9 according to the existing parser output; they were retained rather than
silently modified.

Short maximum-period games:

- 2024-04-25 `401568853` TOR@KC, final 1-2, max period 6, 289 rows.
- 2024-05-05 `401568982` DET@NYY, final 2-5, max period 8, 512 rows.
- 2024-07-04 `401569777` DET@MIN, final 3-12, max period 7, 519 rows.
- 2025-04-11 `401695101` SF@NYY, final 9-1, max period 6, 486 rows.
- 2025-04-24 `401695278` CHW@MIN, final 3-0, max period 8, 483 rows.
- 2025-05-04 `401695418` HOU@CHW, final 4-5, max period 7, 511 rows.
- 2025-06-18 `401696007` MIN@CIN, final 2-4, max period 6, 349 rows.
- 2025-07-08 `401696282` TOR@CHW, final 6-1, max period 7, 412 rows.
