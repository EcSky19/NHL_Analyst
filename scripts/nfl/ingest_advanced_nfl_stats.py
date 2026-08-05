"""
Ingest real nflverse advanced NFL team and QB weekly performance data.

This script never fabricates or imputes data. If an expected nflverse source is
unavailable, the season/source is recorded as missing rather than synthesized.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "nfl"
RAW_DIR = DATA_DIR / "raw" / "nflverse"
REPORT_DIR = ROOT / "data" / "reports"
DB_PATH = DATA_DIR / "nfl_research.db"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/vnd.github+json,text/html,application/octet-stream,*/*",
}

API_RELEASE = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags/{tag}"
API_CONTENTS = "https://api.github.com/repos/nflverse/nfldata/contents/data?ref=master"
NFDATA_RAW_DIR = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/"
NFDATA_TREE = "https://github.com/nflverse/nfldata/tree/master/data"

START_SEASON = 2010


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "pbp").mkdir(exist_ok=True)
    (RAW_DIR / "stats_team").mkdir(exist_ok=True)
    (RAW_DIR / "stats_player").mkdir(exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_json(url: str) -> dict[str, Any] | list[Any]:
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.json()


def probe_url(url: str) -> tuple[int | None, str]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        resp.close()
        return resp.status_code, "ok" if resp.ok else resp.reason
    except requests.RequestException as exc:
        return None, type(exc).__name__


def get_release_assets(tag: str) -> dict[str, dict[str, Any]]:
    release = fetch_json(API_RELEASE.format(tag=tag))
    return {asset["name"]: asset for asset in release["assets"]}


def download_asset(asset: dict[str, Any], dest_dir: Path) -> Path:
    dest = dest_dir / asset["name"]
    expected_size = int(asset.get("size") or 0)
    if dest.exists() and (expected_size == 0 or dest.stat().st_size == expected_size):
        return dest

    url = asset["browser_download_url"]
    with requests.get(url, headers=HEADERS, timeout=180, stream=True) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)

    if expected_size and dest.stat().st_size != expected_size:
        raise RuntimeError(
            f"Downloaded size mismatch for {url}: got {dest.stat().st_size}, expected {expected_size}"
        )
    return dest


def load_alias_map(con: sqlite3.Connection) -> dict[str, str]:
    aliases: dict[str, str] = {}
    try:
        rows = con.execute("SELECT source_team, normalized_team FROM team_alias_map").fetchall()
        aliases.update({str(src): str(dst) for src, dst in rows})
    except sqlite3.Error:
        pass

    aliases.update(
        {
            "STL": "LAR",
            "LA": "LAR",
            "LAR": "LAR",
            "SD": "LAC",
            "OAK": "LV",
            "JAC": "JAX",
            "WSH": "WAS",
        }
    )
    return aliases


def normalize_team(series: pd.Series, aliases: dict[str, str]) -> pd.Series:
    return series.astype("string").map(lambda x: aliases.get(str(x), str(x)) if pd.notna(x) else pd.NA)


def finite_or_none(value: Any) -> float | int | str | None:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def summarize_offense(group: pd.DataFrame) -> pd.Series:
    is_pass = group["is_pass"]
    is_rush = group["is_rush"]
    third = group["down"].eq(3)
    red_zone = group["yardline_100"].le(20)
    giveaway = group["giveaway"]
    opponents = sorted(x for x in group["defteam_norm"].dropna().unique())

    return pd.Series(
        {
            "game_date": group["game_date"].dropna().max(),
            "season_type": group["season_type"].dropna().iloc[0] if group["season_type"].notna().any() else None,
            "opponents": ",".join(opponents) if opponents else None,
            "n_games": int(group["game_id"].nunique()),
            "offensive_plays": int(len(group)),
            "offensive_epa": group["epa"].sum(),
            "offensive_epa_per_play": group["epa"].mean(),
            "offensive_success_rate": group["success"].mean(),
            "pass_plays": int(is_pass.sum()),
            "pass_epa": group.loc[is_pass, "epa"].sum(),
            "pass_epa_per_play": group.loc[is_pass, "epa"].mean(),
            "pass_success_rate": group.loc[is_pass, "success"].mean(),
            "rush_plays": int(is_rush.sum()),
            "rush_epa": group.loc[is_rush, "epa"].sum(),
            "rush_epa_per_play": group.loc[is_rush, "epa"].mean(),
            "rush_success_rate": group.loc[is_rush, "success"].mean(),
            "third_down_plays": int(third.sum()),
            "third_down_success_rate": group.loc[third, "success"].mean(),
            "red_zone_plays": int(red_zone.sum()),
            "red_zone_success_rate": group.loc[red_zone, "success"].mean(),
            "giveaways": int(giveaway.sum()),
            "giveaway_rate": giveaway.mean(),
        }
    )


def summarize_defense(group: pd.DataFrame) -> pd.Series:
    is_pass = group["is_pass"]
    is_rush = group["is_rush"]
    third = group["down"].eq(3)
    red_zone = group["yardline_100"].le(20)
    takeaway = group["giveaway"]

    return pd.Series(
        {
            "defensive_plays": int(len(group)),
            "defensive_epa_allowed": group["epa"].sum(),
            "defensive_epa_per_play_allowed": group["epa"].mean(),
            "defensive_success_rate_allowed": group["success"].mean(),
            "def_pass_plays": int(is_pass.sum()),
            "def_pass_epa_allowed": group.loc[is_pass, "epa"].sum(),
            "def_pass_epa_per_play_allowed": group.loc[is_pass, "epa"].mean(),
            "def_rush_plays": int(is_rush.sum()),
            "def_rush_epa_allowed": group.loc[is_rush, "epa"].sum(),
            "def_rush_epa_per_play_allowed": group.loc[is_rush, "epa"].mean(),
            "def_third_down_plays": int(third.sum()),
            "def_third_down_success_rate_allowed": group.loc[third, "success"].mean(),
            "def_red_zone_plays": int(red_zone.sum()),
            "def_red_zone_success_rate_allowed": group.loc[red_zone, "success"].mean(),
            "takeaways": int(takeaway.sum()),
            "takeaway_rate": takeaway.mean(),
        }
    )


def process_pbp(path: Path, url: str, aliases: dict[str, str], downloaded_at: str) -> pd.DataFrame:
    needed = [
        "season",
        "week",
        "season_type",
        "game_id",
        "game_date",
        "posteam",
        "defteam",
        "play_type",
        "epa",
        "down",
        "yardline_100",
        "qb_kneel",
        "qb_spike",
        "interception",
        "fumble_lost",
    ]
    df = pd.read_parquet(path, columns=needed)
    df = df[df["season_type"].isin(["REG", "POST"])].copy()
    df = df[df["posteam"].notna() & df["defteam"].notna() & df["epa"].notna()].copy()
    df = df[df["play_type"].isin(["pass", "run"])].copy()
    df = df[(df["qb_kneel"].fillna(0) == 0) & (df["qb_spike"].fillna(0) == 0)].copy()

    df["posteam_norm"] = normalize_team(df["posteam"], aliases)
    df["defteam_norm"] = normalize_team(df["defteam"], aliases)
    df["is_pass"] = df["play_type"].eq("pass")
    df["is_rush"] = df["play_type"].eq("run")
    df["success"] = df["epa"] > 0
    df["giveaway"] = (df["interception"].fillna(0).astype(float) > 0) | (
        df["fumble_lost"].fillna(0).astype(float) > 0
    )

    keys_off = ["season", "week", "posteam_norm"]
    off = df.groupby(keys_off, dropna=False).apply(summarize_offense, include_groups=False).reset_index()
    off = off.rename(columns={"posteam_norm": "team"})

    keys_def = ["season", "week", "defteam_norm"]
    defense = df.groupby(keys_def, dropna=False).apply(summarize_defense, include_groups=False).reset_index()
    defense = defense.rename(columns={"defteam_norm": "team"})

    out = off.merge(defense, on=["season", "week", "team"], how="outer")
    out["source_url"] = url
    out["downloaded_at_utc"] = downloaded_at
    out["created_at_utc"] = utc_now()
    return out


def process_team_week(path: Path, url: str, aliases: dict[str, str], downloaded_at: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    cols = [
        "season",
        "week",
        "season_type",
        "game_id",
        "team",
        "opponent_team",
        "completions",
        "attempts",
        "passing_yards",
        "passing_tds",
        "passing_interceptions",
        "sacks_suffered",
        "sack_yards_lost",
        "passing_epa",
        "passing_cpoe",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "rushing_epa",
        "receptions",
        "targets",
        "receiving_yards",
        "receiving_tds",
        "receiving_epa",
        "def_sacks",
        "def_qb_hits",
        "def_interceptions",
        "def_tds",
        "penalties",
        "penalty_yards",
        "fg_made",
        "fg_att",
        "pat_made",
        "pat_att",
        "punts",
        "pt_net_yards",
    ]
    present = [c for c in cols if c in df.columns]
    out = df.loc[df["season_type"].isin(["REG", "POST"]), present].copy()
    out["team"] = normalize_team(out["team"], aliases)
    out["opponent_team"] = normalize_team(out["opponent_team"], aliases)
    out["source_url"] = url
    out["downloaded_at_utc"] = downloaded_at
    out["created_at_utc"] = utc_now()
    return out


def process_qb_week(path: Path, url: str, aliases: dict[str, str], downloaded_at: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    cols = [
        "player_id",
        "player_name",
        "player_display_name",
        "position",
        "season",
        "week",
        "season_type",
        "game_id",
        "team",
        "opponent_team",
        "completions",
        "attempts",
        "passing_yards",
        "passing_tds",
        "passing_interceptions",
        "sacks_suffered",
        "sack_yards_lost",
        "passing_air_yards",
        "passing_yards_after_catch",
        "passing_first_downs",
        "passing_epa",
        "passing_cpoe",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "rushing_first_downs",
        "rushing_epa",
        "fantasy_points",
        "fantasy_points_ppr",
    ]
    present = [c for c in cols if c in df.columns]
    out = df.loc[
        df["season_type"].isin(["REG", "POST"]) & df["position"].eq("QB"),
        present,
    ].copy()
    out = out[(out["attempts"].fillna(0) > 0) | out["passing_epa"].notna()].copy()
    out["team"] = normalize_team(out["team"], aliases)
    out["opponent_team"] = normalize_team(out["opponent_team"], aliases)
    denom = out["attempts"].astype(float) + out.get("sacks_suffered", 0).fillna(0).astype(float)
    out["passing_epa_per_dropback"] = out["passing_epa"] / denom.where(denom > 0)
    out["source_url"] = url
    out["downloaded_at_utc"] = downloaded_at
    out["created_at_utc"] = utc_now()
    return out


def recreate_own_tables(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS nflverse_source_discovery (
            source_key TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            status TEXT NOT NULL,
            status_code INTEGER,
            details TEXT,
            checked_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS nfl_team_week_advanced (
            season INTEGER NOT NULL,
            week INTEGER NOT NULL,
            team TEXT NOT NULL,
            game_date TEXT,
            season_type TEXT,
            opponents TEXT,
            n_games INTEGER,
            offensive_plays INTEGER,
            offensive_epa REAL,
            offensive_epa_per_play REAL,
            offensive_success_rate REAL,
            pass_plays INTEGER,
            pass_epa REAL,
            pass_epa_per_play REAL,
            pass_success_rate REAL,
            rush_plays INTEGER,
            rush_epa REAL,
            rush_epa_per_play REAL,
            rush_success_rate REAL,
            third_down_plays INTEGER,
            third_down_success_rate REAL,
            red_zone_plays INTEGER,
            red_zone_success_rate REAL,
            giveaways INTEGER,
            giveaway_rate REAL,
            defensive_plays INTEGER,
            defensive_epa_allowed REAL,
            defensive_epa_per_play_allowed REAL,
            defensive_success_rate_allowed REAL,
            def_pass_plays INTEGER,
            def_pass_epa_allowed REAL,
            def_pass_epa_per_play_allowed REAL,
            def_rush_plays INTEGER,
            def_rush_epa_allowed REAL,
            def_rush_epa_per_play_allowed REAL,
            def_third_down_plays INTEGER,
            def_third_down_success_rate_allowed REAL,
            def_red_zone_plays INTEGER,
            def_red_zone_success_rate_allowed REAL,
            takeaways INTEGER,
            takeaway_rate REAL,
            source_url TEXT NOT NULL,
            downloaded_at_utc TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            PRIMARY KEY (season, week, team)
        );

        CREATE TABLE IF NOT EXISTS nfl_team_week_box_stats (
            season INTEGER NOT NULL,
            week INTEGER NOT NULL,
            season_type TEXT,
            game_id TEXT,
            team TEXT NOT NULL,
            opponent_team TEXT,
            completions INTEGER,
            attempts INTEGER,
            passing_yards REAL,
            passing_tds REAL,
            passing_interceptions REAL,
            sacks_suffered REAL,
            sack_yards_lost REAL,
            passing_epa REAL,
            passing_cpoe REAL,
            carries INTEGER,
            rushing_yards REAL,
            rushing_tds REAL,
            rushing_epa REAL,
            receptions REAL,
            targets REAL,
            receiving_yards REAL,
            receiving_tds REAL,
            receiving_epa REAL,
            def_sacks REAL,
            def_qb_hits REAL,
            def_interceptions REAL,
            def_tds REAL,
            penalties REAL,
            penalty_yards REAL,
            fg_made REAL,
            fg_att REAL,
            pat_made REAL,
            pat_att REAL,
            punts REAL,
            pt_net_yards REAL,
            source_url TEXT NOT NULL,
            downloaded_at_utc TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            PRIMARY KEY (season, week, team)
        );

        CREATE TABLE IF NOT EXISTS nfl_qb_week_stats (
            player_id TEXT NOT NULL,
            player_name TEXT,
            player_display_name TEXT,
            position TEXT,
            season INTEGER NOT NULL,
            week INTEGER NOT NULL,
            season_type TEXT,
            game_id TEXT,
            team TEXT NOT NULL,
            opponent_team TEXT,
            completions REAL,
            attempts REAL,
            passing_yards REAL,
            passing_tds REAL,
            passing_interceptions REAL,
            sacks_suffered REAL,
            sack_yards_lost REAL,
            passing_air_yards REAL,
            passing_yards_after_catch REAL,
            passing_first_downs REAL,
            passing_epa REAL,
            passing_cpoe REAL,
            carries REAL,
            rushing_yards REAL,
            rushing_tds REAL,
            rushing_first_downs REAL,
            rushing_epa REAL,
            fantasy_points REAL,
            fantasy_points_ppr REAL,
            passing_epa_per_dropback REAL,
            source_url TEXT NOT NULL,
            downloaded_at_utc TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            PRIMARY KEY (player_id, season, week, team, game_id)
        );

        CREATE TABLE IF NOT EXISTS nfl_advanced_ingestion_validation (
            table_name TEXT NOT NULL,
            season INTEGER NOT NULL,
            rows INTEGER NOT NULL,
            teams INTEGER,
            expected_teams_from_games INTEGER,
            missing_teams TEXT,
            null_rate_summary TEXT,
            checked_at_utc TEXT NOT NULL,
            PRIMARY KEY (table_name, season)
        );

        DELETE FROM nflverse_source_discovery;
        DELETE FROM nfl_team_week_advanced;
        DELETE FROM nfl_team_week_box_stats;
        DELETE FROM nfl_qb_week_stats;
        DELETE FROM nfl_advanced_ingestion_validation;
        """
    )


def insert_dataframe(con: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    clean = df.where(pd.notna(df), None)
    clean.to_sql(table, con, if_exists="append", index=False)


def expected_teams_from_games(con: sqlite3.Connection, season: int) -> set[str]:
    try:
        rows = con.execute(
            """
            SELECT home_team_normalized FROM games
            WHERE season = ? AND played = 1
            UNION
            SELECT away_team_normalized FROM games
            WHERE season = ? AND played = 1
            """,
            (season, season),
        ).fetchall()
    except sqlite3.Error:
        return set()
    return {row[0] for row in rows if row[0]}


def metric_null_rates(df: pd.DataFrame, metrics: list[str]) -> dict[str, float]:
    return {col: round(float(df[col].isna().mean()), 4) for col in metrics if col in df.columns}


def simple_markdown_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for _, row in df.iterrows():
        values = []
        for col in cols:
            value = row[col]
            if pd.isna(value):
                values.append("")
            else:
                values.append(str(value).replace("|", "\\|"))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def add_validation_rows(con: sqlite3.Connection, table: str, df: pd.DataFrame, metrics: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season, g in df.groupby("season"):
        expected = expected_teams_from_games(con, int(season))
        observed = set(g["team"].dropna().unique()) if "team" in g.columns else set()
        missing = sorted(expected - observed) if expected else []
        row = {
            "table_name": table,
            "season": int(season),
            "rows": int(len(g)),
            "teams": int(g["team"].nunique()) if "team" in g.columns else None,
            "expected_teams_from_games": len(expected) if expected else None,
            "missing_teams": ",".join(missing) if missing else None,
            "null_rate_summary": json.dumps(metric_null_rates(g, metrics), sort_keys=True),
            "checked_at_utc": utc_now(),
        }
        rows.append(row)
    insert_dataframe(con, "nfl_advanced_ingestion_validation", pd.DataFrame(rows))
    return rows


def main() -> None:
    ensure_dirs()
    con = sqlite3.connect(DB_PATH, timeout=120)
    con.execute("PRAGMA journal_mode=WAL")
    aliases = load_alias_map(con)

    discovery_rows: list[dict[str, Any]] = []
    check_urls = {
        "nflverse-data releases api": "https://api.github.com/repos/nflverse/nflverse-data/releases?per_page=100",
        "nfldata contents api": API_CONTENTS,
        "nfldata github tree html": NFDATA_TREE,
        "nfldata raw directory": NFDATA_RAW_DIR,
        "nfldata games csv": "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
    }
    for key, url in check_urls.items():
        code, details = probe_url(url)
        discovery_rows.append(
            {
                "source_key": key,
                "source_url": url,
                "status": "worked" if code and 200 <= code < 300 else "not_worked",
                "status_code": code,
                "details": details,
                "checked_at_utc": utc_now(),
            }
        )

    release_tags = ["pbp", "stats_team", "stats_player", "player_stats", "pfr_advstats", "nextgen_stats"]
    assets_by_tag: dict[str, dict[str, dict[str, Any]]] = {}
    for tag in release_tags:
        url = API_RELEASE.format(tag=tag)
        try:
            assets = get_release_assets(tag)
            assets_by_tag[tag] = assets
            discovery_rows.append(
                {
                    "source_key": f"release:{tag}",
                    "source_url": url,
                    "status": "worked",
                    "status_code": 200,
                    "details": f"{len(assets)} assets",
                    "checked_at_utc": utc_now(),
                }
            )
        except Exception as exc:
            discovery_rows.append(
                {
                    "source_key": f"release:{tag}",
                    "source_url": url,
                    "status": "not_worked",
                    "status_code": None,
                    "details": repr(exc),
                    "checked_at_utc": utc_now(),
                }
            )

    pbp_assets = assets_by_tag["pbp"]
    seasons = sorted(
        int(name.removeprefix("play_by_play_").removesuffix(".parquet"))
        for name in pbp_assets
        if name.startswith("play_by_play_") and name.endswith(".parquet")
    )
    seasons = [s for s in seasons if s >= START_SEASON]

    team_adv_frames: list[pd.DataFrame] = []
    team_box_frames: list[pd.DataFrame] = []
    qb_frames: list[pd.DataFrame] = []
    source_asset_rows: list[dict[str, Any]] = []

    for season in seasons:
        downloaded_at = utc_now()

        pbp_name = f"play_by_play_{season}.parquet"
        pbp_asset = pbp_assets.get(pbp_name)
        if not pbp_asset:
            source_asset_rows.append({"source": "pbp", "season": season, "status": "missing asset"})
            continue
        pbp_path = download_asset(pbp_asset, RAW_DIR / "pbp")
        team_adv_frames.append(
            process_pbp(pbp_path, pbp_asset["browser_download_url"], aliases, downloaded_at)
        )
        source_asset_rows.append({"source": "pbp", "season": season, "status": "ingested", "url": pbp_asset["browser_download_url"]})

        team_name = f"stats_team_week_{season}.parquet"
        team_asset = assets_by_tag["stats_team"].get(team_name)
        if team_asset:
            team_path = download_asset(team_asset, RAW_DIR / "stats_team")
            team_box_frames.append(
                process_team_week(team_path, team_asset["browser_download_url"], aliases, utc_now())
            )
            source_asset_rows.append({"source": "stats_team_week", "season": season, "status": "ingested", "url": team_asset["browser_download_url"]})
        else:
            source_asset_rows.append({"source": "stats_team_week", "season": season, "status": "missing asset"})

        qb_name = f"stats_player_week_{season}.parquet"
        qb_asset = assets_by_tag["stats_player"].get(qb_name)
        if qb_asset:
            qb_path = download_asset(qb_asset, RAW_DIR / "stats_player")
            qb_frames.append(process_qb_week(qb_path, qb_asset["browser_download_url"], aliases, utc_now()))
            source_asset_rows.append({"source": "stats_player_week", "season": season, "status": "ingested", "url": qb_asset["browser_download_url"]})
        else:
            source_asset_rows.append({"source": "stats_player_week", "season": season, "status": "missing asset"})

    team_adv = pd.concat(team_adv_frames, ignore_index=True) if team_adv_frames else pd.DataFrame()
    team_box = pd.concat(team_box_frames, ignore_index=True) if team_box_frames else pd.DataFrame()
    qb_week = pd.concat(qb_frames, ignore_index=True) if qb_frames else pd.DataFrame()

    if team_adv.empty:
        raise RuntimeError("No real play-by-play EPA data was ingested; refusing to create synthetic fallback.")

    with con:
        recreate_own_tables(con)
        insert_dataframe(con, "nflverse_source_discovery", pd.DataFrame(discovery_rows))
        insert_dataframe(con, "nfl_team_week_advanced", team_adv)
        if not team_box.empty:
            insert_dataframe(con, "nfl_team_week_box_stats", team_box)
        if not qb_week.empty:
            insert_dataframe(con, "nfl_qb_week_stats", qb_week)

        validation = []
        validation.extend(
            add_validation_rows(
                con,
                "nfl_team_week_advanced",
                team_adv,
                [
                    "offensive_epa_per_play",
                    "defensive_epa_per_play_allowed",
                    "pass_epa_per_play",
                    "rush_epa_per_play",
                    "third_down_success_rate",
                    "red_zone_success_rate",
                    "giveaway_rate",
                    "takeaway_rate",
                ],
            )
        )
        if not team_box.empty:
            validation.extend(
                add_validation_rows(
                    con,
                    "nfl_team_week_box_stats",
                    team_box,
                    ["passing_epa", "rushing_epa", "passing_cpoe", "def_sacks", "def_interceptions"],
                )
            )
        if not qb_week.empty:
            validation.extend(
                add_validation_rows(
                    con,
                    "nfl_qb_week_stats",
                    qb_week,
                    ["passing_epa", "passing_cpoe", "passing_epa_per_dropback", "rushing_epa"],
                )
            )
        con.execute(
            """
            INSERT OR REPLACE INTO ingestion_metadata(key, value)
            VALUES (?, ?), (?, ?), (?, ?)
            """,
            (
                "advanced_stats_ingested_at_utc",
                utc_now(),
                "advanced_stats_seasons",
                f"{min(seasons)}-{max(seasons)}",
                "advanced_stats_tables",
                "nfl_team_week_advanced,nfl_team_week_box_stats,nfl_qb_week_stats,nflverse_source_discovery,nfl_advanced_ingestion_validation",
            ),
        )

    write_report(discovery_rows, source_asset_rows, validation, team_adv, team_box, qb_week)
    con.close()


def write_report(
    discovery_rows: list[dict[str, Any]],
    source_asset_rows: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    team_adv: pd.DataFrame,
    team_box: pd.DataFrame,
    qb_week: pd.DataFrame,
) -> None:
    report = REPORT_DIR / "nfl_advanced_stats_ingestion.md"
    worked = [r for r in discovery_rows if r["status"] == "worked"]
    failed = [r for r in discovery_rows if r["status"] != "worked"]
    asset_df = pd.DataFrame(source_asset_rows)
    validation_df = pd.DataFrame(validation)

    metric_nulls = metric_null_rates(
        team_adv,
        [
            "offensive_epa_per_play",
            "defensive_epa_per_play_allowed",
            "pass_epa_per_play",
            "rush_epa_per_play",
            "third_down_success_rate",
            "red_zone_success_rate",
            "giveaway_rate",
            "takeaway_rate",
        ],
    )

    with report.open("w", encoding="utf-8") as fh:
        fh.write("# NFL advanced stats ingestion\n\n")
        fh.write(f"Generated: {utc_now()}\n\n")
        fh.write("## Data integrity rule\n\n")
        fh.write(
            "No synthetic, simulated, randomly generated, or imputed data was created. "
            "Unavailable sources/seasons were recorded as gaps only.\n\n"
        )
        fh.write("## Sources discovered\n\n")
        fh.write("### Worked\n\n")
        for row in worked:
            fh.write(f"- {row['source_key']}: {row['source_url']} ({row['details']})\n")
        fh.write("\n### Did not work or was not listable\n\n")
        for row in failed:
            fh.write(f"- {row['source_key']}: {row['source_url']} (status={row['status_code']}, {row['details']})\n")

        fh.write("\n## Ingested assets\n\n")
        for source, group in asset_df.groupby("source"):
            ok = group[group["status"].eq("ingested")]
            seasons = sorted(ok["season"].astype(int).tolist()) if not ok.empty else []
            coverage = f"{min(seasons)}-{max(seasons)} ({len(seasons)} seasons)" if seasons else "none"
            fh.write(f"- {source}: {coverage}\n")
            if not ok.empty:
                sample_urls = ok["url"].dropna().head(3).tolist()
                for url in sample_urls:
                    fh.write(f"  - sample URL: {url}\n")

        fh.write("\n## Tables and metrics\n\n")
        fh.write(
            "- `nfl_team_week_advanced`: per-(season, week, normalized team) observations from play-by-play EPA. "
            "Metrics include offensive/defensive EPA per play, pass/rush EPA splits, positive-EPA success rates, "
            "third-down/red-zone positive-EPA rates, giveaways, takeaways, and play counts.\n"
        )
        fh.write(
            "- `nfl_team_week_box_stats`: nflverse team-week box/summary stats including passing/rushing EPA, CPOE, "
            "yardage, touchdowns, sacks, interceptions, penalties, and kicking/punting fields.\n"
        )
        fh.write(
            "- `nfl_qb_week_stats`: QB weekly passing/rushing production from nflverse player-week stats, including "
            "passing EPA, CPOE, sacks, interceptions, rushing EPA, and derived passing EPA per dropback.\n\n"
        )

        fh.write("## Coverage summary\n\n")
        fh.write(f"- `nfl_team_week_advanced`: {len(team_adv):,} rows, seasons {int(team_adv.season.min())}-{int(team_adv.season.max())}.\n")
        fh.write(f"- `nfl_team_week_box_stats`: {len(team_box):,} rows.\n")
        fh.write(f"- `nfl_qb_week_stats`: {len(qb_week):,} rows.\n")
        fh.write(f"- Overall null rates for key EPA metrics: `{json.dumps(metric_nulls, sort_keys=True)}`\n\n")

        fh.write("### Rows/teams by season\n\n")
        if not validation_df.empty:
            pivot = validation_df[["table_name", "season", "rows", "teams", "expected_teams_from_games", "missing_teams"]]
            fh.write(simple_markdown_table(pivot))
            fh.write("\n\n")

        gaps = validation_df[validation_df["missing_teams"].notna()] if not validation_df.empty else pd.DataFrame()
        fh.write("## Honest gaps/blockers\n\n")
        if gaps.empty:
            fh.write("- No missing teams versus the local `games` table for ingested seasons were detected.\n")
        else:
            for _, row in gaps.iterrows():
                fh.write(f"- {row['table_name']} {row['season']}: missing teams {row['missing_teams']}.\n")
        fh.write(
            "- Coverage intentionally starts at 2010 to keep play-by-play ingestion pragmatic while covering modern NFL data. "
            "nflverse publishes older play-by-play assets back to 1999, but they were not ingested in this run.\n"
        )
        fh.write(
            "- ESPN API was not used because the task reported 403 responses; all ingested data came from nflverse/GitHub.\n"
        )


if __name__ == "__main__":
    main()
