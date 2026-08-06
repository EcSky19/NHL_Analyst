"""NBA data loading and normalization for the UI router."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime, time, timezone
from json import loads
from typing import Any, Literal, NamedTuple
from zoneinfo import ZoneInfo

from app.cache import cached_fetch
from app.config import settings
from app.services.espn_client import (
    dedupe_by_game_id,
    espn_source,
    fetch_scoreboard,
    fetch_window,
    normalize_events,
)

SOURCE = "local-nba-db"
ESPN_SOURCE = espn_source("nba")
ET_ZONE = ZoneInfo("America/New_York")


class SeasonKey(NamedTuple):
    """Resolved NBA season and backing table source."""

    label: str
    end_year: int
    source: Literal["historical", "current"]


def db_available() -> bool:
    """Return whether the local NBA database exists."""
    return settings.nba_db.exists()


def recent_games_available() -> bool:
    """Return whether the verified basketball-reference game cache exists."""
    return settings.nba_recent_games_db.exists()


def coverage() -> dict[str, Any]:
    """Describe NBA seasons actually present in each local source."""
    with _connect() as con:
        historical = [
            int(row["season"])
            for row in con.execute(
                """
                SELECT season
                FROM nba_games
                WHERE lower(season_type) = 'regular'
                  AND completed = 1
                  AND home_score IS NOT NULL
                  AND away_score IS NOT NULL
                GROUP BY season
                HAVING COUNT(*) > 0
                ORDER BY season
                """
            )
        ]
        current = [
            {
                "season": row["season"],
                "season_end_year": int(row["season_end_year"]),
                "teams": int(row["teams"]),
            }
            for row in con.execute(
                """
                SELECT season, season_end_year, COUNT(*) AS teams
                FROM nba_current_standings
                GROUP BY season, season_end_year
                ORDER BY season_end_year
                """
            )
        ]
    recent_games: list[dict[str, Any]] = []
    if recent_games_available():
        with _connect_recent_games() as con:
            recent_games = [
                {
                    "season": _label_for_end_year(int(row["season"])),
                    "season_end_year": int(row["season"]),
                    "games": int(row["games"]),
                    "completed_games": int(row["completed_games"]),
                    "first_game_date": row["first_game_date"],
                    "last_game_date": row["last_game_date"],
                }
                for row in con.execute(
                    """
                    SELECT season,
                           COUNT(*) AS games,
                           SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) AS completed_games,
                           MIN(game_date) AS first_game_date,
                           MAX(game_date) AS last_game_date
                    FROM nba_games
                    GROUP BY season
                    ORDER BY season
                    """
                )
            ]
    return {
        "season_key_format": "YYYY-YY (for historical nba_games, YYYY is end_year-1)",
        "historical_games": {
            "source": "nba_games / hoopR-data",
            "end_years": historical,
            "seasons": [_label_for_end_year(year) for year in historical],
        },
        "current_standings": {
            "source": "nba_current_standings / basketball-reference cross-check",
            "seasons": current,
        },
        "recent_games": {
            "source": "nba_recent_games / basketball-reference",
            "season_key_format": "INTEGER season END YEAR (2024 means 2023-24)",
            "seasons": recent_games,
        },
    }


def resolve_season(value: str | int | None = None, *, default_current: bool = True) -> SeasonKey:
    """Resolve common NBA season inputs to a canonical YYYY-YY key."""
    cov = coverage()
    historical = set(cov["historical_games"]["end_years"])
    current_by_label = {
        item["season"]: int(item["season_end_year"])
        for item in cov["current_standings"]["seasons"]
    }
    current_by_end = {end: label for label, end in current_by_label.items()}

    if value is None or str(value).strip() == "":
        if default_current and current_by_end:
            end_year = max(current_by_end)
            return SeasonKey(current_by_end[end_year], end_year, "current")
        if historical:
            end_year = max(historical)
            return SeasonKey(_label_for_end_year(end_year), end_year, "historical")
        raise ValueError("No NBA seasons are available")

    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}", text):
        start = int(text[:4])
        end_year = _century_end_year(start, int(text[-2:]))
        label = f"{start}-{str(end_year)[-2:]}"
        if label in current_by_label:
            return SeasonKey(label, current_by_label[label], "current")
        if end_year in historical:
            return SeasonKey(label, end_year, "historical")
        raise ValueError(f"Unknown NBA season: {value}")

    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        start = int(digits[:4])
        end_year = int(digits[4:])
        label = f"{start}-{str(end_year)[-2:]}"
        if label in current_by_label:
            return SeasonKey(label, current_by_label[label], "current")
        if end_year in historical:
            return SeasonKey(label, end_year, "historical")
    elif len(digits) == 6:
        start = int(digits[:4])
        end_year = _century_end_year(start, int(digits[4:]))
        label = f"{start}-{str(end_year)[-2:]}"
        if label in current_by_label:
            return SeasonKey(label, current_by_label[label], "current")
        if end_year in historical:
            return SeasonKey(label, end_year, "historical")
    elif len(digits) == 4:
        year = int(digits)
        if year in current_by_end:
            return SeasonKey(current_by_end[year], year, "current")
        if year in historical:
            return SeasonKey(_label_for_end_year(year), year, "historical")

    raise ValueError(f"Unknown NBA season: {value}")


def latest_schedule_season() -> SeasonKey:
    """Return the newest season with local game rows."""
    cov = coverage()
    recent = cov.get("recent_games", {}).get("seasons") or []
    if recent:
        latest = max(recent, key=lambda item: int(item["season_end_year"]))
        return SeasonKey(latest["season"], int(latest["season_end_year"]), "current")
    return resolve_season(None, default_current=False)


def canonical_team(abbrev: str | None) -> str | None:
    """Return the canonical NBA team abbreviation, if known."""
    if not abbrev:
        return None
    code = abbrev.strip().upper()
    aliases = _team_aliases()
    return aliases.get(code)


def standings_payload(season: SeasonKey) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return standings rows from the right NBA source."""
    return cached_fetch(
        f"nba:standings:{season.source}:{season.end_year}",
        settings.ttl_standings,
        lambda: _current_standings(season) if season.source == "current" else _historical_standings(season),
    )


def teams_payload(season: SeasonKey) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return teams with standings and season stat summaries."""
    return cached_fetch(
        f"nba:teams:{season.source}:{season.end_year}",
        settings.ttl_stats,
        lambda: _teams_payload(season),
    )


def players_payload(team: str | None, stat: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return current NBA player stat leaders."""
    canonical = canonical_team(team) if team else None
    if team and canonical is None:
        raise KeyError(team)
    stat_name = _player_stat(stat)
    return cached_fetch(
        f"nba:players:current:{canonical or 'all'}:{stat_name}:{limit}",
        settings.ttl_stats,
        lambda: _current_player_leaders(canonical, stat_name, limit),
    )


def schedule_payload(game_date: str | None, season: SeasonKey | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return local NBA game rows by date and/or season."""
    key_season = season.label if season else "all"
    return cached_fetch(
        f"nba:schedule:v3:{key_season}:{game_date or 'all'}",
        settings.ttl_schedule,
        lambda: _schedule_rows(game_date, season),
    )


def schedule_window_payload(start_date: str, end_date: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return ESPN NBA game rows in an inclusive date window without stale local fallback."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    days = (end - start).days + 1
    if days < 1:
        raise ValueError("end_date must be on or after start_date")
    return fetch_window("nba", start, days, ttl=settings.ttl_schedule)


def live_payload() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return currently in-progress NBA games from ESPN's explicit-date scoreboard."""
    today_et = datetime.now(ET_ZONE).date().strftime("%Y%m%d")
    events, cache_meta = fetch_scoreboard("nba", dates=today_et, ttl=30)
    rows = [row for row in normalize_events(events, "nba") if row.get("status") == "live"]
    rows = dedupe_by_game_id(rows)
    rows.sort(key=lambda row: (row.get("start_time_utc") or "", row.get("game_id") or ""))
    return rows, cache_meta


def _connect() -> sqlite3.Connection:
    if not settings.nba_db.exists():
        raise FileNotFoundError(f"NBA database not found: {settings.nba_db}")
    con = sqlite3.connect(f"file:{settings.nba_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _connect_recent_games() -> sqlite3.Connection:
    if not settings.nba_recent_games_db.exists():
        raise FileNotFoundError(f"NBA recent games database not found: {settings.nba_recent_games_db}")
    con = sqlite3.connect(f"file:{settings.nba_recent_games_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _team_aliases() -> dict[str, str]:
    with _connect() as con:
        rows = con.execute("SELECT abbreviation, alias_source_codes FROM nba_teams").fetchall()
    aliases: dict[str, str] = {}
    for row in rows:
        canonical = row["abbreviation"]
        aliases[canonical] = canonical
        raw = str(row["alias_source_codes"] or "").split(";", 1)[0]
        for alias in raw.split(","):
            code = alias.strip().upper()
            if code:
                aliases[code] = canonical
    aliases.update({"CHO": "CHA", "CHH": "CHA", "NJ": "BKN", "NJN": "BKN", "NOH": "NOP", "NOK": "NOP", "NO": "NOP", "NY": "NYK", "GS": "GSW", "SA": "SAS", "SEA": "OKC", "WSH": "WAS", "UTAH": "UTA"})
    return aliases


def _teams() -> dict[str, dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            "SELECT abbreviation, full_name, conference, division FROM nba_teams ORDER BY full_name"
        ).fetchall()
    return {
        row["abbreviation"]: {
            "team_id": row["abbreviation"],
            "abbrev": row["abbreviation"],
            "name": row["full_name"],
            "conference": row["conference"],
            "division": _division(row["division"]),
            "logo_url": None,
        }
        for row in rows
    }


def _current_standings(season: SeasonKey) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            """
            SELECT *
            FROM nba_current_standings
            WHERE season = ?
            ORDER BY wins DESC, win_pct DESC,
                     (points_for_total - points_against_total) DESC, team_name
            """,
            (season.label,),
        ).fetchall()
    out = [_standings_row_from_current(row) for row in rows]
    _validate_balanced(out, season.label)
    return out


def _standings_row_from_current(row: sqlite3.Row) -> dict[str, Any]:
    wins = int(row["wins"])
    losses = int(row["losses"])
    games = int(row["games_played"])
    pf = _to_int(row["points_for_total"])
    pa = _to_int(row["points_against_total"])
    return {
        "team_id": row["team_abbrev"],
        "abbrev": row["team_abbrev"],
        "name": row["team_name"],
        "conference": row["conference"],
        "division": _division(row["division"]),
        "rank": _to_int(row["rank"]),
        "games_played": games,
        "wins": wins,
        "losses": losses,
        "otl": None,
        "ties": None,
        "points": wins,
        "points_pct": round(wins / games, 3) if games else 0.0,
        "win_pct": _round(row["win_pct"]),
        "goals_for": pf,
        "goals_against": pa,
        "differential": (pf or 0) - (pa or 0),
        "streak": row["streak"],
        "last10": row["last10"],
        "home_record": row["home_record"],
        "away_record": row["away_record"],
        "logo_url": None,
        "clinched": None,
    }


def _historical_standings(season: SeasonKey) -> list[dict[str, Any]]:
    aliases = _team_aliases()
    teams = _teams()
    stats: dict[str, dict[str, Any]] = {}
    history: dict[str, list[str]] = defaultdict(list)

    with _connect() as con:
        rows = con.execute(
            """
            SELECT game_id, game_date, home_team, away_team, home_score, away_score
            FROM nba_games
            WHERE season = ?
              AND lower(season_type) = 'regular'
              AND completed = 1
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
            ORDER BY game_date, game_id
            """,
            (season.end_year,),
        ).fetchall()

    for game in rows:
        home = aliases.get(str(game["home_team"]).upper())
        away = aliases.get(str(game["away_team"]).upper())
        if not home or not away:
            continue
        home_score = int(game["home_score"])
        away_score = int(game["away_score"])
        if home_score == away_score:
            raise RuntimeError(f"NBA completed tie found in {season.label}: {game['game_id']}")
        for team in (home, away):
            stats.setdefault(team, _empty_record(teams[team]))
        _apply_game(stats, history, home, away, home_score, away_score)

    out = list(stats.values())
    _validate_balanced(out, season.label)
    for row in out:
        gp = row["games_played"]
        wins = row["wins"]
        row["points"] = wins
        row["win_pct"] = round(wins / gp, 3) if gp else 0.0
        row["points_pct"] = row["win_pct"]
        row["differential"] = row["goals_for"] - row["goals_against"]
        row["streak"] = _streak(history[row["abbrev"]])
        row["last10"] = _form(history[row["abbrev"]])
        row["home_record"] = _wl(row.pop("_home"))
        row["away_record"] = _wl(row.pop("_away"))

    out.sort(key=lambda row: (-row["wins"], -row["win_pct"], -row["differential"], row["name"]))
    by_conference: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in out:
        by_conference[str(row["conference"])].append(row)
    for group in by_conference.values():
        group.sort(key=lambda row: (-row["win_pct"], -row["wins"], -row["differential"], row["name"]))
        for rank, row in enumerate(group, start=1):
            row["rank"] = rank
    out.sort(key=lambda row: (-row["wins"], -row["win_pct"], -row["differential"], row["name"]))
    return out


def _empty_record(team: dict[str, Any]) -> dict[str, Any]:
    return {
        **team,
        "rank": None,
        "games_played": 0,
        "wins": 0,
        "losses": 0,
        "otl": None,
        "ties": None,
        "points": 0,
        "points_pct": 0.0,
        "win_pct": 0.0,
        "goals_for": 0,
        "goals_against": 0,
        "differential": 0,
        "streak": None,
        "last10": "0-0",
        "clinched": None,
        "_home": {"wins": 0, "losses": 0},
        "_away": {"wins": 0, "losses": 0},
    }


def _apply_game(stats: dict[str, dict[str, Any]], history: dict[str, list[str]], home: str, away: str, home_score: int, away_score: int) -> None:
    stats[home]["games_played"] += 1
    stats[away]["games_played"] += 1
    stats[home]["goals_for"] += home_score
    stats[home]["goals_against"] += away_score
    stats[away]["goals_for"] += away_score
    stats[away]["goals_against"] += home_score
    if home_score > away_score:
        winner, loser = home, away
        winner_split, loser_split = "_home", "_away"
    else:
        winner, loser = away, home
        winner_split, loser_split = "_away", "_home"
    stats[winner]["wins"] += 1
    stats[loser]["losses"] += 1
    stats[winner][winner_split]["wins"] += 1
    stats[loser][loser_split]["losses"] += 1
    history[winner].append("W")
    history[loser].append("L")


def _teams_payload(season: SeasonKey) -> list[dict[str, Any]]:
    teams = _teams()
    standings, _ = standings_payload(season)
    standings_by_team = {row["abbrev"]: row for row in standings}
    stats = _current_team_stats(season) if season.source == "current" else _historical_team_stats(season)
    out = []
    for team in sorted(teams.values(), key=lambda row: row["name"]):
        abbrev = team["abbrev"]
        out.append({**team, "standings": standings_by_team.get(abbrev), "stats": stats.get(abbrev, {})})
    return out


def _current_team_stats(season: SeasonKey) -> dict[str, dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM nba_current_team_stats WHERE season = ?",
            (season.label,),
        ).fetchall()
    return {
        row["team_abbrev"]: {
            "games": _to_int(row["games"]),
            "points_per_game": _round(row["points_per_game"]),
            "fg_pct": _round(row["fg_pct"]),
            "threep_pct": _round(row["threep_pct"]),
            "ft_pct": _round(row["ft_pct"]),
            "rebounds_per_game": _round(row["rebounds_per_game"]),
            "assists_per_game": _round(row["assists_per_game"]),
            "steals_per_game": _round(row["steals_per_game"]),
            "blocks_per_game": _round(row["blocks_per_game"]),
            "turnovers_per_game": _round(row["turnovers_per_game"]),
        }
        for row in rows
    }


def _historical_team_stats(season: SeasonKey) -> dict[str, dict[str, Any]]:
    aliases = _team_aliases()
    with _connect() as con:
        rows = con.execute(
            """
            SELECT team,
                   COUNT(*) AS games,
                   AVG(points) AS points_per_game,
                   AVG(field_goal_pct) AS fg_pct,
                   AVG(three_point_pct) AS threep_pct,
                   AVG(free_throw_pct) AS ft_pct,
                   AVG(total_rebounds) AS rebounds_per_game,
                   AVG(assists) AS assists_per_game,
                   AVG(steals) AS steals_per_game,
                   AVG(blocks) AS blocks_per_game,
                   AVG(total_turnovers) AS turnovers_per_game
            FROM nba_team_box
            WHERE season = ?
            GROUP BY team
            """,
            (season.end_year,),
        ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        team = aliases.get(str(row["team"]).upper())
        if not team:
            continue
        out[team] = {
            "games": _to_int(row["games"]),
            "points_per_game": _round(row["points_per_game"]),
            "fg_pct": _round(row["fg_pct"]),
            "threep_pct": _round(row["threep_pct"]),
            "ft_pct": _round(row["ft_pct"]),
            "rebounds_per_game": _round(row["rebounds_per_game"]),
            "assists_per_game": _round(row["assists_per_game"]),
            "steals_per_game": _round(row["steals_per_game"]),
            "blocks_per_game": _round(row["blocks_per_game"]),
            "turnovers_per_game": _round(row["turnovers_per_game"]),
        }
    return out


def _current_player_leaders(team: str | None, stat: str, limit: int) -> list[dict[str, Any]]:
    team_filter = "AND team_abbrev = ?" if team else ""
    params: list[Any] = [stat]
    if team:
        params.append(team)
    params.append(limit)
    with _connect() as con:
        rows = con.execute(
            f"""
            SELECT *
            FROM nba_current_player_stats
            WHERE season = (SELECT season FROM nba_current_standings ORDER BY season_end_year DESC LIMIT 1)
              AND stat_type = ?
              {team_filter}
            ORDER BY stat_value DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        {
            "player_id": None,
            "name": row["player_name"],
            "team": row["team_abbrev"],
            "position": None,
            "season": row["season"],
            "games": _to_int(row["games"]),
            "stat": stat,
            "value": _round(row["stat_value"]),
            "points_per_game": _round(row["points_per_game"]),
            "rebounds_per_game": _round(row["rebounds_per_game"]),
            "assists_per_game": _round(row["assists_per_game"]),
        }
        for row in rows
    ]


def _schedule_rows(game_date: str | None, season: SeasonKey | None) -> list[dict[str, Any]]:
    if season is not None and _recent_season_available(season.end_year):
        return _recent_schedule_rows(game_date, season.end_year, None)

    clauses = ["completed IS NOT NULL"]
    params: list[Any] = []
    if season is not None:
        if season.source != "historical":
            return []
        clauses.append("season = ?")
        params.append(season.end_year)
    if game_date:
        clauses.append("game_date = ?")
        params.append(game_date)
    where = " AND ".join(clauses)
    with _connect() as con:
        rows = con.execute(
            f"""
            SELECT *
            FROM nba_games
            WHERE {where}
            ORDER BY game_date DESC, game_id
            LIMIT 1400
            """,
            params,
        ).fetchall()
    return _normalize_schedule_rows(rows, source_kind="historical")


def _schedule_rows_between(start_date: str, end_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if recent_games_available():
        rows.extend(_recent_schedule_rows(None, None, (start_date, end_date)))
    rows.extend(_historical_schedule_rows_between(start_date, end_date))
    rows.sort(key=lambda row: (row.get("start_time_utc") or "", row.get("game_id") or ""))
    return rows


def _recent_schedule_rows(game_date: str | None, season_end_year: int | None, date_range: tuple[str, str] | None) -> list[dict[str, Any]]:
    clauses = ["g.completed IS NOT NULL"]
    params: list[Any] = []
    if season_end_year is not None:
        clauses.append("g.season = ?")
        params.append(season_end_year)
    if game_date is not None:
        clauses.append("g.game_date = ?")
        params.append(game_date)
    if date_range is not None:
        clauses.append("g.game_date BETWEEN ? AND ?")
        params.extend(date_range)
    where = " AND ".join(clauses)
    with _connect_recent_games() as con:
        rows = con.execute(
            f"""
            SELECT g.*, tb.raw_stats_json
            FROM nba_games AS g
            LEFT JOIN nba_team_box AS tb
              ON tb.game_id = g.game_id
             AND tb.is_home = 1
            WHERE {where}
            ORDER BY g.game_date DESC, g.game_id
            LIMIT 1400
            """,
            params,
        ).fetchall()
    return _normalize_schedule_rows(rows, source_kind="recent")


def _historical_schedule_rows_between(start_date: str, end_date: str) -> list[dict[str, Any]]:
    if recent_games_available():
        with _connect_recent_games() as con:
            recent_ranges = con.execute(
                """
                SELECT season, MIN(game_date) AS first_game_date, MAX(game_date) AS last_game_date
                FROM nba_games
                GROUP BY season
                """
            ).fetchall()
        for row in recent_ranges:
            if row["first_game_date"] <= end_date and row["last_game_date"] >= start_date:
                return []
    with _connect() as con:
        rows = con.execute(
            """
            SELECT *
            FROM nba_games
            WHERE completed IS NOT NULL
              AND game_date BETWEEN ? AND ?
            ORDER BY game_date DESC, game_id
            LIMIT 1400
            """,
            (start_date, end_date),
        ).fetchall()
    return _normalize_schedule_rows(rows, source_kind="historical")


def _normalize_schedule_rows(rows: list[sqlite3.Row], *, source_kind: Literal["historical", "recent"]) -> list[dict[str, Any]]:
    aliases = _team_aliases()
    teams = _teams()
    return [
        _normalize_schedule_row(row, aliases, teams, source_kind=source_kind)
        for row in rows
    ]


def _normalize_schedule_row(
    row: sqlite3.Row,
    aliases: dict[str, str],
    teams: dict[str, dict[str, Any]],
    *,
    source_kind: Literal["historical", "recent"],
) -> dict[str, Any]:
    home = aliases.get(str(row["home_team"]).upper(), row["home_team"])
    away = aliases.get(str(row["away_team"]).upper(), row["away_team"])
    played = _row_is_played(row)
    status = _normalized_game_status(row)
    detailed_status = _detailed_status(row, status)
    start_time_utc = _start_time_utc(row) if source_kind == "recent" else None
    return {
        "game_id": str(row["game_id"]),
        "league": "nba",
        "season": _label_for_end_year(int(row["season"])),
        "season_end_year": int(row["season"]),
        "game_date": row["game_date"],
        "season_type": row["season_type"],
        "start_time_utc": start_time_utc,
        "home": home,
        "away": away,
        "home_team": home,
        "away_team": away,
        "home_name": teams.get(home, {}).get("name") or home,
        "away_name": teams.get(away, {}).get("name") or away,
        "home_score": _to_int(row["home_score"]) if played else None,
        "away_score": _to_int(row["away_score"]) if played else None,
        "played": played,
        "status": status,
        "detailed_status": detailed_status,
        "neutral_site": bool(row["neutral_site"]) if row["neutral_site"] is not None else None,
        "venue": row["venue"],
        "attendance": _to_int(row["attendance"]),
    }


def _recent_season_available(season_end_year: int) -> bool:
    if not recent_games_available():
        return False
    with _connect_recent_games() as con:
        row = con.execute("SELECT 1 FROM nba_games WHERE season = ? LIMIT 1", (season_end_year,)).fetchone()
    return row is not None


def _row_is_played(row: sqlite3.Row) -> bool:
    if row["home_score"] is not None and row["away_score"] is not None:
        return True
    game_date = validate_date(str(row["game_date"]))
    return game_date < datetime.now(timezone.utc).date().isoformat()


def _normalized_game_status(row: sqlite3.Row) -> str:
    if _row_is_played(row):
        return "final"
    return "scheduled"


def _detailed_status(row: sqlite3.Row, status: str) -> str:
    if status == "final" and (row["home_score"] is None or row["away_score"] is None):
        return "historical-final-score-missing"
    if row["completed"] == 1:
        return "completed"
    if row["completed"] == 0:
        return "not-started"
    return str(row["completed"])


def _start_time_utc(row: sqlite3.Row) -> str | None:
    try:
        raw = loads(row["raw_stats_json"] or "{}")
    except (TypeError, ValueError, KeyError):
        return None
    start = raw.get("Start (ET)")
    if not isinstance(start, str):
        return None
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?([ap])", start.strip().lower())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    if match.group(3) == "p" and hour != 12:
        hour += 12
    if match.group(3) == "a" and hour == 12:
        hour = 0
    local_date = date.fromisoformat(str(row["game_date"]))
    eastern = ZoneInfo("America/New_York")
    starts_at = datetime.combine(local_date, time(hour, minute), tzinfo=eastern)
    return starts_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_date(value: str) -> str:
    """Validate and normalize an ISO date string."""
    return date.fromisoformat(value).isoformat()


def _player_stat(stat: str) -> str:
    aliases = {
        "points": "points_per_game",
        "ppg": "points_per_game",
        "points_per_game": "points_per_game",
        "rebounds": "rebounds_per_game",
        "rpg": "rebounds_per_game",
        "rebounds_per_game": "rebounds_per_game",
        "assists": "assists_per_game",
        "apg": "assists_per_game",
        "assists_per_game": "assists_per_game",
    }
    try:
        return aliases[stat.strip().lower()]
    except KeyError as exc:
        raise ValueError("Unsupported stat. Use points_per_game, rebounds_per_game, or assists_per_game.") from exc


def _validate_balanced(rows: list[dict[str, Any]], season: str) -> None:
    wins = sum(int(row["wins"]) for row in rows)
    losses = sum(int(row["losses"]) for row in rows)
    if wins != losses:
        raise RuntimeError(f"NBA standings are imbalanced for {season}: wins={wins}, losses={losses}")


def _division(value: Any) -> Any:
    return str(value).replace(" Division", "") if value is not None else None


def _label_for_end_year(end_year: int) -> str:
    return f"{end_year - 1}-{str(end_year)[-2:]}"


def _century_end_year(start: int, two_digit_end: int) -> int:
    century = (start // 100) * 100
    end_year = century + two_digit_end
    if end_year <= start:
        end_year += 100
    return end_year


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


def _form(results: list[str]) -> str:
    recent = results[-10:]
    return f"{recent.count('W')}-{recent.count('L')}"


def _wl(split: dict[str, int]) -> str:
    return f"{split['wins']}-{split['losses']}"


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _round(value: Any, digits: int = 3) -> float | int | None:
    if value is None:
        return None
    number = float(value)
    return int(number) if number.is_integer() else round(number, digits)
