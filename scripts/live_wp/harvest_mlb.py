from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.espn_client import (
    date_range_param,
    dedupe_by_game_id,
    fetch_scoreboard,
    normalize_events,
)
from app.services.espn_pbp import fetch_summary, snapshots_from_summary

DB_PATH = ROOT / "data" / "live_wp" / "mlb_snapshots.db"

# Full MLB regular-season date ranges. These deliberately include the
# international openers and 2024's Sep. 30 makeup doubleheader.
HARVEST_WINDOWS = {
    2024: (date(2024, 3, 20), date(2024, 9, 30)),
    2025: (date(2025, 3, 18), date(2025, 9, 28)),
}
SCOREBOARD_CHUNK_DAYS = 14
MAX_ATTEMPTS = 4
SUMMARY_SLEEP_SECONDS = 0.25


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
            snapshot_index INTEGER NOT NULL,
            league TEXT NOT NULL,
            period INTEGER NOT NULL,
            clock_seconds REAL,
            frac_remaining REAL NOT NULL,
            home_score INTEGER NOT NULL,
            away_score INTEGER NOT NULL,
            margin INTEGER NOT NULL,
            home_won INTEGER NOT NULL,
            espn_home_wp REAL,
            outs INTEGER,
            season INTEGER NOT NULL,
            PRIMARY KEY (game_id, snapshot_index)
        )
        """
    )
    conn.commit()
    return conn


def _season_chunks(start: date, end: date):
    current = start
    while current <= end:
        chunk_end = min(end, current + timedelta(days=SCOREBOARD_CHUNK_DAYS - 1))
        yield current, (chunk_end - current).days + 1
        current = chunk_end + timedelta(days=1)


def fetch_regular_window(start: date, days: int) -> list[dict]:
    end = start + timedelta(days=days - 1)
    padded = date_range_param(start - timedelta(days=1), end + timedelta(days=1))
    events, _meta = fetch_scoreboard("mlb", dates=padded, ttl=60 * 60 * 24 * 30)
    regular = [e for e in events if (e.get("season") or {}).get("type") == 2]
    rows = normalize_events(regular, "mlb")
    lo, hi = start.isoformat(), end.isoformat()
    rows = [r for r in rows if r["game_date"] and lo <= r["game_date"] <= hi]
    rows = dedupe_by_game_id(rows)
    rows.sort(key=lambda r: (r["start_time_utc"] or "", r["game_id"]))
    return rows


def game_rows() -> list[dict]:
    rows: list[dict] = []
    for season, (start, end) in HARVEST_WINDOWS.items():
        season_rows: list[dict] = []
        for chunk_start, days in _season_chunks(start, end):
            chunk_rows = fetch_regular_window(chunk_start, days)
            season_rows.extend(chunk_rows)
            print(
                f"{season}: scoreboard {chunk_start} +{days}d -> {len(chunk_rows)} events",
                flush=True,
            )
        deduped = {str(row["game_id"]): row for row in season_rows}.values()
        status_counts: dict[str, int] = {}
        for row in deduped:
            status_counts[str(row.get("status"))] = status_counts.get(str(row.get("status")), 0) + 1
        finals = [r for r in deduped if r.get("status") == "final"]
        for row in finals:
            row = dict(row)
            row["season"] = season
            rows.append(row)
        print(
            f"{season}: found {len(finals)} final games from {start} through {end}; "
            f"statuses={status_counts}",
            flush=True,
        )
    return rows


def already_harvested(conn: sqlite3.Connection, game_id: str) -> bool:
    return conn.execute("SELECT 1 FROM games WHERE game_id = ?", (game_id,)).fetchone() is not None


def insert_game(conn: sqlite3.Connection, row: dict, n_snapshots: int) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO games (
            game_id, season, game_date, home, away, home_score, away_score, status, n_snapshots
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(row["game_id"]),
            int(row["season"]),
            row.get("game_date"),
            row.get("home"),
            row.get("away"),
            row.get("home_score"),
            row.get("away_score"),
            row.get("status"),
            n_snapshots,
        ),
    )


def insert_snapshots(conn: sqlite3.Connection, season: int, snapshots) -> None:
    conn.executemany(
        """
        INSERT OR IGNORE INTO snapshots (
            game_id, snapshot_index, league, period, clock_seconds, frac_remaining,
            home_score, away_score, margin, home_won, espn_home_wp, outs, season
        ) VALUES (
            :game_id, :snapshot_index, :league, :period, :clock_seconds, :frac_remaining,
            :home_score, :away_score, :margin, :home_won, :espn_home_wp, :outs, :season
        )
        """,
        [dict(asdict(s), snapshot_index=i, season=season) for i, s in enumerate(snapshots)],
    )


def fetch_summary_with_retry(game_id: str) -> dict[str, Any]:
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fetch_summary("mlb", game_id)
        except Exception as exc:
            last_exc = exc
            if attempt == MAX_ATTEMPTS:
                break
            print(
                f"retry {attempt}/{MAX_ATTEMPTS} for {game_id} after {type(exc).__name__}: {exc}",
                flush=True,
            )
            time.sleep(delay)
            delay *= 2
    assert last_exc is not None
    raise last_exc


def harvest(limit: int | None = None) -> None:
    conn = connect()
    rows = game_rows()
    rows.sort(key=lambda r: (r["season"], r["game_date"], r["game_id"]))
    if limit is not None:
        rows = rows[:limit]

    total = len(rows)
    skipped = harvested = empty = errors = 0
    failures: list[tuple[str, str, str]] = []
    for idx, row in enumerate(rows, 1):
        game_id = str(row["game_id"])
        if already_harvested(conn, game_id):
            skipped += 1
            if idx % 25 == 0 or idx == total:
                print(f"{idx}/{total}: skipped cached {game_id}", flush=True)
            continue
        try:
            summary = fetch_summary_with_retry(game_id)
            snaps = snapshots_from_summary(
                summary,
                "mlb",
                game_id,
                final_home=row.get("home_score"),
                final_away=row.get("away_score"),
            )
        except Exception as exc:
            errors += 1
            failures.append((game_id, type(exc).__name__, str(exc)))
            print(f"{idx}/{total}: ERROR {game_id}: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(SUMMARY_SLEEP_SECONDS)
            continue
        insert_snapshots(conn, int(row["season"]), snaps)
        insert_game(conn, row, len(snaps))
        conn.commit()
        if snaps:
            harvested += 1
        else:
            empty += 1
            failures.append((game_id, "empty_snapshots", "summary returned no usable snapshots"))
        print(
            f"{idx}/{total}: {row['season']} {row.get('away')}@{row.get('home')} "
            f"{game_id}: {len(snaps)} snapshots",
            flush=True,
        )
        if not snaps:
            print(f"{idx}/{total}: EMPTY {game_id}: summary returned no usable snapshots", flush=True)
        time.sleep(SUMMARY_SLEEP_SECONDS)

    counts = conn.execute(
        "SELECT COUNT(DISTINCT game_id), COUNT(*), SUM(espn_home_wp IS NOT NULL) FROM snapshots"
    ).fetchone()
    print(
        "done: "
        f"games_with_snapshots={counts[0]}, snapshots={counts[1]}, espn_wp={counts[2]}, "
        f"harvested={harvested}, skipped={skipped}, empty={empty}, errors={errors}",
        flush=True,
    )
    if failures:
        print("failures:", flush=True)
        for game_id, kind, detail in failures:
            print(f"  {kind}\t{game_id}\t{detail}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    harvest(args.limit)


if __name__ == "__main__":
    main()
