"""Harvest NHL live win-probability training snapshots from ESPN.

Writes only to data/live_wp/nhl_snapshots.db. Re-running is incremental:
games with a completed harvest record are read from SQLite and not downloaded
again.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.espn_client import fetch_window  # noqa: E402
from app.services.espn_pbp import fetch_summary, snapshots_from_summary  # noqa: E402

DB_PATH = ROOT / "data" / "live_wp" / "nhl_snapshots.db"

SEASONS = [
    ("2024-25", date(2024, 10, 4), date(2025, 4, 17)),
    ("2025-26", date(2025, 10, 7), date(2026, 4, 16)),
]


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            season TEXT NOT NULL,
            game_date TEXT,
            home TEXT,
            away TEXT,
            home_score INTEGER,
            away_score INTEGER,
            status TEXT,
            harvested_at TEXT,
            n_snapshots INTEGER,
            espn_wp_count INTEGER,
            error TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            league TEXT NOT NULL,
            season TEXT NOT NULL,
            period INTEGER NOT NULL,
            clock_seconds REAL,
            frac_remaining REAL NOT NULL,
            home_score INTEGER NOT NULL,
            away_score INTEGER NOT NULL,
            margin INTEGER NOT NULL,
            home_won INTEGER NOT NULL,
            espn_home_wp REAL,
            outs INTEGER,
            FOREIGN KEY(game_id) REFERENCES games(game_id)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_game ON snapshots(game_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_season ON snapshots(season)")
    return con


def enumerate_completed_games(con: sqlite3.Connection, days: int) -> None:
    for season, start, end in SEASONS:
        cursor = start
        seen = 0
        while cursor <= end:
            window_days = min(days, (end - cursor).days + 1)
            rows, meta = fetch_window("nhl", cursor, window_days, ttl=60 * 60 * 24 * 30)
            completed = [row for row in rows if row.get("status") == "final"]
            for row in completed:
                con.execute(
                    """
                    INSERT INTO games (
                        game_id, season, game_date, home, away, home_score,
                        away_score, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(game_id) DO UPDATE SET
                        season=excluded.season,
                        game_date=excluded.game_date,
                        home=excluded.home,
                        away=excluded.away,
                        home_score=excluded.home_score,
                        away_score=excluded.away_score,
                        status=excluded.status
                    """,
                    (
                        row["game_id"],
                        season,
                        row.get("game_date"),
                        row.get("home"),
                        row.get("away"),
                        row.get("home_score"),
                        row.get("away_score"),
                        row.get("status"),
                    ),
                )
            con.commit()
            seen += len(completed)
            print(
                f"[enumerate] {season} {cursor.isoformat()} +{window_days}d: "
                f"{len(completed)} finals (cache={meta.get('cached')})"
            )
            cursor = cursor.fromordinal(cursor.toordinal() + window_days)
        print(f"[enumerate] {season}: {seen} final rows seen")


def choose_games(con: sqlite3.Connection, max_games: int, per_season: int) -> list[tuple[str, str]]:
    selected: list[tuple[str, str]] = []
    for season, _, _ in SEASONS:
        rows = con.execute(
            """
            SELECT game_id, season
            FROM games
            WHERE season = ? AND status = 'final'
              AND (harvested_at IS NULL OR n_snapshots IS NULL)
            ORDER BY game_date, game_id
            LIMIT ?
            """,
            (season, per_season),
        ).fetchall()
        selected.extend((str(gid), str(season_name)) for gid, season_name in rows)
    if len(selected) > max_games:
        selected = selected[:max_games]
    return selected


def harvested_counts(con: sqlite3.Connection) -> tuple[int, int]:
    games = con.execute(
        "SELECT COUNT(*) FROM games WHERE harvested_at IS NOT NULL AND COALESCE(n_snapshots, 0) > 0"
    ).fetchone()[0]
    snaps = con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    return int(games), int(snaps)


def harvest(con: sqlite3.Connection, games: list[tuple[str, str]], sleep_seconds: float) -> None:
    total = len(games)
    for i, (game_id, season) in enumerate(games, start=1):
        try:
            summary = fetch_summary("nhl", game_id)
            snaps = snapshots_from_summary(summary, "nhl", game_id)
            now = datetime.now(timezone.utc).isoformat()
            con.execute("DELETE FROM snapshots WHERE game_id = ?", (game_id,))
            con.executemany(
                """
                INSERT INTO snapshots (
                    game_id, league, season, period, clock_seconds, frac_remaining,
                    home_score, away_score, margin, home_won, espn_home_wp, outs
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        s.game_id,
                        s.league,
                        season,
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
                    for s in snaps
                ],
            )
            con.execute(
                """
                UPDATE games
                SET harvested_at = ?, n_snapshots = ?, espn_wp_count = ?, error = NULL
                WHERE game_id = ?
                """,
                (now, len(snaps), sum(1 for s in snaps if s.espn_home_wp is not None), game_id),
            )
            con.commit()
            print(f"[harvest] {i}/{total} {game_id} {season}: {len(snaps)} snapshots")
        except Exception as exc:  # noqa: BLE001 - cache the failed attempt
            con.execute(
                "UPDATE games SET harvested_at = ?, n_snapshots = 0, espn_wp_count = 0, error = ? WHERE game_id = ?",
                (datetime.now(timezone.utc).isoformat(), f"{type(exc).__name__}: {exc}", game_id),
            )
            con.commit()
            print(f"[harvest] {i}/{total} {game_id} {season}: ERROR {type(exc).__name__}: {exc}")
        if sleep_seconds:
            time.sleep(sleep_seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-games", type=int, default=500)
    parser.add_argument("--per-season", type=int, default=250)
    parser.add_argument("--window-days", type=int, default=14)
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    args = parser.parse_args()

    with connect() as con:
        enumerate_completed_games(con, args.window_days)
        before_games, before_snaps = harvested_counts(con)
        games = choose_games(con, args.max_games, args.per_season)
        print(f"[plan] already harvested: {before_games} games / {before_snaps} snapshots")
        print(f"[plan] downloading {len(games)} additional games")
        harvest(con, games, args.sleep_seconds)
        after_games, after_snaps = harvested_counts(con)
        print(f"[done] harvested: {after_games} games / {after_snaps} snapshots in {DB_PATH}")


if __name__ == "__main__":
    main()
