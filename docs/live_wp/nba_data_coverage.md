# NBA live win-probability snapshot coverage

Generated from `data/live_wp/nba_snapshots.db` after expanding the ESPN snapshot
harvest on 2026-08-06. Season is resolved by joining `snapshots.game_id` to
`games.game_id` and reading `games.season_start_year`; the NBA `snapshots`
table still has no `season` column.

## Harvest run

- Script: `scripts/live_wp/harvest_nba.py`
- Full run command:
  - `$env:PYTHONPATH='.'; python scripts\live_wp\harvest_nba.py --sleep-seconds 0.35 --attempts 4 --backoff-seconds 2`
- The script was verified as resumable/idempotent before the long run:
  - `--max-games 20 --sleep-seconds 0 --attempts 1` selected 20 games, found all
    20 already harvested, and fetched 0.
- After the long run, a second full invocation selected 2,462 final games, found
  all 2,462 already harvested, and fetched 0.
- Long-run result: fetched 1,962 new games, saved 1,962, empty 0, fetch errors 0.

## Coverage before and after

| Season | Before games | Before rows | After games | After rows |
| --- | ---: | ---: | ---: | ---: |
| 2023 | 250 | 119,349 | 1,231 | 574,228 |
| 2024 | 250 | 119,804 | 1,231 | 581,626 |
| Total | 500 | 239,153 | 2,462 | 1,155,854 |

ESPN's scoreboard returned 1,231 final games in each season window. That is one
more than the 1,230-game regular-season baseline because the window includes the
NBA Cup / In-Season Tournament championship as a final event. The harvest keeps
the existing "all final ESPN events in the window" semantics rather than deleting
or special-casing already harvested data.

## Home win rate over distinct games

| Season | Before home wins / games | Before rate | After home wins / games | After rate |
| --- | ---: | ---: | ---: | ---: |
| 2023 | 139 / 250 | 0.556000 | 669 / 1,231 | 0.543461 |
| 2024 | 152 / 250 | 0.608000 | 669 / 1,231 | 0.543461 |
| Total | 291 / 500 | 0.582000 | 1,338 / 2,462 | 0.543461 |

The high 0.5820 home win rate in the 500-game sample appears to have been
sampling noise; full-window coverage lands at 0.543461.

## ESPN win-probability coverage

| Season | Before non-null `espn_home_wp` | After non-null `espn_home_wp` | After nulls |
| --- | ---: | ---: | ---: |
| 2023 | 119,349 | 574,228 | 0 |
| 2024 | 119,803 | 581,625 | 1 |
| Total | 239,152 | 1,155,853 | 1 |

New rows added: 916,701. New rows with a non-null ESPN value: 916,701. The only
remaining null ESPN value is an existing 2024 row in game `401704628`; no ESPN
values were guessed or interpolated.

## Overtime convention

The existing code path in `app.services.espn_pbp.frac_remaining_clock` returns
`frac_remaining == 0.0` whenever `period > 4` for NBA. Overtime is represented
separately by consumers as `is_overtime = period > 4`; `train_nba.py` follows
that convention when building `GameState`.

Post-harvest overtime checks:

| Season | Games | OT games | OT share | OT rows |
| --- | ---: | ---: | ---: | ---: |
| 2023 | 1,231 | 59 | 0.047929 | 3,652 |
| 2024 | 1,231 | 60 | 0.048741 | 3,559 |
| Total | 2,462 | 119 | 0.048335 | 7,211 |

All overtime rows have `frac_remaining = 0.0`; periods observed beyond
regulation were 5 and 6.

## Failures and sanity checks

- Failed games grouped by reason: none (`harvest_failures` is empty).
- Duplicate `(game_id, seq)` rows: 0.
- `frac_remaining` out of `[0, 1]`: 0 rows; observed min 0.0, max 1.0.
- `margin != home_score - away_score`: 0 rows.
- Snapshot rows with no season resolved through the `games` join: 0.
- Previously harvested games were skipped by the resumable path during the full
  run; a post-run idempotency check fetched 0 games.
- `train_nba.rows_from_db()` read 1,155,854 rows / 2,462 games after the schema
  remained unchanged.
- `scripts/live_wp/verify_artifacts.py nba 2023 2024` completed successfully
  against the expanded database. It reproduced the current artifact on the new
  full-window split at Brier 0.165848 / log loss 0.490248 and confirmed train/test
  game overlap is 0.
