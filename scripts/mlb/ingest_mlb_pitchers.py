from __future__ import annotations

import datetime as dt
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "mlb" / "mlb_research.db"
RAW_DIR = ROOT / "data" / "mlb" / "raw" / "pitchers"
START_SEASON = 2015
END_SEASON = 2025
BASE = "https://statsapi.mlb.com/api/v1"
UA = "SportsAnalyticsPitcherResearch/1.0"
THROTTLE_SECONDS = 0.20
BATCH_SIZE = 40


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def endpoint(path: str, **params: Any) -> str:
    return f"{BASE}{path}?{urllib.parse.urlencode(params)}"


def cached_json(cache_path: Path, url: str, fetch_logs: list[tuple[Any, ...]]) -> dict[str, Any] | None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    last_error = None
    for attempt in range(1, 5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as response:
                raw = response.read()
                cache_path.write_bytes(raw)
                fetch_logs.append((url, str(cache_path.relative_to(ROOT)), "success", response.status, len(raw), now_utc(), None))
                time.sleep(THROTTLE_SECONDS)
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.reason}"
            retryable = exc.code == 429 or 500 <= exc.code <= 599
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = repr(exc)
            retryable = True
        if attempt < 4 and retryable:
            time.sleep(min(30, 2**attempt))
        else:
            break
    fetch_logs.append((url, str(cache_path.relative_to(ROOT)), "failed", None, 0, now_utc(), last_error))
    return None


def month_windows(year: int) -> list[tuple[str, str]]:
    out = []
    for month in range(1, 13):
        start = dt.date(year, month, 1)
        end = dt.date(year, 12, 31) if month == 12 else dt.date(year, month + 1, 1) - dt.timedelta(days=1)
        out.append((start.isoformat(), end.isoformat()))
    return out


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mlb_game_starters (
            game_pk INTEGER PRIMARY KEY,
            season INTEGER NOT NULL,
            game_date TEXT NOT NULL,
            game_datetime_utc TEXT,
            home_team_id INTEGER,
            away_team_id INTEGER,
            home_pitcher_id INTEGER,
            home_pitcher_name TEXT,
            away_pitcher_id INTEGER,
            away_pitcher_name TEXT,
            source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mlb_pitcher_game_logs (
            pitcher_id INTEGER NOT NULL,
            pitcher_name TEXT,
            season INTEGER NOT NULL,
            game_pk INTEGER NOT NULL,
            game_date TEXT NOT NULL,
            team_id INTEGER,
            opponent_id INTEGER,
            is_home INTEGER,
            is_win INTEGER,
            games_started INTEGER,
            games_played INTEGER,
            outs INTEGER,
            earned_runs INTEGER,
            runs INTEGER,
            hits INTEGER,
            base_on_balls INTEGER,
            strike_outs INTEGER,
            home_runs INTEGER,
            batters_faced INTEGER,
            number_of_pitches INTEGER,
            innings_pitched TEXT,
            source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (pitcher_id, game_pk)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mlb_pitcher_fetch_log (
            url TEXT NOT NULL,
            cache_path TEXT,
            status TEXT NOT NULL,
            http_status INTEGER,
            bytes INTEGER,
            fetched_at_utc TEXT NOT NULL,
            error TEXT
        )
        """
    )


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def parse_pitcher(entry: dict[str, Any]) -> tuple[int | None, str | None]:
    pitcher = entry.get("probablePitcher") or {}
    return as_int(pitcher.get("id")), pitcher.get("fullName")


def ingest_starters(fetch_logs: list[tuple[Any, ...]]) -> list[int]:
    rows = []
    pitcher_ids: set[int] = set()
    fetched_at = now_utc()
    for season in range(START_SEASON, END_SEASON + 1):
        for start_date, end_date in month_windows(season):
            url = endpoint(
                "/schedule",
                sportId=1,
                startDate=start_date,
                endDate=end_date,
                gameTypes="R",
                hydrate="probablePitcher",
            )
            cache_path = RAW_DIR / "schedule" / f"schedule_{season}_{start_date[5:7]}.json"
            payload = cached_json(cache_path, url, fetch_logs)
            if not payload:
                continue
            for date_block in payload.get("dates", []):
                for game in date_block.get("games", []):
                    home_id, home_name = parse_pitcher(game.get("teams", {}).get("home", {}))
                    away_id, away_name = parse_pitcher(game.get("teams", {}).get("away", {}))
                    if home_id:
                        pitcher_ids.add(home_id)
                    if away_id:
                        pitcher_ids.add(away_id)
                    rows.append(
                        (
                            as_int(game.get("gamePk")),
                            season,
                            game.get("officialDate"),
                            game.get("gameDate"),
                            as_int(game.get("teams", {}).get("home", {}).get("team", {}).get("id")),
                            as_int(game.get("teams", {}).get("away", {}).get("team", {}).get("id")),
                            home_id,
                            home_name,
                            away_id,
                            away_name,
                            "statsapi_schedule_probablePitcher",
                            fetched_at,
                        )
                    )
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        create_schema(conn)
        conn.executemany(
            """
            INSERT OR REPLACE INTO mlb_game_starters (
                game_pk, season, game_date, game_datetime_utc, home_team_id, away_team_id,
                home_pitcher_id, home_pitcher_name, away_pitcher_id, away_pitcher_name,
                source, fetched_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    return sorted(pitcher_ids)


def chunks(values: list[int], size: int) -> list[list[int]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def stat_int(stat: dict[str, Any], name: str) -> int | None:
    return as_int(stat.get(name))


def ingest_pitcher_logs(pitcher_ids: list[int], fetch_logs: list[tuple[Any, ...]]) -> None:
    rows = []
    fetched_at = now_utc()
    for season in range(START_SEASON, END_SEASON + 1):
        for batch in chunks(pitcher_ids, BATCH_SIZE):
            url = endpoint(
                "/people",
                personIds=",".join(str(v) for v in batch),
                hydrate=f"stats(group=[pitching],type=[gameLog],season={season})",
            )
            cache_path = RAW_DIR / "people_gamelogs" / str(season) / f"people_{batch[0]}_{batch[-1]}.json"
            payload = cached_json(cache_path, url, fetch_logs)
            if not payload:
                continue
            for person in payload.get("people", []):
                pitcher_id = as_int(person.get("id"))
                pitcher_name = person.get("fullName")
                for stat_group in person.get("stats", []):
                    for split in stat_group.get("splits", []):
                        if split.get("gameType") != "R":
                            continue
                        stat = split.get("stat", {})
                        game = split.get("game", {})
                        game_pk = as_int(game.get("gamePk"))
                        if not pitcher_id or not game_pk:
                            continue
                        rows.append(
                            (
                                pitcher_id,
                                pitcher_name,
                                season,
                                game_pk,
                                split.get("date"),
                                as_int(split.get("team", {}).get("id")),
                                as_int(split.get("opponent", {}).get("id")),
                                1 if split.get("isHome") else 0,
                                1 if split.get("isWin") else 0,
                                stat_int(stat, "gamesStarted"),
                                stat_int(stat, "gamesPlayed"),
                                stat_int(stat, "outs"),
                                stat_int(stat, "earnedRuns"),
                                stat_int(stat, "runs"),
                                stat_int(stat, "hits"),
                                stat_int(stat, "baseOnBalls"),
                                stat_int(stat, "strikeOuts"),
                                stat_int(stat, "homeRuns"),
                                stat_int(stat, "battersFaced"),
                                stat_int(stat, "numberOfPitches"),
                                stat.get("inningsPitched"),
                                "statsapi_people_gameLog",
                                fetched_at,
                            )
                        )
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        create_schema(conn)
        conn.executemany(
            """
            INSERT OR REPLACE INTO mlb_pitcher_game_logs (
                pitcher_id, pitcher_name, season, game_pk, game_date, team_id, opponent_id,
                is_home, is_win, games_started, games_played, outs, earned_runs, runs, hits,
                base_on_balls, strike_outs, home_runs, batters_faced, number_of_pitches,
                innings_pitched, source, fetched_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.executemany(
            """
            INSERT INTO mlb_pitcher_fetch_log (
                url, cache_path, status, http_status, bytes, fetched_at_utc, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            fetch_logs,
        )
        conn.commit()


def main() -> None:
    fetch_logs: list[tuple[Any, ...]] = []
    pitcher_ids = ingest_starters(fetch_logs)
    ingest_pitcher_logs(pitcher_ids, fetch_logs)
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        starter_summary = conn.execute(
            "SELECT COUNT(*), SUM(home_pitcher_id IS NOT NULL AND away_pitcher_id IS NOT NULL) FROM mlb_game_starters"
        ).fetchone()
        log_count = conn.execute("SELECT COUNT(*) FROM mlb_pitcher_game_logs").fetchone()[0]
    print(f"Starter rows: {starter_summary[0]}, both starters present: {starter_summary[1]}")
    print(f"Pitcher game-log rows: {log_count}")
    print(f"Raw JSON cache: {RAW_DIR}")


if __name__ == "__main__":
    main()
