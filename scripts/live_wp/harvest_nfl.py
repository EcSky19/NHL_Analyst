from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.espn_client import fetch_window
from app.services.espn_pbp import fetch_summary, snapshots_from_summary

DB_PATH = ROOT / "data" / "live_wp" / "nfl_snapshots.db"

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
            PRIMARY KEY (
                game_id, period, clock_seconds, home_score, away_score, margin, frac_remaining
            )
        )
        """
    )
    conn.commit()
    return conn


def regular_season_game_rows() -> list[dict]:
    rows: list[dict] = []
    for season, (start, end) in REGULAR_SEASONS.items():
        days = (end - start).days + 1
        season_rows, _meta = fetch_window("nfl", start, days, ttl=60 * 60 * 24 * 30)
        finals = [r for r in season_rows if r.get("status") == "final"]
        for row in finals:
            row = dict(row)
            row["season"] = season
            rows.append(row)
        print(f"{season}: found {len(finals)} final regular-season games", flush=True)
    return rows


def already_harvested(conn: sqlite3.Connection, game_id: str) -> bool:
    row = conn.execute("SELECT n_snapshots FROM games WHERE game_id = ?", (game_id,)).fetchone()
    return bool(row and row[0] > 0)


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
            game_id, league, period, clock_seconds, frac_remaining, home_score, away_score,
            margin, home_won, espn_home_wp, outs, season
        ) VALUES (
            :game_id, :league, :period, :clock_seconds, :frac_remaining, :home_score,
            :away_score, :margin, :home_won, :espn_home_wp, :outs, :season
        )
        """,
        [dict(asdict(s), season=season) for s in snapshots],
    )


def harvest(limit: int | None = None) -> None:
    conn = connect()
    rows = regular_season_game_rows()
    rows.sort(key=lambda r: (r["season"], r["game_date"], r["game_id"]))
    if limit is not None:
        rows = rows[:limit]

    total = len(rows)
    skipped = harvested = empty = errors = 0
    for idx, row in enumerate(rows, 1):
        game_id = str(row["game_id"])
        if already_harvested(conn, game_id):
            skipped += 1
            if idx % 25 == 0 or idx == total:
                print(f"{idx}/{total}: skipped cached {game_id}", flush=True)
            continue
        try:
            summary = fetch_summary("nfl", game_id)
            snaps = snapshots_from_summary(
                summary,
                "nfl",
                game_id,
                final_home=row.get("home_score"),
                final_away=row.get("away_score"),
            )
        except Exception as exc:
            errors += 1
            print(f"{idx}/{total}: ERROR {game_id}: {exc}", flush=True)
            continue
        insert_snapshots(conn, int(row["season"]), snaps)
        insert_game(conn, row, len(snaps))
        conn.commit()
        if snaps:
            harvested += 1
        else:
            empty += 1
        print(
            f"{idx}/{total}: {row['season']} {row.get('away')}@{row.get('home')} "
            f"{game_id}: {len(snaps)} snapshots",
            flush=True,
        )

    counts = conn.execute(
        "SELECT COUNT(DISTINCT game_id), COUNT(*), SUM(espn_home_wp IS NOT NULL) FROM snapshots"
    ).fetchone()
    print(
        "done: "
        f"games_with_snapshots={counts[0]}, snapshots={counts[1]}, espn_wp={counts[2]}, "
        f"harvested={harvested}, skipped={skipped}, empty={empty}, errors={errors}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    harvest(args.limit)


if __name__ == "__main__":
    main()
