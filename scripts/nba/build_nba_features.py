"""Build honest pregame NBA features from prior games only."""

from __future__ import annotations

import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "nba" / "nba_research.db"

ROLLING_WINDOWS = (3, 5, 10, 20)
TEAM_METRICS = [
    "win",
    "margin",
    "points",
    "opp_points",
    "off_rating",
    "def_rating",
    "pace",
    "efg_pct",
    "three_point_rate",
    "rebound_rate",
    "oreb_rate",
    "turnover_rate",
]

warnings.simplefilter("ignore", PerformanceWarning)


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    den = den.replace(0, np.nan)
    return num / den


def add_elo(team_games: pd.DataFrame) -> pd.DataFrame:
    ratings: dict[str, float] = {}
    pre_rows: list[dict[str, float | str]] = []
    k_factor = 20.0
    home_adv = 65.0

    games = team_games[["game_id", "game_date", "home_team", "away_team", "home_win"]].drop_duplicates()
    games = games.sort_values(["game_date", "game_id"])
    for row in games.itertuples(index=False):
        home = row.home_team
        away = row.away_team
        rh = ratings.get(home, 1500.0)
        ra = ratings.get(away, 1500.0)
        p_home = 1.0 / (1.0 + 10.0 ** (-((rh + home_adv) - ra) / 400.0))
        actual = float(row.home_win)
        ratings[home] = rh + k_factor * (actual - p_home)
        ratings[away] = ra + k_factor * ((1.0 - actual) - (1.0 - p_home))
        pre_rows.append({"game_id": row.game_id, "team": home, "elo_pre": rh, "opp_elo_pre": ra, "elo_prob": p_home})
        pre_rows.append({"game_id": row.game_id, "team": away, "elo_pre": ra, "opp_elo_pre": rh, "elo_prob": 1.0 - p_home})

    elo = pd.DataFrame(pre_rows)
    return team_games.merge(elo, on=["game_id", "team"], how="left")


def load_team_games() -> pd.DataFrame:
    with connect() as con:
        games = pd.read_sql_query(
            """
            SELECT game_id, season, game_date, home_team, away_team, home_score, away_score,
                   home_win, neutral_site
            FROM nba_games
            WHERE completed = 1
              AND home_win IS NOT NULL
              AND season_type = 'regular'
              AND COALESCE(neutral_site, 0) = 0
            ORDER BY game_date, game_id
            """,
            con,
            parse_dates=["game_date"],
        )
        stats = pd.read_sql_query(
            """
            SELECT p.game_id, p.team,
                   SUM(CAST(NULLIF(json_extract(p.raw_stats_json,'$.field_goals_made'),'') AS REAL)) AS fgm,
                   SUM(CAST(NULLIF(json_extract(p.raw_stats_json,'$.field_goals_attempted'),'') AS REAL)) AS fga,
                   SUM(CAST(NULLIF(json_extract(p.raw_stats_json,'$.three_point_field_goals_made'),'') AS REAL)) AS tpm,
                   SUM(CAST(NULLIF(json_extract(p.raw_stats_json,'$.three_point_field_goals_attempted'),'') AS REAL)) AS tpa,
                   SUM(CAST(NULLIF(json_extract(p.raw_stats_json,'$.free_throws_made'),'') AS REAL)) AS ftm,
                   SUM(CAST(NULLIF(json_extract(p.raw_stats_json,'$.free_throws_attempted'),'') AS REAL)) AS fta,
                   SUM(CAST(NULLIF(json_extract(p.raw_stats_json,'$.offensive_rebounds'),'') AS REAL)) AS oreb,
                   SUM(CAST(NULLIF(json_extract(p.raw_stats_json,'$.defensive_rebounds'),'') AS REAL)) AS dreb,
                   SUM(CAST(NULLIF(json_extract(p.raw_stats_json,'$.rebounds'),'') AS REAL)) AS rebounds,
                   SUM(CAST(NULLIF(json_extract(p.raw_stats_json,'$.turnovers'),'') AS REAL)) AS turnovers
            FROM nba_player_box p
            JOIN nba_games g ON g.game_id = p.game_id
            WHERE g.completed = 1
              AND g.home_win IS NOT NULL
              AND g.season_type = 'regular'
              AND COALESCE(g.neutral_site, 0) = 0
            GROUP BY p.game_id, p.team
            """,
            con,
        )

    home = games.rename(
        columns={"home_team": "team", "away_team": "opponent", "home_score": "points", "away_score": "opp_points"}
    ).copy()
    home["home_team"] = home["team"]
    home["away_team"] = home["opponent"]
    home["is_home"] = 1
    home["win"] = home["home_win"].astype(int)

    away = games.rename(
        columns={"away_team": "team", "home_team": "opponent", "away_score": "points", "home_score": "opp_points"}
    ).copy()
    away["home_team"] = away["opponent"]
    away["away_team"] = away["team"]
    away["is_home"] = 0
    away["win"] = (1 - away["home_win"]).astype(int)

    keep = ["game_id", "season", "game_date", "home_team", "away_team", "team", "opponent", "is_home", "points", "opp_points", "win", "home_win"]
    team_games = pd.concat([home[keep], away[keep]], ignore_index=True)
    team_games = team_games.merge(stats, on=["game_id", "team"], how="left")

    opp_stats = stats.add_prefix("opp_").rename(columns={"opp_game_id": "game_id", "opp_team": "opponent"})
    team_games = team_games.merge(opp_stats, on=["game_id", "opponent"], how="left")

    team_games["margin"] = team_games["points"] - team_games["opp_points"]
    team_games["possessions"] = team_games["fga"] + 0.44 * team_games["fta"] + team_games["turnovers"] - team_games["oreb"]
    team_games["off_rating"] = 100 * safe_div(team_games["points"], team_games["possessions"])
    team_games["def_rating"] = 100 * safe_div(team_games["opp_points"], team_games["possessions"])
    team_games["pace"] = team_games["possessions"]
    team_games["efg_pct"] = safe_div(team_games["fgm"] + 0.5 * team_games["tpm"], team_games["fga"])
    team_games["three_point_rate"] = safe_div(team_games["tpa"], team_games["fga"])
    team_games["rebound_rate"] = safe_div(team_games["rebounds"], team_games["rebounds"] + team_games["opp_rebounds"])
    team_games["oreb_rate"] = safe_div(team_games["oreb"], team_games["oreb"] + team_games["opp_dreb"])
    team_games["turnover_rate"] = safe_div(team_games["turnovers"], team_games["possessions"])
    team_games = add_elo(team_games)
    return team_games.sort_values(["team", "game_date", "game_id"]).reset_index(drop=True)


def add_pregame_team_features(team_games: pd.DataFrame) -> pd.DataFrame:
    team_games = team_games.copy()
    grouped = team_games.groupby("team", group_keys=False)

    team_games["prev_game_date"] = grouped["game_date"].shift()
    team_games["rest_days"] = (team_games["game_date"] - team_games["prev_game_date"]).dt.days.clip(lower=0, upper=10)
    team_games["is_back_to_back"] = (team_games["rest_days"] <= 1).astype(float)
    team_games.loc[team_games["prev_game_date"].isna(), "is_back_to_back"] = np.nan
    team_games["prev_is_home"] = grouped["is_home"].shift()
    team_games["road_trip_game"] = ((team_games["is_home"] == 0) & (team_games["prev_is_home"] == 0)).astype(float)
    team_games.loc[team_games["prev_is_home"].isna(), "road_trip_game"] = np.nan

    team_games["season_games_before"] = team_games.groupby(["team", "season"]).cumcount()
    team_games["season_wins_before"] = team_games.groupby(["team", "season"])["win"].cumsum() - team_games["win"]
    team_games["season_win_pct"] = safe_div(team_games["season_wins_before"], team_games["season_games_before"])

    for metric in TEAM_METRICS:
        for window in ROLLING_WINDOWS:
            name = f"{metric}_last{window}"
            team_games[name] = grouped[metric].transform(lambda s, w=window: s.shift().rolling(w, min_periods=3).mean())
    team_games["opp_strength_last10"] = grouped["opp_elo_pre"].transform(lambda s: s.shift().rolling(10, min_periods=3).mean())
    return team_games


def build_game_features(team_games: pd.DataFrame) -> pd.DataFrame:
    pre = add_pregame_team_features(team_games)
    feature_cols = [
        "elo_pre",
        "opp_elo_pre",
        "season_win_pct",
        "rest_days",
        "is_back_to_back",
        "road_trip_game",
        "opp_strength_last10",
    ]
    feature_cols += [f"{m}_last{w}" for m in TEAM_METRICS for w in ROLLING_WINDOWS]

    home = pre[pre["is_home"] == 1].copy()
    away = pre[pre["is_home"] == 0].copy()
    merged = home.merge(away, on="game_id", suffixes=("_home", "_away"))
    out = pd.DataFrame(
        {
            "game_id": merged["game_id"],
            "season": merged["season_home"],
            "game_date": merged["game_date_home"].dt.strftime("%Y-%m-%d"),
            "home_team": merged["team_home"],
            "away_team": merged["team_away"],
            "home_win": merged["home_win_home"].astype(int),
            "home_score": merged["points_home"].astype(int),
            "away_score": merged["points_away"].astype(int),
            "final_margin": (merged["points_home"] - merged["points_away"]).astype(int),
            "elo_prob_home": merged["elo_prob_home"],
            "elo_diff": merged["elo_pre_home"] - merged["elo_pre_away"],
            "rest_diff": merged["rest_days_home"] - merged["rest_days_away"],
            "home_b2b": merged["is_back_to_back_home"],
            "away_b2b": merged["is_back_to_back_away"],
            "away_road_trip": merged["road_trip_game_away"],
            "home_road_trip_flag": merged["road_trip_game_home"],
        }
    )
    for col in feature_cols:
        out[f"{col}_home"] = merged[f"{col}_home"]
        out[f"{col}_away"] = merged[f"{col}_away"]
        out[f"{col}_diff"] = merged[f"{col}_home"] - merged[f"{col}_away"]

    out = out.sort_values(["game_date", "game_id"]).reset_index(drop=True)
    return out


def write_features(features: pd.DataFrame) -> None:
    with connect() as con:
        cols = []
        for name, dtype in features.dtypes.items():
            sql_type = "INTEGER" if pd.api.types.is_integer_dtype(dtype) else "REAL" if pd.api.types.is_float_dtype(dtype) else "TEXT"
            cols.append(f'"{name}" {sql_type}')
        con.execute(f'CREATE TABLE IF NOT EXISTS nba_features_pregame ({", ".join(cols)})')
        con.execute("DELETE FROM nba_features_pregame")
        features.to_sql("nba_features_pregame", con, if_exists="append", index=False)
        con.execute("CREATE INDEX IF NOT EXISTS idx_nba_features_pregame_season ON nba_features_pregame(season)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_nba_features_pregame_game_id ON nba_features_pregame(game_id)")


def main() -> None:
    team_games = load_team_games()
    features = build_game_features(team_games)
    write_features(features)
    print(f"Built nba_features_pregame: {len(features):,} regular-season, non-neutral completed games")
    print(f"Seasons: {features['season'].min()}-{features['season'].max()}")
    print(f"Feature columns: {len(features.columns) - 9}")


if __name__ == "__main__":
    main()
