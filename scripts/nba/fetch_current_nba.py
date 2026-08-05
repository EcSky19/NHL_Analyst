"""Fetch current NBA standings/team stats from permitted real sources.

Basketball-Reference is used only for robots-permitted /leagues/ pages and
cached under data/nba/raw so repeat runs do not refetch.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections import defaultdict
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "nba" / "nba_research.db"
RAW_DIR = ROOT / "data" / "nba" / "raw"
REPORT_PATH = ROOT / "data" / "reports" / "nba_current_season_report.md"

BREF_BASE = "https://www.basketball-reference.com"
BREF_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
WIKI_UA = "SportsAnalyticsResearch/1.0 (local provenance script)"
CRAWL_DELAY_SECONDS = 3.1
SEASONS = [(2024, "2023-24"), (2025, "2024-25"), (2026, "2025-26")]
CURRENT_SEASON_END_YEAR = 2026

TEAM_ABBREV = {
    "Atlanta Hawks": "ATL",
    "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU",
    "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL",
    "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA",
    "Washington Wizards": "WAS",
}

MONTHS_REGULAR_SEASON = [
    "october",
    "november",
    "december",
    "january",
    "february",
    "march",
    "april",
]
REGULAR_SEASON_END_DATES = {2026: datetime(2026, 4, 12).date()}
BREF_PLAYER_TEAM_ABBREV = {"BRK": "BKN", "CHO": "CHA", "PHO": "PHX"}

last_fetch_by_host: dict[str, float] = {}
urls_fetched: list[str] = []
urls_cached: list[str] = []


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_team_name(value: object) -> str:
    team = str(value).replace("\xa0", " ").strip()
    team = re.sub(r"[*†‡]+$", "", team).strip()
    team = re.sub(r"^(?:[a-z]{1,2}|pi)\s*[–—-]\s*", "", team, flags=re.I)
    return " ".join(team.split())


def fetch_cached(url: str, cache_name: str, user_agent: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / cache_name
    if cache_path.exists() and cache_path.stat().st_size > 0:
        urls_cached.append(url)
        return cache_path

    parsed = urlparse(url)
    if parsed.netloc == "www.basketball-reference.com":
        elapsed = time.monotonic() - last_fetch_by_host.get(parsed.netloc, 0.0)
        if elapsed < CRAWL_DELAY_SECONDS:
            time.sleep(CRAWL_DELAY_SECONDS - elapsed)

    req = Request(url, headers={"User-Agent": user_agent, "Accept": "text/html"})
    with urlopen(req, timeout=60) as response:
        cache_path.write_bytes(response.read())

    last_fetch_by_host[parsed.netloc] = time.monotonic()
    urls_fetched.append(url)
    return cache_path


def read_html_tables(path: Path) -> list[pd.DataFrame]:
    html = path.read_text(encoding="utf-8", errors="replace")
    html = html.replace("<!--", "").replace("-->", "")
    return pd.read_html(StringIO(html))


def to_int(value: object) -> int | None:
    try:
        if pd.isna(value):
            return None
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def to_float(value: object) -> float | None:
    try:
        if pd.isna(value):
            return None
        s = str(value).replace(",", "").strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [str(parts[-1] if parts[-1] and "Unnamed" not in str(parts[-1]) else parts[0]) for parts in df.columns]
    return df


def parse_standings(season_end_year: int, season_label: str, fetched_at: str) -> list[dict[str, object]]:
    standings_url = f"{BREF_BASE}/leagues/NBA_{season_end_year}_standings.html"
    path = fetch_cached(standings_url, f"NBA_{season_end_year}_standings.html", BREF_UA)
    tables = read_html_tables(path)
    if len(tables) < 5:
        raise RuntimeError(f"Expected standings tables not found in {standings_url}")

    divisions: dict[str, str] = {}
    for table_index, conference in [(2, "Eastern"), (3, "Western")]:
        df = tables[table_index]
        team_col = df.columns[0]
        current_division = None
        for _, row in df.iterrows():
            name = str(row[team_col]).strip()
            if "Division" in name:
                current_division = name
                continue
            team = clean_team_name(name)
            if team in TEAM_ABBREV and current_division:
                divisions[team] = current_division

    home_away: dict[str, dict[str, str | None]] = {}
    expanded = flatten_columns(tables[4])
    for _, row in expanded.iterrows():
        team = clean_team_name(row.get("Team"))
        if team in TEAM_ABBREV:
            home_away[team] = {
                "home_record": str(row.get("Home")) if pd.notna(row.get("Home")) else None,
                "away_record": str(row.get("Road")) if pd.notna(row.get("Road")) else None,
            }

    rows: list[dict[str, object]] = []
    for table_index, conference in [(0, "Eastern"), (1, "Western")]:
        df = tables[table_index]
        team_col = df.columns[0]
        for rank, (_, row) in enumerate(df.iterrows(), start=1):
            team = clean_team_name(row[team_col])
            if team not in TEAM_ABBREV:
                continue
            wins = to_int(row["W"])
            losses = to_int(row["L"])
            ppg_for = to_float(row["PS/G"])
            ppg_against = to_float(row["PA/G"])
            rows.append(
                {
                    "season": season_label,
                    "season_end_year": season_end_year,
                    "team_name": team,
                    "team_abbrev": TEAM_ABBREV[team],
                    "conference": conference,
                    "division": divisions.get(team),
                    "rank": rank,
                    "games_played": (wins or 0) + (losses or 0),
                    "wins": wins,
                    "losses": losses,
                    "win_pct": to_float(row["W/L%"]),
                    "games_behind": None if str(row["GB"]).strip() in {"—", "-", "nan"} else str(row["GB"]).strip(),
                    "points_for_per_game": ppg_for,
                    "points_against_per_game": ppg_against,
                    "points_for_total": None,
                    "points_against_total": None,
                    "home_record": home_away.get(team, {}).get("home_record"),
                    "away_record": home_away.get(team, {}).get("away_record"),
                    "streak": None,
                    "last10": None,
                    "data_source": standings_url,
                    "raw_html_path": str(path.relative_to(ROOT)),
                    "fetched_at_utc": fetched_at,
                    "crosscheck_status": None,
                }
            )
    return rows


def parse_point_totals(season_end_year: int) -> dict[str, dict[str, int | None]]:
    url = f"{BREF_BASE}/leagues/NBA_{season_end_year}.html"
    path = fetch_cached(url, f"NBA_{season_end_year}.html", BREF_UA)
    candidates: list[pd.DataFrame] = []
    for df in read_html_tables(path):
        cols = set(map(str, df.columns))
        if {"Team", "G", "PTS"}.issubset(cols):
            pts = pd.to_numeric(df["PTS"], errors="coerce")
            if pts.max(skipna=True) and pts.max(skipna=True) > 1000:
                candidates.append(df)
    if len(candidates) < 2:
        return {}
    totals: dict[str, dict[str, int | None]] = {}
    for source_df, key in [(candidates[0], "points_for_total"), (candidates[1], "points_against_total")]:
        for _, row in source_df.iterrows():
            team = clean_team_name(row["Team"])
            if team in TEAM_ABBREV:
                totals.setdefault(team, {})[key] = to_int(row["PTS"])
    return totals


def parse_team_stats(season_end_year: int, season_label: str, fetched_at: str) -> list[dict[str, object]]:
    url = f"{BREF_BASE}/leagues/NBA_{season_end_year}.html"
    path = fetch_cached(url, f"NBA_{season_end_year}.html", BREF_UA)
    tables = read_html_tables(path)
    table = None
    for df in tables:
        cols = set(map(str, df.columns))
        if {"Team", "G", "FG%", "3P%", "FT%", "TRB", "AST", "STL", "BLK", "TOV", "PTS"}.issubset(cols):
            table = df
            break
    if table is None:
        raise RuntimeError(f"Team per-game stats table not found in {url}")

    rows: list[dict[str, object]] = []
    for _, row in table.iterrows():
        team = clean_team_name(row["Team"])
        if team not in TEAM_ABBREV:
            continue
        rows.append(
            {
                "season": season_label,
                "season_end_year": season_end_year,
                "team_name": team,
                "team_abbrev": TEAM_ABBREV[team],
                "games": to_int(row["G"]),
                "points_per_game": to_float(row["PTS"]),
                "fg_pct": to_float(row["FG%"]),
                "threep_pct": to_float(row["3P%"]),
                "ft_pct": to_float(row["FT%"]),
                "rebounds_per_game": to_float(row["TRB"]),
                "assists_per_game": to_float(row["AST"]),
                "steals_per_game": to_float(row["STL"]),
                "blocks_per_game": to_float(row["BLK"]),
                "turnovers_per_game": to_float(row["TOV"]),
                "data_source": url,
                "raw_html_path": str(path.relative_to(ROOT)),
                "fetched_at_utc": fetched_at,
            }
        )
    return rows


def parse_player_leaders(fetched_at: str) -> list[dict[str, object]]:
    url = f"{BREF_BASE}/leagues/NBA_{CURRENT_SEASON_END_YEAR}_per_game.html"
    path = fetch_cached(url, f"NBA_{CURRENT_SEASON_END_YEAR}_per_game.html", BREF_UA)
    tables = read_html_tables(path)
    df = next((t for t in tables if {"Player", "Team", "G", "PTS", "TRB", "AST"}.issubset(set(map(str, t.columns)))), None)
    if df is None:
        return []
    df = df[df["Player"].astype(str) != "Player"].copy()
    rows: list[dict[str, object]] = []
    for stat, label in [("PTS", "points_per_game"), ("TRB", "rebounds_per_game"), ("AST", "assists_per_game")]:
        leader_df = df.copy()
        leader_df[stat] = pd.to_numeric(leader_df[stat], errors="coerce")
        leader_df = leader_df.dropna(subset=[stat]).sort_values(stat, ascending=False).head(25)
        for rank, (_, row) in enumerate(leader_df.iterrows(), start=1):
            rows.append(
                {
                    "season": "2025-26",
                    "season_end_year": CURRENT_SEASON_END_YEAR,
                    "stat_type": label,
                    "rank": rank,
                    "player_name": str(row["Player"]),
                    "team_abbrev": BREF_PLAYER_TEAM_ABBREV.get(str(row["Team"]), str(row["Team"])),
                    "games": to_int(row["G"]),
                    "stat_value": to_float(row[stat]),
                    "points_per_game": to_float(row.get("PTS")),
                    "rebounds_per_game": to_float(row.get("TRB")),
                    "assists_per_game": to_float(row.get("AST")),
                    "data_source": url,
                    "raw_html_path": str(path.relative_to(ROOT)),
                    "fetched_at_utc": fetched_at,
                }
            )
    return rows


def compute_current_last10_and_streak() -> dict[str, dict[str, str]]:
    games = []
    for month in MONTHS_REGULAR_SEASON:
        url = f"{BREF_BASE}/leagues/NBA_{CURRENT_SEASON_END_YEAR}_games-{month}.html"
        path = fetch_cached(url, f"NBA_{CURRENT_SEASON_END_YEAR}_games-{month}.html", BREF_UA)
        table = read_html_tables(path)[0]
        for _, row in table.iterrows():
            visitor = clean_team_name(row.get("Visitor/Neutral"))
            home = clean_team_name(row.get("Home/Neutral"))
            v_pts = to_int(row.get("PTS"))
            h_pts = to_int(row.get("PTS.1"))
            if visitor in TEAM_ABBREV and home in TEAM_ABBREV and v_pts is not None and h_pts is not None:
                try:
                    game_date = datetime.strptime(str(row["Date"]), "%a, %b %d, %Y")
                except ValueError:
                    continue
                if game_date.date() > REGULAR_SEASON_END_DATES[CURRENT_SEASON_END_YEAR]:
                    continue
                if str(row.get("Notes")).strip() == "NBA Cup" and game_date.date() == datetime(2025, 12, 16).date():
                    continue
                games.append((game_date, visitor, home, v_pts, h_pts))

    games.sort(key=lambda item: item[0])
    results: dict[str, list[str]] = defaultdict(list)
    for _, visitor, home, v_pts, h_pts in games:
        visitor_won = v_pts > h_pts
        results[visitor].append("W" if visitor_won else "L")
        results[home].append("L" if visitor_won else "W")

    summary: dict[str, dict[str, str]] = {}
    for team, outcomes in results.items():
        if len(outcomes) != 82:
            continue
        last10 = outcomes[-10:]
        last = outcomes[-1]
        count = 0
        for outcome in reversed(outcomes):
            if outcome == last:
                count += 1
            else:
                break
        summary[team] = {"last10": f"{last10.count('W')}-{last10.count('L')}", "streak": f"{last}{count}"}
    return summary


def wiki_crosscheck(fetched_at: str) -> tuple[dict[str, int], str]:
    url = "https://en.wikipedia.org/api/rest_v1/page/html/2025%E2%80%9326_NBA_season"
    path = fetch_cached(url, "wikipedia_2025-26_NBA_season.html", WIKI_UA)
    wins: dict[str, int] = {}
    for df in read_html_tables(path):
        cols = list(map(str, df.columns))
        if "W" not in cols or "L" not in cols:
            continue
        team_col = next((c for c in df.columns if "Division" in str(c)), None)
        if team_col is None:
            continue
        for _, row in df.iterrows():
            team = clean_team_name(row[team_col])
            if team in TEAM_ABBREV:
                wins[team] = to_int(row["W"]) or -1
    status = f"Wikipedia REST page cached/fetched at {fetched_at}; parsed {len(wins)} team win totals."
    return wins, status


def open_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(8):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            return conn
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 7:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def execute_with_retry(conn: sqlite3.Connection, sql: str, params: list[dict[str, object]] | None = None) -> None:
    for attempt in range(8):
        try:
            if params is None:
                conn.execute(sql)
            else:
                conn.executemany(sql, params)
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 7:
                raise
            time.sleep(0.5 * (attempt + 1))


def create_tables(conn: sqlite3.Connection) -> None:
    execute_with_retry(
        conn,
        """
        CREATE TABLE IF NOT EXISTS nba_current_standings (
            season TEXT NOT NULL,
            season_end_year INTEGER NOT NULL,
            team_name TEXT NOT NULL,
            team_abbrev TEXT NOT NULL,
            conference TEXT,
            division TEXT,
            rank INTEGER,
            games_played INTEGER,
            wins INTEGER,
            losses INTEGER,
            win_pct REAL,
            games_behind TEXT,
            points_for_per_game REAL,
            points_against_per_game REAL,
            points_for_total INTEGER,
            points_against_total INTEGER,
            home_record TEXT,
            away_record TEXT,
            streak TEXT,
            last10 TEXT,
            data_source TEXT NOT NULL,
            raw_html_path TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            crosscheck_status TEXT,
            PRIMARY KEY (season, team_abbrev)
        )
        """,
    )
    execute_with_retry(
        conn,
        """
        CREATE TABLE IF NOT EXISTS nba_current_team_stats (
            season TEXT NOT NULL,
            season_end_year INTEGER NOT NULL,
            team_name TEXT NOT NULL,
            team_abbrev TEXT NOT NULL,
            games INTEGER,
            points_per_game REAL,
            fg_pct REAL,
            threep_pct REAL,
            ft_pct REAL,
            rebounds_per_game REAL,
            assists_per_game REAL,
            steals_per_game REAL,
            blocks_per_game REAL,
            turnovers_per_game REAL,
            data_source TEXT NOT NULL,
            raw_html_path TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (season, team_abbrev)
        )
        """,
    )
    execute_with_retry(
        conn,
        """
        CREATE TABLE IF NOT EXISTS nba_current_player_stats (
            season TEXT NOT NULL,
            season_end_year INTEGER NOT NULL,
            stat_type TEXT NOT NULL,
            rank INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            team_abbrev TEXT,
            games INTEGER,
            stat_value REAL,
            points_per_game REAL,
            rebounds_per_game REAL,
            assists_per_game REAL,
            data_source TEXT NOT NULL,
            raw_html_path TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (season, stat_type, rank)
        )
        """,
    )


def upsert_rows(conn: sqlite3.Connection, table: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    placeholders = ", ".join(":" + c for c in cols)
    update_cols = [c for c in cols if c not in {"season", "team_abbrev", "stat_type", "rank"}]
    updates = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT DO UPDATE SET {updates}"
    execute_with_retry(conn, sql, rows)


def validate(conn: sqlite3.Connection) -> dict[str, object]:
    cur = conn.cursor()
    validation = {
        "standings_counts": cur.execute("SELECT season, COUNT(*) FROM nba_current_standings GROUP BY season ORDER BY season").fetchall(),
        "team_stats_counts": cur.execute("SELECT season, COUNT(*) FROM nba_current_team_stats GROUP BY season ORDER BY season").fetchall(),
        "player_stats_count": cur.execute("SELECT COUNT(*) FROM nba_current_player_stats WHERE season='2025-26'").fetchone()[0],
        "conference_counts_2026": cur.execute(
            "SELECT conference, COUNT(*) FROM nba_current_standings WHERE season='2025-26' GROUP BY conference ORDER BY conference"
        ).fetchall(),
        "bad_games_2026": cur.execute(
            "SELECT team_name, wins, losses FROM nba_current_standings WHERE season='2025-26' AND wins + losses != 82"
        ).fetchall(),
        "league_totals_2026": cur.execute(
            "SELECT SUM(wins), SUM(losses) FROM nba_current_standings WHERE season='2025-26'"
        ).fetchone(),
        "top_teams_2026": cur.execute(
            "SELECT team_name, wins, losses, conference FROM nba_current_standings WHERE season='2025-26' ORDER BY wins DESC, losses ASC LIMIT 5"
        ).fetchall(),
    }
    return validation


def write_report(validation: dict[str, object], wiki_status: str, wiki_mismatches: list[str]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "# NBA current-season data source report",
        "",
        f"Generated at: {utc_now()}",
        "",
        "## Scope and coverage",
        "",
        "- Real source only; no synthetic or placeholder-filled NBA rows were generated.",
        "- Basketball-Reference current/gap coverage captured: 2023-24, 2024-25, and 2025-26.",
        "- hoopR-data still ends at season 2023; this script closes the 2023-24 and 2024-25 standings/team-stat gap with Basketball-Reference `/leagues/` pages and covers the most recently completed 2025-26 season.",
        "- 2025-26 final last-10 and streak were computed from permitted Basketball-Reference `/leagues/NBA_2026_games-<month>.html` regular-season schedule pages through April 12, excluding the non-standings NBA Cup championship game.",
        "",
        "## Robots and crawl-delay compliance",
        "",
        f"- Basketball-Reference `/leagues/` pages are robots-permitted for `User-agent: *`; disallowed gamelog/splits/on-off/lineups/shooting paths were not requested.",
        f"- Implemented per-host crawl delay of at least {CRAWL_DELAY_SECONDS:.1f} seconds before uncached Basketball-Reference requests.",
        "- Raw HTML is cached under `data\\nba\\raw\\`; cached files are reused on rerun with no network request.",
        "",
        "## URLs fetched this run",
        "",
    ]
    if urls_fetched:
        rows.extend(f"- {url}" for url in urls_fetched)
    else:
        rows.append("- None; all source pages were served from local cache.")
    rows.extend(["", "## URLs served from cache", ""])
    rows.extend(f"- {url}" for url in sorted(set(urls_cached))[:50])
    rows.extend(
        [
            "",
            "## Validation",
            "",
            f"- Standings row counts by season: {validation['standings_counts']}",
            f"- Team-stat row counts by season: {validation['team_stats_counts']}",
            f"- 2025-26 player leader rows: {validation['player_stats_count']}",
            f"- 2025-26 conference counts: {validation['conference_counts_2026']}",
            f"- 2025-26 teams with wins+losses != 82: {validation['bad_games_2026']}",
            f"- 2025-26 league win/loss totals: {validation['league_totals_2026']}",
            f"- 2025-26 top teams: {validation['top_teams_2026']}",
            "",
            "## Wikipedia cross-check",
            "",
            f"- {wiki_status}",
            f"- Result: {'PASS' if not wiki_mismatches else 'MISMATCH'}",
        ]
    )
    rows.extend([f"  - {item}" for item in wiki_mismatches] if wiki_mismatches else ["  - All 30 parsed Wikipedia win totals matched Basketball-Reference."])
    REPORT_PATH.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> None:
    fetched_at = utc_now()
    standings_rows: list[dict[str, object]] = []
    team_stat_rows: list[dict[str, object]] = []
    point_totals_by_season: dict[int, dict[str, dict[str, int | None]]] = {}
    for season_end_year, season_label in SEASONS:
        standings_rows.extend(parse_standings(season_end_year, season_label, fetched_at))
        team_stat_rows.extend(parse_team_stats(season_end_year, season_label, fetched_at))
        point_totals_by_season[season_end_year] = parse_point_totals(season_end_year)

    last10_streak = compute_current_last10_and_streak()
    for row in standings_rows:
        if row["season_end_year"] == CURRENT_SEASON_END_YEAR:
            summary = last10_streak.get(str(row["team_name"]), {})
            row["last10"] = summary.get("last10")
            row["streak"] = summary.get("streak")
        totals = point_totals_by_season.get(int(row["season_end_year"]), {}).get(str(row["team_name"]), {})
        row["points_for_total"] = totals.get("points_for_total")
        row["points_against_total"] = totals.get("points_against_total")

    wiki_wins, wiki_status = wiki_crosscheck(fetched_at)
    wiki_mismatches = []
    for row in standings_rows:
        if row["season_end_year"] != CURRENT_SEASON_END_YEAR:
            continue
        team = str(row["team_name"])
        if wiki_wins.get(team) != row["wins"]:
            wiki_mismatches.append(f"{team}: Basketball-Reference W={row['wins']}, Wikipedia W={wiki_wins.get(team)}")
    cross_status = "wikipedia_win_total_match_all_30" if not wiki_mismatches and len(wiki_wins) == 30 else "wikipedia_win_total_mismatch_or_incomplete"
    for row in standings_rows:
        if row["season_end_year"] == CURRENT_SEASON_END_YEAR:
            row["crosscheck_status"] = cross_status

    player_rows = parse_player_leaders(fetched_at)

    conn = open_db()
    try:
        create_tables(conn)
        upsert_rows(conn, "nba_current_standings", standings_rows)
        upsert_rows(conn, "nba_current_team_stats", team_stat_rows)
        upsert_rows(conn, "nba_current_player_stats", player_rows)
        validation = validate(conn)
    finally:
        conn.close()

    write_report(validation, wiki_status, wiki_mismatches)
    print(f"Wrote {len(standings_rows)} standings rows, {len(team_stat_rows)} team-stat rows, {len(player_rows)} player leader rows.")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
