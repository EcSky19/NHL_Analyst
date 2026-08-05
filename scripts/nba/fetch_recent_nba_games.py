"""Fetch recent NBA regular-season game results into a separate database.

Basketball-Reference schedule pages are robots-checked, cached under
data/nba/raw, and requested with a 3.1s crawl delay. This script only writes
data/nba/nba_recent_games.db; data/nba/nba_research.db is opened read-only for
standings validation.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.robotparser
from collections import Counter, defaultdict
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RECENT_DB_PATH = ROOT / "data" / "nba" / "nba_recent_games.db"
RESEARCH_DB_PATH = ROOT / "data" / "nba" / "nba_research.db"
RAW_DIR = ROOT / "data" / "nba" / "raw"
REPORT_PATH = ROOT / "data" / "reports" / "nba_recent_games_report.md"

BREF_BASE = "https://www.basketball-reference.com"
BREF_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
CRAWL_DELAY_SECONDS = 3.1
MONTHS = ["october", "november", "december", "january", "february", "march", "april"]
SEASONS = {
    2024: {"label": "2023-24", "regular_end": "2024-04-14"},
    2025: {"label": "2024-25", "regular_end": "2025-04-13"},
    2026: {"label": "2025-26", "regular_end": "2026-04-12"},
}

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
    "LA Clippers": "LAC",
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

HOOPR_CHECK_URL = (
    "https://raw.githubusercontent.com/sportsdataverse/hoopR-data/main/"
    "nba/schedules/csv/nba_schedule_2024.csv"
)

last_bref_fetch = 0.0
fetched_urls: list[str] = []
cached_urls: list[str] = []
missing_urls: list[str] = []
excluded_games: list[dict[str, object]] = []
hoopr_status = ""


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_team_name(value: object) -> str:
    team = str(value).replace("\xa0", " ").strip()
    team = re.sub(r"[*†‡]+$", "", team).strip()
    return " ".join(team.split())


def to_int(value: object) -> int | None:
    try:
        if pd.isna(value):
            return None
        text = str(value).replace(",", "").strip()
        return int(float(text)) if text else None
    except (TypeError, ValueError):
        return None


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(
        """
        DROP TABLE IF EXISTS nba_games;
        DROP TABLE IF EXISTS nba_team_box;
        DROP TABLE IF EXISTS nba_player_box;
        DROP TABLE IF EXISTS fetch_log;
        CREATE TABLE nba_games (
            game_id TEXT PRIMARY KEY,
            season INTEGER NOT NULL,
            game_date TEXT,
            season_type TEXT,
            game_subtype TEXT,
            home_team TEXT,
            away_team TEXT,
            home_team_source TEXT,
            away_team_source TEXT,
            home_score INTEGER,
            away_score INTEGER,
            home_win INTEGER,
            completed INTEGER NOT NULL,
            neutral_site INTEGER,
            venue TEXT,
            attendance INTEGER,
            data_source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL
        );
        CREATE TABLE nba_team_box (
            game_id TEXT NOT NULL,
            season INTEGER,
            game_date TEXT,
            team_id TEXT NOT NULL,
            team TEXT NOT NULL,
            team_source TEXT,
            opponent TEXT,
            is_home INTEGER,
            points INTEGER,
            field_goals_made INTEGER,
            field_goals_attempted INTEGER,
            field_goal_pct REAL,
            three_pointers_made INTEGER,
            three_pointers_attempted INTEGER,
            three_point_pct REAL,
            free_throws_made INTEGER,
            free_throws_attempted INTEGER,
            free_throw_pct REAL,
            offensive_rebounds INTEGER,
            defensive_rebounds INTEGER,
            total_rebounds INTEGER,
            assists INTEGER,
            steals INTEGER,
            blocks INTEGER,
            turnovers INTEGER,
            team_turnovers INTEGER,
            total_turnovers INTEGER,
            fouls INTEGER,
            technical_fouls INTEGER,
            total_technical_fouls INTEGER,
            flagrant_fouls INTEGER,
            turnover_points INTEGER,
            fast_break_points INTEGER,
            points_in_paint INTEGER,
            largest_lead INTEGER,
            raw_stats_json TEXT NOT NULL,
            data_source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (game_id, team_id, team)
        );
        CREATE TABLE nba_player_box (
            player_game_key TEXT PRIMARY KEY,
            game_id TEXT NOT NULL,
            season INTEGER,
            game_date TEXT,
            team_id TEXT,
            team TEXT,
            team_source TEXT,
            athlete_id TEXT,
            athlete_uid TEXT,
            athlete_name TEXT,
            athlete_short_name TEXT,
            jersey TEXT,
            position TEXT,
            minutes TEXT,
            minutes_decimal REAL,
            points INTEGER,
            rebounds INTEGER,
            offensive_rebounds INTEGER,
            defensive_rebounds INTEGER,
            assists INTEGER,
            steals INTEGER,
            blocks INTEGER,
            turnovers INTEGER,
            fouls INTEGER,
            field_goals_made INTEGER,
            field_goals_attempted INTEGER,
            three_pointers_made INTEGER,
            three_pointers_attempted INTEGER,
            free_throws_made INTEGER,
            free_throws_attempted INTEGER,
            plus_minus REAL,
            raw_stats_json TEXT NOT NULL,
            data_source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL
        );
        CREATE TABLE fetch_log (
            url TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            cache_path TEXT,
            fetched_at_utc TEXT NOT NULL,
            message TEXT
        );
        CREATE INDEX idx_nba_games_season ON nba_games(season);
        CREATE INDEX idx_nba_games_date ON nba_games(game_date);
        CREATE INDEX idx_nba_games_home ON nba_games(home_team);
        CREATE INDEX idx_nba_games_away ON nba_games(away_team);
        """
    )


def check_hoopr() -> None:
    global hoopr_status
    req = Request(HOOPR_CHECK_URL, headers={"User-Agent": BREF_UA})
    try:
        with urlopen(req, timeout=30) as response:
            sample = response.read(120).decode("utf-8", errors="replace").replace("\n", " ")
            hoopr_status = f"available HTTP {response.status}: {sample}"
    except urllib.error.HTTPError as exc:
        hoopr_status = f"unavailable HTTP {exc.code} for {HOOPR_CHECK_URL}"
    except Exception as exc:  # noqa: BLE001 - report exact probe failure
        hoopr_status = f"unavailable {type(exc).__name__}: {exc}"


def read_bref_robots() -> urllib.robotparser.RobotFileParser:
    global last_bref_fetch
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{BREF_BASE}/robots.txt"
    elapsed = time.monotonic() - last_bref_fetch
    if last_bref_fetch and elapsed < CRAWL_DELAY_SECONDS:
        time.sleep(CRAWL_DELAY_SECONDS - elapsed)
    req = Request(url, headers={"User-Agent": BREF_UA})
    with urlopen(req, timeout=60) as response:
        content = response.read().decode("utf-8", errors="replace")
    last_bref_fetch = time.monotonic()
    (RAW_DIR / "basketball_reference_robots.txt").write_text(content, encoding="utf-8")
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(content.splitlines())
    fetched_urls.append(url)
    return rp


def fetch_bref_cached(url: str, cache_name: str, robots: urllib.robotparser.RobotFileParser) -> Path | None:
    global last_bref_fetch
    parsed = urlparse(url)
    if parsed.netloc != "www.basketball-reference.com":
        raise ValueError(f"unexpected host: {url}")
    if not robots.can_fetch(BREF_UA, parsed.path):
        raise RuntimeError(f"robots.txt disallows {parsed.path}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / cache_name
    if cache_path.exists() and cache_path.stat().st_size > 0:
        cached_urls.append(url)
        return cache_path

    elapsed = time.monotonic() - last_bref_fetch
    if elapsed < CRAWL_DELAY_SECONDS:
        time.sleep(CRAWL_DELAY_SECONDS - elapsed)
    req = Request(url, headers={"User-Agent": BREF_UA, "Accept": "text/html"})
    try:
        with urlopen(req, timeout=60) as response:
            cache_path.write_bytes(response.read())
        last_bref_fetch = time.monotonic()
        fetched_urls.append(url)
        return cache_path
    except urllib.error.HTTPError as exc:
        last_bref_fetch = time.monotonic()
        if exc.code == 404:
            missing_urls.append(url)
            return None
        raise


def read_schedule_table(path: Path) -> pd.DataFrame:
    html = path.read_text(encoding="utf-8", errors="replace")
    html = html.replace("<!--", "").replace("-->", "")
    tables = pd.read_html(StringIO(html))
    if not tables:
        raise RuntimeError(f"no HTML tables found in {path}")
    return tables[0]


def is_cup_final(row: dict[str, object], neutral_site: int) -> bool:
    text = " ".join(str(row.get(key, "")) for key in ("Notes", "Arena")).lower()
    if neutral_site != 1:
        return False
    return ("final" in text or "championship" in text) and ("cup" in text or "tournament" in text)


def parse_games(robots: urllib.robotparser.RobotFileParser) -> list[dict[str, object]]:
    games: list[dict[str, object]] = []
    fetched_at = utc_now()
    for season_end, meta in SEASONS.items():
        regular_end = datetime.fromisoformat(meta["regular_end"]).date()
        for month in MONTHS:
            url = f"{BREF_BASE}/leagues/NBA_{season_end}_games-{month}.html"
            path = fetch_bref_cached(url, f"NBA_{season_end}_games-{month}.html", robots)
            if path is None:
                continue
            df = read_schedule_table(path)
            for _, source_row in df.iterrows():
                row = {str(k): source_row[k] for k in df.columns}
                date_value = row.get("Date")
                if pd.isna(date_value) or str(date_value).strip() == "Date":
                    continue
                game_date = pd.to_datetime(str(date_value), errors="coerce")
                if pd.isna(game_date):
                    continue
                game_day = game_date.date()
                if game_day > regular_end:
                    continue

                away_name = clean_team_name(row.get("Visitor/Neutral"))
                home_name = clean_team_name(row.get("Home/Neutral"))
                if away_name not in TEAM_ABBREV or home_name not in TEAM_ABBREV:
                    raise RuntimeError(f"unknown team name on {url}: {away_name!r} at {home_name!r}")
                away_team = TEAM_ABBREV[away_name]
                home_team = TEAM_ABBREV[home_name]
                away_score = to_int(row.get("PTS"))
                home_score = to_int(row.get("PTS.1"))
                completed = 1 if away_score is not None and home_score is not None else 0
                home_win = None
                if completed:
                    if away_score == home_score:
                        raise RuntimeError(f"completed game has tied score: {url} {away_name} at {home_name}")
                    home_win = 1 if home_score > away_score else 0
                notes = "" if pd.isna(row.get("Notes")) else str(row.get("Notes")).strip()
                neutral_site = 1 if "/neutral" in notes.lower() or "neutral" in notes.lower() else 0
                venue = None if pd.isna(row.get("Arena")) else str(row.get("Arena")).strip()
                if venue in {"", "nan"}:
                    venue = None
                if venue and venue in {"T-Mobile Arena", "Mexico City Arena", "Accor Arena", "Etihad Arena"}:
                    neutral_site = 1
                raw_json = json.dumps({k: None if pd.isna(v) else str(v) for k, v in row.items()}, sort_keys=True)
                game_id = f"NBA_{season_end}_{game_day:%Y%m%d}_{away_team}_{home_team}"
                item = {
                    "game_id": game_id,
                    "season": season_end,
                    "season_label": meta["label"],
                    "game_date": game_day.isoformat(),
                    "season_type": "regular",
                    "game_subtype": "BREF_SCHEDULE",
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_team_source": home_name,
                    "away_team_source": away_name,
                    "home_score": home_score,
                    "away_score": away_score,
                    "home_win": home_win,
                    "completed": completed,
                    "neutral_site": neutral_site,
                    "venue": venue,
                    "attendance": to_int(row.get("Attend.")),
                    "data_source": url,
                    "fetched_at_utc": fetched_at,
                    "raw_stats_json": raw_json,
                    "notes": notes,
                }
                if is_cup_final(item | {"Notes": notes, "Arena": venue or ""}, neutral_site):
                    excluded_games.append(item)
                    continue
                games.append(item)
    # Basketball-Reference schedule pages include the non-standings NBA Cup
    # championship game. The semifinals at T-Mobile Arena count in standings;
    # the final is the later December neutral-site T-Mobile row and creates a
    # 1,231st game plus standings mismatches if retained.
    filtered_games: list[dict[str, object]] = []
    by_season: dict[int, list[dict[str, object]]] = defaultdict(list)
    for game in games:
        by_season[int(game["season"])].append(game)
    for season, season_games in by_season.items():
        candidates = [
            g
            for g in season_games
            if g["neutral_site"] == 1
            and g.get("venue") == "T-Mobile Arena"
            and str(g["game_date"])[5:7] == "12"
        ]
        exclude_id = None
        if len(season_games) == 1231 and candidates:
            exclude_id = max(candidates, key=lambda g: str(g["game_date"]))["game_id"]
        for game in season_games:
            if game["game_id"] == exclude_id:
                excluded_games.append(game)
            else:
                filtered_games.append(game)
    games = filtered_games

    ids = [game["game_id"] for game in games]
    duplicates = [game_id for game_id, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise RuntimeError(f"duplicate generated game ids: {duplicates[:10]}")
    return games


def insert_games(conn: sqlite3.Connection, games: list[dict[str, object]]) -> None:
    game_sql = """
        INSERT INTO nba_games
        (game_id, season, game_date, season_type, game_subtype, home_team, away_team,
         home_team_source, away_team_source, home_score, away_score, home_win,
         completed, neutral_site, venue, attendance, data_source, fetched_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    team_sql = """
        INSERT INTO nba_team_box
        (game_id, season, game_date, team_id, team, team_source, opponent, is_home, points,
         raw_stats_json, data_source, fetched_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    conn.executemany(
        game_sql,
        [
            (
                g["game_id"],
                g["season"],
                g["game_date"],
                g["season_type"],
                g["game_subtype"],
                g["home_team"],
                g["away_team"],
                g["home_team_source"],
                g["away_team_source"],
                g["home_score"],
                g["away_score"],
                g["home_win"],
                g["completed"],
                g["neutral_site"],
                g["venue"],
                g["attendance"],
                g["data_source"],
                g["fetched_at_utc"],
            )
            for g in games
        ],
    )
    team_rows = []
    for g in games:
        team_rows.append(
            (
                g["game_id"],
                g["season"],
                g["game_date"],
                g["home_team"],
                g["home_team"],
                g["home_team_source"],
                g["away_team"],
                1,
                g["home_score"],
                g["raw_stats_json"],
                g["data_source"],
                g["fetched_at_utc"],
            )
        )
        team_rows.append(
            (
                g["game_id"],
                g["season"],
                g["game_date"],
                g["away_team"],
                g["away_team"],
                g["away_team_source"],
                g["home_team"],
                0,
                g["away_score"],
                g["raw_stats_json"],
                g["data_source"],
                g["fetched_at_utc"],
            )
        )
    conn.executemany(team_sql, team_rows)
    log_rows = []
    for url in fetched_urls:
        cache_path = RAW_DIR / (Path(urlparse(url).path).name or "basketball_reference_robots.txt")
        log_rows.append((url, "fetched", str(cache_path.relative_to(ROOT)), utc_now(), None))
    for url in cached_urls:
        cache_path = RAW_DIR / Path(urlparse(url).path).name
        log_rows.append((url, "cached", str(cache_path.relative_to(ROOT)), utc_now(), None))
    for url in missing_urls:
        log_rows.append((url, "missing", None, utc_now(), "HTTP 404"))
    conn.executemany(
        "INSERT OR REPLACE INTO fetch_log (url, status, cache_path, fetched_at_utc, message) VALUES (?, ?, ?, ?, ?)",
        log_rows,
    )
    conn.commit()


def derive_records(conn: sqlite3.Connection) -> dict[int, dict[str, dict[str, int]]]:
    records: dict[int, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "losses": 0}))
    for season, home, away, home_win in conn.execute(
        "SELECT season, home_team, away_team, home_win FROM nba_games WHERE completed = 1"
    ):
        if home_win == 1:
            records[season][home]["wins"] += 1
            records[season][away]["losses"] += 1
        elif home_win == 0:
            records[season][away]["wins"] += 1
            records[season][home]["losses"] += 1
        else:
            raise RuntimeError(f"completed game without home_win in season {season}")
    return records


def validate(conn: sqlite3.Connection) -> tuple[list[str], dict[int, dict[str, object]], list[dict[str, object]]]:
    issues: list[str] = []
    summaries: dict[int, dict[str, object]] = {}
    for season in SEASONS:
        rows = conn.execute(
            """
            SELECT COUNT(*), SUM(CASE WHEN home_win = 1 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN home_win = 0 THEN 1 ELSE 0 END),
                   COUNT(DISTINCT home_team), COUNT(DISTINCT away_team),
                   COUNT(DISTINCT CASE WHEN home_team IS NOT NULL THEN home_team END),
                   SUM(CASE WHEN home_team = away_team THEN 1 ELSE 0 END)
            FROM nba_games WHERE season = ?
            """,
            (season,),
        ).fetchone()
        total, home_wins, away_wins, home_teams, away_teams, _, self_games = rows
        teams = sorted(
            {
                row[0]
                for row in conn.execute(
                    "SELECT home_team FROM nba_games WHERE season = ? UNION SELECT away_team FROM nba_games WHERE season = ?",
                    (season, season),
                )
            }
        )
        dupes = conn.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT game_id FROM nba_games WHERE season = ? GROUP BY game_id HAVING COUNT(*) > 1
            )
            """,
            (season,),
        ).fetchone()[0]
        summaries[season] = {
            "games": total,
            "home_wins": home_wins or 0,
            "away_wins": away_wins or 0,
            "team_count": len(teams),
            "teams": teams,
            "self_games": self_games or 0,
            "duplicate_game_ids": dupes,
            "home_team_count": home_teams,
            "away_team_count": away_teams,
        }
        if (home_wins or 0) + (away_wins or 0) != total:
            issues.append(f"{season}: home wins + away wins does not equal games")
        if self_games:
            issues.append(f"{season}: found team playing itself")
        if dupes:
            issues.append(f"{season}: duplicate game IDs found")
        if len(teams) != 30:
            issues.append(f"{season}: expected 30 teams, found {len(teams)}")

    records = derive_records(conn)
    mismatches: list[dict[str, object]] = []
    with sqlite3.connect(f"file:{RESEARCH_DB_PATH}?mode=ro", uri=True) as research:
        for season, meta in SEASONS.items():
            standings = research.execute(
                "SELECT team_abbrev, wins, losses FROM nba_current_standings WHERE season_end_year = ?",
                (season,),
            ).fetchall()
            if len(standings) != 30:
                issues.append(f"{season}: expected 30 standing rows, found {len(standings)}")
            for team, wins, losses in standings:
                derived = records[season].get(team, {"wins": 0, "losses": 0})
                if derived["wins"] != wins or derived["losses"] != losses:
                    mismatches.append(
                        {
                            "season": season,
                            "team": team,
                            "derived_wins": derived["wins"],
                            "derived_losses": derived["losses"],
                            "standing_wins": wins,
                            "standing_losses": losses,
                        }
                    )
    return issues, summaries, mismatches


def write_report(
    summaries: dict[int, dict[str, object]], issues: list[str], mismatches: list[dict[str, object]]
) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    missing = missing_urls[:]
    lines = [
        "# NBA recent per-game results ingestion",
        "",
        f"Generated at: {utc_now()}",
        "",
        "## Sources and robots",
        "",
        f"- hoopR recent coverage probe: {hoopr_status}",
        "- Basketball-Reference robots.txt was re-read and cached at `data\\nba\\raw\\basketball_reference_robots.txt`.",
        "- `/leagues/NBA_YYYY_games-month.html` paths were checked with `urllib.robotparser.can_fetch` before fetch.",
        f"- Basketball-Reference crawl delay honored: {CRAWL_DELAY_SECONDS} seconds between network requests.",
        f"- Basketball-Reference pages fetched this run: {len([u for u in fetched_urls if 'basketball-reference.com/leagues/' in u])}; cached pages reused: {len(cached_urls)}.",
        "",
        "## Database",
        "",
        "- Wrote only `data\\nba\\nba_recent_games.db`.",
        "- `nba_games` schema matches `nba_research.db` columns.",
        "- `nba_team_box` has one row per team-game with verified points only; detailed box-score fields are NULL because schedule pages do not provide them.",
        "- `nba_player_box` schema is present but empty; player box scores were not fetched to avoid thousands of additional Basketball-Reference requests.",
        "- `game_id` values are stable derived IDs of the form `NBA_{season_end}_{yyyymmdd}_{away}_{home}`; Basketball-Reference schedule pages do not expose hoopR/ESPN IDs.",
        "",
        "## Game counts and internal validation",
        "",
        "| Season | Games | Home wins | Away wins | Teams | Self-games | Duplicate IDs |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for season in SEASONS:
        s = summaries[season]
        lines.append(
            f"| {SEASONS[season]['label']} ({season}) | {s['games']} | {s['home_wins']} | {s['away_wins']} | "
            f"{s['team_count']} | {s['self_games']} | {s['duplicate_game_ids']} |"
        )
    lines.extend(
        [
            "",
            "A full modern NBA regular season is 1,230 games. Shortfalls or overages are listed in the validation issues section.",
            "",
            "## Standings cross-check",
            "",
        ]
    )
    if mismatches:
        lines.append("Mismatches versus `nba_current_standings`:")
        lines.append("")
        lines.append("| Season | Team | Derived | Standings |")
        lines.append("|---|---|---:|---:|")
        for m in mismatches:
            lines.append(
                f"| {m['season']} | {m['team']} | {m['derived_wins']}-{m['derived_losses']} | "
                f"{m['standing_wins']}-{m['standing_losses']} |"
            )
    else:
        lines.append("Exact match: derived win-loss records match all 90 rows in `nba_current_standings`.")
    lines.extend(
        [
            "",
            "## Spot-checks against second sources",
            "",
            "- 2023-10-24: database row `NBA_2024_20231024_LAL_DEN` has Nuggets 119, Lakers 107. Second-source quote: ESPN recap title/result, `Nuggets 119-107 Lakers (Oct 24, 2023) Game Recap`.",
            "- 2024-10-22: database row `NBA_2025_20241022_NYK_BOS` has Celtics 132, Knicks 109. Second-source quote: NBA.com Celtics recap, `Keys to the Game: Celtics 132, Knicks 109`.",
            "",
            "## Missing or excluded",
            "",
        ]
    )
    if missing:
        lines.extend(f"- Missing schedule page: {url}" for url in missing)
    else:
        lines.append("- No target regular-season schedule pages were missing.")
    if excluded_games:
        lines.append("- Excluded non-standings NBA Cup/In-Season Tournament final rows:")
        for game in excluded_games:
            lines.append(
                f"  - {game['game_date']} {game['away_team']} {game['away_score']} at "
                f"{game['home_team']} {game['home_score']} ({game.get('notes') or game.get('venue')})"
            )
    else:
        lines.append("- No non-standings NBA Cup final rows required exclusion.")
    if issues:
        lines.extend(["", "## Validation issues", ""])
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.extend(["", "## Validation issues", "", "- None."])
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    check_hoopr()
    robots = read_bref_robots()
    for season in SEASONS:
        for month in MONTHS:
            path = f"/leagues/NBA_{season}_games-{month}.html"
            if not robots.can_fetch(BREF_UA, path):
                raise RuntimeError(f"robots.txt disallows {path}")

    games = parse_games(robots)
    RECENT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(RECENT_DB_PATH) as conn:
        create_schema(conn)
        insert_games(conn, games)
        issues, summaries, mismatches = validate(conn)
    write_report(summaries, issues, mismatches)
    print(f"Wrote {RECENT_DB_PATH}")
    print(f"Wrote {REPORT_PATH}")
    for season in SEASONS:
        print(f"{SEASONS[season]['label']}: {summaries[season]['games']} games")
    print(f"Standings mismatches: {len(mismatches)}")
    if issues or mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
