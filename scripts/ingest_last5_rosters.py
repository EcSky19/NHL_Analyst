import argparse
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


BOXCORE_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
RAW_SUBDIR = "gamecenter_boxscores_last5"
PLAYER_GROUPS = ("forwards", "defense", "goalies")


@dataclass
class GameFetchResult:
    game_id: int
    season: int
    success: bool
    error: Optional[str]
    roster_rows: List[Dict[str, Any]]
    stat_rows: List[Dict[str, Any]]


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


def canonical_abbrev(team_abbrev: Optional[str], alias_map: Dict[str, str]) -> str:
    normalized = (team_abbrev or "").strip().upper()
    return alias_map.get(normalized, normalized)


def toi_to_seconds(toi_value: Optional[str]) -> Optional[int]:
    if not toi_value:
        return None
    try:
        minutes, seconds = toi_value.split(":")
        return int(minutes) * 60 + int(seconds)
    except Exception:
        return None


def read_games(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT season, game_id
        FROM historical_games_last5
        WHERE is_final = 1 AND game_type = '2'
        ORDER BY season, game_date, game_id
        """
    ).fetchall()
    return [{"season": int(season), "game_id": int(game_id)} for season, game_id in rows]


def fetch_boxscore(session: requests.Session, game_id: int, retries: int = 4) -> Dict[str, Any]:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(BOXCORE_URL.format(game_id=game_id), timeout=30)
            if response.status_code == 404:
                raise RuntimeError("HTTP 404")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"boxscore fetch failed after retries: {last_err}")


def player_name_from_payload(player: Dict[str, Any]) -> str:
    name_blob = player.get("name")
    if isinstance(name_blob, dict):
        return str(name_blob.get("default") or name_blob.get("fr") or "").strip()
    return str(name_blob or "").strip()


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
            starter_flag = player.get("starter")
            starter_goalie_api_flag = (
                1 if bool(starter_flag) else 0 if starter_flag is not None else None
            )
            is_starter_goalie = int(starter_goalie_api_flag or 0)
            toi_raw = player.get("toi")
            toi_seconds = toi_to_seconds(toi_raw)
            player_status = player.get("status")
            played = 1 if toi_seconds and toi_seconds > 0 else 0

            roster_rows.append(
                {
                    "game_id": game_id,
                    "season": season,
                    "team_abbrev": team_abbrev,
                    "player_id": int(player_id),
                    "player_name": player_name_from_payload(player),
                    "position": position,
                    "is_goalie": is_goalie,
                    "is_starter_goalie": is_starter_goalie,
                    "starter_goalie_api_flag": starter_goalie_api_flag,
                    "starter_goalie_source": None,
                    "starter_goalie_confidence": None,
                    "home_away": home_away,
                    "player_status": str(player_status) if player_status is not None else None,
                    "game_state": game_state,
                    "game_schedule_state": game_schedule_state,
                    "played": played,
                    "sweater_number": player.get("sweaterNumber"),
                    "fetched_at_utc": fetched_at_utc,
                }
            )

            stat_rows.append(
                {
                    "game_id": game_id,
                    "season": season,
                    "team_abbrev": team_abbrev,
                    "player_id": int(player_id),
                    "player_name": player_name_from_payload(player),
                    "position": position,
                    "is_goalie": is_goalie,
                    "home_away": home_away,
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
                    "starter_goalie_api_flag": starter_goalie_api_flag,
                    "starter_goalie_source": None,
                    "starter_goalie_confidence": None,
                    "fetched_at_utc": fetched_at_utc,
                }
            )

    return roster_rows, stat_rows


def apply_goalie_starter_inference(roster_rows: List[Dict[str, Any]], stat_rows: List[Dict[str, Any]]) -> None:
    goalie_rows = [r for r in roster_rows if int(r.get("is_goalie") or 0) == 1]
    if not goalie_rows:
        return

    stat_by_player = {int(s["player_id"]): s for s in stat_rows if int(s.get("is_goalie") or 0) == 1}

    def rank_key(row: Dict[str, Any]) -> Tuple[int, int, int, int]:
        player_id = int(row["player_id"])
        stat = stat_by_player.get(player_id, {})
        played = int(row.get("played") or 0)
        toi_seconds = int(stat.get("toi_seconds") or 0)
        shots_against = int(stat.get("shots_against") or 0)
        return (played, toi_seconds, shots_against, -player_id)

    api_confirmed = [r for r in goalie_rows if int(r.get("starter_goalie_api_flag") or 0) == 1]
    chosen: Optional[Dict[str, Any]] = None
    source: Optional[str] = None
    confidence: Optional[float] = None

    if len(api_confirmed) == 1:
        chosen = api_confirmed[0]
        source = "api_flag"
        confidence = 1.0
    elif len(api_confirmed) > 1:
        chosen = max(api_confirmed, key=rank_key)
        source = "api_flag_conflict_resolved"
        confidence = 0.75
    else:
        played_goalies = [r for r in goalie_rows if int(r.get("played") or 0) == 1]
        with_toi = [r for r in played_goalies if int(stat_by_player.get(int(r["player_id"]), {}).get("toi_seconds") or 0) > 0]
        with_shots = [
            r
            for r in played_goalies
            if int(stat_by_player.get(int(r["player_id"]), {}).get("shots_against") or 0) > 0
        ]
        if with_toi:
            chosen = max(with_toi, key=rank_key)
            source = "inferred_played_toi"
            confidence = 0.9
        elif with_shots:
            chosen = max(with_shots, key=rank_key)
            source = "inferred_played_shots_against"
            confidence = 0.8
        elif played_goalies:
            chosen = max(played_goalies, key=rank_key)
            source = "inferred_played_fallback"
            confidence = 0.65
        else:
            chosen = max(goalie_rows, key=lambda r: -int(r["player_id"]))
            source = "inferred_roster_fallback"
            confidence = 0.5

    chosen_player_id = int(chosen["player_id"]) if chosen else None
    for roster_row in goalie_rows:
        player_id = int(roster_row["player_id"])
        is_selected = 1 if chosen_player_id is not None and player_id == chosen_player_id else 0
        roster_row["is_starter_goalie"] = is_selected
        roster_row["starter_goalie_source"] = source
        roster_row["starter_goalie_confidence"] = confidence if is_selected == 1 else 0.0

    for stat_row in stat_rows:
        if int(stat_row.get("is_goalie") or 0) != 1:
            continue
        player_id = int(stat_row["player_id"])
        is_selected = 1 if chosen_player_id is not None and player_id == chosen_player_id else 0
        stat_row["is_starter_goalie"] = is_selected
        stat_row["starter_goalie_source"] = source
        stat_row["starter_goalie_confidence"] = confidence if is_selected == 1 else 0.0


def fetch_and_transform_game(
    *,
    game_id: int,
    season: int,
    alias_map: Dict[str, str],
    raw_dir: Path,
    fetched_at_utc: str,
) -> GameFetchResult:
    session = requests.Session()
    session.headers.update({"User-Agent": "SportsAnalyticsRosterIngest/1.0"})
    try:
        payload = fetch_boxscore(session, game_id=game_id)
    except Exception as exc:
        return GameFetchResult(
            game_id=game_id,
            season=season,
            success=False,
            error=str(exc),
            roster_rows=[],
            stat_rows=[],
        )
    finally:
        session.close()

    output_path = raw_dir / f"boxscore_{season}_{game_id}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    player_stats = payload.get("playerByGameStats") or {}
    away_players = (player_stats.get("awayTeam") or {})
    home_players = (player_stats.get("homeTeam") or {})
    away_team_abbrev = canonical_abbrev((payload.get("awayTeam") or {}).get("abbrev"), alias_map)
    home_team_abbrev = canonical_abbrev((payload.get("homeTeam") or {}).get("abbrev"), alias_map)
    game_state = (payload.get("gameState") or "").upper() or None
    game_schedule_state = (payload.get("gameScheduleState") or "").upper() or None

    away_roster, away_stats = parse_team_rows(
        game_id=game_id,
        season=season,
        home_away="away",
        team_abbrev=away_team_abbrev,
        players_by_group=away_players,
        game_state=game_state,
        game_schedule_state=game_schedule_state,
        fetched_at_utc=fetched_at_utc,
    )
    home_roster, home_stats = parse_team_rows(
        game_id=game_id,
        season=season,
        home_away="home",
        team_abbrev=home_team_abbrev,
        players_by_group=home_players,
        game_state=game_state,
        game_schedule_state=game_schedule_state,
        fetched_at_utc=fetched_at_utc,
    )
    apply_goalie_starter_inference(away_roster, away_stats)
    apply_goalie_starter_inference(home_roster, home_stats)

    roster_rows = away_roster + home_roster
    stat_rows = away_stats + home_stats
    if not roster_rows:
        return GameFetchResult(
            game_id=game_id,
            season=season,
            success=False,
            error="empty roster rows",
            roster_rows=[],
            stat_rows=[],
        )

    return GameFetchResult(
        game_id=game_id,
        season=season,
        success=True,
        error=None,
        roster_rows=roster_rows,
        stat_rows=stat_rows,
    )


def refresh_tables(conn: sqlite3.Connection, roster_rows: List[Dict[str, Any]], stat_rows: List[Dict[str, Any]]) -> None:
    conn.execute("DROP TABLE IF EXISTS historical_game_rosters")
    conn.execute(
        """
        CREATE TABLE historical_game_rosters (
            game_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            team_abbrev TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            player_name TEXT,
            position TEXT,
            is_goalie INTEGER,
            is_starter_goalie INTEGER,
            starter_goalie_api_flag INTEGER,
            starter_goalie_source TEXT,
            starter_goalie_confidence REAL,
            home_away TEXT NOT NULL,
            player_status TEXT,
            game_state TEXT,
            game_schedule_state TEXT,
            played INTEGER,
            sweater_number INTEGER,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (game_id, team_abbrev, player_id)
        )
        """
    )
    conn.execute("DROP TABLE IF EXISTS historical_player_game_stats")
    conn.execute(
        """
        CREATE TABLE historical_player_game_stats (
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
            starter_goalie_api_flag INTEGER,
            starter_goalie_source TEXT,
            starter_goalie_confidence REAL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (game_id, team_abbrev, player_id)
        )
        """
    )

    conn.executemany(
        """
        INSERT INTO historical_game_rosters (
            game_id, season, team_abbrev, player_id, player_name, position, is_goalie,
            is_starter_goalie, starter_goalie_api_flag, starter_goalie_source, starter_goalie_confidence,
            home_away, player_status, game_state, game_schedule_state,
            played, sweater_number, fetched_at_utc
        ) VALUES (
            :game_id, :season, :team_abbrev, :player_id, :player_name, :position, :is_goalie,
            :is_starter_goalie, :starter_goalie_api_flag, :starter_goalie_source, :starter_goalie_confidence,
            :home_away, :player_status, :game_state, :game_schedule_state,
            :played, :sweater_number, :fetched_at_utc
        )
        """,
        roster_rows,
    )

    conn.executemany(
        """
        INSERT INTO historical_player_game_stats (
            game_id, season, team_abbrev, player_id, player_name, position, is_goalie, home_away,
            toi, toi_seconds, goals, assists, points, plus_minus, pim, hits, power_play_goals, sog,
            faceoff_winning_pctg, blocked_shots, shifts, giveaways, takeaways, goals_against,
            shots_against, saves, save_shots_against, even_strength_shots_against,
            power_play_shots_against, shorthanded_shots_against, even_strength_goals_against,
            power_play_goals_against, shorthanded_goals_against, is_starter_goalie,
            starter_goalie_api_flag, starter_goalie_source, starter_goalie_confidence, fetched_at_utc
        ) VALUES (
            :game_id, :season, :team_abbrev, :player_id, :player_name, :position, :is_goalie, :home_away,
            :toi, :toi_seconds, :goals, :assists, :points, :plus_minus, :pim, :hits, :power_play_goals, :sog,
            :faceoff_winning_pctg, :blocked_shots, :shifts, :giveaways, :takeaways, :goals_against,
            :shots_against, :saves, :save_shots_against, :even_strength_shots_against,
            :power_play_shots_against, :shorthanded_shots_against, :even_strength_goals_against,
            :power_play_goals_against, :shorthanded_goals_against, :is_starter_goalie,
            :starter_goalie_api_flag, :starter_goalie_source, :starter_goalie_confidence, :fetched_at_utc
        )
        """,
        stat_rows,
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_historical_game_rosters_season ON historical_game_rosters (season, team_abbrev)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_historical_player_game_stats_season ON historical_player_game_stats (season, team_abbrev)"
    )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest last-five-season NHL game roster participation and player game stats."
    )
    parser.add_argument("--repo-root", default=None, help="Repository root; defaults to script parent parent")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent fetch workers")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parent.parent
    sqlite_db = repo_root / "data" / "processed" / "nhl_research.db"
    raw_dir = repo_root / "data" / "raw" / "nhl" / RAW_SUBDIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    fetched_at_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    with sqlite3.connect(sqlite_db) as con:
        alias_map = load_alias_map(con)
        games = read_games(con)

    expected_by_season: Dict[int, int] = {}
    for game in games:
        expected_by_season[game["season"]] = expected_by_season.get(game["season"], 0) + 1

    results: List[GameFetchResult] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(
                fetch_and_transform_game,
                game_id=game["game_id"],
                season=game["season"],
                alias_map=alias_map,
                raw_dir=raw_dir,
                fetched_at_utc=fetched_at_utc,
            )
            for game in games
        ]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda r: (r.season, r.game_id))
    failed = [r for r in results if not r.success]
    successful = [r for r in results if r.success]
    roster_rows = [row for r in successful for row in r.roster_rows]
    stat_rows = [row for r in successful for row in r.stat_rows]

    with sqlite3.connect(sqlite_db) as con:
        refresh_tables(con, roster_rows=roster_rows, stat_rows=stat_rows)

        actual_by_season = {
            int(season): int(count)
            for season, count in con.execute(
                """
                SELECT season, COUNT(DISTINCT game_id)
                FROM historical_game_rosters
                GROUP BY season
                ORDER BY season
                """
            ).fetchall()
        }
        roster_games = con.execute("SELECT COUNT(DISTINCT game_id) FROM historical_game_rosters").fetchone()[0]
        stats_games = con.execute("SELECT COUNT(DISTINCT game_id) FROM historical_player_game_stats").fetchone()[0]
        roster_rows_count = con.execute("SELECT COUNT(*) FROM historical_game_rosters").fetchone()[0]
        stats_rows_count = con.execute("SELECT COUNT(*) FROM historical_player_game_stats").fetchone()[0]

    missing_by_season: Dict[int, int] = {}
    for season, expected_count in expected_by_season.items():
        got = actual_by_season.get(season, 0)
        if got != expected_count:
            missing_by_season[season] = expected_count - got

    diagnostics = {
        "fetched_at_utc": fetched_at_utc,
        "expected_games": len(games),
        "successful_games": len(successful),
        "failed_games": len(failed),
        "historical_game_rosters_distinct_games": roster_games,
        "historical_player_game_stats_distinct_games": stats_games,
        "historical_game_rosters_rows": roster_rows_count,
        "historical_player_game_stats_rows": stats_rows_count,
        "expected_by_season": expected_by_season,
        "covered_by_season": actual_by_season,
        "missing_by_season": missing_by_season,
        "failed_games": [{"game_id": r.game_id, "season": r.season, "error": r.error} for r in failed],
    }
    diagnostics_path = raw_dir / f"ingest_diagnostics_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    diagnostics_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")

    print(f"expected_games={len(games)}")
    print(f"successful_games={len(successful)}")
    print(f"failed_games={len(failed)}")
    print(f"historical_game_rosters_distinct_games={roster_games}")
    print(f"historical_player_game_stats_distinct_games={stats_games}")
    print(f"historical_game_rosters_rows={roster_rows_count}")
    print(f"historical_player_game_stats_rows={stats_rows_count}")
    print(f"missing_by_season={json.dumps(missing_by_season, sort_keys=True)}")
    print(f"diagnostics_json={diagnostics_path}")


if __name__ == "__main__":
    main()
