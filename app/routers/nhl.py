"""FastAPI router for NHL standings, teams, players, and schedule data."""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter

from app.cache import cached_fetch
from app.config import BROWSER_USER_AGENT, fail, ok, season_state_for, settings
from app.services.espn_pbp import REGULATION, frac_remaining_clock, frac_remaining_innings, parse_clock_seconds
from app.services.live_winprob import GameState, predict_home_win_prob

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


def _validate_days(days: int) -> int:
    if days < 1 or days > 14:
        raise ValueError("days must be between 1 and 14")
    return days


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


def _team_name(team: dict[str, Any]) -> str | None:
    direct = _name(team.get("name"))
    if direct:
        return direct
    return " ".join(
        part
        for part in [_name(team.get("placeName")), _name(team.get("commonName"))]
        if part
    ) or None


def _normalized_status(game: dict[str, Any]) -> str:
    raw_values = {str(game.get(key) or "").upper() for key in ("gameState", "gameScheduleState")}
    if raw_values & {"PPD", "POSTPONED"}:
        return "postponed"
    if raw_values & {"LIVE", "CRIT"}:
        return "live"
    if raw_values & {"OFF", "FINAL"}:
        return "final"
    return "scheduled"


def _detailed_status(game: dict[str, Any]) -> str | None:
    schedule_state = game.get("gameScheduleState")
    if schedule_state and str(schedule_state).upper() != "OK":
        return str(schedule_state)
    game_state = game.get("gameState")
    return str(game_state) if game_state is not None else None


def _score_for(team: dict[str, Any], status: str) -> int | None:
    if status == "scheduled":
        return None
    score = team.get("score")
    return int(score) if score is not None else None


def _period_label(period_descriptor: dict[str, Any] | None) -> str | None:
    if not isinstance(period_descriptor, dict):
        return None
    number = period_descriptor.get("number")
    period_type = str(period_descriptor.get("periodType") or "").upper()
    if period_type == "OT":
        return "OT"
    if period_type == "SO":
        return "SO"
    if number is None:
        return None
    if period_type == "REG" or int(number) <= 3:
        return f"P{int(number)}"
    return "OT"


def _last_play(game: dict[str, Any]) -> str | None:
    for key in ("lastPlay", "last_play"):
        value = game.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            text = value.get("description") or value.get("desc") or value.get("eventOwnerTeamName")
            if isinstance(text, dict):
                return _name(text)
            if isinstance(text, str):
                return text
    return None


def _normalize_game(game: dict[str, Any], date: str | None) -> dict[str, Any]:
    home = game.get("homeTeam") or {}
    away = game.get("awayTeam") or {}
    status = _normalized_status(game)
    return {
        "game_id": str(game.get("id")) if game.get("id") is not None else None,
        "league": "nhl",
        "game_date": date or game.get("gameDate"),
        "season": str(game.get("season")) if game.get("season") is not None else None,
        "game_type": game.get("gameType"),
        "status": status,
        "detailed_status": _detailed_status(game),
        "start_time_utc": game.get("startTimeUTC"),
        "venue": _name(game.get("venue")),
        "neutral_site": game.get("neutralSite"),
        "home": home.get("abbrev"),
        "away": away.get("abbrev"),
        "home_name": _team_name(home),
        "away_name": _team_name(away),
        "home_score": _score_for(home, status),
        "away_score": _score_for(away, status),
        "home_logo_url": home.get("logo"),
        "away_logo_url": away.get("logo"),
    }


def _fetch_schedule_raw(date: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    path = date or "now"
    url = f"{settings.nhl_api_base}/schedule/{path}"
    raw, cache_meta = _cached_api_json(f"nhl:schedule:{path}", url, settings.ttl_schedule)
    if not isinstance(raw, dict) or not isinstance(raw.get("gameWeek"), list):
        raise ValueError("schedule response shape was unexpected")
    return raw, cache_meta


def _fetch_schedule(date: str | None) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    raw, cache_meta = _fetch_schedule_raw(date)
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


def _first_scheduled_game_date(raw: dict[str, Any], start_date: date_type) -> str | None:
    for day in raw.get("gameWeek", []):
        day_date = day.get("date")
        if not day_date:
            continue
        parsed_day = datetime.strptime(day_date, "%Y-%m-%d").date()
        if parsed_day >= start_date and (day.get("numberOfGames") or len(day.get("games", []))):
            return day_date
    return None


def _next_scheduled_game_date(start_date: date_type, max_days: int = 370) -> tuple[str | None, dict[str, Any]]:
    cursor = start_date
    end_date = start_date + timedelta(days=max_days)
    metas: list[dict[str, Any]] = []
    while cursor <= end_date:
        raw, cache_meta = _fetch_schedule_raw(cursor.isoformat())
        metas.append(cache_meta)
        next_date = _first_scheduled_game_date(raw, start_date)
        if next_date:
            return next_date, _merge_cache_meta(*metas)
        cursor += timedelta(days=7)
    return None, _merge_cache_meta(*metas)


def _fetch_schedule_week(start_date: date_type, days: int) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    end_date = start_date + timedelta(days=days - 1)
    cursor = start_date
    games: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    season: str | None = None
    seen_dates: set[str] = set()
    while cursor <= end_date:
        raw, cache_meta = _fetch_schedule_raw(cursor.isoformat())
        metas.append(cache_meta)
        for day in raw.get("gameWeek", []):
            day_date = day.get("date")
            if not day_date or day_date in seen_dates:
                continue
            parsed_day = datetime.strptime(day_date, "%Y-%m-%d").date()
            if start_date <= parsed_day <= end_date:
                seen_dates.add(day_date)
                for game in day.get("games", []):
                    row = _normalize_game(game, day_date)
                    games.append(row)
                    if season is None and row.get("season"):
                        season = row["season"]
        cursor += timedelta(days=7)
    games.sort(key=lambda row: (row.get("start_time_utc") or "", row.get("game_id") or ""))
    return games, _merge_cache_meta(*metas), season


def _live_row(row: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    period_descriptor = game.get("periodDescriptor")
    clock = game.get("clock") if isinstance(game.get("clock"), dict) else {}
    return {
        **row,
        "live": {
            "period": (period_descriptor or {}).get("number") if isinstance(period_descriptor, dict) else game.get("period"),
            "period_label": _period_label(period_descriptor),
            "clock": clock.get("timeRemaining"),
            "last_play": _last_play(game),
        },
    }


def _fetch_live_games(date: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = f"{settings.nhl_api_base}/score/{date}"
    raw, cache_meta = _cached_api_json(f"nhl:score:{date}", url, settings.ttl_schedule)
    if not isinstance(raw, dict) or not isinstance(raw.get("games"), list):
        raise ValueError("score response shape was unexpected")
    live_games: list[dict[str, Any]] = []
    for game in raw.get("games", []):
        row = _normalize_game(game, game.get("gameDate") or raw.get("currentDate") or date)
        if row["status"] == "live":
            live_games.append(_live_row(row, game))
    live_games.sort(key=lambda row: (row.get("start_time_utc") or "", row.get("game_id") or ""))
    return live_games, cache_meta


def _empty_reason(kind: str, season_state: str) -> str:
    if season_state == "offseason":
        suffix = "no games are scheduled in this window" if kind == "schedule" else "no games are live"
        return f"NHL is in its offseason; {suffix}."
    if kind == "schedule":
        return "No NHL games are scheduled in this window."
    return "No NHL games are currently live."


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


@router.get("/schedule/week")
def schedule_week(start: str | None = None, days: int = 7) -> dict[str, Any]:
    """Return a flat NHL schedule window in the UI contract v2 shape."""
    try:
        requested_start = _validate_date(start) or datetime.now(timezone.utc).date().isoformat()
        requested_days = _validate_days(days)
        start_date = datetime.strptime(requested_start, "%Y-%m-%d").date()
        end_date = start_date + timedelta(days=requested_days - 1)
        games, cache_meta, season = _fetch_schedule_week(start_date, requested_days)
        season_state = season_state_for(league="nhl")
        next_scheduled = None
        if not games:
            next_scheduled, next_meta = _next_scheduled_game_date(start_date)
            cache_meta = _merge_cache_meta(cache_meta, next_meta)
        return ok(
            games,
            source=SOURCE_API,
            **cache_meta,
            season=season,
            season_state=season_state,
            league="nhl",
            start_date=requested_start,
            end_date=end_date.isoformat(),
            days=requested_days,
            count=len(games),
            empty_reason=None if games else _empty_reason("schedule", season_state),
            next_scheduled_game_date=next_scheduled if not games else None,
        )
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE_API, season_state=season_state_for(league="nhl"), league="nhl")
    except Exception as exc:  # noqa: BLE001
        logger.warning("NHL weekly schedule failed: %s", exc)
        return fail("upstream_unavailable", "NHL weekly schedule is unavailable.", source=SOURCE_API, season_state=season_state_for(league="nhl"), league="nhl")


@router.get("/live")
def live() -> dict[str, Any]:
    """Return currently in-progress NHL games only."""
    season_state = season_state_for(league="nhl")
    polled_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        games, cache_meta = _fetch_live_games(today)
        games = [_with_live_win_probability(row, "nhl") for row in games]
        next_scheduled = None
        if not games:
            next_scheduled, next_meta = _next_scheduled_game_date(datetime.strptime(today, "%Y-%m-%d").date())
            cache_meta = _merge_cache_meta(cache_meta, next_meta)
        return ok(
            games,
            source=SOURCE_API,
            **cache_meta,
            season_state=season_state,
            league="nhl",
            count=len(games),
            polled_at=polled_at,
            poll_interval_seconds=30,
            empty_reason=None if games else _empty_reason("live", season_state),
            next_scheduled_game_date=next_scheduled if not games else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("NHL live games failed: %s", exc)
        return fail("upstream_unavailable", "NHL live games are unavailable.", source=SOURCE_API, season_state=season_state, league="nhl", polled_at=polled_at, poll_interval_seconds=30)


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
        label = str(live.get("period_label") or row.get("detailed_status") or "")
        is_top = label.upper().startswith("T") or label.lower().startswith("top")
        is_overtime = period > 9
        frac_remaining = 0.0 if is_overtime else frac_remaining_innings(period, is_top)
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
