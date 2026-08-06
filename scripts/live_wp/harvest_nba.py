"""Harvest NBA in-game win-probability training snapshots from ESPN.

The script is intentionally restartable: completed game ids already present in
the SQLite database are skipped, so failed or interrupted harvests can be rerun
without redownloading those summaries.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.espn_client import fetch_window
from app.services.espn_pbp import fetch_summary, snapshots_from_summary

DB_PATH = ROOT / "data" / "live_wp" / "nba_snapshots.db"
DEFAULT_WINDOWS = (
    ("2023-10-24", 174),
    ("2024-10-22", 174),
)


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            game_date TEXT NOT NULL,
            season_start_year INTEGER NOT NULL,
            status TEXT NOT NULL,
            harvested_at TEXT,
            n_snapshots INTEGER NOT NULL DEFAULT 0,
            espn_wp_coverage INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            game_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
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
            PRIMARY KEY (game_id, seq),
            FOREIGN KEY (game_id) REFERENCES games(game_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS harvest_failures (
            game_id TEXT PRIMARY KEY,
            game_date TEXT,
            season_start_year INTEGER,
            reason TEXT NOT NULL,
            detail TEXT,
            attempts INTEGER NOT NULL,
            failed_at TEXT NOT NULL
        )
        """
    )
    return conn


def season_start_year(game_date: str) -> int:
    d = date.fromisoformat(game_date)
    return d.year if d.month >= 7 else d.year - 1


def existing_harvested_ids(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT game_id FROM games WHERE n_snapshots > 0"
        ).fetchall()
    }


def enumerate_final_games(windows: list[tuple[str, int]], max_games: int | None) -> list[dict]:
    """Return final games, optionally capped per window so seasons stay represented."""
    all_rows: dict[str, dict] = {}
    capped = max_games is not None and max_games > 0
    base_quota = (max_games or 0) // max(len(windows), 1)
    remainder = (max_games or 0) % max(len(windows), 1)
    for window_index, (start_text, days) in enumerate(windows):
        window_rows: dict[str, dict] = {}
        quota = base_quota + (1 if window_index < remainder else 0)
        start = date.fromisoformat(start_text)
        cursor = start
        remaining = days
        while remaining > 0:
            chunk = min(14, remaining)
            rows, meta = fetch_window("nba", cursor, chunk, ttl=86400)
            finals = [r for r in rows if r.get("status") == "final" and r.get("game_id")]
            for row in finals:
                window_rows[row["game_id"]] = row
            print(
                f"Enumerated {cursor.isoformat()} +{chunk}d: "
                f"{len(finals)} finals ({len(window_rows)} unique in window), cached={meta.get('cached')}",
                flush=True,
            )
            cursor += timedelta(days=chunk)
            remaining -= chunk
            if capped and len(window_rows) >= quota:
                break
        rows = sorted(window_rows.values(), key=lambda r: (r.get("game_date") or "", r["game_id"]))
        for row in rows[:quota] if capped else rows:
            all_rows[row["game_id"]] = row
    rows = sorted(all_rows.values(), key=lambda r: (r.get("game_date") or "", r["game_id"]))
    return rows[:max_games] if capped else rows


def store_game(conn: sqlite3.Connection, row: dict, snapshots: list) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    game_id = str(row["game_id"])
    game_date = row.get("game_date") or ""
    conn.execute(
        """
        INSERT OR REPLACE INTO games
            (game_id, game_date, season_start_year, status, harvested_at, n_snapshots, espn_wp_coverage)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_id,
            game_date,
            season_start_year(game_date),
            row.get("status") or "final",
            now,
            len(snapshots),
            sum(1 for s in snapshots if s.espn_home_wp is not None),
        ),
    )
    conn.execute("DELETE FROM snapshots WHERE game_id = ?", (game_id,))
    conn.executemany(
        """
        INSERT INTO snapshots
            (game_id, seq, league, period, clock_seconds, frac_remaining,
             home_score, away_score, margin, home_won, espn_home_wp, outs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                s.game_id,
                i,
                s.league,
                s.period,
                s.clock_seconds,
                s.frac_remaining,
                s.home_score,
                s.away_score,
                s.margin,
                s.home_won,
                s.espn_home_wp,
                s.outs,
            )
            for i, s in enumerate(snapshots)
        ],
    )
    conn.commit()
    conn.execute("DELETE FROM harvest_failures WHERE game_id = ?", (game_id,))
    conn.commit()


def record_failure(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    reason: str,
    detail: str,
    attempts: int,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    game_id = str(row["game_id"])
    game_date = row.get("game_date") or ""
    conn.execute(
        """
        INSERT OR REPLACE INTO harvest_failures
            (game_id, game_date, season_start_year, reason, detail, attempts, failed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (game_id, game_date, season_start_year(game_date), reason, detail[:1000], attempts, now),
    )
    conn.commit()


def fetch_snapshots_with_retries(
    game_id: str,
    *,
    attempts: int,
    backoff_seconds: float,
):
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            summary = fetch_summary("nba", game_id)
            return snapshots_from_summary(summary, "nba", game_id), None, attempt
        except Exception as exc:  # noqa: BLE001 - long harvest should continue after final failure.
            last_error = exc
            if attempt < attempts:
                time.sleep(backoff_seconds * (2 ** (attempt - 1)))
    detail = f"{type(last_error).__name__}: {last_error}" if last_error else "unknown error"
    return None, detail, attempts


def parse_windows(values: list[str] | None) -> list[tuple[str, int]]:
    if not values:
        return list(DEFAULT_WINDOWS)
    windows: list[tuple[str, int]] = []
    for value in values:
        start, days = value.split(":", 1)
        windows.append((start, int(days)))
    return windows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-games", type=int, default=None)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--backoff-seconds", type=float, default=1.0)
    parser.add_argument(
        "--window",
        action="append",
        help="Season window as YYYY-MM-DD:DAYS. May be repeated.",
    )
    args = parser.parse_args()

    conn = connect()
    windows = parse_windows(args.window)
    final_games = enumerate_final_games(windows, args.max_games)
    already = existing_harvested_ids(conn)
    to_fetch = [g for g in final_games if str(g["game_id"]) not in already]

    print(
        f"DB={DB_PATH}; selected {len(final_games)} final games from {len(windows)} windows; "
        f"{len(already)} already harvested; {len(to_fetch)} to fetch.",
        flush=True,
    )

    by_id = {str(g["game_id"]): g for g in final_games}
    fetched = 0
    saved = 0
    skipped_empty = 0
    fetch_errors = 0
    for row in to_fetch:
        game_id = str(row["game_id"])
        fetched += 1
        snapshots, error_detail, attempts = fetch_snapshots_with_retries(
            game_id,
            attempts=max(1, args.attempts),
            backoff_seconds=max(0.0, args.backoff_seconds),
        )
        if error_detail is not None:
            fetch_errors += 1
            record_failure(conn, row, "fetch_error", error_detail, attempts)
            print(f"[{fetched}/{len(to_fetch)}] {game_id}: fetch failed: {error_detail}", flush=True)
            if args.sleep_seconds:
                time.sleep(args.sleep_seconds)
            continue
        if not snapshots:
            skipped_empty += 1
            record_failure(conn, row, "no_labelled_snapshots", "summary produced no labelled snapshots", attempts)
            print(f"[{fetched}/{len(to_fetch)}] {game_id}: no labelled snapshots", flush=True)
            if args.sleep_seconds:
                time.sleep(args.sleep_seconds)
            continue
        store_game(conn, by_id[game_id], snapshots)
        saved += 1
        if saved % 10 == 0 or saved == 1:
            total_games, total_snaps = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(n_snapshots), 0) FROM games WHERE n_snapshots > 0"
            ).fetchone()
            print(
                f"[{fetched}/{len(to_fetch)}] saved {game_id}: {len(snapshots)} snapshots; "
                f"db now {total_games} games / {total_snaps} snapshots",
                flush=True,
            )
        if args.sleep_seconds:
            time.sleep(args.sleep_seconds)

    total_games, total_snaps, total_wp = conn.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(n_snapshots), 0), COALESCE(SUM(espn_wp_coverage), 0)
        FROM games WHERE n_snapshots > 0
        """
    ).fetchone()
    seasons = conn.execute(
        "SELECT season_start_year, COUNT(*), SUM(n_snapshots) FROM games WHERE n_snapshots > 0 GROUP BY season_start_year ORDER BY season_start_year"
    ).fetchall()
    print(
        f"Harvest complete: fetched={fetched}, saved={saved}, empty={skipped_empty}, fetch_errors={fetch_errors}; "
        f"database has {total_games} games / {total_snaps} snapshots / {total_wp} ESPN WP values.",
        flush=True,
    )
    print(f"By season: {seasons}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
