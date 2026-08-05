#!/usr/bin/env python
"""Ingest real historical NHL regular-season games and boxscore rosters."""

import argparse
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


SEASON_CATALOG_URL = "https://api.nhle.com/stats/rest/en/season"
SCHEDULE_BY_DATE_URL = "https://api-web.nhle.com/v1/schedule/{date}"
BOXSCORE_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
COMPLETED_GAME_STATES = {"OFF", "FINAL"}
PLAYER_GROUPS = ("forwards", "defense", "goalies")
DEFAULT_SEASONS = (20152016, 20162017, 20172018, 20182019, 20192020)
DEFAULT_ROSTER_SEASONS = (20152016, 20162017, 20172018)
SOURCE_TAG = "real_nhl_api_web"


@dataclass
class SeasonWindow:
    season_id: int
    start_date: str
    regular_season_end_date: str


def fetch_json(session: requests.Session, url: str, delay_seconds: float, retries: int = 4) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"fetch failed after {retries} attempts for {url}: {last_error}")


def load_alias_map(conn: sqlite3.Connection) -> Dict[str, str]:
    alias_to_canonical: Dict[str, str] = {}
    for canonical_abbrev, alias_abbrevs in conn.execute(
        "SELECT canonical_abbrev, alias_abbrevs FROM team_alias_map"
    ).fetchall():
        canonical = (canonical_abbrev or "").strip().upper()
        if not canonical:
            continue
        alias_to_canonical[canonical] = canonical
        for alias in (alias_abbrevs or "").split("|"):
            token = alias.strip().upper()
            if token:
                alias_to_canonical[token] = canonical
    return alias_to_canonical


def canonical_abbrev(team_abbrev: Optional[str], alias_map: Dict[str, str], season: Optional[int] = None) -> str:
    normalized = (team_abbrev or "").strip().upper()
    if season is not None and int(season) < 20242025 and normalized in {"ARI", "PHX"}:
        return "ARI"
    return alias_map.get(normalized, normalized)


def toi_to_seconds(toi_value: Optional[str]) -> Optional[int]:
    if not toi_value:
        return None
    try:
        minutes, seconds = str(toi_value).split(":")
        return int(minutes) * 60 + int(seconds)
    except Exception:
        return None


def name_from_payload(name_blob: Any) -> str:
    if isinstance(name_blob, dict):
        return str(name_blob.get("default") or name_blob.get("fr") or "").strip()
    return str(name_blob or "").strip()


def get_season_windows(
    session: requests.Session,
    season_ids: Iterable[int],
    delay_seconds: float,
) -> Dict[int, SeasonWindow]:
    payload = fetch_json(session, SEASON_CATALOG_URL, delay_seconds)
    wanted = {int(season_id) for season_id in season_ids}
    windows: Dict[int, SeasonWindow] = {}
    for row in payload.get("data", []):
        season_id = int(row.get("id") or 0)
        if season_id not in wanted:
            continue
        start_date = str(row.get("startDate") or "")[:10]
        regular_end = str(row.get("regularSeasonEndDate") or "")[:10]
        if start_date and regular_end:
            windows[season_id] = SeasonWindow(season_id, start_date, regular_end)
    missing = sorted(wanted - set(windows))
    if missing:
        raise RuntimeError(f"season catalog did not contain required seasons: {missing}")
    return windows


def persist_raw_json(raw_dir: Path, filename: str, payload: Dict[str, Any]) -> str:
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_dir / filename
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(output_path)


def fetch_regular_games_for_season(
    session: requests.Session,
    window: SeasonWindow,
    alias_map: Dict[str, str],
    raw_dir: Path,
    delay_seconds: float,
    fetched_at_utc: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    rows: List[Dict[str, Any]] = []
    raw_paths: List[str] = []
    seen_ids = set()
    next_date = window.start_date

    while next_date and next_date <= window.regular_season_end_date:
        url = SCHEDULE_BY_DATE_URL.format(date=next_date)
        payload = fetch_json(session, url, delay_seconds)
        raw_path = persist_raw_json(raw_dir, f"schedule_{window.season_id}_{next_date}.json", payload)
        raw_paths.append(raw_path)

        for game_day in payload.get("gameWeek", []):
            game_day_date = game_day.get("date") or next_date
            for game in game_day.get("games", []) or []:
                if int(game.get("season") or 0) != window.season_id or int(game.get("gameType") or 0) != 2:
                    continue
                game_state = (game.get("gameState") or "").upper()
                if game_state not in COMPLETED_GAME_STATES:
                    continue
                game_id = game.get("id")
                if game_id is None or game_id in seen_ids:
                    continue
                away = game.get("awayTeam") or {}
                home = game.get("homeTeam") or {}
                away_goals = away.get("score")
                home_goals = home.get("score")
                if away_goals is None or home_goals is None:
                    continue

                home_abbrev = canonical_abbrev(home.get("abbrev"), alias_map, window.season_id)
                away_abbrev = canonical_abbrev(away.get("abbrev"), alias_map, window.season_id)
                winner = home_abbrev if int(home_goals) > int(away_goals) else away_abbrev
                game_date = game.get("gameDate") or game_day_date or str(game.get("startTimeUTC") or "")[:10]

                rows.append(
                    {
                        "season": window.season_id,
                        "game_id": int(game_id),
                        "game_date": game_date,
                        "home_team_abbrev": home_abbrev,
                        "away_team_abbrev": away_abbrev,
                        "home_goals": int(home_goals),
                        "away_goals": int(away_goals),
                        "winner_abbrev": winner,
                        "game_type": "2",
                        "status": game_state,
                        "is_final": 1,
                        "data_source": SOURCE_TAG,
                        "source_url": url,
                        "raw_json_path": raw_path,
                        "fetched_at_utc": fetched_at_utc,
                    }
                )
                seen_ids.add(game_id)

        following = payload.get("nextStartDate")
        if not following or following <= next_date:
            break
        next_date = following

    return sorted(rows, key=lambda r: (r["game_date"], r["game_id"])), raw_paths


def parse_team_rows(
    *,
    game_id: int,
    season: int,
    home_away: str,
    team_abbrev: str,
    players_by_group: Dict[str, Any],
    game_state: Optional[str],
    game_schedule_state: Optional[str],
    fetched_at_utc: str,
    source_url: str,
    raw_json_path: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    roster_rows: List[Dict[str, Any]] = []
    stat_rows: List[Dict[str, Any]] = []

    for group in PLAYER_GROUPS:
        for player in players_by_group.get(group, []) or []:
            player_id = player.get("playerId")
            if player_id is None:
                continue
            position = (player.get("position") or "").strip().upper() or None
            is_goalie = 1 if position == "G" or group == "goalies" else 0
            toi_raw = player.get("toi")
            toi_seconds = toi_to_seconds(toi_raw)
            played = 1 if toi_seconds and toi_seconds > 0 else 0
            starter_flag = player.get("starter")
            is_starter_goalie = 1 if bool(starter_flag) and is_goalie else 0
            common = {
                "game_id": game_id,
                "season": season,
                "team_abbrev": team_abbrev,
                "player_id": int(player_id),
                "player_name": name_from_payload(player.get("name")),
                "position": position,
                "is_goalie": is_goalie,
                "home_away": home_away,
                "fetched_at_utc": fetched_at_utc,
                "data_source": SOURCE_TAG,
                "source_url": source_url,
                "raw_json_path": raw_json_path,
            }
            roster_rows.append(
                {
                    **common,
                    "is_starter_goalie": is_starter_goalie,
                    "player_status": str(player.get("status")) if player.get("status") is not None else None,
                    "game_state": game_state,
                    "game_schedule_state": game_schedule_state,
                    "played": played,
                    "sweater_number": player.get("sweaterNumber"),
                }
            )
            stat_rows.append(
                {
                    **common,
                    "toi": toi_raw,
                    "toi_seconds": toi_seconds,
                    "goals": player.get("goals"),
                    "assists": player.get("assists"),
                    "points": player.get("points"),
                    "plus_minus": player.get("plusMinus"),
                    "pim": player.get("pim"),
                    "hits": player.get("hits"),
                    "power_play_goals": player.get("powerPlayGoals"),
                    "sog": player.get("sog"),
                    "faceoff_winning_pctg": player.get("faceoffWinningPctg"),
                    "blocked_shots": player.get("blockedShots"),
                    "shifts": player.get("shifts"),
                    "giveaways": player.get("giveaways"),
                    "takeaways": player.get("takeaways"),
                    "goals_against": player.get("goalsAgainst"),
                    "shots_against": player.get("shotsAgainst"),
                    "saves": player.get("saves"),
                    "save_shots_against": player.get("saveShotsAgainst"),
                    "even_strength_shots_against": player.get("evenStrengthShotsAgainst"),
                    "power_play_shots_against": player.get("powerPlayShotsAgainst"),
                    "shorthanded_shots_against": player.get("shorthandedShotsAgainst"),
                    "even_strength_goals_against": player.get("evenStrengthGoalsAgainst"),
                    "power_play_goals_against": player.get("powerPlayGoalsAgainst"),
                    "shorthanded_goals_against": player.get("shorthandedGoalsAgainst"),
                    "is_starter_goalie": is_starter_goalie,
                }
            )
    infer_starter_goalies(roster_rows, stat_rows)
    return roster_rows, stat_rows


def infer_starter_goalies(roster_rows: List[Dict[str, Any]], stat_rows: List[Dict[str, Any]]) -> None:
    for home_away in ("home", "away"):
        goalies = [r for r in roster_rows if r["home_away"] == home_away and int(r.get("is_goalie") or 0) == 1]
        if not goalies:
            continue
        stat_by_player = {s["player_id"]: s for s in stat_rows if s["home_away"] == home_away and int(s.get("is_goalie") or 0) == 1}
        flagged = [g for g in goalies if int(g.get("is_starter_goalie") or 0) == 1]
        if len(flagged) == 1:
            chosen_id = flagged[0]["player_id"]
        else:
            chosen = max(
                goalies,
                key=lambda g: (
                    int(g.get("played") or 0),
                    int(stat_by_player.get(g["player_id"], {}).get("toi_seconds") or 0),
                    int(stat_by_player.get(g["player_id"], {}).get("shots_against") or 0),
                    -int(g["player_id"]),
                ),
            )
            chosen_id = chosen["player_id"]
        for row in goalies:
            row["is_starter_goalie"] = 1 if row["player_id"] == chosen_id else 0
        for row in stat_rows:
            if row["home_away"] == home_away and int(row.get("is_goalie") or 0) == 1:
                row["is_starter_goalie"] = 1 if row["player_id"] == chosen_id else 0


def fetch_boxscore_rows(
    session: requests.Session,
    game: Dict[str, Any],
    alias_map: Dict[str, str],
    raw_dir: Path,
    delay_seconds: float,
    fetched_at_utc: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    game_id = int(game["game_id"])
    season = int(game["season"])
    url = BOXSCORE_URL.format(game_id=game_id)
    try:
        payload = fetch_json(session, url, delay_seconds)
    except Exception as exc:
        return [], [], str(exc)

    raw_path = persist_raw_json(raw_dir, f"boxscore_{season}_{game_id}.json", payload)
    player_stats = payload.get("playerByGameStats") or {}
    away_team_abbrev = canonical_abbrev((payload.get("awayTeam") or {}).get("abbrev"), alias_map, season)
    home_team_abbrev = canonical_abbrev((payload.get("homeTeam") or {}).get("abbrev"), alias_map, season)
    game_state = (payload.get("gameState") or "").upper() or None
    game_schedule_state = (payload.get("gameScheduleState") or "").upper() or None

    away_roster, away_stats = parse_team_rows(
        game_id=game_id,
        season=season,
        home_away="away",
        team_abbrev=away_team_abbrev,
        players_by_group=(player_stats.get("awayTeam") or {}),
        game_state=game_state,
        game_schedule_state=game_schedule_state,
        fetched_at_utc=fetched_at_utc,
        source_url=url,
        raw_json_path=raw_path,
    )
    home_roster, home_stats = parse_team_rows(
        game_id=game_id,
        season=season,
        home_away="home",
        team_abbrev=home_team_abbrev,
        players_by_group=(player_stats.get("homeTeam") or {}),
        game_state=game_state,
        game_schedule_state=game_schedule_state,
        fetched_at_utc=fetched_at_utc,
        source_url=url,
        raw_json_path=raw_path,
    )
    return away_roster + home_roster, away_stats + home_stats, None


def ensure_columns(conn: sqlite3.Connection, table: str, columns: Dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for column, col_type in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def create_real_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS real_historical_games_api (
            season INTEGER NOT NULL,
            game_id INTEGER PRIMARY KEY,
            game_date TEXT NOT NULL,
            home_team_abbrev TEXT NOT NULL,
            away_team_abbrev TEXT NOT NULL,
            home_goals INTEGER NOT NULL,
            away_goals INTEGER NOT NULL,
            winner_abbrev TEXT NOT NULL,
            game_type TEXT NOT NULL,
            status TEXT NOT NULL,
            is_final INTEGER NOT NULL,
            data_source TEXT NOT NULL,
            source_url TEXT NOT NULL,
            raw_json_path TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS real_historical_game_rosters_api (
            game_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            team_abbrev TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            player_name TEXT,
            position TEXT,
            is_goalie INTEGER,
            is_starter_goalie INTEGER,
            home_away TEXT NOT NULL,
            player_status TEXT,
            game_state TEXT,
            game_schedule_state TEXT,
            played INTEGER,
            sweater_number INTEGER,
            fetched_at_utc TEXT NOT NULL,
            data_source TEXT NOT NULL,
            source_url TEXT NOT NULL,
            raw_json_path TEXT NOT NULL,
            PRIMARY KEY (game_id, team_abbrev, player_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS real_historical_player_game_stats_api (
            game_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            team_abbrev TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            player_name TEXT,
            position TEXT,
            is_goalie INTEGER,
            home_away TEXT NOT NULL,
            toi TEXT,
            toi_seconds INTEGER,
            goals INTEGER,
            assists INTEGER,
            points INTEGER,
            plus_minus INTEGER,
            pim INTEGER,
            hits INTEGER,
            power_play_goals INTEGER,
            sog INTEGER,
            faceoff_winning_pctg REAL,
            blocked_shots INTEGER,
            shifts INTEGER,
            giveaways INTEGER,
            takeaways INTEGER,
            goals_against INTEGER,
            shots_against INTEGER,
            saves INTEGER,
            save_shots_against TEXT,
            even_strength_shots_against TEXT,
            power_play_shots_against TEXT,
            shorthanded_shots_against TEXT,
            even_strength_goals_against INTEGER,
            power_play_goals_against INTEGER,
            shorthanded_goals_against INTEGER,
            is_starter_goalie INTEGER,
            fetched_at_utc TEXT NOT NULL,
            data_source TEXT NOT NULL,
            source_url TEXT NOT NULL,
            raw_json_path TEXT NOT NULL,
            PRIMARY KEY (game_id, team_abbrev, player_id)
        )
        """
    )


def insert_rows(conn: sqlite3.Connection, table: str, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    if not rows:
        return
    placeholders = ", ".join(f":{column}" for column in columns)
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [{column: row.get(column) for column in columns} for row in rows],
    )


def persist_to_database(
    db_path: Path,
    games: List[Dict[str, Any]],
    roster_rows: List[Dict[str, Any]],
    stat_rows: List[Dict[str, Any]],
    seasons: List[int],
    roster_seasons: List[int],
) -> None:
    game_cols = [
        "season", "game_id", "game_date", "home_team_abbrev", "away_team_abbrev",
        "home_goals", "away_goals", "winner_abbrev", "game_type", "status", "is_final",
        "data_source", "source_url", "raw_json_path", "fetched_at_utc",
    ]
    roster_cols = [
        "game_id", "season", "team_abbrev", "player_id", "player_name", "position",
        "is_goalie", "is_starter_goalie", "home_away", "player_status", "game_state",
        "game_schedule_state", "played", "sweater_number", "fetched_at_utc",
        "data_source", "source_url", "raw_json_path",
    ]
    stat_cols = [
        "game_id", "season", "team_abbrev", "player_id", "player_name", "position",
        "is_goalie", "home_away", "toi", "toi_seconds", "goals", "assists", "points",
        "plus_minus", "pim", "hits", "power_play_goals", "sog", "faceoff_winning_pctg",
        "blocked_shots", "shifts", "giveaways", "takeaways", "goals_against",
        "shots_against", "saves", "save_shots_against", "even_strength_shots_against",
        "power_play_shots_against", "shorthanded_shots_against",
        "even_strength_goals_against", "power_play_goals_against",
        "shorthanded_goals_against", "is_starter_goalie", "fetched_at_utc",
        "data_source", "source_url", "raw_json_path",
    ]
    source_cols = {"data_source": "TEXT", "source_url": "TEXT", "raw_json_path": "TEXT", "fetched_at_utc": "TEXT"}
    with sqlite3.connect(db_path) as conn:
        create_real_tables(conn)
        ensure_columns(conn, "historical_games_last5", source_cols)
        ensure_columns(conn, "historical_game_rosters", source_cols)
        ensure_columns(conn, "historical_player_game_stats", source_cols)

        for season in seasons:
            conn.execute("DELETE FROM real_historical_games_api WHERE season = ?", (season,))
            conn.execute("DELETE FROM historical_games_last5 WHERE season = ?", (season,))
        for season in roster_seasons:
            conn.execute("DELETE FROM real_historical_game_rosters_api WHERE season = ?", (season,))
            conn.execute("DELETE FROM real_historical_player_game_stats_api WHERE season = ?", (season,))
            conn.execute("DELETE FROM historical_game_rosters WHERE season = ?", (season,))
            conn.execute("DELETE FROM historical_player_game_stats WHERE season = ?", (season,))

        insert_rows(conn, "real_historical_games_api", games, game_cols)
        insert_rows(conn, "historical_games_last5", games, game_cols)
        insert_rows(conn, "real_historical_game_rosters_api", roster_rows, roster_cols)
        insert_rows(conn, "historical_game_rosters", roster_rows, roster_cols)
        insert_rows(conn, "real_historical_player_game_stats_api", stat_rows, stat_cols)
        insert_rows(conn, "historical_player_game_stats", stat_rows, stat_cols)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_real_historical_games_api_season ON real_historical_games_api(season)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_real_historical_rosters_api_season ON real_historical_game_rosters_api(season, team_abbrev)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_real_historical_stats_api_season ON real_historical_player_game_stats_api(season, team_abbrev)")
        conn.commit()


def compute_validation(db_path: Path, seasons: List[int], roster_seasons: List[int], boxscore_failures: List[Dict[str, Any]]) -> Dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        season_rows = [
            {
                "season": int(season),
                "games": int(games),
                "teams": int(teams),
                "home_win_rate": round(float(home_win_rate), 4),
                "first_game_date": first_date,
                "last_game_date": last_date,
            }
            for season, games, teams, home_win_rate, first_date, last_date in conn.execute(
                """
                SELECT season,
                       COUNT(DISTINCT game_id) AS games,
                       COUNT(DISTINCT team) AS teams,
                       AVG(CASE WHEN winner_abbrev = home_team_abbrev THEN 1.0 ELSE 0.0 END) AS home_win_rate,
                       MIN(game_date),
                       MAX(game_date)
                FROM (
                    SELECT season, game_id, game_date, home_team_abbrev, away_team_abbrev, winner_abbrev, home_team_abbrev AS team
                    FROM real_historical_games_api
                    UNION ALL
                    SELECT season, game_id, game_date, home_team_abbrev, away_team_abbrev, winner_abbrev, away_team_abbrev AS team
                    FROM real_historical_games_api
                )
                WHERE season IN ({})
                GROUP BY season
                ORDER BY season
                """.format(",".join("?" for _ in seasons)),
                seasons,
            ).fetchall()
        ]
        roster_counts = {
            int(season): {"games": int(games), "rows": int(rows)}
            for season, games, rows in conn.execute(
                """
                SELECT season, COUNT(DISTINCT game_id), COUNT(*)
                FROM real_historical_game_rosters_api
                WHERE season IN ({})
                GROUP BY season
                ORDER BY season
                """.format(",".join("?" for _ in roster_seasons)),
                roster_seasons,
            ).fetchall()
        } if roster_seasons else {}
        spot_checks = [
            {
                "game_id": int(game_id),
                "game_date": game_date,
                "away": away,
                "away_goals": int(away_goals),
                "home": home,
                "home_goals": int(home_goals),
                "winner": winner,
            }
            for game_id, game_date, away, away_goals, home, home_goals, winner in conn.execute(
                """
                SELECT game_id, game_date, away_team_abbrev, away_goals, home_team_abbrev, home_goals, winner_abbrev
                FROM real_historical_games_api
                WHERE game_id IN (2015020001, 2016020001, 2017020015, 2018020001, 2019020001)
                ORDER BY game_id
                """
            ).fetchall()
        ]
    return {
        "season_summary": season_rows,
        "roster_summary": roster_counts,
        "spot_checks": spot_checks,
        "boxscore_failures": boxscore_failures,
    }


def write_report(report_path: Path, validation: Dict[str, Any], seasons: List[int], roster_seasons: List[int]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Real Historical NHL Ingestion Results",
        "",
        f"Generated at: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "## Data sources",
        "",
        "- Season metadata: `https://api.nhle.com/stats/rest/en/season`",
        "- Game schedules/results: `https://api-web.nhle.com/v1/schedule/{date}`",
        "- Boxscore rosters/player stats: `https://api-web.nhle.com/v1/gamecenter/{gameId}/boxscore`",
        "",
        "All ingested rows use `data_source='real_nhl_api_web'` and include `source_url`, `raw_json_path`, and `fetched_at_utc` provenance columns.",
        "",
        "## Historical team handling",
        "",
        "- Team membership is derived from teams that actually appear in each season's API games.",
        "- Pre-2024 Arizona/Phoenix aliases are stored as `ARI`; Utah (`UTA`) is not used for these historical seasons.",
        "- Vegas (`VGK`) appears beginning in 20172018; Seattle (`SEA`) is absent from these seasons.",
        "",
        "## Tables updated",
        "",
        "- Source-specific: `real_historical_games_api`, `real_historical_game_rosters_api`, `real_historical_player_game_stats_api`.",
        "- Canonical compatibility: replaced matching seasons in `historical_games_last5`, `historical_game_rosters`, and `historical_player_game_stats` with the same real API rows.",
        "",
        "## Games by season",
        "",
        "| Season | Real games | Teams | First date | Last date | Home win rate |",
        "| --- | ---: | ---: | --- | --- | ---: |",
    ]
    for row in validation["season_summary"]:
        lines.append(
            f"| {row['season']} | {row['games']} | {row['teams']} | {row['first_game_date']} | "
            f"{row['last_game_date']} | {row['home_win_rate']:.4f} |"
        )
    lines.extend(["", "## Roster ingestion", "", "| Season | Games with roster rows | Roster rows |", "| --- | ---: | ---: |"])
    for season in roster_seasons:
        row = validation["roster_summary"].get(season, {"games": 0, "rows": 0})
        lines.append(f"| {season} | {row['games']} | {row['rows']} |")
    lines.extend(["", "## Spot checks", "", "| Game ID | Date | Result | Winner |", "| ---: | --- | --- | --- |"])
    for row in validation["spot_checks"]:
        lines.append(
            f"| {row['game_id']} | {row['game_date']} | {row['away']} {row['away_goals']} @ "
            f"{row['home']} {row['home_goals']} | {row['winner']} |"
        )
    failures = validation["boxscore_failures"]
    lines.extend(["", "## Gaps and failures", ""])
    optional_without_rosters = sorted(set(seasons) - set(roster_seasons))
    if optional_without_rosters:
        lines.append(f"- Boxscore rosters were not fetched for optional seasons: {optional_without_rosters}.")
    if failures:
        lines.append(f"- Boxscore failures: {len(failures)} games. Details are in the run diagnostics/raw logs.")
        for failure in failures[:20]:
            lines.append(f"  - {failure['season']} game {failure['game_id']}: {failure['error']}")
        if len(failures) > 20:
            lines.append(f"  - ... {len(failures) - 20} additional failures omitted.")
    else:
        lines.append("- No schedule-result gaps or boxscore failures for the fetched roster seasons.")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest real historical NHL regular seasons from NHL API.")
    parser.add_argument("--repo-root", default=None, help="Repository root; defaults to script parent parent.")
    parser.add_argument("--seasons", nargs="+", type=int, default=list(DEFAULT_SEASONS))
    parser.add_argument("--roster-seasons", nargs="*", type=int, default=list(DEFAULT_ROSTER_SEASONS))
    parser.add_argument("--delay-seconds", type=float, default=0.08, help="Delay before each API request.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parent.parent
    db_path = repo_root / "data" / "processed" / "nhl_research.db"
    raw_dir = repo_root / "data" / "raw" / "nhl" / "real_historical_api"
    schedule_raw_dir = raw_dir / "schedules"
    boxscore_raw_dir = raw_dir / "boxscores"
    report_path = repo_root / "data" / "reports" / "real_historical_ingestion_results.md"
    fetched_at_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    seasons = sorted(set(args.seasons))
    roster_seasons = sorted(set(args.roster_seasons) & set(seasons))

    http = requests.Session()
    http.headers.update({"User-Agent": "SportsAnalyticsRealHistoricalIngest/1.0"})
    with sqlite3.connect(db_path) as conn:
        alias_map = load_alias_map(conn)

    windows = get_season_windows(http, seasons, args.delay_seconds)
    all_games: List[Dict[str, Any]] = []
    print(f"seasons={seasons}")
    for season in seasons:
        rows, raw_paths = fetch_regular_games_for_season(
            http, windows[season], alias_map, schedule_raw_dir, args.delay_seconds, fetched_at_utc
        )
        all_games.extend(rows)
        print(f"season={season} games={len(rows)} schedule_payloads={len(raw_paths)}")

    roster_rows: List[Dict[str, Any]] = []
    stat_rows: List[Dict[str, Any]] = []
    boxscore_failures: List[Dict[str, Any]] = []
    roster_games = [game for game in all_games if int(game["season"]) in roster_seasons]
    for index, game in enumerate(roster_games, start=1):
        if index == 1 or index % 100 == 0:
            print(f"boxscores_progress={index}/{len(roster_games)}")
        game_rosters, game_stats, error = fetch_boxscore_rows(
            http, game, alias_map, boxscore_raw_dir, args.delay_seconds, fetched_at_utc
        )
        if error:
            boxscore_failures.append({"season": game["season"], "game_id": game["game_id"], "error": error})
            continue
        roster_rows.extend(game_rosters)
        stat_rows.extend(game_stats)

    http.close()
    persist_to_database(db_path, all_games, roster_rows, stat_rows, seasons, roster_seasons)
    validation = compute_validation(db_path, seasons, roster_seasons, boxscore_failures)
    write_report(report_path, validation, seasons, roster_seasons)
    print(f"games_inserted={len(all_games)}")
    print(f"roster_rows_inserted={len(roster_rows)}")
    print(f"player_stat_rows_inserted={len(stat_rows)}")
    print(f"boxscore_failures={len(boxscore_failures)}")
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
