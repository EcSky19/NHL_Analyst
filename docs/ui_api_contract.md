# Sports Analytics UI — API Contract (FROZEN)

This contract is **frozen**. Every backend router and the frontend are built against it in
parallel. Do not change a path, field name, or envelope shape without updating this file first
and announcing it, or you will break another agent's work.

## Response envelope

Every endpoint returns HTTP 200 with this JSON envelope (errors included), so the frontend has
exactly one shape to parse:

```json
{
  "ok": true,
  "data": {},
  "meta": {
    "source": "nhl-api",
    "fetched_at": "2026-08-05T14:00:00Z",
    "cached": true,
    "stale": false,
    "season": "20252026",
    "season_state": "offseason"
  }
}
```

Failure:

```json
{
  "ok": false,
  "data": null,
  "error": { "code": "upstream_unavailable", "message": "NHL API timed out" },
  "meta": { "source": "nhl-api", "fetched_at": null, "cached": false, "stale": true }
}
```

Error codes: `upstream_unavailable`, `not_found`, `bad_request`, `no_data`, `internal`.

### Staleness rule (important)

If the upstream fetch fails but a cached copy exists, serve the **cached copy** with
`ok: true`, `"stale": true`, and `meta.stale_reason`. The UI must never show a blank screen
because an upstream API blipped. Only return `ok: false` when there is no data at all.

## Season state (offseason handling)

Today is **August 2026**. NHL and NBA are between seasons, NFL is in preseason, and MLB is
in the regular season. Every endpoint reports `meta.season_state`:

- `"regular"` — regular season in progress
- `"playoffs"` — postseason in progress
- `"offseason"` — between seasons; `season` is the most recent completed season
- `"preseason"` — scheduled but not started

The UI must render an explicit banner when `season_state` is not `regular`, so a user is never
misled into thinking a final table is a live one.

## Endpoints

Base: `/api`. All list endpoints accept optional `?season=`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness + dependency status |
| GET | `/api/meta/seasons` | Available seasons per league |
| GET | `/api/nhl/standings` | NHL standings |
| GET | `/api/nhl/teams` | NHL team list + summary stats |
| GET | `/api/nhl/teams/{abbrev}` | One NHL team detail |
| GET | `/api/nhl/players` | NHL player leaders (`?team=&stat=&limit=`) |
| GET | `/api/nhl/schedule` | NHL games (`?date=YYYY-MM-DD`) |
| GET | `/api/nfl/standings` | NFL standings |
| GET | `/api/nfl/teams` | NFL team list + summary stats |
| GET | `/api/nfl/teams/{abbrev}` | One NFL team detail |
| GET | `/api/nfl/players` | NFL player leaders (`?team=&stat=&limit=`) |
| GET | `/api/nfl/schedule` | NFL games (`?season=&week=`) |
| GET | `/api/nba/standings` | NBA standings |
| GET | `/api/nba/teams` | NBA team list + summary stats |
| GET | `/api/nba/teams/{abbrev}` | One NBA team detail |
| GET | `/api/nba/players` | NBA player leaders (`?team=&stat=&limit=`) |
| GET | `/api/nba/schedule` | NBA games (`?date=YYYY-MM-DD&season=`) |
| GET | `/api/mlb/standings` | MLB standings |
| GET | `/api/mlb/teams` | MLB team list + summary stats |
| GET | `/api/mlb/teams/{abbrev}` | One MLB team detail |
| GET | `/api/mlb/players` | MLB player leaders (`?team=&stat=&group=hitting\|pitching&limit=`) |
| GET | `/api/mlb/schedule` | MLB games (`?date=YYYY-MM-DD&season=`) |
| GET | `/api/predictions/nhl` | NHL matchup predictions |
| GET | `/api/predictions/nfl` | NFL matchup predictions |
| GET | `/api/predictions/nba` | NBA matchup predictions |
| GET | `/api/predictions/mlb` | MLB matchup predictions |
| GET | `/api/predictions/matchup` | Ad-hoc `?league=&home=&away=` |

### Standings row (shared base keys)

```json
{
  "team_id": "TOR", "abbrev": "TOR", "name": "Toronto Maple Leafs",
  "conference": "Eastern", "division": "Atlantic",
  "rank": 1, "games_played": 82, "wins": 50, "losses": 25, "otl": 7, "ties": null,
  "points": 107, "points_pct": 0.652, "win_pct": 0.610,
  "goals_for": 303, "goals_against": 260, "differential": 43,
  "streak": "W3", "last10": "7-2-1",
  "home_record": "28-10-3", "away_record": "22-15-4",
  "logo_url": "https://...", "clinched": null
}
```

NFL uses the same keys: `otl` is null, `ties` is populated, `goals_for`/`goals_against` carry
points for/against. Keeping one shape lets the frontend use a single table component.

NBA uses the same keys too: `otl` and `ties` are null (NBA games cannot tie),
`goals_for`/`goals_against` carry points for/against, `points` carries wins for ranking
purposes, and `conference`/`division` carry Eastern/Western + the six divisions.

MLB exposes the same base keys plus `games_behind`. `otl` and `ties` are null,
`goals_for`/`goals_against` carry runs scored/allowed, and `points` carries wins.

## NBA data sources (verified 2026-08-05)

NBA access is more constrained than the other two leagues. These were tested directly:

- `stats.nba.com` — **times out / blocked.** Do not rely on it.
- `cdn.nba.com` live JSON — **403.** ESPN NBA — **403.** balldontlie — **401** (needs a key).
- **hoopR-data (works, primary historical source):**
  `https://raw.githubusercontent.com/sportsdataverse/hoopR-data/main/nba/schedules/csv/nba_schedule_{YEAR}.csv`
  plus `nba/team_box/csv/team_box_{YEAR}.csv` and `nba/player_box/csv/player_box_{YEAR}.csv`.
  Requires a browser `User-Agent`. Historical coverage is seasons 2001-02 through 2022-23:
  28,222 games, 56,136 team box rows, 739,524 player box rows, and 30 teams. It does not include
  the 2023-24, 2024-25, or 2025-26 seasons.
- **basketball-reference (works, for current standings):**
  `https://www.basketball-reference.com/leagues/NBA_2026_standings.html` (the 2025-26 season).
  `/leagues/` is permitted by their robots.txt for `User-agent: *`, which specifies
  `Crawl-delay: 3`. Fetch at most one page per request cycle, honor that delay at 3.1 seconds,
  cache aggressively (>=300s), and never hammer it. Wikipedia's season page is a licensed
  cross-check. Current standings for 2023-24, 2024-25, and 2025-26 have wins equal losses
  at 1,230 per season.

Basketball-reference uses the season end year in URLs, so `NBA_2026` is the 2025-26 season.

**Because of the 2024-2025 coverage gap, any NBA claim must state which seasons it rests on.**
Do not imply continuous coverage through the present.

## MLB data sources (verified 2026-08-05)

MLB is the easiest of the four leagues: the **official MLB StatsAPI is free, public, and needs
no API key**. All of these returned HTTP 200:

- Standings: `https://statsapi.mlb.com/api/v1/standings?leagueId=103,104&season={YEAR}`
  (103 = American League, 104 = National League; 6 divisions, 30 teams)
- Teams: `https://statsapi.mlb.com/api/v1/teams?sportId=1&season={YEAR}`
- Schedule: `https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=YYYY-MM-DD`
  (also `&startDate=&endDate=`)
- League leaders: `https://statsapi.mlb.com/api/v1/stats?stats=season&group=hitting|pitching&season={YEAR}&sportId=1`
- Team stats: `https://statsapi.mlb.com/api/v1/teams/{teamId}/stats?stats=season&season={YEAR}&group=hitting`
- ESPN MLB returns **403** — do not use it.

Historical ingest contains 32,906 games. Regular-season completed counts for 2015-2026 are:
2,429, 2,428, 2,430, 2,431, 2,429, 898, 2,429, 2,430, 2,430, 2,429, 2,430, 1,709. 2020 is
COVID-shortened, and 2026 is in progress as of 2026-08-05. Doubleheaders are preserved by
`gamePk` (verified: 2026-07-29 ATL at NYM, gamePks 823596 and 823598). Spot-check:
2025 World Series Game 7, LAD 5 at TOR 4.

**MLB is MID-SEASON right now.** Unlike the other three leagues, August falls inside the MLB
regular season, so `season_state` is `regular` and standings are genuinely live and changing
(verified: Rays 68-46 on 2026-08-05, with games scheduled that day). This is the one league where
the UI's auto-refresh shows real movement, so treat freshness as a first-class concern: use the
short standings TTL and make sure `fetched_at` is surfaced.

MLB-specific shape notes: `otl` and `ties` are null (ties are essentially nonexistent in the
modern game), `goals_for`/`goals_against` carry runs scored/allowed, `points` carries wins for
ranking, `conference` carries the league (American/National), and `division` carries
East/Central/West.

There is no trained MLB prediction model. MLB matchup predictions intentionally return an
honest unsupported error rather than inventing probabilities.

### Prediction row

```json
{
  "game_id": "2025020123", "game_date": "2026-01-14", "league": "nhl",
  "home": "TOR", "away": "BOS",
  "home_win_prob": 0.58, "away_win_prob": 0.42,
  "confidence": "medium", "model": "nhl-roster-aware-v2",
  "model_accuracy": 0.5682, "baseline_accuracy": 0.535,
  "features_used": ["elo_diff", "rest_diff"],
  "disclaimer": "Model accuracy 56.8% vs 53.5% home baseline."
}
```

**Honesty requirement (non-negotiable).** Predictions must ship with their real measured
accuracy. NHL is **56.82%** (vs ~53.5% always-home baseline). NFL market-free is **66.11%** and
full is **67.40%**, against a same-holdout Vegas bar of **68.51%** — neither NFL model beats the
market. The UI must surface these numbers next to any probability. Do **not** display confidence
tiers built on fewer than 150 games; that small-sample trap already produced one retracted claim
in this repo. Never present a probability as a betting edge.

## Module ownership (no two agents touch the same file)

| Module | Owner | Must expose |
|---|---|---|
| `app/main.py`, `app/config.py`, `app/cache.py` | scaffold (done) | app, settings, cached_fetch |
| `app/routers/nhl.py` | nhl agent | `router` |
| `app/routers/nfl.py` | nfl agent | `router` |
| `app/routers/predictions.py` | predictions agent | `router` |
| `app/static/*` | frontend agent | index.html, app.js, styles.css |
| `tests/ui/*` | tests agent | pytest suite |

`app/main.py` already imports all sport routers and mounts `app/static`. Create your module at
the exact path with a module-level `router = APIRouter()` or the app will fail to boot.

## Caching

Use `app.cache.cached_fetch(key, ttl_seconds, loader)`. TTLs: standings 300s, stats 900s,
schedule 120s, predictions 600s. Cache is on-disk under `data/ui_cache/` so a restart stays warm.

## Verified data sources

- NHL standings: `https://api-web.nhle.com/v1/standings/now` (HTTP 200 verified)
- NHL schedule: `https://api-web.nhle.com/v1/schedule/now` (HTTP 200 verified)
- NHL team meta: `https://api.nhle.com/stats/rest/en/team` (HTTP 200 verified)
- NFL games: `https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv`
  — **requires** a browser `User-Agent` header or GitHub returns 403.
- **ESPN NFL API returns 403 and must not be used.** ESPN NBA and MLB also return 403 and are
  deliberately not used.
- Local databases: `data/processed/nhl_research.db`, `data/nfl/nfl_research.db` (read-only).

## Live games and week schedule (contract v2)

Frozen before implementation so the four league routers and the frontend can be built
in parallel. All responses use the standard `ok()` / `fail()` envelope from
`app/config.py`. Failures are still HTTP 200.

### `GET /api/{league}/schedule/week`

Query params:

| param | type | default | notes |
| --- | --- | --- | --- |
| `start` | `YYYY-MM-DD` | today (UTC) | first day of the window, inclusive |
| `days` | int | 7 | 1-14; reject anything else with `fail("bad_request", ...)` |

`data` is a **flat array** of game rows sorted by `start_time_utc` then `game_id`,
not a nested per-day structure. The frontend groups by `game_date` itself.

`meta` adds: `start_date`, `end_date`, `days`, `count`, `season_state`, `league`,
and `empty_reason` (string or null).

### `GET /api/{league}/live`

No required params. `data` is a flat array of **currently in-progress games only**.
`meta` adds: `count`, `season_state`, `league`, `polled_at`, `poll_interval_seconds`
(integer hint for the frontend; use 30), and `empty_reason` (string or null).

Each live row carries all shared keys below plus a `live` object:

- `period` — integer or null
- `period_label` — short display string, league-specific (`"T7"`, `"Q3"`, `"P2"`)
- `clock` — string or null (null is legitimate for baseball)
- `last_play` — string or null

### Shared game row keys (all four leagues, both endpoints)

Every league MUST emit these exact key names, even where its internal schema differs.
NFL and NBA currently expose `home_team`/`away_team`; they must **also** emit
`home`/`away`. Existing keys stay for backward compatibility; this is additive.

`game_id` (string), `league`, `game_date` (`YYYY-MM-DD`), `start_time_utc` (ISO-8601
string or null), `home`, `away` (abbrev), `home_name`, `away_name`, `home_score`,
`away_score` (int or null, null when not yet played), `status`, `detailed_status`,
`venue`.

`status` MUST be normalized to exactly one of: `scheduled`, `live`, `final`,
`postponed`. Raw upstream values (`FUT`, `OFF`, `In Progress`, ...) go in
`detailed_status`.

### Honesty rules (non-negotiable)

As of August 2026 the NHL and NBA are in their offseason and the NFL has not played
a regular-season game yet. Therefore:

- An empty week or empty live list is a **correct answer**, not a bug to paper over.
  Return `ok` with `data: []` and a truthful `meta.empty_reason`, for example
  `"NHL is in its offseason; no games are scheduled in this window."`
- Never invent, simulate, or placeholder a game.
- Never substitute games from a previous season and present them as upcoming. A
  historical row must never appear in `/schedule/week` or `/live`.
- Never mark a game `live` unless upstream genuinely reports it in progress.
- Scores for unplayed games are `null`, never `0`.
