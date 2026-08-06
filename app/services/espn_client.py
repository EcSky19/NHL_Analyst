"""Shared ESPN scoreboard client for NBA and NFL live/schedule data.

Why this module exists
----------------------
`site.api.espn.com` returns HTTP 403 to this app, which is why earlier work
concluded that no free source could supply live NBA/NFL state. That conclusion
was wrong in one specific way: the sibling host `site.web.api.espn.com` serves
the same scoreboard schema and does NOT 403. Verified 2026-08-05.

Host notes, all measured rather than assumed:

    site.api.espn.com        403 Forbidden (with or without a browser UA)
    cdn.nba.com              403 Forbidden
    site.web.api.espn.com    200 OK        <- what we use
    sports.core.api.espn.com 200 OK        but HATEOAS; ~5 requests per game

The core API was rejected deliberately: it returns `$ref` links that must each
be dereferenced (status, both teams, both scores), which is roughly 5 HTTP
requests per game. At a 30-second live poll that is far too expensive and
invites rate limiting. The web host returns a full slate in ONE request.

Both are cross-checked against each other in the notes below: for the window
2026-08-05..2026-08-15 both hosts independently reported 17 NFL preseason
events, and the web host's 2025-01-15 NBA slate reproduced this repo's own
database exactly (NY@PHI 125-119).

A browser User-Agent is required; ESPN rejects the default httpx agent.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.cache import cached_fetch
from app.config import BROWSER_USER_AGENT, settings

WEB_API_BASE = "https://site.web.api.espn.com/apis/site/v2/sports"

SPORT_PATHS = {
    "nba": "basketball/nba",
    "nfl": "football/nfl",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
}

# ESPN's coarse state lives at competition.status.type.state and takes exactly
# three values: pre, in, post. Postponed/canceled are NOT expressed there --
# they surface via status.type.name, so both must be consulted.
_STATE_TO_STATUS = {"pre": "scheduled", "in": "live", "post": "final"}

_POSTPONED_TYPE_NAMES = {
    "STATUS_POSTPONED",
    "STATUS_CANCELED",
    "STATUS_SUSPENDED",
    "STATUS_DELAYED",
    "STATUS_RAIN_DELAY",
}

# ESPN abbreviations differ from the ones this repo's databases and models use.
# Left unmapped, joins to standings/models silently miss: a 2025-01-15 NBA
# comparison matched only 6 of 11 games until these were applied, after which
# all 11 matched with zero score mismatches.
TEAM_ABBREV_FIXES = {
    "nba": {
        "GS": "GSW",
        "NO": "NOP",
        "NY": "NYK",
        "SA": "SAS",
        "UTAH": "UTA",
        "WSH": "WAS",
    },
    "nfl": {
        "LAR": "LA",
        "WSH": "WAS",
    },
}

# ESPN carries exhibition games on the normal slate. All-Star teams ("Team
# Chuck", "Team Shaq") would otherwise appear as real matchups against teams
# that do not exist. Note season.type is still 2 (regular-season) for these, so
# filtering on season type alone does NOT remove them; the competition type is
# the reliable marker.
_EXCLUDED_COMPETITION_TYPES = {"ALLSTAR"}

ET_ZONE = ZoneInfo("America/New_York")


def map_abbrev(league: str, abbrev: str | None) -> str | None:
    if abbrev is None:
        return None
    return TEAM_ABBREV_FIXES.get(league, {}).get(abbrev, abbrev)


def eastern_date(iso_utc: str | None) -> str | None:
    """Return the US Eastern calendar date for a UTC timestamp.

    Leagues label games by their local slate date, not by UTC. A 10pm ET tip-off
    on Jan 15 is a "Jan 15" game even though it is Jan 16 UTC. This repo's own
    NBA database follows that convention (11 games on 2025-01-15, matching
    ESPN's local slate), so dating by UTC would contradict our stored history.
    """
    if not iso_utc:
        return None
    try:
        parsed = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return str(iso_utc)[:10]
    return parsed.astimezone(ET_ZONE).date().isoformat()


def espn_source(league: str) -> str:
    return f"espn-web-api:{SPORT_PATHS.get(league, league)}"


def _fetch_json(url: str) -> Any:
    headers = {"User-Agent": BROWSER_USER_AGENT}
    with httpx.Client(headers=headers, timeout=settings.request_timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def scoreboard_url(league: str, *, dates: str | None = None, limit: int = 1000) -> str:
    path = SPORT_PATHS[league]
    url = f"{WEB_API_BASE}/{path}/scoreboard?limit={limit}"
    if dates:
        url += f"&dates={dates}"
    return url


def date_range_param(start: date, end: date) -> str:
    """ESPN accepts YYYYMMDD for one day and YYYYMMDD-YYYYMMDD for a range."""
    if start == end:
        return start.strftime("%Y%m%d")
    return f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"


def fetch_scoreboard(
    league: str,
    *,
    dates: str | None = None,
    ttl: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (raw ESPN events, cache meta).

    `ttl` defaults to 30s, matching the live poll interval. Callers fetching a
    static week window should pass a longer ttl.
    """
    url = scoreboard_url(league, dates=dates)
    key = f"espn:{league}:{dates or 'today'}"
    payload, cache_meta = cached_fetch(key, ttl, lambda: _fetch_json(url))
    events = list((payload or {}).get("events") or [])
    return events, cache_meta


def _score(competitor: dict[str, Any], has_played: bool) -> int | None:
    """ESPN reports "0" for games that never took place.

    That applies to scheduled games AND to postponed/canceled ones. Returning it
    verbatim would render an unplayed game as a real 0-0 result, which this repo
    treats as fabrication, so anything not live or final scores null.
    """
    if not has_played:
        return None
    raw = competitor.get("score")
    if raw is None or raw == "":
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def normalize_status(status: dict[str, Any]) -> tuple[str, str | None]:
    """Map an ESPN status object to (contract status, detailed status)."""
    stype = status.get("type") or {}
    type_name = str(stype.get("name") or "")
    detail = stype.get("shortDetail") or stype.get("detail") or stype.get("description")
    if type_name in _POSTPONED_TYPE_NAMES:
        return "postponed", detail
    state = str(stype.get("state") or "").lower()
    return _STATE_TO_STATUS.get(state, "scheduled"), detail


def normalize_event(event: dict[str, Any], league: str) -> dict[str, Any] | None:
    """Convert one ESPN event into the shared contract row.

    Returns None when the event is too malformed to represent honestly rather
    than emitting a row with invented placeholders.
    """
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    comp = competitions[0]
    if str((comp.get("type") or {}).get("abbreviation") or "").upper() in _EXCLUDED_COMPETITION_TYPES:
        return None
    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if home is None or away is None:
        return None

    status_obj = comp.get("status") or event.get("status") or {}
    status, detailed = normalize_status(status_obj)
    has_played = status in ("live", "final")

    start_utc = event.get("date") or comp.get("date")
    start_iso = _iso_z(start_utc)
    venue = ((comp.get("venue") or {}).get("fullName")) or None

    row: dict[str, Any] = {
        "game_id": str(event.get("id") or comp.get("id") or ""),
        "league": league,
        "game_date": eastern_date(start_iso),
        "start_time_utc": start_iso,
        "home": map_abbrev(league, _abbrev(home)),
        "away": map_abbrev(league, _abbrev(away)),
        "home_name": _team_name(home),
        "away_name": _team_name(away),
        "home_score": _score(home, has_played),
        "away_score": _score(away, has_played),
        "status": status,
        "detailed_status": detailed,
        "venue": venue,
        "neutral_site": bool(comp.get("neutralSite")),
    }
    if status == "live":
        row["live"] = _live_block(comp, status_obj, league)
    return row


def _live_block(comp: dict[str, Any], status_obj: dict[str, Any], league: str) -> dict[str, Any]:
    period = status_obj.get("period")
    try:
        period_int = int(period) if period is not None else None
    except (TypeError, ValueError):
        period_int = None

    clock = status_obj.get("displayClock")
    if clock in ("", "0.0"):
        clock = None

    situation = comp.get("situation") or {}
    last_play = (situation.get("lastPlay") or {}).get("text") or None

    block: dict[str, Any] = {
        "period": period_int,
        "period_label": _period_label(period_int, league, status_obj),
        "clock": clock,
        "last_play": last_play,
    }
    if league == "nfl":
        # Only present while a drive is active; absent between possessions.
        down_distance = situation.get("shortDownDistanceText") or situation.get("downDistanceText")
        if down_distance:
            block["down_distance"] = down_distance
        if situation.get("possession") is not None:
            block["possession"] = map_abbrev(league, _possession_abbrev(comp, situation.get("possession")))
        if situation.get("isRedZone") is not None:
            block["red_zone"] = bool(situation.get("isRedZone"))
    return block


def _period_label(period: int | None, league: str, status_obj: dict[str, Any]) -> str | None:
    short_detail = (status_obj.get("type") or {}).get("shortDetail")
    if period is None:
        return short_detail
    if league == "nfl":
        return f"Q{period}" if period <= 4 else "OT"
    if league == "nba":
        return f"Q{period}" if period <= 4 else f"OT{period - 4}"
    # Sports without quarters (e.g. baseball innings) read far better as the
    # upstream phrasing "Bot 8th" than as a bare period number.
    return short_detail or str(period)


def _possession_abbrev(comp: dict[str, Any], possession_id: Any) -> str | None:
    for competitor in comp.get("competitors") or []:
        if str(competitor.get("id")) == str(possession_id):
            return _abbrev(competitor)
    return None


def _abbrev(competitor: dict[str, Any]) -> str | None:
    team = competitor.get("team") or {}
    return team.get("abbreviation") or team.get("shortDisplayName") or None


def _team_name(competitor: dict[str, Any]) -> str | None:
    team = competitor.get("team") or {}
    return team.get("displayName") or team.get("name") or None


def _iso_z(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    # ESPN emits "2026-08-07T00:00Z"; normalize to full seconds precision.
    if text.endswith("Z") and len(text) == 17:
        return text[:-1] + ":00Z"
    return text


def normalize_events(events: list[dict[str, Any]], league: str) -> list[dict[str, Any]]:
    rows = [normalize_event(e, league) for e in events]
    return [r for r in rows if r is not None]


def window_dates(start: date, days: int) -> str:
    return date_range_param(start, start + timedelta(days=days - 1))


def fetch_window(
    league: str,
    start: date,
    days: int,
    *,
    ttl: int = 300,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch a date window and return contract rows inside it.

    Dates are US Eastern slate dates (see `eastern_date`), which is how the
    leagues and this repo's own databases label games.

    ESPN's `dates` parameter also filters by Eastern local date, but the event
    payload only carries a UTC timestamp. Deriving the date naively from that
    UTC string is a measured trap, not a theoretical one: the 2026 Hall of Fame
    game starts at 2026-08-07T00:00Z, so a UTC reading files it under 08-07
    while ESPN returns it only for `dates=20260806` (it is 8/6 8:00 PM EDT).
    We therefore convert to Eastern before filtering, and pad the upstream query
    by a day on each side so no boundary game is dropped.
    """
    end = start + timedelta(days=days - 1)
    padded = date_range_param(start - timedelta(days=1), end + timedelta(days=1))
    events, cache_meta = fetch_scoreboard(league, dates=padded, ttl=ttl)
    rows = normalize_events(events, league)

    lo, hi = start.isoformat(), end.isoformat()
    rows = [r for r in rows if r["game_date"] and lo <= r["game_date"] <= hi]
    rows = dedupe_by_game_id(rows)
    rows.sort(key=lambda r: (r["start_time_utc"] or "", r["game_id"]))
    return rows, cache_meta


def dedupe_by_game_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated game_ids, preferring the most-progressed row.

    The padded window can return the same event twice. Distinct games that
    happen to share a slot (doubleheaders) have distinct ESPN ids and are
    preserved.
    """
    rank = {"scheduled": 0, "postponed": 1, "live": 2, "final": 3}
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        gid = row["game_id"]
        current = best.get(gid)
        if current is None or rank.get(row["status"], 0) >= rank.get(current["status"], 0):
            best[gid] = row
    return list(best.values())
