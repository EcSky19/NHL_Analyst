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
from app.services.espn_pbp import (
    MLB_REGULATION_INNINGS,
    REGULATION,
    frac_remaining_clock,
    frac_remaining_innings,
    parse_clock_seconds,
)
from app.services.live_winprob import GameState, predict_home_win_prob

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


def _validate_week_params(start: str | None, days: str | int | None) -> tuple[str, int, str]:
    start_date = _validate_date(start)
    try:
        day_count = 7 if days is None else int(days)
    except (TypeError, ValueError):
        raise ValueError("days must be an integer between 1 and 14") from None
    if day_count < 1 or day_count > 14:
        raise ValueError("days must be an integer between 1 and 14")
    end_date = (datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=day_count - 1)).strftime("%Y-%m-%d")
    return start_date, day_count, end_date


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
    normalized = _contract_status(game)
    return "in-progress" if normalized == "live" else normalized


def _contract_status(game: dict[str, Any]) -> str:
    status = game.get("status") or {}
    abstract = str(status.get("abstractGameState") or "").lower()
    detailed = str(status.get("detailedState") or "").lower()
    coded = str(status.get("codedGameState") or "").lower()
    if "postpon" in detailed or "suspend" in detailed or "delay" in detailed:
        # The shared contract has no delayed/suspended bucket. Treat them as
        # postponed rather than live because play is not currently in progress.
        return "postponed"
    if abstract == "final" or detailed in {"final", "game over"} or coded == "f":
        return "final"
    if abstract == "live":
        return "live"
    return "scheduled"


def _score_for_status(score: Any, status: str, detailed_status: Any) -> int | None:
    detailed = str(detailed_status or "").lower()
    if status == "scheduled" or "postpon" in detailed:
        return None
    return _as_int(score)


def _runner_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return value.get("fullName") or value.get("name")


def _period_label(inning: int | None, half: str | None) -> str | None:
    if inning is None:
        return None
    half_lower = str(half or "").lower()
    if half_lower.startswith("top"):
        return f"T{inning}"
    if half_lower.startswith("bottom"):
        return f"B{inning}"
    if half_lower.startswith("middle"):
        return f"M{inning}"
    if half_lower.startswith("end"):
        return f"E{inning}"
    return str(inning)


def _live_object(game: dict[str, Any]) -> dict[str, Any]:
    linescore = game.get("linescore") or {}
    inning = _as_int(linescore.get("currentInning"))
    half = linescore.get("inningState") or linescore.get("inningHalf")
    current_play = linescore.get("currentPlay") or game.get("currentPlay") or {}
    result = current_play.get("result") if isinstance(current_play, dict) else {}
    live: dict[str, Any] = {
        "period": inning,
        "period_label": _period_label(inning, half),
        "clock": None,
        "last_play": result.get("description") if isinstance(result, dict) else None,
    }
    for key in ("balls", "strikes", "outs"):
        value = _as_int(linescore.get(key))
        if value is not None:
            live[key] = value
    offense = linescore.get("offense") or {}
    if isinstance(offense, dict):
        runner_names = {base: _runner_name(offense.get(base)) for base in ("first", "second", "third")}
        if any(name is not None for name in runner_names.values()):
            live["runners_on_base"] = {base: name is not None for base, name in runner_names.items()}
            live["runners"] = runner_names
    return live


def _normalize_game(game: dict[str, Any], teams_by_id: dict[int, dict[str, Any]], slate_date: str | None = None) -> dict[str, Any]:
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
        "game_date": slate_date or game.get("officialDate"),
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
        "rescheduled_from": game.get("rescheduledFrom"),
        "live": _live_object(game) if _contract_status(game) == "live" else None,
    }


def _dedupe_schedule_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one row per gamePk in a response.

    StatsAPI can list a postponed game on its original slate and again on the
    makeup slate with the same gamePk. The UI keys rows by game_id, so we drop
    the superseded postponed ledger row and keep the resolved non-postponed row.
    Doubleheaders remain safe because they use distinct gamePks.
    """
    by_id: dict[str, dict[str, Any]] = {}
    no_id: list[dict[str, Any]] = []
    for game in games:
        game_id = game.get("game_id")
        if game_id is None:
            no_id.append(game)
            continue
        key = str(game_id)
        current = by_id.get(key)
        if current is None:
            by_id[key] = game
            continue
        current_status = _contract_game_row(current)["status"]
        candidate_status = _contract_game_row(game)["status"]
        if current_status == "postponed" and candidate_status != "postponed":
            by_id[key] = game
        elif current_status == candidate_status and str(game.get("start_time_utc") or "") > str(current.get("start_time_utc") or ""):
            by_id[key] = game
    return [*by_id.values(), *no_id]


def _contract_game_row(game: dict[str, Any]) -> dict[str, Any]:
    status = "live" if game.get("status") == "in-progress" else game.get("status")
    if status not in {"scheduled", "live", "final", "postponed"}:
        status = "scheduled"
    detailed = game.get("detailed_status")
    row = {
        "game_id": str(game.get("game_id")) if game.get("game_id") is not None else None,
        "league": "mlb",
        "game_date": game.get("game_date"),
        "start_time_utc": game.get("start_time_utc"),
        "home": game.get("home"),
        "away": game.get("away"),
        "home_name": game.get("home_name"),
        "away_name": game.get("away_name"),
        "home_score": _score_for_status(game.get("home_score"), status, detailed),
        "away_score": _score_for_status(game.get("away_score"), status, detailed),
        "status": status,
        "detailed_status": detailed,
        "venue": game.get("venue"),
    }
    if status == "live":
        row["live"] = game.get("live") or {"period": None, "period_label": None, "clock": None, "last_play": None}
    return row


def _fetch_schedule(date: str, season: str) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    url = f"{settings.mlb_api_base}/schedule?sportId=1&date={date}"
    raw, schedule_meta = _cached_api_json(f"mlb:schedule:{date}", url, settings.ttl_schedule)
    teams_by_id, teams_meta = _team_meta(season)
    if not isinstance(raw, dict):
        raise ValueError("schedule response was not a JSON object")
    games = [_normalize_game(game, teams_by_id) for day in raw.get("dates", []) for game in day.get("games", [])]
    resolved = next((game.get("season") for game in games if game.get("season")), season)
    return games, _merge_cache_meta(schedule_meta, teams_meta), str(resolved)


def _fetch_schedule_range(start_date: str, end_date: str, season: str, ttl: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    url = f"{settings.mlb_api_base}/schedule?sportId=1&startDate={start_date}&endDate={end_date}&hydrate=linescore,team"
    raw, schedule_meta = _cached_api_json(f"mlb:schedule-range:{start_date}:{end_date}", url, ttl or settings.ttl_schedule)
    teams_by_id, teams_meta = _team_meta(season)
    if not isinstance(raw, dict):
        raise ValueError("schedule response was not a JSON object")
    games = [_normalize_game(game, teams_by_id, day.get("date")) for day in raw.get("dates", []) for game in day.get("games", [])]
    resolved = next((game.get("season") for game in games if game.get("season")), season)
    return games, _merge_cache_meta(schedule_meta, teams_meta), str(resolved)


def _fetch_live_window() -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    end_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    season = _current_mlb_season()
    games, meta, resolved = _fetch_schedule_range(start_date, end_date, season, ttl=30)
    return [game for game in _dedupe_schedule_games(games) if _contract_game_row(game)["status"] == "live"], meta, resolved


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


@router.get("/schedule/week")
def schedule_week(start: str | None = None, days: str | None = None) -> dict[str, Any]:
    """Return a flat MLB schedule window in the frozen shared game-row shape."""
    league_state = season_state_for(league="mlb")
    try:
        start_date, day_count, end_date = _validate_week_params(start, days)
        requested_season = _validate_season(start_date[:4])
        games, cache_meta, resolved = _fetch_schedule_range(start_date, end_date, requested_season)
        if cache_meta.get("stale"):
            return fail(
                "upstream_unavailable",
                "MLB schedule is unavailable from StatsAPI.",
                source=SOURCE_API,
                **cache_meta,
                season=resolved,
                season_state=league_state,
                league="mlb",
                start_date=start_date,
                end_date=end_date,
                days=day_count,
                count=0,
                empty_reason=None,
            )
        rows = [_contract_game_row(game) for game in _dedupe_schedule_games(games)]
        rows.sort(key=lambda row: (row.get("start_time_utc") or "", row.get("game_id") or ""))
        empty_reason = None if rows else "No MLB games are scheduled in this window."
        return ok(
            rows,
            source=SOURCE_API,
            **cache_meta,
            season=resolved,
            season_state=league_state,
            league="mlb",
            start_date=start_date,
            end_date=end_date,
            days=day_count,
            count=len(rows),
            empty_reason=empty_reason,
        )
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE_API, season_state=league_state, league="mlb")
    except Exception as exc:  # noqa: BLE001
        logger.warning("MLB week schedule failed: %s", exc)
        return fail("upstream_unavailable", "MLB schedule is unavailable from StatsAPI.", source=SOURCE_API, season_state=league_state, league="mlb")


@router.get("/live")
def live() -> dict[str, Any]:
    """Return currently in-progress MLB games only."""
    league_state = season_state_for(league="mlb")
    try:
        games, cache_meta, resolved = _fetch_live_window()
        if cache_meta.get("stale"):
            return fail(
                "upstream_unavailable",
                "MLB live games are unavailable from StatsAPI.",
                source=SOURCE_API,
                **cache_meta,
                season=resolved,
                season_state=league_state,
                league="mlb",
                count=0,
                polled_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                poll_interval_seconds=30,
                empty_reason=None,
            )
        rows = [_with_live_win_probability(_contract_game_row(game), "mlb") for game in games if _contract_game_row(game)["status"] == "live"]
        rows.sort(key=lambda row: (row.get("start_time_utc") or "", row.get("game_id") or ""))
        empty_reason = None if rows else "No MLB games are currently in progress."
        return ok(
            rows,
            source=SOURCE_API,
            **cache_meta,
            season=resolved,
            season_state=league_state,
            league="mlb",
            count=len(rows),
            polled_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            poll_interval_seconds=30,
            empty_reason=empty_reason,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("MLB live failed: %s", exc)
        return fail("upstream_unavailable", "MLB live games are unavailable from StatsAPI.", source=SOURCE_API, season_state=league_state, league="mlb")


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


def _live_win_probability(row: dict[str, Any], league: str) -> dict[str, Any]:
    """Return the honest live win-probability payload for one live row."""
    unavailable = {
        "available": False,
        "home": None,
        "away": None,
        "model": f"{league}_live_wp",
        "reason": "Live win probability unavailable because live game state is incomplete.",
    }
    if row.get("status") != "live":
        return unavailable
    live = row.get("live") if isinstance(row.get("live"), dict) else {}
    home_score = _wp_int(row.get("home_score"))
    away_score = _wp_int(row.get("away_score"))
    period = _wp_int(live.get("period"))
    if home_score is None or away_score is None or period is None:
        return unavailable

    if league == "mlb":
        # _period_label emits T5 / M5 (middle) / B5 / E5 (end) / bare "5".
        # "M" (top over, bottom not started) is equivalent to bottom of the
        # same inning, but "E" means the inning is COMPLETE, so the live state
        # is the top of the next inning. Folding E into the bottom case leaves
        # the model half an inning behind the real game.
        label = str(live.get("period_label") or row.get("detailed_status") or "").strip().upper()
        inning, is_top = period, False
        if label.startswith("T"):
            is_top = True
        elif label.startswith("E"):
            inning, is_top = period + 1, True
        is_overtime = inning > MLB_REGULATION_INNINGS
        frac_remaining = 0.0 if is_overtime else frac_remaining_innings(inning, is_top)
    else:
        is_overtime = period > int(REGULATION[league]["periods"])
        frac_remaining = frac_remaining_clock(league, period, parse_clock_seconds(live.get("clock")))

    prob, meta = predict_home_win_prob(
        GameState(
            league=league,
            margin=home_score - away_score,
            frac_remaining=frac_remaining,
            period=period,
            is_overtime=is_overtime,
        )
    )
    if prob is None:
        return {
            "available": False,
            "home": None,
            "away": None,
            "model": f"{league}_live_wp",
            "reason": str(meta.get("reason") or "Live win-probability model is unavailable."),
        }
    home_prob = round(float(prob), 6)
    return {
        "available": True,
        "home": home_prob,
        "away": round(1.0 - home_prob, 6),
        "model": f"{league}_live_wp",
        "reason": None,
    }


def _with_live_win_probability(row: dict[str, Any], league: str) -> dict[str, Any]:
    if row.get("status") != "live":
        return row
    return {**row, "win_probability": _live_win_probability(row, league)}


def _wp_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
