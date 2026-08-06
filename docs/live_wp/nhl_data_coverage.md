# NHL live win-probability snapshot coverage

Harvest completed on 2026-08-06 for `data/live_wp/nhl_snapshots.db` using `scripts/live_wp/harvest_nhl.py`.

## Script configuration

`SEASONS` is configured for:

- `2024-25`: 2024-10-04 through 2025-04-17
- `2025-26`: 2025-10-07 through 2026-04-16

The previous script defaulted to `--max-games 500 --per-season 250`, so it stopped after roughly the existing sample. Those defaults are now uncapped. The harvest remains resumable/idempotent: games with `harvested_at IS NOT NULL` and `n_snapshots > 0` are skipped. Failed/zero-snapshot games remain eligible for retry.

The enumerator now filters ESPN scoreboard events to regular-season NHL-team games before adding new `games` rows. It uses ESPN's per-event `season.type == 2` signal for regular season and also requires both teams to be NHL clubs. This prevents preseason games and the 2025 4 Nations Face-Off national-team games from being newly harvested as NHL training data.

After the initial expansion, 16 pre-existing preseason games dated 2024-10-04/2024-10-05 were found in the 2024-25 sample and removed from both `games` and `snapshots`. ESPN's event season type positively distinguishes those games from the legitimate Prague Global Series opener on the same date: the removed game IDs have `season.type == 1`, while `401687600` and `401687601` have `season.type == 2`.

## Coverage

Counts below are direct SQLite counts from `snapshots`.

| Season | Before games | Before rows | After games in DB | After rows in DB | Regular-season NHL games covered |
|---|---:|---:|---:|---:|---:|
| 2024-25 | 249 | 78,979 | 1,312 | 416,699 | 1,312 |
| 2025-26 | 248 | 78,966 | 1,312 | 410,454 | 1,312 |

Both seasons now contain exactly 1,312 regular-season NHL games.

## Home win rate

Computed over distinct games.

| Season | Before | After |
|---|---:|---:|
| 2024-25 | 0.5502 | 0.5625 |
| 2025-26 | 0.5282 | 0.5221 |

## OT/shootout convention

The existing code path in `app.services.espn_pbp.snapshots_from_summary` was used unchanged for snapshot construction.

- NHL clocks count up inside each period.
- `frac_remaining` is fraction of regulation remaining.
- Any period after regulation (`period > 3`) receives `frac_remaining = 0.0`.
- `home_won` is `1` when the final home score is greater than the final away score, else `0`; this same convention applies to regulation, overtime, and shootout finals.

Verification:

- Rows where `period > 3` and `frac_remaining != 0.0`: 0.
- Rows where `home_won` disagrees with `games.home_score > games.away_score`: 0.

OT/shootout share, using `MAX(period) > 3` per game:

| Season | OT/SO games |
|---|---:|
| 2024-25 | 271 / 1,312 = 0.2066 |
| 2025-26 | 326 / 1,312 = 0.2485 |

## Failures and exclusions

Permanent harvest failures: none.

Rows with ESPN win probability values: 0 of 827,153.

Excluded from new harvest:

- Non-final/postponed games, because they lack settled labels.
- Preseason events (`season.type == 1`).
- 2025 4 Nations Face-Off national-team games. Six of these were temporarily harvested during the run and then removed from `games` and `snapshots`.

Removed after contamination check:

- 16 pre-existing 2024-25 preseason games (`401685344` through `401685359`, non-contiguous only by listing order) and their 3,811 snapshot rows.
- 6 2025 4 Nations Face-Off games and their 1,923 snapshot rows.

Positive season-type recheck after cleanup:

- 2024-25: all 1,312 DB games found in ESPN scoreboard windows with `season.type == 2`; non-regular games: 0.
- 2025-26: all 1,312 DB games found in ESPN scoreboard windows with `season.type == 2`; non-regular games: 0.

## Sanity checks

- `frac_remaining` outside `[0, 1]`: 0 rows.
- `margin != home_score - away_score`: 0 rows.
- `games` duplicate primary keys: 0 (`COUNT(*) == COUNT(DISTINCT game_id) == 2,624`).
- Snapshot/game count mismatches (`games.n_snapshots` vs actual rows): 0 games.
- Snapshot games missing a `games` row: 0 games.
- Idempotence after the run: `choose_games(..., None, None)` returns 0 games.
- Team appearance counts: 32 teams at exactly 82 appearances in 2024-25, and 32 teams at exactly 82 appearances in 2025-26.

Exact-state duplicate rows are present: 157,030 duplicate groups / 170,499 extra rows when grouping by `(game_id, period, clock_seconds, frac_remaining, home_score, away_score, margin, home_won, espn_home_wp, outs)`. This is not duplicate harvesting; it is produced by the existing ESPN play-by-play code path because multiple plays can occur at the same clock/score state and the schema has no play-id column. The same phenomenon existed before the expansion.

## Pre-existing rows

The initial expansion preserved the pre-harvest rows, but the follow-up contamination check found that 16 of those pre-existing 2024-25 games were preseason games. Those 16 games were intentionally deleted from both `games` and `snapshots`; therefore the original pre-harvest full-table digest no longer applies.

No other pre-existing games were targeted for deletion or re-harvested.
