import csv
import datetime as dt
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path
from statistics import mean

SOURCE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
ROOT = Path(__file__).resolve().parents[2]
NFL_DIR = ROOT / "data" / "nfl"
REPORT_DIR = ROOT / "data" / "reports"
DB_PATH = NFL_DIR / "nfl_research.db"
RAW_PATH = NFL_DIR / "games.csv"
REPORT_PATH = REPORT_DIR / "nfl_ingestion_report.md"

EXPECTED_COLUMNS = [
    "game_id", "season", "game_type", "week", "gameday", "weekday", "gametime", "away_team", "away_score", "home_team", "home_score",
    "location", "result", "total", "overtime", "old_game_id", "gsis", "nfl_detail_id", "pfr", "pff", "espn", "ftn",
    "away_rest", "home_rest", "away_moneyline", "home_moneyline", "spread_line", "away_spread_odds", "home_spread_odds",
    "total_line", "under_odds", "over_odds", "div_game", "roof", "surface", "temp", "wind",
    "away_qb_id", "home_qb_id", "away_qb_name", "home_qb_name", "away_coach", "home_coach", "referee", "stadium_id", "stadium",
]

TYPE_MAP = {
    "season": "INTEGER", "week": "INTEGER", "away_score": "INTEGER", "home_score": "INTEGER", "overtime": "INTEGER",
    "away_rest": "INTEGER", "home_rest": "INTEGER", "div_game": "INTEGER",
    "result": "REAL", "total": "REAL", "away_moneyline": "REAL", "home_moneyline": "REAL", "spread_line": "REAL",
    "away_spread_odds": "REAL", "home_spread_odds": "REAL", "total_line": "REAL", "under_odds": "REAL", "over_odds": "REAL",
    "temp": "REAL", "wind": "REAL",
}

TEAM_ALIASES = [
    ("ARI", "ARI", "Arizona Cardinals"), ("ATL", "ATL", "Atlanta Falcons"), ("BAL", "BAL", "Baltimore Ravens"),
    ("BUF", "BUF", "Buffalo Bills"), ("CAR", "CAR", "Carolina Panthers"), ("CHI", "CHI", "Chicago Bears"),
    ("CIN", "CIN", "Cincinnati Bengals"), ("CLE", "CLE", "Cleveland Browns"), ("DAL", "DAL", "Dallas Cowboys"),
    ("DEN", "DEN", "Denver Broncos"), ("DET", "DET", "Detroit Lions"), ("GB", "GB", "Green Bay Packers"),
    ("HOU", "HOU", "Houston Texans"), ("IND", "IND", "Indianapolis Colts"), ("JAC", "JAX", "Jacksonville Jaguars alias"),
    ("JAX", "JAX", "Jacksonville Jaguars"), ("KC", "KC", "Kansas City Chiefs"), ("LA", "LAR", "Los Angeles Rams alias"),
    ("LAR", "LAR", "Los Angeles Rams"), ("STL", "LAR", "St. Louis Rams historical alias"),
    ("SD", "LAC", "San Diego Chargers historical alias"), ("LAC", "LAC", "Los Angeles Chargers"),
    ("OAK", "LV", "Oakland Raiders historical alias"), ("LV", "LV", "Las Vegas Raiders"),
    ("MIA", "MIA", "Miami Dolphins"), ("MIN", "MIN", "Minnesota Vikings"), ("NE", "NE", "New England Patriots"),
    ("NO", "NO", "New Orleans Saints"), ("NYG", "NYG", "New York Giants"), ("NYJ", "NYJ", "New York Jets"),
    ("PHI", "PHI", "Philadelphia Eagles"), ("PIT", "PIT", "Pittsburgh Steelers"), ("SEA", "SEA", "Seattle Seahawks"),
    ("SF", "SF", "San Francisco 49ers"), ("TB", "TB", "Tampa Bay Buccaneers"), ("TEN", "TEN", "Tennessee Titans"),
    ("WAS", "WAS", "Washington historical/source code"), ("WSH", "WAS", "Washington alias"),
]
ALIAS_MAP = {a: n for a, n, _ in TEAM_ALIASES}


def clean(v):
    if v is None:
        return None
    v = v.strip()
    return None if v == "" or v.upper() == "NA" else v


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


def convert(col, val):
    if TYPE_MAP.get(col) == "INTEGER":
        return as_int(val)
    if TYPE_MAP.get(col) == "REAL":
        return as_float(val)
    return clean(val)


def pct(num, den):
    return None if den == 0 else 100.0 * num / den


def fmt_pct(x):
    return "n/a" if x is None else f"{x:.2f}%"


def download():
    NFL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"download failed: HTTP {response.status}")
        data = response.read()
    RAW_PATH.write_bytes(data)
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(), len(data)


def load_csv(downloaded_at):
    with RAW_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise RuntimeError(f"Unexpected columns. Got {reader.fieldnames}")
        rows = list(reader)

    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    original_cols = [f'"{c}" {TYPE_MAP.get(c, "TEXT")}' for c in EXPECTED_COLUMNS]
    derived_cols = [
        '"source_url" TEXT NOT NULL', '"downloaded_at_utc" TEXT NOT NULL',
        '"played" INTEGER NOT NULL', '"unplayed" INTEGER NOT NULL', '"tie_game" INTEGER NOT NULL',
        '"home_win" INTEGER', '"season_phase" TEXT NOT NULL', '"is_preseason" INTEGER NOT NULL',
        '"is_regular_season" INTEGER NOT NULL', '"is_postseason" INTEGER NOT NULL',
        '"away_team_normalized" TEXT', '"home_team_normalized" TEXT',
        '"unknown_team_alias" INTEGER NOT NULL', '"data_quality_notes" TEXT',
    ]
    conn.execute(f"CREATE TABLE games ({', '.join(original_cols + derived_cols)})")
    conn.execute("""
        CREATE TABLE team_alias_map (
            source_team TEXT PRIMARY KEY,
            normalized_team TEXT NOT NULL,
            description TEXT NOT NULL
        )
    """)
    conn.executemany("INSERT INTO team_alias_map VALUES (?, ?, ?)", TEAM_ALIASES)

    insert_cols = EXPECTED_COLUMNS + [
        "source_url", "downloaded_at_utc", "played", "unplayed", "tie_game", "home_win", "season_phase", "is_preseason",
        "is_regular_season", "is_postseason", "away_team_normalized", "home_team_normalized", "unknown_team_alias", "data_quality_notes",
    ]
    placeholders = ",".join("?" for _ in insert_cols)
    insert_sql = f"INSERT INTO games ({','.join('"'+c+'"' for c in insert_cols)}) VALUES ({placeholders})"

    out = []
    for r in rows:
        converted = {c: convert(c, r[c]) for c in EXPECTED_COLUMNS}
        away = converted["away_team"]
        home = converted["home_team"]
        away_norm = ALIAS_MAP.get(away)
        home_norm = ALIAS_MAP.get(home)
        unknown = int(away_norm is None or home_norm is None)
        game_type = converted["game_type"]
        if game_type == "PRE":
            phase = "PRE"
        elif game_type == "REG":
            phase = "REG"
        else:
            phase = "POST"
        scores_present = converted["away_score"] is not None and converted["home_score"] is not None and converted["result"] is not None
        played = int(scores_present)
        result = converted["result"]
        tie = int(scores_present and float(result) == 0.0)
        home_win = None
        if scores_present and not tie:
            home_win = int(float(result) > 0.0)
        notes = []
        if not scores_present:
            notes.append("unplayed_or_missing_score")
        if tie:
            notes.append("tie_excluded_from_binary_home_win")
        if unknown:
            notes.append("unknown_team_alias")
        if phase == "PRE":
            notes.append("preseason_flagged_exclude_from_training")
        out.append([converted[c] for c in EXPECTED_COLUMNS] + [
            SOURCE_URL, downloaded_at, played, int(not played), tie, home_win, phase,
            int(phase == "PRE"), int(phase == "REG"), int(phase == "POST"),
            away_norm, home_norm, unknown, ";".join(notes) if notes else None,
        ])
    conn.executemany(insert_sql, out)
    conn.execute("CREATE INDEX idx_games_season ON games(season)")
    conn.execute("CREATE INDEX idx_games_phase ON games(season_phase)")
    conn.execute("CREATE INDEX idx_games_played ON games(played)")

    conn.execute("""
        CREATE TABLE season_team_validation AS
        WITH teams AS (
            SELECT season, away_team_normalized AS team FROM games WHERE away_team_normalized IS NOT NULL
            UNION
            SELECT season, home_team_normalized AS team FROM games WHERE home_team_normalized IS NOT NULL
        )
        SELECT season,
               COUNT(DISTINCT team) AS normalized_distinct_teams,
               CASE WHEN season BETWEEN 1999 AND 2001 THEN 31 ELSE 32 END AS expected_distinct_teams,
               CASE WHEN COUNT(DISTINCT team) = CASE WHEN season BETWEEN 1999 AND 2001 THEN 31 ELSE 32 END THEN 1 ELSE 0 END AS team_count_ok
        FROM teams
        GROUP BY season
        ORDER BY season
    """)
    conn.execute("""
        CREATE TABLE season_quality AS
        SELECT season,
               COUNT(*) AS games,
               SUM(CASE WHEN season_phase='REG' THEN 1 ELSE 0 END) AS reg_games,
               SUM(CASE WHEN season_phase='POST' THEN 1 ELSE 0 END) AS post_games,
               SUM(CASE WHEN season_phase='PRE' THEN 1 ELSE 0 END) AS pre_games,
               SUM(played) AS played_games,
               SUM(unplayed) AS unplayed_games,
               SUM(tie_game) AS ties,
               SUM(CASE WHEN played=1 AND tie_game=0 THEN 1 ELSE 0 END) AS binary_model_games,
               AVG(CASE WHEN played=1 AND tie_game=0 THEN home_win END) AS home_win_rate,
               AVG(CASE WHEN played=1 THEN away_moneyline IS NOT NULL END) AS away_moneyline_coverage,
               AVG(CASE WHEN played=1 THEN home_moneyline IS NOT NULL END) AS home_moneyline_coverage,
               AVG(CASE WHEN played=1 THEN spread_line IS NOT NULL END) AS spread_line_coverage,
               AVG(CASE WHEN played=1 THEN total_line IS NOT NULL END) AS total_line_coverage,
               AVG(CASE WHEN played=1 THEN away_qb_id IS NOT NULL AND home_qb_id IS NOT NULL END) AS qb_id_pair_coverage,
               AVG(CASE WHEN played=1 THEN away_qb_name IS NOT NULL AND home_qb_name IS NOT NULL END) AS qb_name_pair_coverage,
               AVG(CASE WHEN played=1 THEN temp IS NOT NULL END) AS temp_coverage,
               AVG(CASE WHEN played=1 THEN wind IS NOT NULL END) AS wind_coverage
        FROM games
        GROUP BY season
        ORDER BY season
    """)
    conn.execute("""
        CREATE TABLE ingestion_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.executemany("INSERT INTO ingestion_metadata VALUES (?, ?)", [
        ("source_url", SOURCE_URL), ("downloaded_at_utc", downloaded_at), ("raw_file", str(RAW_PATH)),
        ("database", str(DB_PATH)), ("tie_handling", "Ties are flagged with tie_game=1 and home_win=NULL; exclude from binary win/loss modeling."),
    ])
    conn.commit()
    return conn, len(rows)


def q(conn, sql):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql)]


def make_report(conn, row_count, byte_count, downloaded_at):
    seasons = q(conn, "SELECT MIN(season) min_season, MAX(season) max_season, COUNT(DISTINCT season) season_count FROM games")[0]
    overall = q(conn, """
        SELECT COUNT(*) rows, SUM(played) played, SUM(unplayed) unplayed, SUM(tie_game) ties,
               SUM(CASE WHEN played=1 AND tie_game=0 THEN 1 ELSE 0 END) binary_games,
               AVG(CASE WHEN played=1 AND tie_game=0 THEN home_win END) home_win_rate,
               AVG(CASE WHEN played=1 THEN away_moneyline IS NOT NULL END) away_moneyline_coverage,
               AVG(CASE WHEN played=1 THEN home_moneyline IS NOT NULL END) home_moneyline_coverage,
               AVG(CASE WHEN played=1 THEN spread_line IS NOT NULL END) spread_line_coverage,
               AVG(CASE WHEN played=1 THEN total_line IS NOT NULL END) total_line_coverage,
               AVG(CASE WHEN played=1 THEN away_qb_id IS NOT NULL AND home_qb_id IS NOT NULL END) qb_id_pair_coverage,
               AVG(CASE WHEN played=1 THEN away_qb_name IS NOT NULL AND home_qb_name IS NOT NULL END) qb_name_pair_coverage,
               AVG(CASE WHEN played=1 THEN temp IS NOT NULL END) temp_coverage,
               AVG(CASE WHEN played=1 THEN wind IS NOT NULL END) wind_coverage
        FROM games
    """)[0]
    phases = q(conn, "SELECT season_phase, COUNT(*) rows, SUM(played) played, SUM(unplayed) unplayed FROM games GROUP BY season_phase ORDER BY season_phase")
    season_quality = q(conn, "SELECT * FROM season_quality ORDER BY season")
    team_validation = q(conn, "SELECT * FROM season_team_validation ORDER BY season")
    aliases = q(conn, "SELECT * FROM team_alias_map ORDER BY normalized_team, source_team")
    unknown_aliases = q(conn, """
        WITH teams(team) AS (SELECT away_team FROM games UNION SELECT home_team FROM games)
        SELECT team FROM teams WHERE team NOT IN (SELECT source_team FROM team_alias_map) ORDER BY team
    """)

    def md_table(rows, columns, formatters=None):
        if not rows:
            return "(none)\n"
        formatters = formatters or {}
        lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
        for r in rows:
            vals = []
            for c in columns:
                v = r.get(c)
                if c in formatters:
                    v = formatters[c](v)
                elif v is None:
                    v = ""
                vals.append(str(v))
            lines.append("| " + " | ".join(vals) + " |")
        return "\n".join(lines) + "\n"

    rate_cols = {c: (lambda x: fmt_pct(x * 100 if x is not None and x <= 1 else x)) for c in []}
    season_fmt = {
        "home_win_rate": lambda x: fmt_pct(None if x is None else x * 100),
        "away_moneyline_coverage": lambda x: fmt_pct(None if x is None else x * 100),
        "home_moneyline_coverage": lambda x: fmt_pct(None if x is None else x * 100),
        "spread_line_coverage": lambda x: fmt_pct(None if x is None else x * 100),
        "total_line_coverage": lambda x: fmt_pct(None if x is None else x * 100),
        "qb_id_pair_coverage": lambda x: fmt_pct(None if x is None else x * 100),
        "qb_name_pair_coverage": lambda x: fmt_pct(None if x is None else x * 100),
        "temp_coverage": lambda x: fmt_pct(None if x is None else x * 100),
        "wind_coverage": lambda x: fmt_pct(None if x is None else x * 100),
    }

    report = []
    report.append("# NFL ingestion report\n")
    report.append(f"Generated: {dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()}\n")
    report.append("## Source and provenance\n")
    report.append(f"- Source URL: `{SOURCE_URL}`\n")
    report.append(f"- Downloaded at (UTC): `{downloaded_at}`\n")
    report.append(f"- Raw file: `{RAW_PATH}` ({byte_count:,} bytes)\n")
    report.append(f"- SQLite database: `{DB_PATH}`\n")
    report.append(f"- Rows ingested: {row_count:,}\n")
    report.append(f"- Seasons covered: {seasons['min_season']}-{seasons['max_season']} ({seasons['season_count']} seasons)\n")
    report.append("Every `games` row includes `source_url` and `downloaded_at_utc`; no synthetic, simulated, randomized, or imputed game rows were created.\n")

    report.append("## Schema\n")
    report.append("The `games` table preserves every nflverse source column exactly by name and adds explicit derived data-quality/provenance columns. Numeric source columns are stored with SQLite numeric affinity where appropriate; blanks are stored as NULL.\n\n")
    report.append("Derived columns:\n")
    report.append("- `source_url`, `downloaded_at_utc`: row-level provenance.\n")
    report.append("- `played` / `unplayed`: score/result completeness flags. Future or scheduled rows with NULL scores are `unplayed=1` and must be excluded from training/evaluation.\n")
    report.append("- `tie_game`: `1` when `result == 0` on a played game.\n")
    report.append("- `home_win`: binary label for non-tie played games only (`1` if `result > 0`, `0` if `result < 0`, NULL for ties/unplayed).\n")
    report.append("- `season_phase`: `REG`, `POST`, or `PRE`; `is_preseason`, `is_regular_season`, and `is_postseason` are one-hot flags.\n")
    report.append("- `away_team_normalized`, `home_team_normalized`, `unknown_team_alias`, `data_quality_notes`: team-alias and row-quality fields.\n")
    report.append("Additional tables: `team_alias_map`, `season_team_validation`, `season_quality`, and `ingestion_metadata`.\n\n")

    report.append("## Tie handling decision\n")
    report.append(f"NFL regular-season games can end tied. Ties are explicitly flagged and **excluded from binary win/loss modeling** by setting `home_win=NULL`; they are not coerced to home wins/losses. Current tied played games: {overall['ties']:,}.\n\n")

    report.append("## Overall data quality\n")
    report.append(md_table([overall], ["rows", "played", "unplayed", "ties", "binary_games", "home_win_rate", "away_moneyline_coverage", "home_moneyline_coverage", "spread_line_coverage", "total_line_coverage", "qb_id_pair_coverage", "qb_name_pair_coverage", "temp_coverage", "wind_coverage"], season_fmt))
    report.append("\n## Game phase counts\n")
    report.append(md_table(phases, ["season_phase", "rows", "played", "unplayed"]))
    report.append("\n## Per-season coverage and home win rate\n")
    report.append(md_table(season_quality, ["season", "games", "reg_games", "post_games", "pre_games", "played_games", "unplayed_games", "ties", "binary_model_games", "home_win_rate", "away_moneyline_coverage", "home_moneyline_coverage", "spread_line_coverage", "total_line_coverage", "qb_id_pair_coverage", "qb_name_pair_coverage", "temp_coverage", "wind_coverage"], season_fmt))
    report.append("\n## Team normalization and validation\n")
    report.append("Teams are normalized to stable current franchise-style codes before joining. Relocation/rebrand aliases are explicit, including STL/LA/LAR -> LAR, SD/LAC -> LAC, OAK/LV -> LV, WSH/WAS -> WAS, and JAC/JAX -> JAX.\n\n")
    report.append(md_table(team_validation, ["season", "normalized_distinct_teams", "expected_distinct_teams", "team_count_ok"]))
    if unknown_aliases:
        report.append("\n### Unknown team aliases\n")
        report.append(md_table(unknown_aliases, ["team"]))
    report.append("\n### Alias map\n")
    report.append(md_table(aliases, ["source_team", "normalized_team", "description"]))

    report.append("\n## Known gaps and modeling cautions\n")
    report.append("- Betting columns are real nflverse market data and are legitimate pregame predictors, but they are very strong; keep them separated from post-game/in-game fields to avoid leakage.\n")
    report.append("- Older seasons have lower betting/QB/weather coverage; use the per-season table above to choose model cutoffs rather than filling gaps.\n")
    report.append("- Unplayed/future rows are retained for schedule awareness but must never enter training or evaluation.\n")
    report.append("- Preseason rows, if present, are flagged as `PRE`/`is_preseason=1` and should be excluded from outcome modeling unless intentionally analyzed separately.\n")

    REPORT_PATH.write_text("".join(report), encoding="utf-8")

    summary = {
        "rows_ingested": row_count,
        "seasons": f"{seasons['min_season']}-{seasons['max_season']}",
        "season_count": seasons["season_count"],
        "overall_home_win_rate": overall["home_win_rate"],
        "betting_coverage": {
            "away_moneyline": overall["away_moneyline_coverage"],
            "home_moneyline": overall["home_moneyline_coverage"],
            "spread_line": overall["spread_line_coverage"],
            "total_line": overall["total_line_coverage"],
        },
        "ties": overall["ties"],
        "unplayed": overall["unplayed"],
        "unknown_aliases": [r["team"] for r in unknown_aliases],
        "team_validation_failures": [r for r in team_validation if r["team_count_ok"] != 1],
        "report": str(REPORT_PATH),
        "database": str(DB_PATH),
    }
    (NFL_DIR / "ingestion_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    downloaded_at, byte_count = download()
    conn, row_count = load_csv(downloaded_at)
    summary = make_report(conn, row_count, byte_count, downloaded_at)
    conn.close()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        sys.exit(1)
