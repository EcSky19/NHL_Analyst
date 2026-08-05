"""FastAPI router for live MLB StatsAPI data."""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter

from app.cache import cached_fetch
from app.config import BROWSER_USER_AGENT, fail, ok, season_state_for, settings

logger = logging.getLogger(__name__)
router = APIRouter()

SOURCE_API = "mlb-statsapi"
SOURCE_DB = "mlb-db"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEASON_RE = re.compile(r"^\d{4}$")
LEAGUE_NAMES = {103: "American", 104: "National"}
STAT_DEFAULTS = {"hitting": "ops", "pitching": "era"}


def _current_mlb_season() -> str:
    """Return the season year that MLB current endpoints should use."""
    today = datetime.now(timezone.utc)
    return str(today.year - 1 if today.month in (1, 2) else today.year)


def _validate_season(season: str | None) -> str:
    if season is None:
        return _current_mlb_season()
    if not SEASON_RE.match(season):
        raise ValueError("season must use four digits, for example 2026")
    year = int(season)
    current = int(_current_mlb_season())
    if year < 1876 or year > current:
        raise ValueError(f"season must be between 1876 and {current}")
    return season


def _validate_date(date: str | None) -> str:
    if date is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not DATE_RE.match(date):
        raise ValueError("date must use format YYYY-MM-DD")
    datetime.strptime(date, "%Y-%m-%d")
    return date


def _api_json(url: str) -> Any:
    headers = {"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json"}
    with httpx.Client(headers=headers, timeout=settings.request_timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def _cached_api_json(key: str, url: str, ttl: int) -> tuple[Any, dict[str, Any]]:
    value, meta = cached_fetch(key, ttl, lambda: _api_json(url))
    return value, _with_fetched_at(meta)


def _with_fetched_at(meta: dict[str, Any]) -> dict[str, Any]:
    """Add a fetch timestamp inferred from cache age."""
    out = dict(meta)
    age = float(out.get("age_seconds") or 0.0)
    out["fetched_at"] = (datetime.now(timezone.utc) - timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def _merge_cache_meta(*metas: dict[str, Any]) -> dict[str, Any]:
    """Combine cache metadata from multiple StatsAPI requests."""
    merged: dict[str, Any] = {"cached": False, "stale": False, "age_seconds": 0.0}
    stale_reasons: list[str] = []
    fetched: list[str] = []
    for meta in metas:
        if not meta:
            continue
        merged["cached"] = bool(merged["cached"] or meta.get("cached"))
        merged["stale"] = bool(merged["stale"] or meta.get("stale"))
        merged["age_seconds"] = max(float(merged["age_seconds"]), float(meta.get("age_seconds") or 0.0))
        if meta.get("stale_reason"):
            stale_reasons.append(str(meta["stale_reason"]))
        if meta.get("fetched_at"):
            fetched.append(str(meta["fetched_at"]))
    if stale_reasons:
        merged["stale_reason"] = "; ".join(stale_reasons)
    if fetched:
        merged["fetched_at"] = min(fetched)
    return merged


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record(wins: Any, losses: Any, ties: Any = None) -> str | None:
    if wins is None or losses is None:
        return None
    parts = [str(int(wins)), str(int(losses))]
    if ties not in (None, 0, "0"):
        parts.append(str(int(ties)))
    return "-".join(parts)


def _short_division(name: str | None) -> str | None:
    if not name:
        return None
    for suffix in (" East", " Central", " West"):
        if name.endswith(suffix):
            return suffix.strip()
    return name.replace("American League ", "").replace("National League ", "")


def _league_name(record: dict[str, Any], team: dict[str, Any] | None = None) -> str | None:
    league = record.get("league") or (team or {}).get("league") or {}
    name = league.get("name")
    league_id = _as_int(league.get("id"))
    if league_id in LEAGUE_NAMES:
        return LEAGUE_NAMES[league_id]
    if isinstance(name, str):
        return name.replace(" League", "")
    return None


def _split_record(team_record: dict[str, Any], split_type: str) -> str | None:
    for split in team_record.get("records", {}).get("splitRecords", []):
        if split.get("type") == split_type:
            return _record(split.get("wins"), split.get("losses"), split.get("ties"))
    return None


def _team_logo(team_id: Any) -> str | None:
    return f"https://www.mlbstatic.com/team-logos/{team_id}.svg" if team_id is not None else None


def _normalize_standing(team_record: dict[str, Any], division_record: dict[str, Any], team_meta: dict[int, dict[str, Any]]) -> dict[str, Any]:
    team = team_record.get("team") or {}
    team_id = team.get("id")
    meta = team_meta.get(_as_int(team_id) or -1, {})
    wins = _as_int(team_record.get("wins") or team_record.get("leagueRecord", {}).get("wins"))
    losses = _as_int(team_record.get("losses") or team_record.get("leagueRecord", {}).get("losses"))
    games = _as_int(team_record.get("gamesPlayed")) or ((wins or 0) + (losses or 0))
    runs_for = _as_int(team_record.get("runsScored"))
    runs_against = _as_int(team_record.get("runsAllowed"))
    rank = _as_int(team_record.get("divisionRank") or team_record.get("leagueRank") or team_record.get("sportRank"))
    division_name = (division_record.get("division") or {}).get("name") or (meta.get("division") or {}).get("name")
    clinched = team_record.get("clinchIndicator") or ("Y" if team_record.get("clinched") else None)
    return {
        "team_id": str(team_id) if team_id is not None else None,
        "abbrev": meta.get("abbreviation") or meta.get("fileCode", "").upper() or None,
        "name": meta.get("name") or team.get("name"),
        "conference": _league_name(division_record, meta),
        "division": _short_division(division_name),
        "rank": rank,
        "games_played": games,
        "wins": wins,
        "losses": losses,
        "otl": None,
        "ties": None,
        "points": wins,
        "points_pct": _as_float(team_record.get("winningPercentage") or team_record.get("leagueRecord", {}).get("pct")),
        "win_pct": _as_float(team_record.get("winningPercentage") or team_record.get("leagueRecord", {}).get("pct")),
        "goals_for": runs_for,
        "goals_against": runs_against,
        "differential": _as_int(team_record.get("runDifferential")) if team_record.get("runDifferential") is not None else ((runs_for - runs_against) if runs_for is not None and runs_against is not None else None),
        "streak": (team_record.get("streak") or {}).get("streakCode"),
        "last10": _split_record(team_record, "lastTen"),
        "home_record": _split_record(team_record, "home"),
        "away_record": _split_record(team_record, "away"),
        "logo_url": _team_logo(team_id),
        "clinched": clinched,
        "games_behind": None if team_record.get("gamesBack") == "-" else team_record.get("gamesBack"),
    }


def _fetch_teams(season: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = f"{settings.mlb_api_base}/teams?sportId=1&season={season}"
    raw, meta = _cached_api_json(f"mlb:teams:{season}", url, settings.ttl_stats)
    teams = raw.get("teams", []) if isinstance(raw, dict) else []
    return teams, meta


def _team_meta(season: str) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    teams, meta = _fetch_teams(season)
    return {_as_int(team.get("id")) or -1: team for team in teams}, meta


def _fetch_standings(season: str) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    url = f"{settings.mlb_api_base}/standings?leagueId=103,104&season={season}"
    raw, standings_meta = _cached_api_json(f"mlb:standings:{season}", url, settings.ttl_standings)
    team_meta, teams_meta = _team_meta(season)
    if not isinstance(raw, dict):
        raise ValueError("standings response was not a JSON object")
    rows: list[dict[str, Any]] = []
    for division in raw.get("records", []):
        rows.extend(_normalize_standing(row, division, team_meta) for row in division.get("teamRecords", []))
    rows.sort(key=lambda row: (row.get("conference") or "", row.get("division") or "", row.get("rank") or 99))
    resolved = next((str(row.get("season")) for rec in raw.get("records", []) for row in rec.get("teamRecords", []) if row.get("season")), season)
    return rows, _merge_cache_meta(standings_meta, teams_meta), resolved


def _team_from_standing(row: dict[str, Any], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {**row, "record": _record(row.get("wins"), row.get("losses"))}
    if meta:
        payload.update(
            {
                "venue": (meta.get("venue") or {}).get("name"),
                "location": meta.get("locationName"),
                "club_name": meta.get("clubName"),
                "first_year": meta.get("firstYearOfPlay"),
                "active": meta.get("active"),
            }
        )
    return payload


def _db_standings(season: str) -> list[dict[str, Any]]:
    """Best-effort read-only fallback if the research DB exists."""
    if not settings.mlb_db.exists():
        return []
    try:
        with sqlite3.connect(f"file:{settings.mlb_db}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "standings" not in tables:
                return []
            rows = con.execute("SELECT * FROM standings WHERE season = ?", (season,)).fetchall()
    except sqlite3.Error as exc:
        logger.warning("MLB standings DB fallback failed: %s", exc)
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        wins = _as_int(data.get("wins"))
        losses = _as_int(data.get("losses"))
        rf = _as_int(data.get("runs_scored") or data.get("runsScored"))
        ra = _as_int(data.get("runs_allowed") or data.get("runsAllowed"))
        normalized.append(
            {
                "team_id": str(data.get("team_id") or data.get("teamId") or data.get("abbrev")),
                "abbrev": data.get("abbrev") or data.get("abbreviation"),
                "name": data.get("name") or data.get("team_name"),
                "conference": data.get("league") or data.get("conference"),
                "division": data.get("division"),
                "rank": _as_int(data.get("rank") or data.get("division_rank")),
                "games_played": _as_int(data.get("games_played") or data.get("gamesPlayed")) or ((wins or 0) + (losses or 0)),
                "wins": wins,
                "losses": losses,
                "otl": None,
                "ties": None,
                "points": wins,
                "points_pct": _as_float(data.get("winning_percentage") or data.get("win_pct")),
                "win_pct": _as_float(data.get("winning_percentage") or data.get("win_pct")),
                "goals_for": rf,
                "goals_against": ra,
                "differential": _as_int(data.get("run_differential")) if data.get("run_differential") is not None else ((rf - ra) if rf is not None and ra is not None else None),
                "streak": data.get("streak"),
                "last10": data.get("last10"),
                "home_record": data.get("home_record"),
                "away_record": data.get("away_record"),
                "logo_url": _team_logo(data.get("team_id") or data.get("teamId")),
                "clinched": data.get("clinched"),
                "games_behind": data.get("games_behind") or data.get("gamesBack"),
            }
        )
    return normalized


def _status(game: dict[str, Any]) -> str:
    status = game.get("status") or {}
    abstract = str(status.get("abstractGameState") or "").lower()
    detailed = str(status.get("detailedState") or "").lower()
    if "suspend" in detailed:
        return "suspended"
    if "postpon" in detailed:
        return "postponed"
    if abstract == "final":
        return "final"
    if abstract == "live":
        return "in-progress"
    return "scheduled"


def _normalize_game(game: dict[str, Any], teams_by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    home = (game.get("teams") or {}).get("home") or {}
    away = (game.get("teams") or {}).get("away") or {}
    home_team = home.get("team") or {}
    away_team = away.get("team") or {}
    home_meta = teams_by_id.get(_as_int(home_team.get("id")) or -1, {})
    away_meta = teams_by_id.get(_as_int(away_team.get("id")) or -1, {})
    status = game.get("status") or {}
    return {
        "game_id": str(game.get("gamePk")) if game.get("gamePk") is not None else game.get("gameGuid"),
        "game_guid": game.get("gameGuid"),
        "game_date": game.get("officialDate"),
        "season": str(game.get("season")) if game.get("season") is not None else None,
        "game_type": game.get("gameType"),
        "status": _status(game),
        "detailed_status": status.get("detailedState"),
        "start_time_utc": game.get("gameDate"),
        "venue": (game.get("venue") or {}).get("name"),
        "home": home_meta.get("abbreviation") or home_meta.get("fileCode", "").upper() or home_team.get("name"),
        "away": away_meta.get("abbreviation") or away_meta.get("fileCode", "").upper() or away_team.get("name"),
        "home_name": home_team.get("name"),
        "away_name": away_team.get("name"),
        "home_score": home.get("score"),
        "away_score": away.get("score"),
        "home_logo_url": _team_logo(home_team.get("id")),
        "away_logo_url": _team_logo(away_team.get("id")),
        "doubleheader": game.get("doubleHeader"),
        "game_number": game.get("gameNumber"),
        "calendar_event_id": game.get("calendarEventID"),
    }


def _fetch_schedule(date: str, season: str) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    url = f"{settings.mlb_api_base}/schedule?sportId=1&date={date}"
    raw, schedule_meta = _cached_api_json(f"mlb:schedule:{date}", url, settings.ttl_schedule)
    teams_by_id, teams_meta = _team_meta(season)
    if not isinstance(raw, dict):
        raise ValueError("schedule response was not a JSON object")
    games = [_normalize_game(game, teams_by_id) for day in raw.get("dates", []) for game in day.get("games", [])]
    resolved = next((game.get("season") for game in games if game.get("season")), season)
    return games, _merge_cache_meta(schedule_meta, teams_meta), str(resolved)


def _normalize_player(split: dict[str, Any], group: str, stat_name: str) -> dict[str, Any]:
    player = split.get("player") or {}
    team = split.get("team") or {}
    stat = split.get("stat") or {}
    value = stat.get(stat_name)
    return {
        "player_id": str(player.get("id")) if player.get("id") is not None else None,
        "name": player.get("fullName"),
        "team": team.get("name"),
        "team_id": str(team.get("id")) if team.get("id") is not None else None,
        "position": (split.get("position") or {}).get("abbreviation"),
        "group": group,
        "rank": _as_int(split.get("rank")),
        "games_played": stat.get("gamesPlayed") or stat.get("gamesPitched"),
        "stat": stat_name,
        "value": value,
        "stats": stat,
    }


def _sort_players(players: list[dict[str, Any]], stat: str, limit: int) -> list[dict[str, Any]]:
    reverse = stat not in {"era", "whip", "losses"}
    available = [player for player in players if player.get("value") is not None]
    available.sort(key=lambda p: _as_float(p.get("value")) if _as_float(p.get("value")) is not None else -1, reverse=reverse)
    return available[:limit]


def _fetch_players(season: str, team: str | None, stat: str | None, group: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    stat_name = stat or STAT_DEFAULTS[group]
    team_param = ""
    team_meta: dict[str, Any] = {}
    if team:
        teams, team_meta = _fetch_teams(season)
        match = next((item for item in teams if item.get("abbreviation") == team.upper()), None)
        if not match:
            return [], team_meta, season
        team_param = f"&teamId={match.get('id')}"
    url = f"{settings.mlb_api_base}/stats?stats=season&group={group}&season={season}&sportId=1&limit={limit}&sortStat={stat_name}{team_param}"
    raw, stats_meta = _cached_api_json(f"mlb:players:{season}:{group}:{team or 'all'}:{stat_name}:{limit}", url, settings.ttl_stats)
    splits = []
    if isinstance(raw, dict):
        for block in raw.get("stats", []):
            splits.extend(block.get("splits", []))
    players = [_normalize_player(split, group, stat_name) for split in splits]
    players = _sort_players(players, stat_name, limit)
    return players, _merge_cache_meta(team_meta, stats_meta), season


@router.get("/standings")
def standings(season: str | None = None) -> dict[str, Any]:
    """Return live MLB standings in the shared UI shape."""
    try:
        requested = _validate_season(season)
        rows, cache_meta, resolved = _fetch_standings(requested)
        if not rows:
            return fail("no_data", "No MLB standings were returned.", source=SOURCE_API, **cache_meta, season=requested, season_state=season_state_for(league="mlb"))
        return ok(rows, source=SOURCE_API, **cache_meta, season=resolved, season_state=season_state_for(league="mlb"), count=len(rows))
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE_API, season_state=season_state_for(league="mlb"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("MLB standings upstream failed: %s", exc)
        requested = season if season and SEASON_RE.match(season) else _current_mlb_season()
        rows = _db_standings(requested)
        if rows:
            return ok(rows, source=SOURCE_DB, season=requested, season_state=season_state_for(league="mlb"), count=len(rows))
        return fail("upstream_unavailable", "MLB standings are unavailable.", source=SOURCE_API, season=requested, season_state=season_state_for(league="mlb"))


@router.get("/teams")
def teams(season: str | None = None) -> dict[str, Any]:
    """Return MLB teams with standings summary stats."""
    try:
        requested = _validate_season(season)
        rows, standings_meta, resolved = _fetch_standings(requested)
        teams_by_id, teams_meta = _team_meta(requested)
        data = [_team_from_standing(row, teams_by_id.get(_as_int(row.get("team_id")) or -1)) for row in rows]
        if not data:
            return fail("no_data", "No MLB teams were returned.", source=SOURCE_API, **_merge_cache_meta(standings_meta, teams_meta), season=resolved, season_state=season_state_for(league="mlb"))
        return ok(data, source=SOURCE_API, **_merge_cache_meta(standings_meta, teams_meta), season=resolved, season_state=season_state_for(league="mlb"), count=len(data))
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE_API, season_state=season_state_for(league="mlb"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("MLB teams failed: %s", exc)
        return fail("upstream_unavailable", "MLB teams are unavailable.", source=SOURCE_API, season_state=season_state_for(league="mlb"))


@router.get("/teams/{abbrev}")
def team_detail(abbrev: str, season: str | None = None) -> dict[str, Any]:
    """Return one MLB team detail by abbreviation."""
    try:
        requested = _validate_season(season)
        rows, standings_meta, resolved = _fetch_standings(requested)
        teams_by_id, teams_meta = _team_meta(requested)
        meta = _merge_cache_meta(standings_meta, teams_meta)
        target = abbrev.upper()
        for row in rows:
            if row.get("abbrev") == target:
                return ok(_team_from_standing(row, teams_by_id.get(_as_int(row.get("team_id")) or -1)), source=SOURCE_API, **meta, season=resolved, season_state=season_state_for(league="mlb"))
        return fail("not_found", f"MLB team '{abbrev}' was not found.", source=SOURCE_API, **meta, season=resolved, season_state=season_state_for(league="mlb"))
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE_API, season_state=season_state_for(league="mlb"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("MLB team detail failed: %s", exc)
        return fail("upstream_unavailable", "MLB team detail is unavailable.", source=SOURCE_API, season_state=season_state_for(league="mlb"))


@router.get("/players")
def players(team: str | None = None, stat: str | None = None, group: str = "hitting", limit: int = 50, season: str | None = None) -> dict[str, Any]:
    """Return MLB hitting or pitching player leaders."""
    try:
        requested = _validate_season(season)
        if group not in {"hitting", "pitching"}:
            raise ValueError("group must be hitting or pitching")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        leaders, cache_meta, resolved = _fetch_players(requested, team.upper() if team else None, stat, group, limit)
        if team and not leaders:
            return fail("not_found", f"MLB team '{team}' was not found or has no matching leaders.", source=SOURCE_API, **cache_meta, season=resolved, season_state=season_state_for(league="mlb"))
        if not leaders:
            return fail("no_data", "No MLB player leaders were returned.", source=SOURCE_API, **cache_meta, season=resolved, season_state=season_state_for(league="mlb"))
        return ok(leaders, source=SOURCE_API, **cache_meta, season=resolved, season_state=season_state_for(league="mlb"), count=len(leaders), stat=stat or STAT_DEFAULTS[group], group=group)
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE_API, season_state=season_state_for(league="mlb"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("MLB players failed: %s", exc)
        return fail("upstream_unavailable", "MLB player leaders are unavailable.", source=SOURCE_API, season_state=season_state_for(league="mlb"))


@router.get("/schedule")
def schedule(date: str | None = None, season: str | None = None) -> dict[str, Any]:
    """Return MLB games for a date without collapsing doubleheaders."""
    try:
        requested_date = _validate_date(date)
        requested_season = _validate_season(season or requested_date[:4])
        games, cache_meta, resolved = _fetch_schedule(requested_date, requested_season)
        return ok(games, source=SOURCE_API, **cache_meta, season=resolved, season_state=season_state_for(league="mlb"), count=len(games), date=requested_date)
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE_API, season_state=season_state_for(league="mlb"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("MLB schedule failed: %s", exc)
        return fail("upstream_unavailable", "MLB schedule is unavailable.", source=SOURCE_API, season_state=season_state_for(league="mlb"))
