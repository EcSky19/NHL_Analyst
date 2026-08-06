from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.espn_client import fetch_window
from app.services.espn_pbp import fetch_summary, frac_remaining_clock, parse_clock_seconds

DB_PATH = ROOT / "data" / "live_wp" / "nfl_situation.db"
OLD_DB_PATH = ROOT / "data" / "live_wp" / "nfl_snapshots.db"

REGULAR_SEASONS = {
    2023: (date(2023, 9, 7), date(2024, 1, 7)),
    2024: (date(2024, 9, 5), date(2025, 1, 5)),
}


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            season INTEGER NOT NULL,
            game_date TEXT NOT NULL,
            home TEXT,
            away TEXT,
            home_team_id TEXT,
            away_team_id TEXT,
            home_score INTEGER,
            away_score INTEGER,
            status TEXT NOT NULL,
            harvested_at TEXT DEFAULT CURRENT_TIMESTAMP,
            n_snapshots INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            game_id TEXT NOT NULL,
            season INTEGER NOT NULL,
            play_index INTEGER NOT NULL,
            play_id TEXT,
            sequence_number INTEGER,
            period INTEGER NOT NULL,
            clock_seconds REAL,
            frac_remaining REAL NOT NULL,
            home_score INTEGER NOT NULL,
            away_score INTEGER NOT NULL,
            margin INTEGER NOT NULL,
            home_won INTEGER NOT NULL,
            espn_home_wp REAL,
            offense_is_home INTEGER,
            offense_team_id TEXT,
            down INTEGER,
            distance INTEGER,
            yard_line INTEGER,
            yards_to_endzone INTEGER,
            is_turnover INTEGER,
            play_type TEXT,
            down_distance_text TEXT,
            PRIMARY KEY (game_id, play_index)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS failed_games (
            game_id TEXT PRIMARY KEY,
            season INTEGER NOT NULL,
            game_date TEXT,
            home TEXT,
            away TEXT,
            error TEXT NOT NULL,
            failed_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def _old_db_uri() -> str:
    return "file:" + OLD_DB_PATH.resolve().as_posix() + "?mode=ro"


def game_rows_from_old_db() -> list[dict[str, Any]]:
    if not OLD_DB_PATH.exists():
        return []
    old = sqlite3.connect(_old_db_uri(), uri=True)
    old.row_factory = sqlite3.Row
    try:
        rows = old.execute(
            """
            SELECT game_id, season, game_date, home, away, home_score, away_score, status
            FROM games
            WHERE season IN (2023, 2024) AND status = 'final'
            ORDER BY season, game_date, game_id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        old.close()


def game_rows_from_schedule() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season, (start, end) in REGULAR_SEASONS.items():
        days = (end - start).days + 1
        season_rows, _meta = fetch_window("nfl", start, days, ttl=60 * 60 * 24 * 30)
        finals = [dict(r, season=season) for r in season_rows if r.get("status") == "final"]
        rows.extend(finals)
        print(f"{season}: found {len(finals)} final regular-season games from schedule", flush=True)
    return rows


def regular_season_game_rows() -> list[dict[str, Any]]:
    rows = game_rows_from_old_db()
    if rows:
        print(f"loaded {len(rows)} game ids from existing nfl_snapshots.db in read-only mode", flush=True)
        return rows
    return game_rows_from_schedule()


def already_harvested(conn: sqlite3.Connection, game_id: str) -> bool:
    row = conn.execute("SELECT n_snapshots FROM games WHERE game_id = ?", (game_id,)).fetchone()
    return bool(row and row[0] > 0)


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _competitors(summary: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    home: dict[str, Any] = {}
    away: dict[str, Any] = {}
    for competitor in comp.get("competitors") or []:
        if competitor.get("homeAway") == "home":
            home = competitor
        elif competitor.get("homeAway") == "away":
            away = competitor
    return home, away


def _team_id(competitor: dict[str, Any]) -> str | None:
    team = competitor.get("team") or {}
    value = team.get("id") or competitor.get("id")
    return str(value) if value is not None else None


def _team_abbrev(competitor: dict[str, Any], fallback: Any) -> str | None:
    team = competitor.get("team") or {}
    return team.get("abbreviation") or team.get("shortDisplayName") or fallback


def _flat_plays(summary: dict[str, Any]) -> list[dict[str, Any]]:
    plays = summary.get("plays")
    if plays:
        return list(plays)
    out: list[dict[str, Any]] = []
    drives = summary.get("drives") or {}
    if isinstance(drives, dict):
        for bucket in ("previous", "current"):
            for drive in drives.get(bucket) or []:
                out.extend(drive.get("plays") or [])
    return out


def _wp_by_play(summary: dict[str, Any]) -> dict[str, float]:
    by_play: dict[str, float] = {}
    for entry in summary.get("winprobability") or []:
        play_id = entry.get("playId")
        pct = entry.get("homeWinPercentage")
        if play_id is not None and pct is not None:
            by_play[str(play_id)] = float(pct)
    return by_play


def parse_snapshots(summary: dict[str, Any], row: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plays = _flat_plays(summary)
    if not plays:
        raise ValueError("summary contained no plays")

    home_comp, away_comp = _competitors(summary)
    home_id = _team_id(home_comp)
    away_id = _team_id(away_comp)
    home_score_final = _int(row.get("home_score")) or _int(home_comp.get("score"))
    away_score_final = _int(row.get("away_score")) or _int(away_comp.get("score"))
    if home_score_final is None or away_score_final is None:
        raise ValueError("missing final score")
    if home_score_final == away_score_final:
        raise ValueError("final score was tied; cannot label home_won")
    home_won = 1 if home_score_final > away_score_final else 0
    wp_by_play = _wp_by_play(summary)

    parsed: list[dict[str, Any]] = []
    for play in plays:
        period = _int((play.get("period") or {}).get("number"))
        home_score = _int(play.get("homeScore"))
        away_score = _int(play.get("awayScore"))
        if period is None or home_score is None or away_score is None:
            continue
        clock_seconds = parse_clock_seconds((play.get("clock") or {}).get("displayValue"))
        frac = frac_remaining_clock("nfl", period, clock_seconds)
        start = play.get("start") or {}
        offense_team_id = ((start.get("team") or {}).get("id"))
        offense_team_id = str(offense_team_id) if offense_team_id is not None else None
        offense_is_home = None
        if offense_team_id is not None and home_id is not None:
            offense_is_home = 1 if offense_team_id == home_id else 0
        play_id = play.get("id")
        end = play.get("end") or {}
        parsed.append(
            {
                "game_id": str(row["game_id"]),
                "season": int(row["season"]),
                "play_index": len(parsed),
                "play_id": str(play_id) if play_id is not None else None,
                "sequence_number": _int(play.get("sequenceNumber")),
                "period": period,
                "clock_seconds": clock_seconds,
                "frac_remaining": frac,
                "home_score": home_score,
                "away_score": away_score,
                "margin": home_score - away_score,
                "home_won": home_won,
                "espn_home_wp": wp_by_play.get(str(play_id)) if play_id is not None else None,
                "offense_is_home": offense_is_home,
                "offense_team_id": offense_team_id,
                "down": _int(start.get("down")),
                "distance": _int(start.get("distance")),
                "yard_line": _int(start.get("yardLine")),
                "yards_to_endzone": _int(start.get("yardsToEndzone")),
                "is_turnover": 1 if play.get("isTurnover") else 0,
                "play_type": (play.get("type") or {}).get("text"),
                "down_distance_text": start.get("downDistanceText") or end.get("downDistanceText"),
            }
        )
    if not parsed:
        raise ValueError("no usable plays after parsing")

    game = {
        "game_id": str(row["game_id"]),
        "season": int(row["season"]),
        "game_date": row.get("game_date") or ((summary.get("header") or {}).get("competitions") or [{}])[0].get("date"),
        "home": _team_abbrev(home_comp, row.get("home")),
        "away": _team_abbrev(away_comp, row.get("away")),
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_score": home_score_final,
        "away_score": away_score_final,
        "status": row.get("status") or "final",
        "n_snapshots": len(parsed),
    }
    return game, parsed


def fetch_with_retry(game_id: str, client: httpx.Client, retries: int = 3) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fetch_summary("nfl", game_id, client=client)
        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
            sleep = 1.0 * (2**attempt)
            print(f"retry {attempt + 1}/{retries} for {game_id} after {exc}; sleeping {sleep:.1f}s", flush=True)
            time.sleep(sleep)
    raise RuntimeError(f"failed after {retries + 1} attempts: {last_exc}")


def insert_game(conn: sqlite3.Connection, game: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO games (
            game_id, season, game_date, home, away, home_team_id, away_team_id,
            home_score, away_score, status, n_snapshots
        ) VALUES (
            :game_id, :season, :game_date, :home, :away, :home_team_id, :away_team_id,
            :home_score, :away_score, :status, :n_snapshots
        )
        """,
        game,
    )


def insert_snapshots(conn: sqlite3.Connection, game_id: str, snapshots: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM snapshots WHERE game_id = ?", (game_id,))
    conn.executemany(
        """
        INSERT OR REPLACE INTO snapshots (
            game_id, season, play_index, play_id, sequence_number, period, clock_seconds,
            frac_remaining, home_score, away_score, margin, home_won, espn_home_wp,
            offense_is_home, offense_team_id, down, distance, yard_line, yards_to_endzone,
            is_turnover, play_type, down_distance_text
        ) VALUES (
            :game_id, :season, :play_index, :play_id, :sequence_number, :period, :clock_seconds,
            :frac_remaining, :home_score, :away_score, :margin, :home_won, :espn_home_wp,
            :offense_is_home, :offense_team_id, :down, :distance, :yard_line, :yards_to_endzone,
            :is_turnover, :play_type, :down_distance_text
        )
        """,
        snapshots,
    )


def record_failure(conn: sqlite3.Connection, row: dict[str, Any], error: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO failed_games (
            game_id, season, game_date, home, away, error, failed_at
        ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            str(row["game_id"]),
            int(row["season"]),
            row.get("game_date"),
            row.get("home"),
            row.get("away"),
            error[:1000],
        ),
    )


def harvest(limit: int | None, sleep_seconds: float, force: bool) -> None:
    conn = connect()
    rows = regular_season_game_rows()
    rows.sort(key=lambda r: (r["season"], r.get("game_date") or "", str(r["game_id"])))
    if limit is not None:
        rows = rows[:limit]

    skipped = harvested = errors = 0
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for idx, row in enumerate(rows, 1):
            game_id = str(row["game_id"])
            if not force and already_harvested(conn, game_id):
                skipped += 1
                if idx % 25 == 0 or idx == len(rows):
                    print(f"{idx}/{len(rows)}: skipped cached {game_id}", flush=True)
                continue
            try:
                summary = fetch_with_retry(game_id, client)
                game, snapshots = parse_snapshots(summary, row)
                insert_snapshots(conn, game_id, snapshots)
                insert_game(conn, game)
                conn.execute("DELETE FROM failed_games WHERE game_id = ?", (game_id,))
                conn.commit()
                harvested += 1
                print(
                    f"{idx}/{len(rows)}: {game['season']} {game['away']}@{game['home']} "
                    f"{game_id}: {len(snapshots)} snapshots",
                    flush=True,
                )
            except Exception as exc:
                conn.rollback()
                record_failure(conn, row, str(exc))
                conn.commit()
                errors += 1
                print(f"{idx}/{len(rows)}: ERROR {game_id}: {exc}", flush=True)
            if sleep_seconds:
                time.sleep(sleep_seconds)

    total = conn.execute(
        "SELECT COUNT(DISTINCT game_id), COUNT(*), SUM(espn_home_wp IS NOT NULL) FROM snapshots"
    ).fetchone()
    failed = conn.execute("SELECT COUNT(*) FROM failed_games").fetchone()[0]
    print(
        f"done: games={total[0]}, snapshots={total[1]}, espn_wp={total[2]}, "
        f"harvested={harvested}, skipped={skipped}, run_errors={errors}, failed_recorded={failed}",
        flush=True,
    )


def _summary_stats(conn: sqlite3.Connection, column: str) -> dict[str, Any]:
    values = [r[0] for r in conn.execute(f"SELECT {column} FROM snapshots WHERE {column} IS NOT NULL")]
    total = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    nulls = conn.execute(f"SELECT COUNT(*) FROM snapshots WHERE {column} IS NULL").fetchone()[0]
    return {
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "median": median(values) if values else None,
        "null_rate": (nulls / total) if total else None,
    }


def validate() -> None:
    conn = connect()
    print("coverage by season:")
    for row in conn.execute(
        "SELECT season, COUNT(*) rows, COUNT(DISTINCT game_id) games FROM snapshots GROUP BY season ORDER BY season"
    ):
        print(f"  {row[0]}: rows={row[1]}, games={row[2]}")
    print(f"failed_games={conn.execute('SELECT COUNT(*) FROM failed_games').fetchone()[0]}")

    if OLD_DB_PATH.exists():
        old = sqlite3.connect(_old_db_uri(), uri=True)
        try:
            intersection = old.execute(
                """
                ATTACH DATABASE ? AS newdb;
                """,
                (str(DB_PATH),),
            )
        except sqlite3.Error:
            intersection = None
        finally:
            if intersection is None:
                old.close()
        if intersection is not None:
            inter = old.execute(
                """
                SELECT COUNT(DISTINCT o.game_id)
                FROM main.games o
                JOIN newdb.games n ON n.game_id = o.game_id
                WHERE o.season IN (2023, 2024)
                """
            ).fetchone()[0]
            missing = old.execute(
                """
                SELECT o.season, o.game_id
                FROM main.games o
                LEFT JOIN newdb.games n ON n.game_id = o.game_id
                WHERE o.season IN (2023, 2024) AND n.game_id IS NULL
                ORDER BY o.season, o.game_id
                """
            ).fetchall()
            print(f"old/new game_id intersection={inter}")
            print(f"old games lacking new harvest={len(missing)}")
            if missing:
                print("missing:", ", ".join(f"{s}:{g}" for s, g in missing[:25]))
            old.close()

    for column in ("down", "distance", "yards_to_endzone"):
        stats = _summary_stats(conn, column)
        print(
            f"{column}: min={stats['min']} max={stats['max']} "
            f"median={stats['median']} null_rate={stats['null_rate']:.4f}"
        )
    offense_mean = conn.execute("SELECT AVG(offense_is_home) FROM snapshots").fetchone()[0]
    print(f"offense_is_home mean={offense_mean:.4f}" if offense_mean is not None else "offense_is_home mean=NULL")
    wp = conn.execute("SELECT COUNT(*), SUM(espn_home_wp IS NOT NULL) FROM snapshots").fetchone()
    print(f"espn_home_wp non_null={wp[1]} of {wp[0]}")
    frac = conn.execute(
        "SELECT MIN(frac_remaining), MAX(frac_remaining), SUM(frac_remaining < 0 OR frac_remaining > 1) FROM snapshots"
    ).fetchone()
    increases = conn.execute(
        """
        WITH ordered AS (
            SELECT game_id, play_index, frac_remaining,
                   LAG(frac_remaining) OVER (PARTITION BY game_id ORDER BY play_index) prev_frac
            FROM snapshots
        )
        SELECT COUNT(*) FROM ordered WHERE prev_frac IS NOT NULL AND frac_remaining > prev_frac + 1e-9
        """
    ).fetchone()[0]
    print(f"frac_remaining min={frac[0]} max={frac[1]} out_of_range={frac[2]} increases={increases}")

    game_id = "401671789"
    print(f"spot check {game_id}:")
    for row in conn.execute(
        """
        SELECT play_index, away_score, home_score, period, clock_seconds, down, distance,
               yards_to_endzone, offense_team_id, offense_is_home, play_type, down_distance_text
        FROM snapshots
        WHERE game_id = ?
        ORDER BY play_index
        LIMIT 5 OFFSET 1
        """,
        (game_id,),
    ):
        print(
            "  "
            f"idx={row[0]} score away-home={row[1]}-{row[2]} Q{row[3]} clock_s={row[4]} "
            f"down={row[5]} dist={row[6]} yte={row[7]} off={row[8]} "
            f"home_off={row[9]} type={row[10]} text={row[11]}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        validate()
    else:
        harvest(args.limit, args.sleep, args.force)


if __name__ == "__main__":
    main()
