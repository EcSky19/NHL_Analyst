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

Today is **August 2026 — both leagues are between seasons.** "Current standings" therefore means
*the most recently completed season*. Every endpoint reports `meta.season_state`:

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
| GET | `/api/predictions/nhl` | NHL matchup predictions |
| GET | `/api/predictions/nfl` | NFL matchup predictions |
| GET | `/api/predictions/matchup` | Ad-hoc `?league=&home=&away=` |

### Standings row (both leagues share these keys)

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

`app/main.py` already imports all three routers and mounts `app/static`. Create your module at
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
- **ESPN NFL API returns 403 and must not be used.** This was verified twice.
- Local databases: `data/processed/nhl_research.db`, `data/nfl/nfl_research.db` (read-only).
