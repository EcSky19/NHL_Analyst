import datetime as dt
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "mlb" / "mlb_research.db"
REPORT_PATH = ROOT / "data" / "reports" / "mlb_ingestion_report.md"
START_SEASON = 2015
END_SEASON = 2026
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
BASE = "https://statsapi.mlb.com/api/v1"

GAME_TYPE_MAP = {
    "R": "regular",
    "S": "spring",
    "E": "exhibition",
    "A": "all_star",
    "F": "postseason",
    "D": "postseason",
    "L": "postseason",
    "W": "postseason",
}


def now_utc():
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if v == "" or v.upper() in {"NA", "N/A", "NULL", "-"}:
            return None
    return v


def as_int(v):
    v = clean(v)
    if v is None:
        return None
    return int(float(v))


def as_float(v):
    v = clean(v)
    if v is None:
        return None
    return float(v)


def endpoint(path, **params):
    qs = urllib.parse.urlencode(params)
    return f"{BASE}{path}?{qs}" if qs else f"{BASE}{path}"


def fetch_json(url, fetch_logs, retries=4):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as response:
                raw = response.read()
                fetched_at = now_utc()
                fetch_logs.append((url, "success", response.status, len(raw), fetched_at, None))
                return json.loads(raw.decode("utf-8")), fetched_at
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.reason}"
            retryable = exc.code == 429 or 500 <= exc.code <= 599
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = repr(exc)
            retryable = True
        if attempt < retries and retryable:
            time.sleep(min(30, 2 ** attempt))
        else:
            break
    fetch_logs.append((url, "failed", None, 0, now_utc(), last_error))
    return None, None


def month_windows(year):
    for month in range(1, 13):
        start = dt.date(year, month, 1)
        if month == 12:
            end = dt.date(year, 12, 31)
        else:
            end = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
        yield start.isoformat(), end.isoformat()


def create_schema(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mlb_teams (
            season INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            abbreviation TEXT,
            full_name TEXT,
            team_name TEXT,
            location_name TEXT,
            league TEXT,
            division TEXT,
            venue TEXT,
            active INTEGER,
            data_source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (season, team_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mlb_games (
            game_pk INTEGER PRIMARY KEY,
            season INTEGER NOT NULL,
            game_date TEXT,
            game_datetime_utc TEXT,
            game_type_code TEXT,
            game_type TEXT,
            home_team_id INTEGER,
            away_team_id INTEGER,
            home_team TEXT,
            away_team TEXT,
            home_team_name TEXT,
            away_team_name TEXT,
            home_score INTEGER,
            away_score INTEGER,
            home_win INTEGER,
            status TEXT,
            status_code TEXT,
            abstract_game_state TEXT,
            doubleheader TEXT,
            game_number INTEGER,
            venue TEXT,
            is_tie INTEGER,
            data_source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mlb_team_season_stats (
            season INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            abbreviation TEXT,
            team_name TEXT,
            hitting_games_played INTEGER,
            runs INTEGER,
            hits INTEGER,
            doubles INTEGER,
            triples INTEGER,
            home_runs INTEGER,
            rbi INTEGER,
            stolen_bases INTEGER,
            caught_stealing INTEGER,
            base_on_balls INTEGER,
            strike_outs INTEGER,
            avg REAL,
            obp REAL,
            slg REAL,
            ops REAL,
            pitching_games_played INTEGER,
            pitching_runs INTEGER,
            pitching_hits INTEGER,
            pitching_home_runs INTEGER,
            pitching_era REAL,
            pitching_whip REAL,
            pitching_strike_outs INTEGER,
            pitching_base_on_balls INTEGER,
            pitching_saves INTEGER,
            pitching_save_opportunities INTEGER,
            pitching_blown_saves INTEGER,
            pitching_earned_runs INTEGER,
            pitching_wins INTEGER,
            pitching_losses INTEGER,
            pitching_innings_pitched TEXT,
            pitching_strikeouts_per_9 REAL,
            pitching_walks_per_9 REAL,
            pitching_hits_per_9 REAL,
            hitting_stats_json TEXT,
            pitching_stats_json TEXT,
            data_source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (season, team_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mlb_player_season_stats (
            season INTEGER NOT NULL,
            group_name TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            player_name TEXT,
            team_id INTEGER,
            team_name TEXT,
            team_abbreviation TEXT,
            league TEXT,
            position TEXT,
            rank INTEGER,
            games_played INTEGER,
            runs INTEGER,
            hits INTEGER,
            doubles INTEGER,
            triples INTEGER,
            home_runs INTEGER,
            rbi INTEGER,
            stolen_bases INTEGER,
            avg REAL,
            obp REAL,
            slg REAL,
            ops REAL,
            wins INTEGER,
            losses INTEGER,
            saves INTEGER,
            era REAL,
            whip REAL,
            innings_pitched TEXT,
            strike_outs INTEGER,
            base_on_balls INTEGER,
            earned_runs INTEGER,
            stats_json TEXT,
            data_source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (season, group_name, player_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mlb_standings (
            season INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            team_abbreviation TEXT,
            team_name TEXT,
            league TEXT,
            division TEXT,
            games_played INTEGER,
            wins INTEGER,
            losses INTEGER,
            winning_percentage REAL,
            runs_scored INTEGER,
            runs_allowed INTEGER,
            run_differential INTEGER,
            division_rank TEXT,
            league_rank TEXT,
            sport_rank TEXT,
            data_source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL,
            PRIMARY KEY (season, team_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mlb_seasons (
            season INTEGER PRIMARY KEY,
            season_state TEXT NOT NULL,
            complete INTEGER NOT NULL,
            note TEXT,
            data_source TEXT NOT NULL,
            fetched_at_utc TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mlb_fetch_log (
            url TEXT NOT NULL,
            status TEXT NOT NULL,
            http_status INTEGER,
            bytes_downloaded INTEGER,
            fetched_at_utc TEXT NOT NULL,
            message TEXT
        )
    """)
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_mlb_games_season ON mlb_games(season)",
        "CREATE INDEX IF NOT EXISTS idx_mlb_games_date ON mlb_games(game_date)",
        "CREATE INDEX IF NOT EXISTS idx_mlb_games_home_away ON mlb_games(home_team, away_team)",
        "CREATE INDEX IF NOT EXISTS idx_mlb_games_team_ids ON mlb_games(home_team_id, away_team_id)",
        "CREATE INDEX IF NOT EXISTS idx_mlb_team_stats_season ON mlb_team_season_stats(season)",
        "CREATE INDEX IF NOT EXISTS idx_mlb_team_stats_team ON mlb_team_season_stats(team_id)",
        "CREATE INDEX IF NOT EXISTS idx_mlb_player_stats_season ON mlb_player_season_stats(season)",
        "CREATE INDEX IF NOT EXISTS idx_mlb_player_stats_player ON mlb_player_season_stats(player_id)",
        "CREATE INDEX IF NOT EXISTS idx_mlb_player_stats_team ON mlb_player_season_stats(team_id)",
        "CREATE INDEX IF NOT EXISTS idx_mlb_teams_season ON mlb_teams(season)",
    ]
    for sql in indexes:
        conn.execute(sql)


def division_short(name):
    if not name:
        return None
    for suffix in ("East", "Central", "West"):
        if name.endswith(suffix):
            return suffix
    return name


def league_short(name):
    if not name:
        return None
    if "American" in name or name == "AL":
        return "American"
    if "National" in name or name == "NL":
        return "National"
    return name


def stat_num(stat, key, typ="int"):
    if typ == "float":
        return as_float(stat.get(key))
    return as_int(stat.get(key))


def upsert_teams(conn, season, data, url, fetched_at):
    rows = []
    for t in data.get("teams", []):
        league = league_short((t.get("league") or {}).get("name"))
        division = division_short((t.get("division") or {}).get("name"))
        rows.append((season, t.get("id"), t.get("abbreviation"), t.get("name"), t.get("teamName"),
                     t.get("locationName"), league, division, (t.get("venue") or {}).get("name"),
                     1 if t.get("active") else 0, url, fetched_at))
    conn.executemany("""
        INSERT OR REPLACE INTO mlb_teams
        (season, team_id, abbreviation, full_name, team_name, location_name, league, division, venue, active, data_source, fetched_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)


def upsert_schedule(conn, data, url, fetched_at, completed_only=False):
    team_lookup = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT team_id, abbreviation, full_name FROM mlb_teams")}
    rows = []
    for date_block in data.get("dates", []):
        for g in date_block.get("games", []):
            away = (g.get("teams") or {}).get("away") or {}
            home = (g.get("teams") or {}).get("home") or {}
            away_team = away.get("team") or {}
            home_team = home.get("team") or {}
            away_id, home_id = away_team.get("id"), home_team.get("id")
            away_abbr, away_name = team_lookup.get(away_id, (None, away_team.get("name")))
            home_abbr, home_name = team_lookup.get(home_id, (None, home_team.get("name")))
            status = g.get("status") or {}
            status_text = status.get("detailedState") or status.get("abstractGameState")
            status_code = status.get("statusCode") or status.get("codedGameState")
            final = (status.get("abstractGameState") == "Final") or (status_code in {"F", "O"})
            home_score = as_int(home.get("score"))
            away_score = as_int(away.get("score"))
            completed_final = final and home_score is not None and away_score is not None
            if completed_only and not completed_final:
                continue
            home_win = None
            if completed_final and home_score != away_score:
                home_win = 1 if home_score > away_score else 0
            code = g.get("gameType")
            abstract_state = "Final" if completed_final else (status_text or status.get("abstractGameState"))
            rows.append((
                g.get("gamePk"), as_int(g.get("season")), g.get("officialDate"), g.get("gameDate"),
                code, GAME_TYPE_MAP.get(code, "postseason" if code in {"C", "P"} else "other"),
                home_id, away_id, home_abbr, away_abbr, home_name, away_name, home_score, away_score,
                home_win, status_text, status_code, abstract_state, g.get("doubleHeader"),
                as_int(g.get("gameNumber")), (g.get("venue") or {}).get("name"), 1 if g.get("isTie") else 0,
                url, fetched_at
            ))
    conn.executemany("""
        INSERT OR REPLACE INTO mlb_games
        (game_pk, season, game_date, game_datetime_utc, game_type_code, game_type, home_team_id, away_team_id,
         home_team, away_team, home_team_name, away_team_name, home_score, away_score, home_win, status,
         status_code, abstract_game_state, doubleheader, game_number, venue, is_tie, data_source, fetched_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)


def extract_team_stat_split(data):
    for block in data.get("stats", []):
        splits = block.get("splits") or []
        if splits:
            return splits[0].get("stat") or {}
    return {}


def upsert_team_stats(conn, season, team_id, hitting, pitching, data_source, fetched_at):
    team = conn.execute("SELECT abbreviation, full_name FROM mlb_teams WHERE season=? AND team_id=?", (season, team_id)).fetchone()
    abbr, name = team if team else (None, None)
    h, p = hitting or {}, pitching or {}
    conn.execute("""
        INSERT OR REPLACE INTO mlb_team_season_stats
        (season, team_id, abbreviation, team_name, hitting_games_played, runs, hits, doubles, triples, home_runs,
         rbi, stolen_bases, caught_stealing, base_on_balls, strike_outs, avg, obp, slg, ops,
         pitching_games_played, pitching_runs, pitching_hits, pitching_home_runs, pitching_era, pitching_whip,
         pitching_strike_outs, pitching_base_on_balls, pitching_saves, pitching_save_opportunities, pitching_blown_saves,
         pitching_earned_runs, pitching_wins, pitching_losses, pitching_innings_pitched, pitching_strikeouts_per_9,
         pitching_walks_per_9, pitching_hits_per_9, hitting_stats_json, pitching_stats_json, data_source, fetched_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        season, team_id, abbr, name, stat_num(h, "gamesPlayed"), stat_num(h, "runs"), stat_num(h, "hits"),
        stat_num(h, "doubles"), stat_num(h, "triples"), stat_num(h, "homeRuns"), stat_num(h, "rbi"),
        stat_num(h, "stolenBases"), stat_num(h, "caughtStealing"), stat_num(h, "baseOnBalls"), stat_num(h, "strikeOuts"),
        stat_num(h, "avg", "float"), stat_num(h, "obp", "float"), stat_num(h, "slg", "float"), stat_num(h, "ops", "float"),
        stat_num(p, "gamesPlayed"), stat_num(p, "runs"), stat_num(p, "hits"), stat_num(p, "homeRuns"),
        stat_num(p, "era", "float"), stat_num(p, "whip", "float"), stat_num(p, "strikeOuts"), stat_num(p, "baseOnBalls"),
        stat_num(p, "saves"), stat_num(p, "saveOpportunities"), stat_num(p, "blownSaves"), stat_num(p, "earnedRuns"),
        stat_num(p, "wins"), stat_num(p, "losses"), clean(p.get("inningsPitched")), stat_num(p, "strikeoutsPer9Inn", "float"),
        stat_num(p, "walksPer9Inn", "float"), stat_num(p, "hitsPer9Inn", "float"), json.dumps(h, sort_keys=True),
        json.dumps(p, sort_keys=True), data_source, fetched_at
    ))


def upsert_player_stats(conn, season, group_name, data, url, fetched_at):
    team_lookup = {row[0]: row[1] for row in conn.execute("SELECT team_id, abbreviation FROM mlb_teams WHERE season=?", (season,))}
    rows = []
    for block in data.get("stats", []):
        for split in block.get("splits") or []:
            stat = split.get("stat") or {}
            player = split.get("player") or {}
            team = split.get("team") or {}
            team_id = team.get("id")
            rows.append((
                season, group_name, player.get("id"), player.get("fullName"), team_id, team.get("name"), team_lookup.get(team_id),
                league_short((split.get("league") or {}).get("name")), (split.get("position") or {}).get("abbreviation"), as_int(split.get("rank")),
                stat_num(stat, "gamesPlayed"), stat_num(stat, "runs"), stat_num(stat, "hits"), stat_num(stat, "doubles"),
                stat_num(stat, "triples"), stat_num(stat, "homeRuns"), stat_num(stat, "rbi"), stat_num(stat, "stolenBases"),
                stat_num(stat, "avg", "float"), stat_num(stat, "obp", "float"), stat_num(stat, "slg", "float"),
                stat_num(stat, "ops", "float"), stat_num(stat, "wins"), stat_num(stat, "losses"), stat_num(stat, "saves"),
                stat_num(stat, "era", "float"), stat_num(stat, "whip", "float"), clean(stat.get("inningsPitched")),
                stat_num(stat, "strikeOuts"), stat_num(stat, "baseOnBalls"), stat_num(stat, "earnedRuns"),
                json.dumps(stat, sort_keys=True), url, fetched_at
            ))
    conn.executemany("""
        INSERT OR REPLACE INTO mlb_player_season_stats
        (season, group_name, player_id, player_name, team_id, team_name, team_abbreviation, league, position, rank,
         games_played, runs, hits, doubles, triples, home_runs, rbi, stolen_bases, avg, obp, slg, ops,
         wins, losses, saves, era, whip, innings_pitched, strike_outs, base_on_balls, earned_runs,
         stats_json, data_source, fetched_at_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)


def upsert_standings(conn, season, data, url, fetched_at):
    rows = []
    for rec in data.get("records", []):
        league = league_short((rec.get("league") or {}).get("name"))
        division = division_short((rec.get("division") or {}).get("name"))
        for tr in rec.get("teamRecords") or []:
            team = tr.get("team") or {}
            rows.append((
                season, team.get("id"), None, team.get("name"), league, division, stat_num(tr, "gamesPlayed"), stat_num(tr, "wins"),
                stat_num(tr, "losses"), as_float(tr.get("winningPercentage")), stat_num(tr, "runsScored"), stat_num(tr, "runsAllowed"),
                stat_num(tr, "runDifferential"), clean(tr.get("divisionRank")), clean(tr.get("leagueRank")), clean(tr.get("sportRank")),
                url, fetched_at
            ))
    conn.executemany("""
        INSERT OR REPLACE INTO mlb_standings
        (season, team_id, team_abbreviation, team_name, league, division, games_played, wins, losses, winning_percentage,
         runs_scored, runs_allowed, run_differential, division_rank, league_rank, sport_rank, data_source, fetched_at_utc)
        VALUES (?, ?, (SELECT abbreviation FROM mlb_teams WHERE season=? AND team_id=?), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [(r[0], r[1], r[0], r[1], *r[3:]) for r in rows])


def run_ingest():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fetch_logs = []
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        create_schema(conn)
        with conn:
            conn.execute("DELETE FROM mlb_fetch_log")
        for season in range(START_SEASON, END_SEASON + 1):
            print(f"Ingesting MLB season {season} teams/standings/schedule", flush=True)
            teams_url = endpoint("/teams", sportId=1, season=season)
            teams_data, fetched_at = fetch_json(teams_url, fetch_logs)
            if teams_data:
                with conn:
                    upsert_teams(conn, season, teams_data, teams_url, fetched_at)

            standings_url = endpoint("/standings", leagueId="103,104", season=season)
            standings_data, standings_at = fetch_json(standings_url, fetch_logs)
            if standings_data:
                with conn:
                    upsert_standings(conn, season, standings_data, standings_url, standings_at)

            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO mlb_seasons
                    (season, season_state, complete, note, data_source, fetched_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    season,
                    "regular" if season == END_SEASON else "completed",
                    0 if season == END_SEASON else 1,
                    "In-progress season; only completed games are retained." if season == END_SEASON else None,
                    standings_url,
                    standings_at or now_utc(),
                ))
                if season == END_SEASON:
                    conn.execute("""
                        DELETE FROM mlb_games
                        WHERE season=?
                          AND (abstract_game_state != 'Final' OR home_score IS NULL OR away_score IS NULL)
                    """, (season,))

            for start, end in month_windows(season):
                sched_url = endpoint("/schedule", sportId=1, startDate=start, endDate=end)
                sched_data, sched_at = fetch_json(sched_url, fetch_logs)
                if sched_data:
                    with conn:
                        upsert_schedule(conn, sched_data, sched_url, sched_at, completed_only=(season == END_SEASON))
                time.sleep(0.05)

            team_ids = [row[0] for row in conn.execute("SELECT team_id FROM mlb_teams WHERE season=? AND active=1 ORDER BY team_id", (season,))]
            for team_id in team_ids:
                hit_url = endpoint(f"/teams/{team_id}/stats", stats="season", season=season, group="hitting")
                pitch_url = endpoint(f"/teams/{team_id}/stats", stats="season", season=season, group="pitching")
                hit_data, hit_at = fetch_json(hit_url, fetch_logs)
                pitch_data, pitch_at = fetch_json(pitch_url, fetch_logs)
                if hit_data or pitch_data:
                    with conn:
                        upsert_team_stats(conn, season, team_id, extract_team_stat_split(hit_data or {}), extract_team_stat_split(pitch_data or {}), f"{hit_url} ; {pitch_url}", pitch_at or hit_at or now_utc())
                time.sleep(0.05)

            for group in ("hitting", "pitching"):
                leaders_url = endpoint("/stats", stats="season", group=group, season=season, sportId=1, limit=1000)
                leaders_data, leaders_at = fetch_json(leaders_url, fetch_logs)
                if leaders_data:
                    with conn:
                        upsert_player_stats(conn, season, group, leaders_data, leaders_url, leaders_at)
                time.sleep(0.05)

        with conn:
            conn.executemany("INSERT INTO mlb_fetch_log VALUES (?, ?, ?, ?, ?, ?)", fetch_logs)
        write_report(conn, fetch_logs)
    finally:
        conn.close()


def q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def markdown_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return "\n".join(out)


def write_report(conn, fetch_logs):
    generated = now_utc()
    counts = q(conn, """
        SELECT 'mlb_games', COUNT(*) FROM mlb_games UNION ALL
        SELECT 'mlb_team_season_stats', COUNT(*) FROM mlb_team_season_stats UNION ALL
        SELECT 'mlb_player_season_stats', COUNT(*) FROM mlb_player_season_stats UNION ALL
        SELECT 'mlb_teams', COUNT(*) FROM mlb_teams UNION ALL
        SELECT 'mlb_standings', COUNT(*) FROM mlb_standings UNION ALL
        SELECT 'mlb_seasons', COUNT(*) FROM mlb_seasons
    """)
    season_counts = q(conn, """
        SELECT season, game_type, COUNT(*) AS rows,
               SUM(CASE WHEN abstract_game_state='Final' AND home_score IS NOT NULL AND away_score IS NOT NULL THEN 1 ELSE 0 END) AS completed,
               MIN(game_date), MAX(game_date)
        FROM mlb_games GROUP BY season, game_type ORDER BY season, game_type
    """)
    reg_counts = q(conn, """
        SELECT season, COUNT(*) AS regular_rows,
               SUM(CASE WHEN abstract_game_state='Final' AND home_score IS NOT NULL AND away_score IS NOT NULL THEN 1 ELSE 0 END) AS completed_regular
        FROM mlb_games WHERE game_type='regular' GROUP BY season ORDER BY season
    """)
    validation = q(conn, """
        SELECT 'final games with missing scores', COUNT(*) FROM mlb_games WHERE abstract_game_state='Final' AND (home_score IS NULL OR away_score IS NULL)
        UNION ALL SELECT 'home_win score mismatches', COUNT(*) FROM mlb_games WHERE abstract_game_state='Final' AND home_score IS NOT NULL AND away_score IS NOT NULL AND home_score != away_score AND home_win != CASE WHEN home_score > away_score THEN 1 ELSE 0 END
        UNION ALL SELECT 'self-games', COUNT(*) FROM mlb_games WHERE home_team_id=away_team_id
        UNION ALL SELECT 'recent seasons with not 30 active teams', COUNT(*) FROM (SELECT season, COUNT(DISTINCT team_id) c FROM mlb_teams WHERE season BETWEEN 2019 AND 2026 AND active=1 GROUP BY season HAVING c != 30)
        UNION ALL SELECT 'failed fetches', COUNT(*) FROM mlb_fetch_log WHERE status='failed'
    """)
    team_counts = q(conn, "SELECT season, COUNT(DISTINCT team_id) FROM mlb_teams WHERE active=1 GROUP BY season ORDER BY season")
    doubleheader = q(conn, """
        SELECT season, game_date, away_team, home_team, COUNT(*) AS games,
               GROUP_CONCAT(game_pk, ', ') AS game_pks,
               GROUP_CONCAT(away_score || '-' || home_score, ', ') AS away_home_scores
        FROM mlb_games
        WHERE game_type='regular'
        GROUP BY season, game_date, away_team, home_team
        HAVING COUNT(*) >= 2
        ORDER BY season DESC, game_date DESC
        LIMIT 5
    """)
    ws = q(conn, """
        SELECT game_pk, season, game_date, away_team, away_score, home_team, home_score, home_win, venue, status
        FROM mlb_games
        WHERE season=2025 AND game_type='postseason' AND game_type_code='W'
        ORDER BY game_date DESC, game_pk DESC LIMIT 1
    """)
    failures = q(conn, "SELECT url, message FROM mlb_fetch_log WHERE status='failed' ORDER BY fetched_at_utc LIMIT 20")
    lines = [
        "# MLB ingestion report", "", f"Generated: {generated}", "",
        "No synthetic, simulated, or placeholder data was generated. Rows come only from official MLB StatsAPI responses that returned successfully.", "",
        "## Table row counts", "", markdown_table(["Table", "Rows"], counts), "",
        "## Regular-season game counts", "", markdown_table(["Season", "Regular rows", "Completed regular"], reg_counts), "",
        "Notes: a modern full MLB regular season is usually 2,430 games; 2020 is the COVID-shortened season, and 2026 is in progress as of this ingest.", "",
        "## All game rows by season/type", "", markdown_table(["Season", "Type", "Rows", "Completed", "Min date", "Max date"], season_counts), "",
        "## Active MLB teams by season", "", markdown_table(["Season", "Active teams"], team_counts), "",
        "## Validation queries", "", markdown_table(["Check", "Count"], validation), "",
        "## Doubleheader preservation check", "", markdown_table(["Season", "Date", "Away", "Home", "Rows", "Game PKs", "Away-home scores"], doubleheader), "",
        "## World Series spot-check", "",
        "Famous-result spot-check using the final game of the 2025 World Series (Dodgers at Blue Jays).", "",
        markdown_table(["game_pk", "season", "date", "away", "away_score", "home", "home_score", "home_win", "venue", "status"], ws), "",
        "## Fetch failures", "",
    ]
    if failures:
        lines.append(markdown_table(["URL", "Message"], failures))
    else:
        lines.append("No failed fetches recorded.")
    lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    run_ingest()
    print(f"Wrote {DB_PATH}")
    print(f"Wrote {REPORT_PATH}")
