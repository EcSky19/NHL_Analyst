import argparse
import csv
import json
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional


def normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in normalized.lower() if ch.isalnum())


def latest_file(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No files matched pattern {pattern} in {directory}")
    return matches[-1]


def pct(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def signed_streak(code: Optional[str], count: Optional[int]) -> Optional[int]:
    if code is None or count is None:
        return None
    if code.upper().startswith("W"):
        return int(count)
    return -int(count)


def subtract(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def load_standings(standings_path: Path) -> Dict[str, Dict[str, Any]]:
    payload = json.loads(standings_path.read_text(encoding="utf-8"))
    rows = payload.get("standings", [])

    by_abbrev: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        team_abbrev = row.get("teamAbbrev", {}).get("default")
        team_name = row.get("teamName", {}).get("default")
        if not team_abbrev or not team_name:
            continue

        games_played = row.get("gamesPlayed")
        goals_for = row.get("goalFor")
        goals_against = row.get("goalAgainst")
        goal_diff = row.get("goalDifferential")

        home_games = row.get("homeGamesPlayed")
        road_games = row.get("roadGamesPlayed")
        l10_games = row.get("l10GamesPlayed")

        team_features = {
            "team_abbrev": team_abbrev,
            "team_name": team_name,
            "season_id": row.get("seasonId"),
            "points_pct": row.get("pointPctg"),
            "goal_diff_per_game": safe_div(goal_diff, games_played),
            "goals_for_per_game": safe_div(goals_for, games_played),
            "goals_against_per_game": safe_div(goals_against, games_played),
            "home_points_pct": pct(row.get("homePoints"), (home_games or 0) * 2),
            "road_points_pct": pct(row.get("roadPoints"), (road_games or 0) * 2),
            "home_goal_diff_per_game": safe_div(row.get("homeGoalDifferential"), home_games),
            "road_goal_diff_per_game": safe_div(row.get("roadGoalDifferential"), road_games),
            "l10_points_pct": pct(row.get("l10Points"), (l10_games or 0) * 2),
            "l10_goal_diff_per_game": safe_div(row.get("l10GoalDifferential"), l10_games),
            "l10_goals_for_per_game": safe_div(row.get("l10GoalsFor"), l10_games),
            "l10_goals_against_per_game": safe_div(row.get("l10GoalsAgainst"), l10_games),
            "streak_signed": signed_streak(row.get("streakCode"), row.get("streakCount")),
            "streak_code": row.get("streakCode"),
            "streak_count": row.get("streakCount"),
        }

        team_features["trend_points_pct_l10_minus_season"] = subtract(
            team_features["l10_points_pct"], team_features["points_pct"]
        )
        team_features["trend_goal_diff_pg_l10_minus_season"] = subtract(
            team_features["l10_goal_diff_per_game"], team_features["goal_diff_per_game"]
        )
        team_features["trend_goals_for_pg_l10_minus_season"] = subtract(
            team_features["l10_goals_for_per_game"], team_features["goals_for_per_game"]
        )
        team_features["trend_goals_against_pg_season_minus_l10"] = subtract(
            team_features["goals_against_per_game"], team_features["l10_goals_against_per_game"]
        )

        by_abbrev[team_abbrev] = team_features
        by_name[normalize_name(team_name)] = team_features

    return {"by_abbrev": by_abbrev, "by_name": by_name}


def get_team_context(team: Dict[str, Any], standings_lookup: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    abbrev = team.get("abbreviation")
    name = team.get("displayName")
    if abbrev and abbrev in standings_lookup["by_abbrev"]:
        return standings_lookup["by_abbrev"][abbrev]
    if name:
        return standings_lookup["by_name"].get(normalize_name(name))
    return None


def add_prefixed_fields(record: Dict[str, Any], prefix: str, context: Dict[str, Any]) -> None:
    for key, value in context.items():
        record[f"{prefix}_{key}"] = value


def build_matchup_rows(scoreboard_path: Path, standings_lookup: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    scoreboard = json.loads(scoreboard_path.read_text(encoding="utf-8"))
    events = scoreboard.get("events", [])
    matchup_rows: List[Dict[str, Any]] = []

    for event in events:
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        competition = competitions[0]
        competitors = competition.get("competitors", [])
        home_comp = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away_comp = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home_comp or not away_comp:
            continue

        home_team = home_comp.get("team", {})
        away_team = away_comp.get("team", {})
        home_ctx = get_team_context(home_team, standings_lookup)
        away_ctx = get_team_context(away_team, standings_lookup)
        if not home_ctx or not away_ctx:
            continue

        venue = competition.get("venue", {})
        address = venue.get("address", {})
        neutral_site = bool(competition.get("neutralSite", False))

        row: Dict[str, Any] = {
            "game_id": event.get("id"),
            "game_date_utc": event.get("date"),
            "event_name": event.get("name"),
            "season_year": event.get("season", {}).get("year"),
            "home_team_abbrev": home_team.get("abbreviation"),
            "away_team_abbrev": away_team.get("abbreviation"),
            "home_indicator": 1,
            "is_neutral_site": 1 if neutral_site else 0,
            "venue_full_name": venue.get("fullName"),
            "venue_city": address.get("city"),
            "venue_state": address.get("state"),
            "venue_country": address.get("country"),
            "matchup_key": f"{event.get('date', '')}_{away_team.get('abbreviation', '')}_{home_team.get('abbreviation', '')}",
        }

        add_prefixed_fields(row, "home", home_ctx)
        add_prefixed_fields(row, "away", away_ctx)

        delta_fields = [
            "streak_signed",
            "points_pct",
            "goal_diff_per_game",
            "goals_for_per_game",
            "goals_against_per_game",
            "l10_points_pct",
            "l10_goal_diff_per_game",
            "l10_goals_for_per_game",
            "l10_goals_against_per_game",
            "trend_points_pct_l10_minus_season",
            "trend_goal_diff_pg_l10_minus_season",
            "trend_goals_for_pg_l10_minus_season",
            "trend_goals_against_pg_season_minus_l10",
        ]
        for field in delta_fields:
            row[f"delta_{field}_home_minus_away"] = subtract(row.get(f"home_{field}"), row.get(f"away_{field}"))

        row["home_vs_away_location_edge_points_pct"] = subtract(
            row.get("home_home_points_pct"), row.get("away_road_points_pct")
        )
        row["home_vs_away_location_edge_goal_diff_pg"] = subtract(
            row.get("home_home_goal_diff_per_game"), row.get("away_road_goal_diff_per_game")
        )

        matchup_rows.append(row)

    matchup_rows.sort(key=lambda r: (r["game_date_utc"] or "", r["game_id"] or ""))
    return matchup_rows


def infer_sql_type(value: Any) -> str:
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    return "TEXT"


def write_csv(rows: List[Dict[str, Any]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("No matchup rows generated from available files.")
    fieldnames = list(rows[0].keys())
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_sqlite_table(rows: List[Dict[str, Any]], sqlite_db: Path, table_name: str) -> None:
    con = sqlite3.connect(sqlite_db)
    cur = con.cursor()
    columns = rows[0].keys()
    column_defs = []
    first_row = rows[0]
    for col in columns:
        column_defs.append(f'"{col}" {infer_sql_type(first_row.get(col))}')

    cur.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    cur.execute(f'CREATE TABLE "{table_name}" ({", ".join(column_defs)})')

    placeholders = ", ".join(["?"] * len(columns))
    column_list = ", ".join([f'"{c}"' for c in columns])
    insert_sql = f'INSERT INTO "{table_name}" ({column_list}) VALUES ({placeholders})'
    cur.executemany(insert_sql, [[row.get(c) for c in columns] for row in rows])
    con.commit()
    con.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build contextual matchup features for NHL win-probability modeling.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--scoreboard", default=None, help="Path to ESPN scoreboard JSON. Defaults to data/raw/espn/scoreboard.json")
    parser.add_argument(
        "--standings",
        default=None,
        help="Path to standings JSON. Defaults to latest apiweb_standings_now_*.json in data/raw/nhl",
    )
    parser.add_argument(
        "--output-csv",
        default=None,
        help="Output CSV path. Defaults to data/processed/matchup_context_features.csv",
    )
    parser.add_argument("--sqlite-db", default=None, help="SQLite DB path. Defaults to data/processed/nhl_research.db")
    parser.add_argument("--table-name", default="matchup_context_features")
    parser.add_argument("--skip-sqlite", action="store_true", help="Skip SQLite table write")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    raw_espn = repo_root / "data" / "raw" / "espn"
    raw_nhl = repo_root / "data" / "raw" / "nhl"

    scoreboard_path = Path(args.scoreboard).resolve() if args.scoreboard else raw_espn / "scoreboard.json"
    standings_path = Path(args.standings).resolve() if args.standings else latest_file(raw_nhl, "apiweb_standings_now_*.json")
    output_csv = (
        Path(args.output_csv).resolve()
        if args.output_csv
        else repo_root / "data" / "processed" / "matchup_context_features.csv"
    )
    sqlite_db = Path(args.sqlite_db).resolve() if args.sqlite_db else repo_root / "data" / "processed" / "nhl_research.db"

    standings_lookup = load_standings(standings_path)
    rows = build_matchup_rows(scoreboard_path, standings_lookup)

    for row in rows:
        row["standings_source_file"] = standings_path.name
        row["scoreboard_source_file"] = scoreboard_path.name

    write_csv(rows, output_csv)
    if not args.skip_sqlite:
        write_sqlite_table(rows, sqlite_db, args.table_name)

    print(f"Wrote {len(rows)} rows to {output_csv}")
    if not args.skip_sqlite:
        print(f"Wrote SQLite table '{args.table_name}' in {sqlite_db}")


if __name__ == "__main__":
    main()
