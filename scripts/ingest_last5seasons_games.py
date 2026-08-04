import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests


SEASON_CATALOG_URL = "https://api.nhle.com/stats/rest/en/season"
SCHEDULE_BY_DATE_URL = "https://api-web.nhle.com/v1/schedule/{date}"
COMPLETED_GAME_STATES = {"OFF", "FINAL"}


def fetch_json(url: str) -> Dict[str, Any]:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def determine_last_completed_regular_seasons(now_utc: datetime, count: int = 5) -> List[Dict[str, Any]]:
    payload = fetch_json(SEASON_CATALOG_URL)
    seasons = payload.get("data", [])
    completed = []
    for season in seasons:
        season_id = season.get("id")
        reg_end = season.get("regularSeasonEndDate")
        if not season_id or not reg_end:
            continue
        reg_end_dt = datetime.fromisoformat(reg_end)
        if reg_end_dt <= now_utc:
            completed.append(season)
    completed.sort(key=lambda s: s["id"], reverse=True)
    return completed[:count]


def load_alias_map(sqlite_db: Path) -> Dict[str, str]:
    alias_to_canonical: Dict[str, str] = {}
    with sqlite3.connect(sqlite_db) as con:
        cur = con.execute("SELECT canonical_abbrev, alias_abbrevs FROM team_alias_map")
        for canonical_abbrev, alias_abbrevs in cur.fetchall():
            canonical = (canonical_abbrev or "").strip().upper()
            if not canonical:
                continue
            for alias in (alias_abbrevs or "").split("|"):
                token = alias.strip().upper()
                if token:
                    alias_to_canonical[token] = canonical
            alias_to_canonical[canonical] = canonical
    return alias_to_canonical


def canonical_abbrev(abbrev: str, alias_map: Dict[str, str]) -> str:
    key = (abbrev or "").strip().upper()
    return alias_map.get(key, key)


def pull_regular_completed_games_for_season(
    season_id: int,
    season_start: str,
    regular_season_end: str,
    alias_map: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    raw_weeks: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    seen_ids = set()
    next_date = season_start
    end_date = regular_season_end

    while next_date and next_date <= end_date:
        payload = fetch_json(SCHEDULE_BY_DATE_URL.format(date=next_date))
        raw_weeks.append(payload)
        for game_day in payload.get("gameWeek", []):
            game_day_date = game_day.get("date")
            for game in game_day.get("games", []):
                if game.get("season") != season_id:
                    continue
                if game.get("gameType") != 2:
                    continue
                game_state = (game.get("gameState") or "").upper()
                if game_state not in COMPLETED_GAME_STATES:
                    continue
                game_id = game.get("id")
                if game_id in seen_ids:
                    continue
                away = game.get("awayTeam") or {}
                home = game.get("homeTeam") or {}
                away_goals = away.get("score")
                home_goals = home.get("score")
                if away_goals is None or home_goals is None:
                    continue

                home_abbrev = canonical_abbrev(home.get("abbrev", ""), alias_map)
                away_abbrev = canonical_abbrev(away.get("abbrev", ""), alias_map)
                winner = home_abbrev if int(home_goals) > int(away_goals) else away_abbrev

                game_date = game.get("gameDate") or game_day_date
                if not game_date:
                    continue

                rows.append(
                    {
                        "season": season_id,
                        "game_id": int(game_id),
                        "game_date": game_date,
                        "home_team_abbrev": home_abbrev,
                        "away_team_abbrev": away_abbrev,
                        "home_goals": int(home_goals),
                        "away_goals": int(away_goals),
                        "winner_abbrev": winner,
                        "game_type": str(game.get("gameType")),
                        "status": game_state,
                        "is_final": 1,
                    }
                )
                seen_ids.add(game_id)
        next_date = payload.get("nextStartDate")

    return raw_weeks, rows


def persist_raw_json(raw_dir: Path, filename: str, payload: Dict[str, Any]) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_dir / filename
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def refresh_historical_table(sqlite_db: Path, rows: List[Dict[str, Any]]) -> None:
    sqlite_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(sqlite_db) as con:
        con.execute("DROP TABLE IF EXISTS historical_games_last5")
        con.execute(
            """
            CREATE TABLE historical_games_last5 (
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
                is_final INTEGER NOT NULL
            )
            """
        )
        con.executemany(
            """
            INSERT INTO historical_games_last5 (
                season, game_id, game_date, home_team_abbrev, away_team_abbrev,
                home_goals, away_goals, winner_abbrev, game_type, status, is_final
            ) VALUES (
                :season, :game_id, :game_date, :home_team_abbrev, :away_team_abbrev,
                :home_goals, :away_goals, :winner_abbrev, :game_type, :status, :is_final
            )
            """,
            rows,
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_historical_games_last5_season ON historical_games_last5(season)")
        con.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest completed regular-season NHL games for last five completed seasons.")
    parser.add_argument("--repo-root", default=None, help="Repository root. Defaults to script parent parent.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parent.parent
    raw_dir = repo_root / "data" / "raw" / "nhl"
    sqlite_db = repo_root / "data" / "processed" / "nhl_research.db"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    now_utc = datetime.now(UTC).replace(tzinfo=None)
    last_five = determine_last_completed_regular_seasons(now_utc, count=5)
    seasons_selected = [season["id"] for season in last_five]

    season_catalog_payload = fetch_json(SEASON_CATALOG_URL)
    persist_raw_json(raw_dir, f"season_catalog_{timestamp}.json", season_catalog_payload)

    alias_map = load_alias_map(sqlite_db)
    all_rows: List[Dict[str, Any]] = []
    season_payload_index: Dict[str, Any] = {"fetched_at_utc": timestamp, "selected_seasons": seasons_selected, "seasons": {}}

    for season in last_five:
        season_id = int(season["id"])
        season_start = season["startDate"][:10]
        reg_end = season["regularSeasonEndDate"][:10]
        raw_weeks, rows = pull_regular_completed_games_for_season(
            season_id=season_id,
            season_start=season_start,
            regular_season_end=reg_end,
            alias_map=alias_map,
        )
        all_rows.extend(rows)
        season_payload_index["seasons"][str(season_id)] = {
            "regular_season_start": season_start,
            "regular_season_end": reg_end,
            "week_payload_count": len(raw_weeks),
            "completed_regular_games": len(rows),
            "payloads": raw_weeks,
        }

    deduped = {row["game_id"]: row for row in all_rows}
    final_rows = sorted(deduped.values(), key=lambda r: (r["season"], r["game_date"], r["game_id"]))
    refresh_historical_table(sqlite_db, final_rows)
    persist_raw_json(raw_dir, f"apiweb_regularseason_games_last5_{timestamp}.json", season_payload_index)

    print(f"selected_seasons={seasons_selected}")
    print(f"rows_inserted={len(final_rows)}")
    print("table_refreshed=historical_games_last5")


if __name__ == "__main__":
    main()
