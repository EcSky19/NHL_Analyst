"""NFL data loading and normalization for the UI router."""

from __future__ import annotations

import csv
import sqlite3
import threading
from collections import defaultdict
from datetime import date, datetime, time, timezone
from functools import lru_cache
from io import StringIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.cache import cached_fetch
from app.config import BROWSER_USER_AGENT, settings
from app.services.espn_client import ET_ZONE, espn_source, fetch_scoreboard, fetch_window, normalize_events

SOURCE = "nflverse"
ESPN_SOURCE = espn_source("nfl")

TEAM_ALIASES = {
    "ARI": "ARI",
    "ATL": "ATL",
    "BAL": "BAL",
    "BUF": "BUF",
    "CAR": "CAR",
    "CHI": "CHI",
    "CIN": "CIN",
    "CLE": "CLE",
    "DAL": "DAL",
    "DEN": "DEN",
    "DET": "DET",
    "GB": "GB",
    "HOU": "HOU",
    "IND": "IND",
    "JAC": "JAX",
    "JAX": "JAX",
    "KC": "KC",
    "LA": "LA",
    "LAR": "LA",
    "STL": "LA",
    "LAC": "LAC",
    "SD": "LAC",
    "LV": "LV",
    "OAK": "LV",
    "MIA": "MIA",
    "MIN": "MIN",
    "NE": "NE",
    "NO": "NO",
    "NYG": "NYG",
    "NYJ": "NYJ",
    "PHI": "PHI",
    "PIT": "PIT",
    "SEA": "SEA",
    "SF": "SF",
    "TB": "TB",
    "TEN": "TEN",
    "WAS": "WAS",
    "WSH": "WAS",
}

TEAM_INFO: dict[str, dict[str, str]] = {
    "ARI": {"name": "Arizona Cardinals", "conference": "NFC", "division": "West"},
    "ATL": {"name": "Atlanta Falcons", "conference": "NFC", "division": "South"},
    "BAL": {"name": "Baltimore Ravens", "conference": "AFC", "division": "North"},
    "BUF": {"name": "Buffalo Bills", "conference": "AFC", "division": "East"},
    "CAR": {"name": "Carolina Panthers", "conference": "NFC", "division": "South"},
    "CHI": {"name": "Chicago Bears", "conference": "NFC", "division": "North"},
    "CIN": {"name": "Cincinnati Bengals", "conference": "AFC", "division": "North"},
    "CLE": {"name": "Cleveland Browns", "conference": "AFC", "division": "North"},
    "DAL": {"name": "Dallas Cowboys", "conference": "NFC", "division": "East"},
    "DEN": {"name": "Denver Broncos", "conference": "AFC", "division": "West"},
    "DET": {"name": "Detroit Lions", "conference": "NFC", "division": "North"},
    "GB": {"name": "Green Bay Packers", "conference": "NFC", "division": "North"},
    "HOU": {"name": "Houston Texans", "conference": "AFC", "division": "South"},
    "IND": {"name": "Indianapolis Colts", "conference": "AFC", "division": "South"},
    "JAX": {"name": "Jacksonville Jaguars", "conference": "AFC", "division": "South"},
    "KC": {"name": "Kansas City Chiefs", "conference": "AFC", "division": "West"},
    "LA": {"name": "Los Angeles Rams", "conference": "NFC", "division": "West"},
    "LAC": {"name": "Los Angeles Chargers", "conference": "AFC", "division": "West"},
    "LV": {"name": "Las Vegas Raiders", "conference": "AFC", "division": "West"},
    "MIA": {"name": "Miami Dolphins", "conference": "AFC", "division": "East"},
    "MIN": {"name": "Minnesota Vikings", "conference": "NFC", "division": "North"},
    "NE": {"name": "New England Patriots", "conference": "AFC", "division": "East"},
    "NO": {"name": "New Orleans Saints", "conference": "NFC", "division": "South"},
    "NYG": {"name": "New York Giants", "conference": "NFC", "division": "East"},
    "NYJ": {"name": "New York Jets", "conference": "AFC", "division": "East"},
    "PHI": {"name": "Philadelphia Eagles", "conference": "NFC", "division": "East"},
    "PIT": {"name": "Pittsburgh Steelers", "conference": "AFC", "division": "North"},
    "SEA": {"name": "Seattle Seahawks", "conference": "NFC", "division": "West"},
    "SF": {"name": "San Francisco 49ers", "conference": "NFC", "division": "West"},
    "TB": {"name": "Tampa Bay Buccaneers", "conference": "NFC", "division": "South"},
    "TEN": {"name": "Tennessee Titans", "conference": "AFC", "division": "South"},
    "WAS": {"name": "Washington Commanders", "conference": "NFC", "division": "East"},
}

TEAM_TIME_ZONES = {
    "ARI": "America/Phoenix",
    "ATL": "America/New_York",
    "BAL": "America/New_York",
    "BUF": "America/New_York",
    "CAR": "America/New_York",
    "CHI": "America/Chicago",
    "CIN": "America/New_York",
    "CLE": "America/New_York",
    "DAL": "America/Chicago",
    "DEN": "America/Denver",
    "DET": "America/New_York",
    "GB": "America/Chicago",
    "HOU": "America/Chicago",
    "IND": "America/Indiana/Indianapolis",
    "JAX": "America/New_York",
    "KC": "America/Chicago",
    "LA": "America/Los_Angeles",
    "LAC": "America/Los_Angeles",
    "LV": "America/Los_Angeles",
    "MIA": "America/New_York",
    "MIN": "America/Chicago",
    "NE": "America/New_York",
    "NO": "America/Chicago",
    "NYG": "America/New_York",
    "NYJ": "America/New_York",
    "PHI": "America/New_York",
    "PIT": "America/New_York",
    "SEA": "America/Los_Angeles",
    "SF": "America/Los_Angeles",
    "TB": "America/New_York",
    "TEN": "America/Chicago",
    "WAS": "America/New_York",
}

_OLD_ALIGNMENT: dict[str, tuple[str, str]] = {
    "ARI": ("NFC", "East"),
    "DAL": ("NFC", "East"),
    "NYG": ("NFC", "East"),
    "PHI": ("NFC", "East"),
    "WAS": ("NFC", "East"),
    "CHI": ("NFC", "Central"),
    "DET": ("NFC", "Central"),
    "GB": ("NFC", "Central"),
    "MIN": ("NFC", "Central"),
    "TB": ("NFC", "Central"),
    "ATL": ("NFC", "West"),
    "CAR": ("NFC", "West"),
    "LA": ("NFC", "West"),
    "NO": ("NFC", "West"),
    "SF": ("NFC", "West"),
    "BUF": ("AFC", "East"),
    "IND": ("AFC", "East"),
    "MIA": ("AFC", "East"),
    "NE": ("AFC", "East"),
    "NYJ": ("AFC", "East"),
    "BAL": ("AFC", "Central"),
    "CIN": ("AFC", "Central"),
    "CLE": ("AFC", "Central"),
    "JAX": ("AFC", "Central"),
    "PIT": ("AFC", "Central"),
    "TEN": ("AFC", "Central"),
    "DEN": ("AFC", "West"),
    "KC": ("AFC", "West"),
    "LV": ("AFC", "West"),
    "LAC": ("AFC", "West"),
    "SEA": ("AFC", "West"),
}

_games_lock = threading.Lock()
_games_cache: list[dict[str, Any]] | None = None


def canonical_team(abbrev: str | None) -> str | None:
    """Return the canonical team abbreviation, if known."""
    if not abbrev:
        return None
    return TEAM_ALIASES.get(abbrev.strip().upper())


def fetch_games(ttl_seconds: int, *, force_refresh: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load nflverse games through the shared cache."""
    global _games_cache
    with _games_lock:
        value, meta = cached_fetch(
            "nfl:games:parsed",
            ttl_seconds,
            _download_games_csv,
            force_refresh=force_refresh,
        )
        _games_cache = value
        return value, meta


def _download_games_csv() -> list[dict[str, Any]]:
    request = Request(settings.nflverse_games_url, headers={"User-Agent": BROWSER_USER_AGENT})
    try:
        with urlopen(request, timeout=settings.request_timeout) as response:  # noqa: S310 - verified public CSV
            text = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not fetch nflverse games: {exc}") from exc

    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(StringIO(text)):
        row["season"] = _to_int(row.get("season"))
        row["week"] = _to_int(row.get("week"))
        row["away_score"] = _to_int(row.get("away_score"))
        row["home_score"] = _to_int(row.get("home_score"))
        row["away_team"] = canonical_team(row.get("away_team")) or row.get("away_team")
        row["home_team"] = canonical_team(row.get("home_team")) or row.get("home_team")
        rows.append(row)
    return rows


def available_seasons(games: list[dict[str, Any]]) -> list[int]:
    """Return seasons present in the games feed."""
    return sorted({int(row["season"]) for row in games if row.get("season")})


def latest_completed_season(games: list[dict[str, Any]]) -> int | None:
    """Return the newest season with played regular-season games."""
    seasons = [
        int(row["season"])
        for row in games
        if _is_regular(row) and _is_played(row)
    ]
    return max(seasons) if seasons else None


@lru_cache(maxsize=64)
def standings_for_season_cached(season: int) -> list[dict[str, Any]]:
    """Compute regular-season standings from played nflverse games."""
    games, _ = fetch_games(settings.ttl_standings)
    return _compute_standings(games, season)


def schedule_for(games: list[dict[str, Any]], season: int, week: int | None = None) -> list[dict[str, Any]]:
    """Normalize schedule rows for one season and optional week."""
    rows = [
        _schedule_row(row)
        for row in games
        if row.get("season") == season and (week is None or row.get("week") == week)
    ]
    return sorted(rows, key=lambda row: (row["week"] or 0, row["gameday"] or "", row["game_id"] or ""))


def schedule_window(games: list[dict[str, Any]], start_date: date, days: int) -> list[dict[str, Any]]:
    """Return contract schedule rows in an inclusive calendar window."""
    end_date = start_date.toordinal() + days - 1
    rows: list[dict[str, Any]] = []
    for row in games:
        game_date = _parse_date(row.get("gameday"))
        if game_date is None:
            continue
        ordinal = game_date.toordinal()
        if start_date.toordinal() <= ordinal <= end_date:
            rows.append(_schedule_row(row))
    return _sort_contract_rows(rows)


def schedule_week(games: list[dict[str, Any]], season: int, week: int) -> list[dict[str, Any]]:
    """Return contract schedule rows for one NFL week."""
    rows = [
        _schedule_row(row)
        for row in games
        if row.get("season") == season and row.get("week") == week
    ]
    return _sort_contract_rows(rows)


def espn_schedule_window(start_date: date, days: int, ttl_seconds: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return ESPN-backed NFL schedule rows for an Eastern-date window."""
    return fetch_window("nfl", start_date, days, ttl=ttl_seconds)


def espn_live_games(ttl_seconds: int = 30) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return (live rows, current ESPN slate rows, cache meta) for NFL."""
    today_et = datetime.now(timezone.utc).astimezone(ET_ZONE).date()
    events, meta = fetch_scoreboard("nfl", dates=today_et.strftime("%Y%m%d"), ttl=ttl_seconds)
    slate = normalize_events(events, "nfl")
    live_rows = [row for row in slate if row.get("status") == "live"]
    live_rows = _sort_contract_rows(live_rows)
    return live_rows, _sort_contract_rows(slate), meta


def live_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deprecated nflverse live hook.

    Kept for callers/tests that still import it; live NFL state now comes from ESPN.
    """
    return []


def teams_payload(season: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return teams with standings and season-to-date advanced summaries."""
    standings = standings_for_season_cached(season)
    advanced, meta = cached_fetch(
        f"nfl:team-advanced:{season}",
        settings.ttl_stats,
        lambda: _load_team_advanced(season),
    )
    by_team = {row["abbrev"]: row for row in standings}
    teams: list[dict[str, Any]] = []
    for abbrev, info in sorted(TEAM_INFO.items(), key=lambda item: item[1]["name"]):
        item = {
            "team_id": abbrev,
            "abbrev": abbrev,
            "name": info["name"],
            "conference": info["conference"],
            "division": info["division"],
            "logo_url": None,
            "standings": by_team.get(abbrev),
            "advanced": advanced.get(abbrev, {}),
        }
        teams.append(item)
    return teams, meta


def players_payload(team: str | None, stat: str, limit: int, season: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return QB leaders from the local NFL research database."""
    valid_stats = {
        "passing_yards",
        "passing_tds",
        "passing_epa",
        "passing_epa_per_dropback",
        "passing_cpoe",
        "fantasy_points",
        "fantasy_points_ppr",
        "attempts",
        "completions",
        "rushing_yards",
        "rushing_tds",
    }
    if stat not in valid_stats:
        raise ValueError(f"Unsupported stat '{stat}'")
    canonical = canonical_team(team) if team else None
    if team and canonical is None:
        raise KeyError(team)
    key = f"nfl:players:{season}:{canonical or 'all'}:{stat}:{limit}"
    return cached_fetch(
        key,
        settings.ttl_stats,
        lambda: _load_qb_leaders(season, canonical, stat, limit),
    )


def _compute_standings(games: list[dict[str, Any]], season: int) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    history: dict[str, list[tuple[str, bool]]] = defaultdict(list)

    for game in sorted(games, key=lambda row: (row.get("gameday") or "", row.get("week") or 0, row.get("game_id") or "")):
        if game.get("season") != season or not _is_regular(game) or not _is_played(game):
            continue
        away = canonical_team(str(game.get("away_team"))) or str(game.get("away_team"))
        home = canonical_team(str(game.get("home_team"))) or str(game.get("home_team"))
        away_score = int(game["away_score"])
        home_score = int(game["home_score"])
        for team in (away, home):
            stats.setdefault(team, _empty_record(team, season))
        stats[away]["games_played"] += 1
        stats[home]["games_played"] += 1
        stats[away]["goals_for"] += away_score
        stats[away]["goals_against"] += home_score
        stats[home]["goals_for"] += home_score
        stats[home]["goals_against"] += away_score

        if away_score == home_score:
            for team, is_home in ((away, False), (home, True)):
                stats[team]["ties"] += 1
                _record_split(stats[team], is_home, "T")
                history[team].append(("T", is_home))
        elif away_score > home_score:
            stats[away]["wins"] += 1
            stats[home]["losses"] += 1
            _record_split(stats[away], False, "W")
            _record_split(stats[home], True, "L")
            history[away].append(("W", False))
            history[home].append(("L", True))
        else:
            stats[home]["wins"] += 1
            stats[away]["losses"] += 1
            _record_split(stats[home], True, "W")
            _record_split(stats[away], False, "L")
            history[home].append(("W", True))
            history[away].append(("L", False))

    rows: list[dict[str, Any]] = []
    for team, row in stats.items():
        gp = row["games_played"]
        row["differential"] = row["goals_for"] - row["goals_against"]
        row["win_pct"] = round((row["wins"] + 0.5 * row["ties"]) / gp, 3) if gp else 0.0
        row["points_pct"] = row["win_pct"]
        row["streak"] = _streak([result for result, _ in history[team]])
        row["last10"] = _form([result for result, _ in history[team]], 10)
        row["home_record"] = _split_text(row["home"])
        row["away_record"] = _split_text(row["away"])
        del row["home"]
        del row["away"]
        rows.append(row)

    rows.sort(key=lambda row: (row["conference"], row["division"], -row["win_pct"], -row["wins"], -row["differential"], row["name"]))
    for (_, _), group in _group_by_division(rows).items():
        group.sort(key=lambda row: (-row["win_pct"], -row["wins"], -row["differential"], row["name"]))
        for rank, row in enumerate(group, start=1):
            row["rank"] = rank
    return rows


def _empty_record(team: str, season: int) -> dict[str, Any]:
    info = _team_info_for(team, season)
    return {
        "team_id": team,
        "abbrev": team,
        "name": info["name"],
        "conference": info["conference"],
        "division": info["division"],
        "rank": None,
        "games_played": 0,
        "wins": 0,
        "losses": 0,
        "otl": None,
        "ties": 0,
        "points": None,
        "points_pct": 0.0,
        "win_pct": 0.0,
        "goals_for": 0,
        "goals_against": 0,
        "differential": 0,
        "streak": None,
        "last10": "0-0-0",
        "home_record": "0-0-0",
        "away_record": "0-0-0",
        "logo_url": None,
        "clinched": None,
        "home": {"wins": 0, "losses": 0, "ties": 0},
        "away": {"wins": 0, "losses": 0, "ties": 0},
    }


def _team_info_for(team: str, season: int) -> dict[str, str]:
    info = dict(TEAM_INFO.get(team, {"name": team, "conference": None, "division": None}))
    if season <= 2001 and team in _OLD_ALIGNMENT:
        conference, division = _OLD_ALIGNMENT[team]
        info["conference"] = conference
        info["division"] = division
    return info


def _record_split(row: dict[str, Any], is_home: bool, result: str) -> None:
    split = row["home" if is_home else "away"]
    if result == "W":
        split["wins"] += 1
    elif result == "L":
        split["losses"] += 1
    else:
        split["ties"] += 1


def _group_by_division(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["conference"], row["division"])].append(row)
    return grouped


def _streak(results: list[str]) -> str | None:
    if not results:
        return None
    last = results[-1]
    count = 0
    for result in reversed(results):
        if result != last:
            break
        count += 1
    return f"{last}{count}"


def _form(results: list[str], window: int) -> str:
    recent = results[-window:]
    return f"{recent.count('W')}-{recent.count('L')}-{recent.count('T')}"


def _split_text(split: dict[str, int]) -> str:
    return f"{split['wins']}-{split['losses']}-{split['ties']}"


def _schedule_row(row: dict[str, Any]) -> dict[str, Any]:
    played = _is_played(row)
    away = row.get("away_team")
    home = row.get("home_team")
    status, detailed_status = _normalize_status(row, played)
    away_score = row.get("away_score") if played else None
    home_score = row.get("home_score") if played else None
    return {
        "game_id": row.get("game_id"),
        "league": "nfl",
        "season": row.get("season"),
        "week": row.get("week"),
        "game_type": row.get("game_type"),
        "game_date": row.get("gameday") or None,
        "start_time_utc": _start_time_utc(row),
        "gameday": row.get("gameday"),
        "weekday": row.get("weekday"),
        "gametime": row.get("gametime"),
        "away": away,
        "home": home,
        "away_team": away,
        "home_team": home,
        "away_name": _team_name(away, row.get("season")),
        "home_name": _team_name(home, row.get("season")),
        "away_score": away_score,
        "home_score": home_score,
        "played": played,
        "status": status,
        "detailed_status": detailed_status,
        "venue": row.get("stadium") or None,
        "location": row.get("location"),
        "stadium": row.get("stadium"),
        "roof": row.get("roof"),
        "surface": row.get("surface"),
        "spread_line": _to_float(row.get("spread_line")),
        "total_line": _to_float(row.get("total_line")),
        "home_moneyline": _to_float(row.get("home_moneyline")),
        "away_moneyline": _to_float(row.get("away_moneyline")),
        "home_qb": row.get("home_qb_name") or None,
        "away_qb": row.get("away_qb_name") or None,
    }


def _load_team_advanced(season: int) -> dict[str, dict[str, Any]]:
    query = """
        SELECT team,
               SUM(n_games) AS games,
               AVG(offensive_epa_per_play) AS offensive_epa_per_play,
               AVG(defensive_epa_per_play_allowed) AS defensive_epa_per_play_allowed,
               AVG(offensive_success_rate) AS offensive_success_rate,
               AVG(defensive_success_rate_allowed) AS defensive_success_rate_allowed,
               AVG(giveaway_rate) AS giveaway_rate,
               AVG(takeaway_rate) AS takeaway_rate
        FROM nfl_team_week_advanced
        WHERE season = ? AND season_type = 'REG'
        GROUP BY team
    """
    out: dict[str, dict[str, Any]] = {}
    with sqlite3.connect(settings.nfl_db) as con:
        con.row_factory = sqlite3.Row
        for row in con.execute(query, (season,)):
            team = canonical_team(row["team"]) or row["team"]
            out[team] = {
                "games": row["games"],
                "offensive_epa_per_play": _round(row["offensive_epa_per_play"]),
                "defensive_epa_per_play_allowed": _round(row["defensive_epa_per_play_allowed"]),
                "offensive_success_rate": _round(row["offensive_success_rate"]),
                "defensive_success_rate_allowed": _round(row["defensive_success_rate_allowed"]),
                "giveaway_rate": _round(row["giveaway_rate"]),
                "takeaway_rate": _round(row["takeaway_rate"]),
            }
    return out


def _load_qb_leaders(season: int, team: str | None, stat: str, limit: int) -> list[dict[str, Any]]:
    team_filter = "AND team = ?" if team else ""
    params: list[Any] = [season]
    if team:
        params.append(team)
    query = f"""
        SELECT player_id, player_display_name, team,
               COUNT(DISTINCT game_id) AS games,
               SUM(attempts) AS attempts,
               SUM(completions) AS completions,
               SUM(passing_yards) AS passing_yards,
               SUM(passing_tds) AS passing_tds,
               SUM(passing_interceptions) AS passing_interceptions,
               SUM(passing_epa) AS passing_epa,
               AVG(passing_epa_per_dropback) AS passing_epa_per_dropback,
               AVG(passing_cpoe) AS passing_cpoe,
               SUM(rushing_yards) AS rushing_yards,
               SUM(rushing_tds) AS rushing_tds,
               SUM(fantasy_points) AS fantasy_points,
               SUM(fantasy_points_ppr) AS fantasy_points_ppr
        FROM nfl_qb_week_stats
        WHERE season = ? AND season_type = 'REG' {team_filter}
        GROUP BY player_id, player_display_name, team
        HAVING attempts > 0
        ORDER BY {stat} DESC
        LIMIT ?
    """
    params.append(limit)
    leaders: list[dict[str, Any]] = []
    with sqlite3.connect(settings.nfl_db) as con:
        con.row_factory = sqlite3.Row
        for row in con.execute(query, params):
            leaders.append(
                {
                    "player_id": row["player_id"],
                    "name": row["player_display_name"],
                    "team": canonical_team(row["team"]) or row["team"],
                    "position": "QB",
                    "season": season,
                    "games": row["games"],
                    "stat": stat,
                    "value": _round(row[stat]),
                    "passing_yards": _round(row["passing_yards"]),
                    "passing_tds": _round(row["passing_tds"]),
                    "interceptions": _round(row["passing_interceptions"]),
                    "passing_epa": _round(row["passing_epa"]),
                    "passing_epa_per_dropback": _round(row["passing_epa_per_dropback"]),
                    "passing_cpoe": _round(row["passing_cpoe"]),
                    "rushing_yards": _round(row["rushing_yards"]),
                    "fantasy_points": _round(row["fantasy_points"]),
                }
            )
    return leaders


def _is_regular(row: dict[str, Any]) -> bool:
    return str(row.get("game_type") or "").upper() == "REG"


def _is_played(row: dict[str, Any]) -> bool:
    return row.get("away_score") is not None and row.get("home_score") is not None


def _normalize_status(row: dict[str, Any], played: bool) -> tuple[str, str | None]:
    raw = row.get("status") or row.get("game_status") or row.get("game_status_detail")
    # nflverse games.csv exposes no raw upstream status text; keep this null
    # rather than duplicating our normalized status as if it came from upstream.
    if raw in (None, ""):
        return ("final" if played else "scheduled"), None
    detailed = str(raw)
    text = detailed.strip().lower()
    if any(token in text for token in ("postponed", "postpon", "cancelled", "canceled", "suspended")):
        return "postponed", detailed
    if any(token in text for token in ("in progress", "in-progress", "live", "halftime")):
        return "live", detailed
    if played:
        return "final", detailed
    return "scheduled", detailed


def _team_name(abbrev: Any, season: Any) -> str | None:
    if abbrev is None:
        return None
    try:
        season_int = int(season) if season is not None else _fallback_team_name_season()
    except (TypeError, ValueError):
        season_int = _fallback_team_name_season()
    return _team_info_for(str(abbrev), season_int).get("name")


def _fallback_team_name_season() -> int:
    cached = _games_cache or []
    seasons = []
    for row in cached:
        try:
            seasons.append(int(row["season"]))
        except (KeyError, TypeError, ValueError):
            continue
    if seasons:
        return max(seasons)
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 8 else now.year - 1


def _start_time_utc(row: dict[str, Any]) -> str | None:
    game_date = _parse_date(row.get("gameday"))
    game_time = _parse_time(row.get("gametime"))
    if game_date is None or game_time is None:
        return None
    tz_name = _time_zone_for(row)
    if tz_name is None:
        return None
    try:
        local = datetime.combine(game_date, game_time, ZoneInfo(tz_name))
    except ZoneInfoNotFoundError:
        return None
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _time_zone_for(row: dict[str, Any]) -> str | None:
    if str(row.get("location") or "").lower() == "neutral":
        return None
    team = canonical_team(str(row.get("home_team") or "")) or row.get("home_team")
    return TEAM_TIME_ZONES.get(str(team))


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_time(value: Any) -> time | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(str(value), "%H:%M")
    except ValueError:
        return None
    return parsed.time()


def _sort_contract_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            row.get("start_time_utc") is None,
            row.get("start_time_utc") or row.get("game_date") or "",
            row.get("game_id") or "",
        ),
    )


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 3) -> float | int | None:
    if value is None:
        return None
    value = float(value)
    return int(value) if value.is_integer() else round(value, digits)
