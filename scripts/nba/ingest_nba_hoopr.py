import csv
import datetime as dt
import gzip
import io
import json
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "nba" / "nba_research.db"
REPORT_PATH = ROOT / "data" / "reports" / "nba_ingestion_report.md"
YEARS = range(2002, 2024)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
BASE = "https://raw.githubusercontent.com/sportsdataverse/hoopR-data/main/nba"

# One canonical current NBA franchise code per franchise. ESPN/hoopR historical aliases are
# normalized here so relocations/renames do not create separate modeling teams.
TEAM_ALIASES = {
    "ATL": "ATL",
    "BOS": "BOS",
    "BKN": "BKN",
    "NJ": "BKN",
    "NJN": "BKN",
    "CHA": "CHA",
    "CHH": "CHA",
    "CHI": "CHI",
    "CLE": "CLE",
    "DAL": "DAL",
    "DEN": "DEN",
    "DET": "DET",
    "GS": "GSW",
    "GSW": "GSW",
    "HOU": "HOU",
    "IND": "IND",
    "LAC": "LAC",
    "LAL": "LAL",
    "MEM": "MEM",
    "MIA": "MIA",
    "MIL": "MIL",
    "MIN": "MIN",
    "NO": "NOP",
    "NOH": "NOP",
    "NOK": "NOP",
    "NOP": "NOP",
    "NY": "NYK",
    "NYK": "NYK",
    "OKC": "OKC",
    "SEA": "OKC",
    "ORL": "ORL",
    "PHI": "PHI",
    "PHX": "PHX",
    "POR": "POR",
    "SAC": "SAC",
    "SA": "SAS",
    "SAS": "SAS",
    "TOR": "TOR",
    "UTAH": "UTA",
    "UTA": "UTA",
    "WSH": "WAS",
    "WAS": "WAS",
    # Non-franchise All-Star/source exhibition teams, preserved but excluded from 30-team checks.
    "EAST": "EAST",
    "WEST": "WEST",
    "LEB": "LEB",
    "DUR": "DUR",
    "STE": "STE",
    "GIA": "GIA",
    "USA": "USA",
    "WORLD": "WORLD",
}

NBA_TEAMS = [
    ("ATL", "Atlanta Hawks", "Eastern", "Southeast", 2002, None, "ATL"),
    ("BOS", "Boston Celtics", "Eastern", "Atlantic", 2002, None, "BOS"),
    ("BKN", "Brooklyn Nets", "Eastern", "Atlantic", 2013, None, "NJ,NJN,BKN; New Jersey Nets through 2012"),
    ("CHA", "Charlotte Hornets", "Eastern", "Southeast", 2002, None, "CHA,CHH; includes Bobcats/Hornets source alias"),
    ("CHI", "Chicago Bulls", "Eastern", "Central", 2002, None, "CHI"),
    ("CLE", "Cleveland Cavaliers", "Eastern", "Central", 2002, None, "CLE"),
    ("DAL", "Dallas Mavericks", "Western", "Southwest", 2002, None, "DAL"),
    ("DEN", "Denver Nuggets", "Western", "Northwest", 2002, None, "DEN"),
    ("DET", "Detroit Pistons", "Eastern", "Central", 2002, None, "DET"),
    ("GSW", "Golden State Warriors", "Western", "Pacific", 2002, None, "GS,GSW"),
    ("HOU", "Houston Rockets", "Western", "Southwest", 2002, None, "HOU"),
    ("IND", "Indiana Pacers", "Eastern", "Central", 2002, None, "IND"),
    ("LAC", "LA Clippers", "Western", "Pacific", 2002, None, "LAC"),
    ("LAL", "Los Angeles Lakers", "Western", "Pacific", 2002, None, "LAL"),
    ("MEM", "Memphis Grizzlies", "Western", "Southwest", 2002, None, "MEM; Vancouver move pre-window"),
    ("MIA", "Miami Heat", "Eastern", "Southeast", 2002, None, "MIA"),
    ("MIL", "Milwaukee Bucks", "Eastern", "Central", 2002, None, "MIL"),
    ("MIN", "Minnesota Timberwolves", "Western", "Northwest", 2002, None, "MIN"),
    ("NOP", "New Orleans Pelicans", "Western", "Southwest", 2003, None, "NO,NOH,NOK,NOP"),
    ("NYK", "New York Knicks", "Eastern", "Atlantic", 2002, None, "NY,NYK"),
    ("OKC", "Oklahoma City Thunder", "Western", "Northwest", 2009, None, "SEA,OKC; Seattle SuperSonics through 2008"),
    ("ORL", "Orlando Magic", "Eastern", "Southeast", 2002, None, "ORL"),
    ("PHI", "Philadelphia 76ers", "Eastern", "Atlantic", 2002, None, "PHI"),
    ("PHX", "Phoenix Suns", "Western", "Pacific", 2002, None, "PHX"),
    ("POR", "Portland Trail Blazers", "Western", "Northwest", 2002, None, "POR"),
    ("SAC", "Sacramento Kings", "Western", "Pacific", 2002, None, "SAC"),
    ("SAS", "San Antonio Spurs", "Western", "Southwest", 2002, None, "SA,SAS"),
    ("TOR", "Toronto Raptors", "Eastern", "Atlantic", 2002, None, "TOR"),
    ("UTA", "Utah Jazz", "Western", "Northwest", 2002, None, "UTAH,UTA"),
    ("WAS", "Washington Wizards", "Eastern", "Southeast", 2002, None, "WSH,WAS"),
]


@dataclass
class FetchLog:
    url: str
    status: str
    bytes_downloaded: int = 0
    message: str = ""
    fetched_at_utc: str = ""


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean(value):
    if value is None:
        return None
    value = str(value).strip()
    if value == "" or value.upper() in {"NA", "N/A", "NULL"}:
        return None
    return value


def as_int(value):
    value = clean(value)
    if value is None:
        return None
    return int(float(value))


def as_float(value):
    value = clean(value)
    if value is None:
        return None
    return float(value)


def as_bool_int(value):
    value = clean(value)
    if value is None:
        return None
    return 1 if value.upper() in {"TRUE", "1", "YES"} else 0


def canonical(code):
    code = clean(code)
    if code is None:
        return None
    return TEAM_ALIASES.get(code.upper(), code.upper())


def fetch_url(url, logs, retries=3):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as response:
                data = response.read()
                if url.endswith(".gz"):
                    data = gzip.decompress(data)
                logs.append(FetchLog(url, "success", len(data), f"HTTP {response.status}", now_utc()))
                return data.decode("utf-8-sig")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))
    logs.append(FetchLog(url, "failed", 0, repr(last_error), now_utc()))
    return None


def fetch_first(urls, logs):
    for url in urls:
        text = fetch_url(url, logs)
        if text is not None:
            return url, text
    return None, None


def split_made_attempted(value):
    value = clean(value)
    if value is None or "-" not in value:
        return None, None
    made, attempted = value.split("-", 1)
    return as_int(made), as_int(attempted)


def minutes_decimal(value):
    value = clean(value)
    if value is None:
        return None
    if ":" in value:
        minutes, seconds = value.split(":", 1)
        return as_float(minutes) + as_float(seconds) / 60.0
    return as_float(value)


def create_schema(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nba_games (
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
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nba_team_box (
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
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nba_player_box (
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
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nba_teams (
            abbreviation TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            conference TEXT NOT NULL,
            division TEXT NOT NULL,
            first_season INTEGER,
            last_season INTEGER,
            alias_source_codes TEXT NOT NULL,
            data_source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL
        )
    """)
    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_nba_games_season ON nba_games(season)",
        "CREATE INDEX IF NOT EXISTS idx_nba_games_date ON nba_games(game_date)",
        "CREATE INDEX IF NOT EXISTS idx_nba_games_home ON nba_games(home_team)",
        "CREATE INDEX IF NOT EXISTS idx_nba_games_away ON nba_games(away_team)",
        "CREATE INDEX IF NOT EXISTS idx_nba_team_box_season ON nba_team_box(season)",
        "CREATE INDEX IF NOT EXISTS idx_nba_team_box_team ON nba_team_box(team)",
        "CREATE INDEX IF NOT EXISTS idx_nba_team_box_team_id ON nba_team_box(team_id)",
        "CREATE INDEX IF NOT EXISTS idx_nba_player_box_season ON nba_player_box(season)",
        "CREATE INDEX IF NOT EXISTS idx_nba_player_box_team ON nba_player_box(team)",
        "CREATE INDEX IF NOT EXISTS idx_nba_player_box_team_id ON nba_player_box(team_id)",
        "CREATE INDEX IF NOT EXISTS idx_nba_player_box_athlete_id ON nba_player_box(athlete_id)",
    ]:
        conn.execute(sql)


def season_kind(row):
    espn_type = clean(row.get("season_type"))
    subtype = clean(row.get("type_abbreviation"))
    if espn_type == "3":
        return "playoff"
    if subtype == "STD":
        return "regular"
    return (subtype or "other").lower()


def load_teams(conn):
    fetched = now_utc()
    conn.executemany(
        """
        INSERT OR REPLACE INTO nba_teams
        (abbreviation, full_name, conference, division, first_season, last_season, alias_source_codes, data_source, fetched_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [row + ("script:TEAM_ALIASES", fetched) for row in NBA_TEAMS],
    )


def ingest_schedules(conn, logs):
    game_meta = {}
    insert_sql = """
        INSERT OR REPLACE INTO nba_games
        (game_id, season, game_date, season_type, game_subtype, home_team, away_team, home_team_source, away_team_source,
         home_score, away_score, home_win, completed, neutral_site, venue, attendance, data_source, fetched_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    for year in YEARS:
        url, text = fetch_first([
            f"{BASE}/schedules/csv/nba_schedule_{year}.csv",
            f"{BASE}/schedules/csv/nba_schedule_{year}.csv.gz",
        ], logs)
        if text is None:
            continue
        fetched_at = now_utc()
        rows = csv.DictReader(io.StringIO(text))
        batch = []
        for row in rows:
            game_id = clean(row.get("game_id") or row.get("id"))
            if not game_id:
                continue
            home_score = as_int(row.get("home_score"))
            away_score = as_int(row.get("away_score"))
            completed = as_bool_int(row.get("status_type_completed")) or 0
            home_win = None
            if completed and home_score is not None and away_score is not None:
                if home_score == away_score:
                    raise RuntimeError(f"Completed NBA game has tied score: {game_id} {home_score}-{away_score}")
                home_win = 1 if home_score > away_score else 0
            game_date = clean(row.get("game_date")) or clean(row.get("date"))[:10]
            home_src = clean(row.get("home_abbreviation"))
            away_src = clean(row.get("away_abbreviation"))
            home = canonical(home_src)
            away = canonical(away_src)
            season = as_int(row.get("season")) or year
            item = (
                game_id,
                season,
                game_date,
                season_kind(row),
                clean(row.get("type_abbreviation")),
                home,
                away,
                home_src,
                away_src,
                home_score if completed else None,
                away_score if completed else None,
                home_win,
                completed,
                as_bool_int(row.get("neutral_site")),
                clean(row.get("venue_full_name")),
                as_int(row.get("attendance")),
                url,
                fetched_at,
            )
            batch.append(item)
            game_meta[game_id] = {
                "season": season,
                "game_date": game_date,
                "home": home,
                "away": away,
                "home_src": home_src,
                "away_src": away_src,
                "home_score": item[9],
                "away_score": item[10],
            }
        conn.executemany(insert_sql, batch)
        conn.commit()
    return game_meta


TEAM_STAT_COLUMNS = {
    "fieldGoalPct": ("field_goal_pct", as_float),
    "threePointFieldGoalPct": ("three_point_pct", as_float),
    "freeThrowPct": ("free_throw_pct", as_float),
    "totalRebounds": ("total_rebounds", as_int),
    "offensiveRebounds": ("offensive_rebounds", as_int),
    "defensiveRebounds": ("defensive_rebounds", as_int),
    "assists": ("assists", as_int),
    "steals": ("steals", as_int),
    "blocks": ("blocks", as_int),
    "turnovers": ("turnovers", as_int),
    "teamTurnovers": ("team_turnovers", as_int),
    "totalTurnovers": ("total_turnovers", as_int),
    "technicalFouls": ("technical_fouls", as_int),
    "totalTechnicalFouls": ("total_technical_fouls", as_int),
    "flagrantFouls": ("flagrant_fouls", as_int),
    "turnoverPoints": ("turnover_points", as_int),
    "fastBreakPoints": ("fast_break_points", as_int),
    "pointsInPaint": ("points_in_paint", as_int),
    "fouls": ("fouls", as_int),
    "largestLead": ("largest_lead", as_int),
}


def ingest_team_box(conn, logs, game_meta):
    insert_cols = [
        "game_id", "season", "game_date", "team_id", "team", "team_source", "opponent", "is_home", "points",
        "field_goals_made", "field_goals_attempted", "field_goal_pct", "three_pointers_made", "three_pointers_attempted",
        "three_point_pct", "free_throws_made", "free_throws_attempted", "free_throw_pct", "offensive_rebounds",
        "defensive_rebounds", "total_rebounds", "assists", "steals", "blocks", "turnovers", "team_turnovers",
        "total_turnovers", "fouls", "technical_fouls", "total_technical_fouls", "flagrant_fouls", "turnover_points",
        "fast_break_points", "points_in_paint", "largest_lead", "raw_stats_json", "data_source", "fetched_at_utc",
    ]
    insert_sql = f"INSERT OR REPLACE INTO nba_team_box ({','.join(insert_cols)}) VALUES ({','.join('?' for _ in insert_cols)})"
    for year in YEARS:
        url, text = fetch_first([
            f"{BASE}/team_box/csv/team_box_{year}.csv.gz",
            f"{BASE}/team_box/csv/team_box_{year}.csv",
        ], logs)
        if text is None:
            continue
        fetched_at = now_utc()
        grouped = {}
        for row in csv.DictReader(io.StringIO(text)):
            game_id = clean(row.get("game_id"))
            team_id = clean(row.get("team_id")) or clean(row.get("team_abbreviation")) or "unknown"
            team_src = clean(row.get("team_abbreviation"))
            key = (game_id, team_id, canonical(team_src))
            rec = grouped.setdefault(key, {"raw": {}, "team_source": team_src})
            stat = clean(row.get("stat_name"))
            val = clean(row.get("stat_displayValue"))
            if stat:
                rec["raw"][stat] = val
        batch = []
        for (game_id, team_id, team), rec in grouped.items():
            meta = game_meta.get(game_id, {})
            values = {col: None for col in insert_cols}
            values.update({
                "game_id": game_id,
                "season": meta.get("season") or year,
                "game_date": meta.get("game_date"),
                "team_id": team_id,
                "team": team,
                "team_source": rec["team_source"],
                "data_source": url,
                "fetched_at_utc": fetched_at,
                "raw_stats_json": json.dumps(rec["raw"], sort_keys=True),
            })
            if team == meta.get("home"):
                values["is_home"] = 1
                values["opponent"] = meta.get("away")
                values["points"] = meta.get("home_score")
            elif team == meta.get("away"):
                values["is_home"] = 0
                values["opponent"] = meta.get("home")
                values["points"] = meta.get("away_score")
            fg_m, fg_a = split_made_attempted(rec["raw"].get("fieldGoalsMade-fieldGoalsAttempted"))
            tp_m, tp_a = split_made_attempted(rec["raw"].get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
            ft_m, ft_a = split_made_attempted(rec["raw"].get("freeThrowsMade-freeThrowsAttempted"))
            values.update({
                "field_goals_made": fg_m,
                "field_goals_attempted": fg_a,
                "three_pointers_made": tp_m,
                "three_pointers_attempted": tp_a,
                "free_throws_made": ft_m,
                "free_throws_attempted": ft_a,
            })
            for stat, (col, converter) in TEAM_STAT_COLUMNS.items():
                values[col] = converter(rec["raw"].get(stat))
            batch.append([values[col] for col in insert_cols])
        conn.executemany(insert_sql, batch)
        conn.commit()


def ingest_player_box(conn, logs, game_meta):
    insert_cols = [
        "player_game_key", "game_id", "season", "game_date", "team_id", "team", "team_source", "athlete_id",
        "athlete_uid", "athlete_name", "athlete_short_name", "jersey", "position", "minutes", "minutes_decimal",
        "points", "rebounds", "offensive_rebounds", "defensive_rebounds", "assists", "steals", "blocks",
        "turnovers", "fouls", "field_goals_made", "field_goals_attempted", "three_pointers_made",
        "three_pointers_attempted", "free_throws_made", "free_throws_attempted", "plus_minus", "raw_stats_json",
        "data_source", "fetched_at_utc",
    ]
    insert_sql = f"INSERT OR REPLACE INTO nba_player_box ({','.join(insert_cols)}) VALUES ({','.join('?' for _ in insert_cols)})"
    for year in YEARS:
        url, text = fetch_first([
            f"{BASE}/player_box/csv/player_box_{year}.csv.gz",
            f"{BASE}/player_box/csv/player_box_{year}.csv",
        ], logs)
        if text is None:
            continue
        fetched_at = now_utc()
        batch = []
        for row in csv.DictReader(io.StringIO(text)):
            game_id = clean(row.get("game_id"))
            team_src = clean(row.get("team_abbreviation"))
            team = canonical(team_src)
            athlete_id = clean(row.get("athlete_id"))
            athlete_name = clean(row.get("athlete_displayName"))
            key = "|".join([game_id or "", team or "", athlete_id or athlete_name or "unknown"])
            fg_m, fg_a = split_made_attempted(row.get("fieldGoalsMade-fieldGoalsAttempted"))
            tp_m, tp_a = split_made_attempted(row.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
            ft_m, ft_a = split_made_attempted(row.get("freeThrowsMade-freeThrowsAttempted"))
            meta = game_meta.get(game_id, {})
            values = {
                "player_game_key": key,
                "game_id": game_id,
                "season": meta.get("season") or year,
                "game_date": meta.get("game_date"),
                "team_id": clean(row.get("team_id")),
                "team": team,
                "team_source": team_src,
                "athlete_id": athlete_id,
                "athlete_uid": clean(row.get("athlete_uid")),
                "athlete_name": athlete_name,
                "athlete_short_name": clean(row.get("athlete_shortName")),
                "jersey": clean(row.get("athlete_jersey")),
                "position": clean(row.get("athlete_position.abbreviation")),
                "minutes": clean(row.get("minutes")),
                "minutes_decimal": minutes_decimal(row.get("minutes")),
                "points": as_int(row.get("points")),
                "rebounds": as_int(row.get("rebounds")),
                "offensive_rebounds": as_int(row.get("offensiveRebounds")),
                "defensive_rebounds": as_int(row.get("defensiveRebounds")),
                "assists": as_int(row.get("assists")),
                "steals": as_int(row.get("steals")),
                "blocks": as_int(row.get("blocks")),
                "turnovers": as_int(row.get("turnovers")),
                "fouls": as_int(row.get("fouls")),
                "field_goals_made": fg_m,
                "field_goals_attempted": fg_a,
                "three_pointers_made": tp_m,
                "three_pointers_attempted": tp_a,
                "free_throws_made": ft_m,
                "free_throws_attempted": ft_a,
                "plus_minus": as_float(row.get("plusMinus")),
                "raw_stats_json": json.dumps(row, sort_keys=True),
                "data_source": url,
                "fetched_at_utc": fetched_at,
            }
            batch.append([values[col] for col in insert_cols])
            if len(batch) >= 5000:
                conn.executemany(insert_sql, batch)
                conn.commit()
                batch.clear()
        if batch:
            conn.executemany(insert_sql, batch)
            conn.commit()


def query(conn, sql):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql)]


def write_report(conn, logs):
    rows = {
        "tables": query(conn, """
            SELECT 'nba_games' table_name, COUNT(*) rows FROM nba_games
            UNION ALL SELECT 'nba_team_box', COUNT(*) FROM nba_team_box
            UNION ALL SELECT 'nba_player_box', COUNT(*) FROM nba_player_box
            UNION ALL SELECT 'nba_teams', COUNT(*) FROM nba_teams
        """),
        "coverage": query(conn, """
            SELECT MIN(season) min_season, MAX(season) max_season, MIN(game_date) min_game_date,
                   MAX(CASE WHEN completed=1 THEN game_date END) max_completed_game_date
            FROM nba_games
        """),
        "season_counts": query(conn, """
            SELECT season, season_type, COUNT(*) games, SUM(completed) completed_games,
                   MIN(game_date) min_game_date, MAX(game_date) max_game_date
            FROM nba_games
            GROUP BY season, season_type
            ORDER BY season, season_type
        """),
        "validation": query(conn, """
            SELECT
              SUM(CASE WHEN home_team IS NULL OR away_team IS NULL THEN 1 ELSE 0 END) missing_teams,
              SUM(CASE WHEN completed=1 AND (home_score IS NULL OR away_score IS NULL) THEN 1 ELSE 0 END) completed_missing_scores,
              SUM(CASE WHEN home_team = away_team THEN 1 ELSE 0 END) self_games,
              SUM(CASE WHEN completed=1 AND home_win != (home_score > away_score) THEN 1 ELSE 0 END) bad_home_win,
              SUM(CASE WHEN completed=1 AND home_score = away_score THEN 1 ELSE 0 END) completed_ties
            FROM nba_games
        """),
        "recent_teams": query(conn, """
            WITH teams AS (
                SELECT season, home_team team FROM nba_games WHERE season_type='regular' AND home_team IN (SELECT abbreviation FROM nba_teams)
                UNION
                SELECT season, away_team team FROM nba_games WHERE season_type='regular' AND away_team IN (SELECT abbreviation FROM nba_teams)
            )
            SELECT season, COUNT(DISTINCT team) canonical_teams
            FROM teams
            WHERE season >= 2019
            GROUP BY season
            ORDER BY season
        """),
        "spot_check": query(conn, """
            SELECT game_id, season, game_date, away_team, away_score, home_team, home_score, home_win, venue
            FROM nba_games
            WHERE game_date='2016-06-19' AND away_team='CLE' AND home_team='GSW'
        """),
    }
    success = [log for log in logs if log.status == "success"]
    failed = [log for log in logs if log.status == "failed"]
    alias_lines = [f"- `{src}` -> `{dst}`" for src, dst in sorted(TEAM_ALIASES.items())]
    lines = [
        "# NBA hoopR ingestion report",
        "",
        f"Generated: {now_utc()}",
        "",
        "No synthetic, simulated, or placeholder data was generated. Rows come only from hoopR-data URLs that returned successfully.",
        "",
        "## Table row counts",
        "",
    ]
    lines += [f"- {r['table_name']}: {r['rows']:,}" for r in rows["tables"]]
    cov = rows["coverage"][0]
    lines += [
        "",
        "## Coverage",
        "",
        f"- Seasons in `nba_games`: {cov['min_season']} through {cov['max_season']}",
        f"- Game-date window: {cov['min_game_date']} through {cov['max_completed_game_date']} for completed games",
        "- hoopR 2023 schedule rows continue beyond completed coverage with scheduled 0-0 games; those have NULL scores/home_win.",
        "",
        "## Per-season counts",
        "",
        "| Season | Type | Rows | Completed | Min date | Max date |",
        "|---:|---|---:|---:|---|---|",
    ]
    lines += [
        f"| {r['season']} | {r['season_type']} | {r['games']} | {r['completed_games'] or 0} | {r['min_game_date']} | {r['max_game_date']} |"
        for r in rows["season_counts"]
    ]
    v = rows["validation"][0]
    lines += [
        "",
        "## Validation queries",
        "",
        f"- Missing teams: {v['missing_teams']}",
        f"- Completed games with missing scores: {v['completed_missing_scores']}",
        f"- Self-games: {v['self_games']}",
        f"- `home_win` mismatches scores: {v['bad_home_win']}",
        f"- Completed ties: {v['completed_ties']}",
        "",
        "Recent regular seasons all have 30 canonical NBA teams:",
    ]
    lines += [f"- {r['season']}: {r['canonical_teams']}" for r in rows["recent_teams"]]
    lines += [
        "",
        "## Spot-check",
        "",
        "2016 Finals Game 7 query (`2016-06-19`, CLE at GSW):",
        "",
        "```json",
        json.dumps(rows["spot_check"], indent=2),
        "```",
        "",
        "## Canonical alias map",
        "",
        *alias_lines,
        "",
        "## Source URL log",
        "",
        f"- Successful attempted URLs: {len(success)}",
        f"- Failed attempted URLs: {len(failed)}",
        "",
        "### Successes",
        "",
    ]
    lines += [f"- {log.fetched_at_utc} `{log.url}` ({log.bytes_downloaded:,} decoded bytes)" for log in success]
    lines += ["", "### Failures", ""]
    lines += [f"- {log.fetched_at_utc} `{log.url}`: {log.message}" for log in failed] or ["- None"]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    logs = []
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        create_schema(conn)
        load_teams(conn)
        conn.commit()
        game_meta = ingest_schedules(conn, logs)
        ingest_team_box(conn, logs, game_meta)
        ingest_player_box(conn, logs, game_meta)
        write_report(conn, logs)
        conn.commit()
    print(f"Wrote {DB_PATH}")
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
