"""FastAPI router for NHL standings, teams, players, and schedule data."""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter

from app.cache import cached_fetch
from app.config import BROWSER_USER_AGENT, fail, ok, season_state_for, settings

logger = logging.getLogger(__name__)
router = APIRouter()

SOURCE_API = "nhl-api"
SOURCE_DB = "nhl-db"
CURRENT_TEAM_COUNT = 32
SEASON_RE = re.compile(r"^\d{8}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _name(value: Any) -> str | None:
    """Return the default localized name from NHL API objects."""
    if isinstance(value, dict):
        return value.get("default") or value.get("en") or next(iter(value.values()), None)
    return value if isinstance(value, str) else None


def _validate_season(season: str | None) -> str | None:
    if season is None:
        return None
    if not SEASON_RE.match(season):
        raise ValueError("season must use format YYYYYYYY, for example 20242025")
    if int(season[4:]) != int(season[:4]) + 1:
        raise ValueError("season end year must be one year after start year")
    return season


def _validate_date(date: str | None) -> str | None:
    if date is None:
        return None
    if not DATE_RE.match(date):
        raise ValueError("date must use format YYYY-MM-DD")
    datetime.strptime(date, "%Y-%m-%d")
    return date


def _api_json(url: str) -> Any:
    headers = {"User-Agent": BROWSER_USER_AGENT}
    with httpx.Client(headers=headers, timeout=settings.request_timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def _cached_api_json(key: str, url: str, ttl: int) -> tuple[Any, dict[str, Any]]:
    return cached_fetch(key, ttl, lambda: _api_json(url))


def _record(wins: Any, losses: Any, otl: Any = None, ties: Any = None) -> str | None:
    if wins is None or losses is None:
        return None
    parts = [str(int(wins)), str(int(losses))]
    if otl not in (None, 0):
        parts.append(str(int(otl)))
    elif ties not in (None, 0):
        parts.append(str(int(ties)))
    return "-".join(parts)


def _normalize_standing(row: dict[str, Any]) -> dict[str, Any]:
    abbrev = _name(row.get("teamAbbrev"))
    wins = row.get("wins")
    losses = row.get("losses")
    otl = row.get("otLosses")
    games = row.get("gamesPlayed")
    return {
        "team_id": str(row.get("teamId") or abbrev) if (row.get("teamId") or abbrev) else None,
        "abbrev": abbrev,
        "name": _name(row.get("teamName")),
        "conference": row.get("conferenceName"),
        "division": row.get("divisionName"),
        "rank": row.get("leagueSequence") or row.get("divisionSequence"),
        "games_played": games,
        "wins": wins,
        "losses": losses,
        "otl": otl,
        "ties": row.get("ties") if row.get("ties") not in (0, "0") else None,
        "points": row.get("points"),
        "points_pct": row.get("pointPctg"),
        "win_pct": row.get("winPctg"),
        "goals_for": row.get("goalFor"),
        "goals_against": row.get("goalAgainst"),
        "differential": row.get("goalDifferential"),
        "streak": (
            f"{row.get('streakCode')}{row.get('streakCount')}"
            if row.get("streakCode") and row.get("streakCount") is not None
            else None
        ),
        "last10": _record(row.get("l10Wins"), row.get("l10Losses"), row.get("l10OtLosses"), row.get("l10Ties")),
        "home_record": _record(row.get("homeWins"), row.get("homeLosses"), row.get("homeOtLosses"), row.get("homeTies")),
        "away_record": _record(row.get("roadWins"), row.get("roadLosses"), row.get("roadOtLosses"), row.get("roadTies")),
        "logo_url": row.get("teamLogo"),
        "clinched": row.get("clinchIndicator"),
    }


def _season_from_standings(raw: dict[str, Any], rows: list[dict[str, Any]]) -> str | None:
    for row in raw.get("standings", []):
        if row.get("seasonId"):
            return str(row["seasonId"])
    return str(rows[0]["season"]) if rows and rows[0].get("season") else None


def _standings_dates_for_season(season: str) -> list[str]:
    end_year = int(season[4:])
    return [f"{end_year}-04-{day:02d}" for day in range(20, 9, -1)]


def _fetch_standings(season: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    if season is None:
        url = f"{settings.nhl_api_base}/standings/now"
        raw, cache_meta = _cached_api_json("nhl:standings:now", url, settings.ttl_standings)
        rows = [_normalize_standing(row) for row in raw.get("standings", [])]
        return rows, cache_meta, _season_from_standings(raw, rows)

    last_error: Exception | None = None
    for date in _standings_dates_for_season(season):
        url = f"{settings.nhl_api_base}/standings/{date}"
        try:
            raw, cache_meta = _cached_api_json(f"nhl:standings:{date}", url, settings.ttl_standings)
            if not isinstance(raw, dict):
                raise ValueError("standings response was not a JSON object")
            rows = [_normalize_standing(row) for row in raw.get("standings", [])]
            if rows:
                return rows, cache_meta, _season_from_standings(raw, rows) or season
        except Exception as exc:  # noqa: BLE001 - try adjacent final regular-season dates
            last_error = exc
            logger.warning("Could not load NHL standings for %s: %s", date, exc)
    raise last_error or ValueError(f"no standings found for season {season}")


def _db_standings(season: str | None) -> tuple[list[dict[str, Any]], str | None]:
    db_season = season or "20252026"
    compact = db_season[4:] if db_season else "2026"
    with sqlite3.connect(settings.nhl_db) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT t.abbreviation, t.name, ts.metric_name, ts.metric_value
            FROM team_stats ts
            JOIN teams t ON t.team_id = ts.team_id
            WHERE ts.season IN (?, ?)
            """,
            (db_season, compact),
        ).fetchall()
    by_team: dict[str, dict[str, Any]] = {}
    for row in rows:
        abbrev = row["abbreviation"]
        item = by_team.setdefault(abbrev, {"abbrev": abbrev, "name": row["name"], "metrics": {}})
        item["metrics"][row["metric_name"]] = row["metric_value"]

    standings: list[dict[str, Any]] = []
    for abbrev, item in by_team.items():
        m = item["metrics"]
        games = m.get("gamesPlayed") or m.get("general.games") or m.get("general.teamGamesPlayed")
        wins = m.get("wins") or m.get("general.wins")
        losses = m.get("losses") or m.get("general.losses")
        otl = m.get("otLosses") or m.get("defensive.overtimeLosses")
        points = (2 * wins + otl) if wins is not None and otl is not None else None
        standings.append(
            {
                "team_id": abbrev,
                "abbrev": abbrev,
                "name": item["name"],
                "conference": None,
                "division": None,
                "rank": None,
                "games_played": int(games) if games is not None else None,
                "wins": int(wins) if wins is not None else None,
                "losses": int(losses) if losses is not None else None,
                "otl": int(otl) if otl is not None else None,
                "ties": None,
                "points": int(points) if points is not None else None,
                "points_pct": round(points / (2 * games), 6) if points is not None and games else None,
                "win_pct": round(wins / games, 6) if wins is not None and games else None,
                "goals_for": int(m["goalsFor"]) if m.get("goalsFor") is not None else None,
                "goals_against": int(m["goalsAgainst"]) if m.get("goalsAgainst") is not None else None,
                "differential": int(m["general.goalDifferential"]) if m.get("general.goalDifferential") is not None else None,
                "streak": None,
                "last10": None,
                "home_record": None,
                "away_record": None,
                "logo_url": None,
                "clinched": None,
            }
        )
    standings.sort(key=lambda row: (row["points"] is None, -(row["points"] or 0), row["abbrev"] or ""))
    for index, row in enumerate(standings, start=1):
        row["rank"] = index
    return standings, db_season


def _current_abbrevs(season: str | None = None) -> list[str]:
    rows, _, _ = _fetch_standings(season)
    return [row["abbrev"] for row in rows if row.get("abbrev")]


def _team_from_standing(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "record": _record(row.get("wins"), row.get("losses"), row.get("otl"), row.get("ties")),
    }


def _normalize_game(game: dict[str, Any], date: str) -> dict[str, Any]:
    home = game.get("homeTeam") or {}
    away = game.get("awayTeam") or {}
    return {
        "game_id": str(game.get("id")) if game.get("id") is not None else None,
        "game_date": date,
        "season": str(game.get("season")) if game.get("season") is not None else None,
        "game_type": game.get("gameType"),
        "status": game.get("gameState"),
        "start_time_utc": game.get("startTimeUTC"),
        "venue": _name(game.get("venue")),
        "neutral_site": game.get("neutralSite"),
        "home": home.get("abbrev"),
        "away": away.get("abbrev"),
        "home_name": f"{_name(home.get('placeName'))} {_name(home.get('commonName'))}".strip(),
        "away_name": f"{_name(away.get('placeName'))} {_name(away.get('commonName'))}".strip(),
        "home_score": home.get("score"),
        "away_score": away.get("score"),
        "home_logo_url": home.get("logo"),
        "away_logo_url": away.get("logo"),
    }


def _fetch_schedule(date: str | None) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    path = date or "now"
    url = f"{settings.nhl_api_base}/schedule/{path}"
    raw, cache_meta = _cached_api_json(f"nhl:schedule:{path}", url, settings.ttl_schedule)
    if not isinstance(raw, dict) or not isinstance(raw.get("gameWeek"), list):
        raise ValueError("schedule response shape was unexpected")
    games: list[dict[str, Any]] = []
    selected_date = date
    for day in raw["gameWeek"]:
        day_date = day.get("date")
        if date is not None and day_date != date:
            continue
        if selected_date is None and day_date:
            selected_date = day_date
        games.extend(_normalize_game(game, day_date) for game in day.get("games", []))
    season = next((game.get("season") for game in games if game.get("season")), None)
    return games, cache_meta, season


def _player_name(player: dict[str, Any]) -> str:
    return " ".join(part for part in [_name(player.get("firstName")), _name(player.get("lastName"))] if part)


def _normalize_skater(player: dict[str, Any], team: str) -> dict[str, Any]:
    return {
        "player_id": str(player.get("playerId")),
        "name": _player_name(player),
        "team": team,
        "position": player.get("positionCode"),
        "player_type": "skater",
        "games_played": player.get("gamesPlayed"),
        "goals": player.get("goals"),
        "assists": player.get("assists"),
        "points": player.get("points"),
        "plus_minus": player.get("plusMinus"),
        "shots": player.get("shots"),
        "wins": None,
        "losses": None,
        "save_pct": None,
        "gaa": None,
        "headshot": player.get("headshot"),
    }


def _normalize_goalie(player: dict[str, Any], team: str) -> dict[str, Any]:
    return {
        "player_id": str(player.get("playerId")),
        "name": _player_name(player),
        "team": team,
        "position": "G",
        "player_type": "goalie",
        "games_played": player.get("gamesPlayed"),
        "goals": player.get("goals"),
        "assists": player.get("assists"),
        "points": player.get("points"),
        "plus_minus": None,
        "shots": None,
        "wins": player.get("wins"),
        "losses": player.get("losses"),
        "save_pct": player.get("savePercentage"),
        "gaa": player.get("goalsAgainstAverage"),
        "headshot": player.get("headshot"),
    }


def _merge_cache_meta(*metas: dict[str, Any]) -> dict[str, Any]:
    """Combine cache metadata from multiple NHL API requests."""
    merged: dict[str, Any] = {"cached": False, "stale": False, "age_seconds": 0.0}
    stale_reasons: list[str] = []
    for meta in metas:
        merged["cached"] = bool(merged["cached"] or meta.get("cached"))
        merged["stale"] = bool(merged["stale"] or meta.get("stale"))
        merged["age_seconds"] = max(float(merged["age_seconds"]), float(meta.get("age_seconds") or 0.0))
        if meta.get("stale_reason"):
            stale_reasons.append(str(meta["stale_reason"]))
    if stale_reasons:
        merged["stale_reason"] = "; ".join(stale_reasons)
    return merged


def _fetch_team_players(team: str, season: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = f"{settings.nhl_api_base}/club-stats/{team}/{season}/2"
    raw, cache_meta = _cached_api_json(f"nhl:club-stats:{team}:{season}", url, settings.ttl_stats)
    if not isinstance(raw, dict):
        raise ValueError(f"club-stats response for {team} was not an object")
    players = [_normalize_skater(player, team) for player in raw.get("skaters", [])]
    players.extend(_normalize_goalie(player, team) for player in raw.get("goalies", []))
    return players, cache_meta


def _fetch_players(teams: Iterable[str], season: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    players: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_fetch_team_players, team, season): team for team in teams}
        for future in as_completed(futures):
            team = futures[future]
            try:
                team_players, team_meta = future.result()
                players.extend(team_players)
                metas.append(team_meta)
            except Exception as exc:  # noqa: BLE001 - keep useful teams if one upstream fails
                logger.warning("Could not load NHL player stats for %s: %s", team, exc)
    return players, _merge_cache_meta(*metas)


def _db_team_abbrevs() -> list[str]:
    with sqlite3.connect(settings.nhl_db) as con:
        return [
            row[0]
            for row in con.execute(
                "SELECT team_abbreviation FROM current_nhl_32_teams ORDER BY team_abbreviation"
            ).fetchall()
        ]


def _db_players(season: str, team: str | None) -> list[dict[str, Any]]:
    compact = season[4:]
    params: list[Any] = [season, compact]
    team_filter = ""
    if team:
        team_filter = "AND t.abbreviation = ?"
        params.append(team)
    with sqlite3.connect(settings.nhl_db) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"""
            SELECT p.external_player_id, p.full_name, p.position, t.abbreviation, ps.metric_name, ps.metric_value
            FROM player_stats ps
            JOIN players p ON p.player_id = ps.player_id
            LEFT JOIN teams t ON t.team_id = COALESCE(ps.team_id, p.team_id)
            WHERE ps.season IN (?, ?) {team_filter}
            """,
            params,
        ).fetchall()
    by_player: dict[str, dict[str, Any]] = {}
    for row in rows:
        player = by_player.setdefault(
            row["external_player_id"],
            {
                "player_id": row["external_player_id"],
                "name": row["full_name"],
                "team": row["abbreviation"],
                "position": row["position"],
                "player_type": "goalie" if row["position"] == "G" else "skater",
                "games_played": None,
                "goals": None,
                "assists": None,
                "points": None,
                "plus_minus": None,
                "shots": None,
                "wins": None,
                "losses": None,
                "save_pct": None,
                "gaa": None,
                "headshot": None,
            },
        )
        metric = row["metric_name"].replace("league_leader.", "")
        target = {
            "gamesPlayed": "games_played",
            "goals": "goals",
            "assists": "assists",
            "points": "points",
            "plusMinus": "plus_minus",
            "shots": "shots",
            "wins": "wins",
            "losses": "losses",
            "savePct": "save_pct",
            "savePercentage": "save_pct",
            "goalsAgainstAverage": "gaa",
        }.get(metric)
        if target:
            player[target] = row["metric_value"]
    return list(by_player.values())


def _sort_players(players: list[dict[str, Any]], stat: str, limit: int) -> list[dict[str, Any]]:
    stat_key = {
        "save_percentage": "save_pct",
        "save_pct": "save_pct",
        "gaa": "gaa",
        "goals_against_average": "gaa",
        "plus_minus": "plus_minus",
    }.get(stat, stat)
    reverse = stat_key != "gaa"
    filtered = [player for player in players if player.get(stat_key) is not None]
    filtered.sort(key=lambda player: player.get(stat_key) or 0, reverse=reverse)
    leaders = filtered[:limit]
    for player in leaders:
        player["stat"] = stat_key
        player["value"] = player.get(stat_key)
    return leaders


@router.get("/standings")
def standings(season: str | None = None) -> dict[str, Any]:
    """Return normalized NHL standings rows."""
    try:
        requested_season = _validate_season(season)
        rows, cache_meta, resolved_season = _fetch_standings(requested_season)
        if not rows:
            return fail("no_data", "No NHL standings were returned.", source=SOURCE_API, **cache_meta)
        return ok(
            rows,
            source=SOURCE_API,
            **cache_meta,
            season=resolved_season,
            season_state=season_state_for(league="nhl"),
            count=len(rows),
        )
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE_API)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NHL standings upstream failed: %s", exc)
        try:
            rows, resolved_season = _db_standings(season)
            if rows:
                return ok(rows, source=SOURCE_DB, season=resolved_season, season_state=season_state_for(league="nhl"), count=len(rows))
        except Exception as db_exc:  # noqa: BLE001
            logger.warning("NHL standings DB fallback failed: %s", db_exc)
        return fail("upstream_unavailable", "NHL standings are unavailable.", source=SOURCE_API)


@router.get("/teams")
def teams(season: str | None = None) -> dict[str, Any]:
    """Return NHL teams with summary standings stats."""
    try:
        requested_season = _validate_season(season)
        rows, cache_meta, resolved_season = _fetch_standings(requested_season)
        data = [_team_from_standing(row) for row in rows]
        if not data:
            return fail("no_data", "No NHL teams were returned.", source=SOURCE_API, **cache_meta)
        return ok(data, source=SOURCE_API, **cache_meta, season=resolved_season, season_state=season_state_for(league="nhl"), count=len(data))
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE_API)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NHL teams failed: %s", exc)
        return fail("upstream_unavailable", "NHL teams are unavailable.", source=SOURCE_API)


@router.get("/teams/{abbrev}")
def team_detail(abbrev: str) -> dict[str, Any]:
    """Return one NHL team detail by abbreviation."""
    try:
        rows, cache_meta, resolved_season = _fetch_standings(None)
        target = abbrev.upper()
        for row in rows:
            if row.get("abbrev") == target:
                return ok(_team_from_standing(row), source=SOURCE_API, **cache_meta, season=resolved_season, season_state=season_state_for(league="nhl"))
        return fail("not_found", f"NHL team '{abbrev}' was not found.", source=SOURCE_API, **cache_meta, season=resolved_season, season_state=season_state_for(league="nhl"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("NHL team detail failed: %s", exc)
        return fail("upstream_unavailable", "NHL team detail is unavailable.", source=SOURCE_API)


@router.get("/players")
def players(team: str | None = None, stat: str = "points", limit: int = 50, season: str | None = None) -> dict[str, Any]:
    """Return NHL player leaders from club stats."""
    try:
        requested_season = _validate_season(season)
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        try:
            standings_rows, standings_meta, resolved_season = _fetch_standings(requested_season)
        except Exception as exc:  # noqa: BLE001 - DB can still answer player leaders
            logger.warning("NHL standings unavailable while loading players: %s", exc)
            standings_rows, standings_meta, resolved_season = [], {}, requested_season or "20252026"
        season_id = resolved_season or requested_season or "20252026"
        available = {row["abbrev"] for row in standings_rows if row.get("abbrev")} or set(_db_team_abbrevs())
        teams_to_fetch = [team.upper()] if team else sorted(available)
        if team and team.upper() not in available:
            return fail("not_found", f"NHL team '{team}' was not found.", source=SOURCE_API, **standings_meta, season=season_id, season_state=season_state_for(league="nhl"))
        all_players, player_meta = _fetch_players(teams_to_fetch, season_id)
        response_meta = _merge_cache_meta(standings_meta, player_meta)
        source = SOURCE_API
        if not all_players:
            all_players = _db_players(season_id, team.upper() if team else None)
            source = SOURCE_DB
        leaders = _sort_players(all_players, stat, limit)
        if not leaders:
            return fail("no_data", f"No NHL player results found for stat '{stat}'.", source=source, **response_meta, season=season_id, season_state=season_state_for(league="nhl"))
        return ok(leaders, source=source, **response_meta, season=season_id, season_state=season_state_for(league="nhl"), count=len(leaders), stat=stat)
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE_API)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NHL players failed: %s", exc)
        return fail("upstream_unavailable", "NHL player leaders are unavailable.", source=SOURCE_API)


@router.get("/schedule")
def schedule(date: str | None = None) -> dict[str, Any]:
    """Return NHL games for a date or the API's current schedule window."""
    try:
        requested_date = _validate_date(date)
        games, cache_meta, season = _fetch_schedule(requested_date)
        return ok(
            games,
            source=SOURCE_API,
            **cache_meta,
            season=season,
            season_state=season_state_for(league="nhl"),
            count=len(games),
            date=requested_date,
        )
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE_API)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NHL schedule failed: %s", exc)
        return fail("upstream_unavailable", "NHL schedule is unavailable.", source=SOURCE_API)
