"""Build leakage-safe pregame NFL model features.

All rolling features use only games/stat rows dated strictly before the target
game. Missing source data is left NULL and summarized in the report.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "nfl"
REPORT_DIR = ROOT / "data" / "reports"
DB_PATH = DATA_DIR / "nfl_research.db"
REPORT_PATH = REPORT_DIR / "nfl_feature_engineering.md"

START_SEASON = 2010
ELO_K = 20.0
ELO_HOME_FIELD = 55.0
ELO_REGRESSION = 0.67
ELO_MEAN = 1500.0

TEAM_METRICS = [
    "offensive_epa_per_play",
    "defensive_epa_per_play_allowed",
    "pass_epa_per_play",
    "rush_epa_per_play",
    "offensive_success_rate",
    "defensive_success_rate_allowed",
    "pass_success_rate",
    "rush_success_rate",
    "third_down_success_rate",
    "red_zone_success_rate",
    "giveaway_rate",
    "takeaway_rate",
    "turnover_margin",
]
TEAM_WINDOWS = (3, 5, 8)
QB_METRICS = ["passing_epa_per_dropback", "passing_cpoe", "passing_epa"]
QB_WINDOWS = (3, 5)

TEAM_TZ_OFFSET = {
    # Standard UTC offsets by NFL market/stadium timezone.
    "ARI": -7,
    "ATL": -5,
    "BAL": -5,
    "BUF": -5,
    "CAR": -5,
    "CHI": -6,
    "CIN": -5,
    "CLE": -5,
    "DAL": -6,
    "DEN": -7,
    "DET": -5,
    "GB": -6,
    "HOU": -6,
    "IND": -5,
    "JAX": -5,
    "KC": -6,
    "LAC": -8,
    "LAR": -8,
    "LV": -8,
    "MIA": -5,
    "MIN": -6,
    "NE": -5,
    "NO": -6,
    "NYG": -5,
    "NYJ": -5,
    "PHI": -5,
    "PIT": -5,
    "SEA": -8,
    "SF": -8,
    "TB": -5,
    "TEN": -6,
    "WAS": -5,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def american_implied_probability(moneyline: Any) -> float | None:
    if moneyline is None or pd.isna(moneyline):
        return None
    ml = float(moneyline)
    if ml < 0:
        return abs(ml) / (abs(ml) + 100.0)
    return 100.0 / (ml + 100.0)


def finite_or_none(value: Any) -> float | int | str | None:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (float, np.floating)) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def mean_or_none(rows: list[dict[str, Any]], metric: str) -> float | None:
    values = [float(row[metric]) for row in rows if row.get(metric) is not None and pd.notna(row.get(metric))]
    return float(np.mean(values)) if values else None


def max_date_or_none(rows: list[dict[str, Any]]) -> str | None:
    dates = [str(row["game_date"]) for row in rows if row.get("game_date") is not None and pd.notna(row.get("game_date"))]
    return max(dates) if dates else None


def load_tables(con: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    games = pd.read_sql_query(
        """
        SELECT *
        FROM games
        WHERE season >= ?
          AND played = 1
          AND COALESCE(is_preseason, 0) = 0
          AND COALESCE(unplayed, 0) = 0
        ORDER BY season, gameday, week, game_id
        """,
        con,
        params=(START_SEASON,),
        parse_dates=["gameday"],
    )
    team = pd.read_sql_query(
        """
        SELECT *
        FROM nfl_team_week_advanced
        WHERE season >= ?
        ORDER BY team, game_date, season, week
        """,
        con,
        params=(START_SEASON,),
        parse_dates=["game_date"],
    )
    qb = pd.read_sql_query(
        """
        SELECT *
        FROM nfl_qb_week_stats
        WHERE season >= ?
          AND position = 'QB'
        ORDER BY player_id, season, week, game_id
        """,
        con,
        params=(START_SEASON,),
    )
    return games, team, qb


def build_elo(games_all: pd.DataFrame) -> dict[str, dict[str, float]]:
    ratings: defaultdict[str, float] = defaultdict(lambda: ELO_MEAN)
    pregame: dict[str, dict[str, float]] = {}
    last_season: int | None = None
    ordered = games_all.sort_values(["season", "gameday", "week", "game_id"])

    for row in ordered.itertuples(index=False):
        season = int(row.season)
        if last_season is None or season != last_season:
            for team in list(ratings):
                ratings[team] = ELO_MEAN + ELO_REGRESSION * (ratings[team] - ELO_MEAN)
            last_season = season

        home = str(row.home_team_normalized or row.home_team)
        away = str(row.away_team_normalized or row.away_team)
        home_elo = ratings[home]
        away_elo = ratings[away]
        hfa = 0.0 if str(getattr(row, "location", "")).lower() == "neutral" else ELO_HOME_FIELD
        pregame[str(row.game_id)] = {
            "home_elo_pregame": home_elo,
            "away_elo_pregame": away_elo,
            "elo_diff_home_minus_away": home_elo - away_elo,
            "elo_home_field_adjustment": hfa,
            "elo_diff_with_hfa": home_elo - away_elo + hfa,
        }

        home_score = getattr(row, "home_score")
        away_score = getattr(row, "away_score")
        if pd.isna(home_score) or pd.isna(away_score):
            continue
        actual = 0.5 if home_score == away_score else (1.0 if home_score > away_score else 0.0)
        expected_home = 1.0 / (1.0 + 10.0 ** (-((home_elo + hfa) - away_elo) / 400.0))
        change = ELO_K * (actual - expected_home)
        ratings[home] = home_elo + change
        ratings[away] = away_elo - change

    return pregame


def prepare_histories(
    games: pd.DataFrame, team: pd.DataFrame, qb: pd.DataFrame
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    team = team.copy()
    team["turnover_margin"] = team["takeaways"] - team["giveaways"]
    team_hist: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in team.sort_values(["team", "game_date", "season", "week"]).to_dict("records"):
        row["game_date"] = row["game_date"].date().isoformat() if pd.notna(row["game_date"]) else None
        team_hist[str(row["team"])].append(row)

    qb_hist: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in qb.sort_values(["player_id", "season", "week", "game_id"]).to_dict("records"):
        game_date = games.loc[games["game_id"] == row.get("game_id"), "gameday"]
        row["game_date"] = game_date.iloc[0].date().isoformat() if len(game_date) and pd.notna(game_date.iloc[0]) else None
        qb_hist[str(row["player_id"])].append(row)

    starter_hist: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in games.sort_values(["gameday", "week", "game_id"]).itertuples(index=False):
        game_date = row.gameday.date().isoformat() if pd.notna(row.gameday) else None
        for side in ("home", "away"):
            team_id = str(getattr(row, f"{side}_team_normalized") or getattr(row, f"{side}_team"))
            qb_id = getattr(row, f"{side}_qb_id")
            if qb_id is not None and pd.notna(qb_id):
                starter_hist[team_id].append(
                    {"game_date": game_date, "game_id": row.game_id, "qb_id": str(qb_id), "season": int(row.season)}
                )
    return team_hist, qb_hist, starter_hist


def add_team_features(out: dict[str, Any], prefix: str, team_id: str, game_date: str, season: int, hist: dict[str, list[dict[str, Any]]]) -> None:
    rows = [r for r in hist.get(team_id, []) if r.get("game_date") and r["game_date"] < game_date]
    out[f"{prefix}_team_games_available"] = len(rows)
    out[f"{prefix}_team_max_source_date"] = max_date_or_none(rows)
    for window in TEAM_WINDOWS:
        window_rows = rows[-window:]
        out[f"{prefix}_team_games_last{window}"] = len(window_rows)
        for metric in TEAM_METRICS:
            out[f"{prefix}_{metric}_last{window}"] = mean_or_none(window_rows, metric)
    season_rows = [r for r in rows if int(r["season"]) == season]
    out[f"{prefix}_team_games_season_to_date"] = len(season_rows)
    for metric in TEAM_METRICS:
        out[f"{prefix}_{metric}_season_to_date"] = mean_or_none(season_rows, metric)


def add_qb_features(
    out: dict[str, Any],
    prefix: str,
    qb_id: str | None,
    team_id: str,
    game_date: str,
    qb_hist: dict[str, list[dict[str, Any]]],
    starter_hist: dict[str, list[dict[str, Any]]],
) -> None:
    if qb_id is None or pd.isna(qb_id):
        out[f"{prefix}_qb_id_known"] = 0
        return
    qid = str(qb_id)
    out[f"{prefix}_qb_id_known"] = 1
    qrows = [r for r in qb_hist.get(qid, []) if r.get("game_date") and r["game_date"] < game_date]
    out[f"{prefix}_qb_stat_games_available"] = len(qrows)
    out[f"{prefix}_qb_max_source_date"] = max_date_or_none(qrows)
    for window in QB_WINDOWS:
        window_rows = qrows[-window:]
        out[f"{prefix}_qb_games_last{window}"] = len(window_rows)
        for metric in QB_METRICS:
            out[f"{prefix}_qb_{metric}_last{window}"] = mean_or_none(window_rows, metric)
    for metric in QB_METRICS:
        out[f"{prefix}_qb_{metric}_career_to_date"] = mean_or_none(qrows, metric)

    prior_starts = [r for r in starter_hist.get(team_id, []) if r.get("game_date") and r["game_date"] < game_date]
    out[f"{prefix}_qb_prior_starts"] = sum(1 for r in starter_hist.values() for s in r if s.get("game_date") and s["game_date"] < game_date and s["qb_id"] == qid)
    out[f"{prefix}_team_previous_starter_known"] = int(bool(prior_starts))
    out[f"{prefix}_qb_changed_from_previous_game"] = (
        int(prior_starts[-1]["qb_id"] != qid) if prior_starts else None
    )


def add_differences(row: dict[str, Any]) -> None:
    prefixes = []
    for key in list(row):
        if key.startswith("home_"):
            away_key = "away_" + key[len("home_") :]
            if away_key in row and isinstance(row[key], (int, float)) and isinstance(row[away_key], (int, float)):
                prefixes.append((key[len("home_") :], row[key], row[away_key]))
    for suffix, home_value, away_value in prefixes:
        row[f"diff_{suffix}"] = finite_or_none(home_value - away_value)


def build_features() -> tuple[pd.DataFrame, dict[str, Any]]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        games, team, qb = load_tables(con)
        games_all = pd.read_sql_query(
            """
            SELECT *
            FROM games
            WHERE played = 1
              AND COALESCE(is_preseason, 0) = 0
              AND COALESCE(unplayed, 0) = 0
            ORDER BY season, gameday, week, game_id
            """,
            con,
            parse_dates=["gameday"],
        )

    elo = build_elo(games_all)
    team_hist, qb_hist, starter_hist = prepare_histories(games, team, qb)
    rows: list[dict[str, Any]] = []

    for game in games.itertuples(index=False):
        game_date = game.gameday.date().isoformat()
        home = str(game.home_team_normalized or game.home_team)
        away = str(game.away_team_normalized or game.away_team)
        home_ml_raw = american_implied_probability(game.home_moneyline)
        away_ml_raw = american_implied_probability(game.away_moneyline)
        no_vig_home = (
            home_ml_raw / (home_ml_raw + away_ml_raw)
            if home_ml_raw is not None and away_ml_raw is not None and (home_ml_raw + away_ml_raw) > 0
            else None
        )
        home_tz = TEAM_TZ_OFFSET.get(home)
        away_tz = TEAM_TZ_OFFSET.get(away)
        roof = str(game.roof).lower() if game.roof is not None and pd.notna(game.roof) else None

        row: dict[str, Any] = {
            "game_id": game.game_id,
            "season": int(game.season),
            "week": int(game.week),
            "game_type": game.game_type,
            "gameday": game_date,
            "home_team": home,
            "away_team": away,
            "target_home_win": None if pd.isna(game.home_win) else int(game.home_win),
            "target_home_margin": None if pd.isna(game.result) else float(game.result),
            "is_tie": int(bool(game.tie_game)),
            "home_rest": finite_or_none(game.home_rest),
            "away_rest": finite_or_none(game.away_rest),
            "rest_diff_home_minus_away": finite_or_none(game.home_rest - game.away_rest) if pd.notna(game.home_rest) and pd.notna(game.away_rest) else None,
            "home_short_week": int(game.home_rest <= 4) if pd.notna(game.home_rest) else None,
            "away_short_week": int(game.away_rest <= 4) if pd.notna(game.away_rest) else None,
            "home_post_bye": int(game.home_rest >= 10) if pd.notna(game.home_rest) else None,
            "away_post_bye": int(game.away_rest >= 10) if pd.notna(game.away_rest) else None,
            "thursday_game": int(str(game.weekday).lower() == "thursday"),
            "division_game": finite_or_none(game.div_game),
            "neutral_site": int(str(game.location).lower() == "neutral"),
            "roof": game.roof,
            "roof_dome_or_closed": int(roof in {"dome", "closed"}) if roof else None,
            "outdoor_game": int(roof in {"outdoors", "open"}) if roof else None,
            "surface": game.surface,
            "temp": finite_or_none(game.temp),
            "wind": finite_or_none(game.wind),
            "home_timezone_offset": home_tz,
            "away_timezone_offset": away_tz,
            "away_travel_timezones_eastward": finite_or_none(home_tz - away_tz) if home_tz is not None and away_tz is not None else None,
            "away_travel_timezone_abs": abs(home_tz - away_tz) if home_tz is not None and away_tz is not None else None,
            "spread_line": finite_or_none(game.spread_line),
            "total_line": finite_or_none(game.total_line),
            "home_moneyline": finite_or_none(game.home_moneyline),
            "away_moneyline": finite_or_none(game.away_moneyline),
            "home_moneyline_implied_raw": home_ml_raw,
            "away_moneyline_implied_raw": away_ml_raw,
            "home_moneyline_implied_no_vig": no_vig_home,
            "market_features_available": int(home_ml_raw is not None and away_ml_raw is not None and pd.notna(game.spread_line)),
        }
        row.update(elo.get(str(game.game_id), {}))
        add_team_features(row, "home", home, game_date, int(game.season), team_hist)
        add_team_features(row, "away", away, game_date, int(game.season), team_hist)
        add_qb_features(row, "home", getattr(game, "home_qb_id"), home, game_date, qb_hist, starter_hist)
        add_qb_features(row, "away", getattr(game, "away_qb_id"), away, game_date, qb_hist, starter_hist)
        add_differences(row)
        rows.append({k: finite_or_none(v) for k, v in row.items()})

    features = pd.DataFrame(rows)
    features["created_at_utc"] = utc_now()
    return features, {"source_games": len(games), "source_team_rows": len(team), "source_qb_rows": len(qb)}


def write_table(features: pd.DataFrame) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DROP TABLE IF EXISTS nfl_features")
        features.to_sql("nfl_features", con, if_exists="replace", index=False)
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_nfl_features_game_id ON nfl_features(game_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_nfl_features_season_week ON nfl_features(season, week)")
        con.commit()


def leakage_checks(features: pd.DataFrame) -> dict[str, Any]:
    source_cols = [c for c in features.columns if c.endswith("_max_source_date")]
    violations = 0
    for col in source_cols:
        mask = features[col].notna() & (features[col] >= features["gameday"])
        violations += int(mask.sum())

    numeric = features.select_dtypes(include=[np.number]).copy()
    exclude = [c for c in numeric.columns if c.startswith("target_") or c in {"is_tie"}]
    x = numeric.drop(columns=exclude, errors="ignore")
    y = numeric["target_home_margin"]
    seasons = features["season"]
    train_mask = y.notna() & (seasons <= 2022)
    test_mask = y.notna() & (seasons >= 2023)
    usable = x.columns[x.loc[train_mask].notna().mean() >= 0.50]
    x = x[usable]
    med = x.loc[train_mask].median()
    train_x = x.loc[train_mask].fillna(med).to_numpy(dtype=float)
    test_x = x.loc[test_mask].fillna(med).to_numpy(dtype=float)
    train_y = y.loc[train_mask].to_numpy(dtype=float)
    test_y = y.loc[test_mask].to_numpy(dtype=float)
    if len(test_y) and train_x.size:
        train_x = np.column_stack([np.ones(len(train_x)), train_x])
        test_x = np.column_stack([np.ones(len(test_x)), test_x])
        coef = np.linalg.pinv(train_x) @ train_y
        pred = test_x @ coef
        ss_res = float(np.sum((test_y - pred) ** 2))
        ss_tot = float(np.sum((test_y - np.mean(test_y)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot else float("nan")
        exact_margin = float(np.mean(np.rint(pred) == test_y))
    else:
        r2 = float("nan")
        exact_margin = float("nan")

    forbidden = [c for c in features.columns if "score" in c.lower()]
    passed = violations == 0 and not forbidden and (math.isnan(exact_margin) or exact_margin < 0.25)
    if not passed:
        raise AssertionError(
            f"Leakage verification failed: violations={violations}, forbidden={forbidden}, exact_margin={exact_margin}"
        )
    return {
        "source_date_columns_checked": len(source_cols),
        "source_date_violations": violations,
        "forbidden_score_columns": forbidden,
        "holdout_margin_r2_2023_2025": r2,
        "holdout_exact_margin_reconstruction_rate": exact_margin,
        "passed": passed,
    }


def summarize(features: pd.DataFrame, source_summary: dict[str, Any], leakage: dict[str, Any]) -> str:
    row_count = len(features)
    played_no_ties = int(features["target_home_win"].notna().sum())
    by_season = features.groupby("season").size().to_dict()
    null_rates = features.isna().mean().sort_values(ascending=False)
    high_missing = null_rates[null_rates > 0.50]
    key_cols = [
        "home_elo_pregame",
        "elo_diff_with_hfa",
        "home_moneyline_implied_no_vig",
        "spread_line",
        "diff_offensive_epa_per_play_last5",
        "diff_defensive_epa_per_play_allowed_last5",
        "diff_pass_epa_per_play_last5",
        "diff_qb_passing_epa_per_dropback_last5",
        "diff_qb_passing_cpoe_last5",
        "diff_qb_prior_starts",
        "rest_diff_home_minus_away",
        "division_game",
        "wind",
        "temp",
    ]
    corr_rows = []
    target = features["target_home_win"]
    for col in key_cols:
        if col in features:
            pairs = features[[col, "target_home_win"]].dropna()
            if len(pairs) > 25 and pairs[col].nunique() > 1:
                corr = float(pairs[col].corr(pairs["target_home_win"]))
                corr_rows.append((col, corr, len(pairs)))
    corr_rows = sorted(corr_rows, key=lambda x: abs(x[1]), reverse=True)

    coverage_cols = [
        "home_moneyline_implied_no_vig",
        "spread_line",
        "home_offensive_epa_per_play_last5",
        "away_offensive_epa_per_play_last5",
        "home_offensive_epa_per_play_season_to_date",
        "home_qb_passing_epa_per_dropback_last5",
        "home_qb_changed_from_previous_game",
        "temp",
        "wind",
        "away_travel_timezone_abs",
    ]

    lines = [
        "# NFL feature engineering",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Scope and integrity",
        "",
        f"- Built table: `nfl_features` in `{DB_PATH.relative_to(ROOT)}`.",
        f"- Rows: {row_count:,} played, non-preseason games from {START_SEASON} onward; unplayed/future rows excluded.",
        f"- Non-tie binary outcome rows: {played_no_ties:,}. Ties are retained with `target_home_win` NULL.",
        f"- Source rows available: games={source_summary['source_games']:,}, team EPA={source_summary['source_team_rows']:,}, QB weekly={source_summary['source_qb_rows']:,}.",
        "- No synthetic, simulated, randomly generated, or silently imputed data was created. Missing values remain NULL.",
        "- Week 1/cold starts: trailing 3/5/8 features carry prior-season games when available; season-to-date features are NULL until a team has played earlier in the same season.",
        "- Opponent adjustment: not applied in this version. Implementing it leakage-safely would require a second pass of opponent pregame rolling baselines; raw rolling EPA is stored instead.",
        "",
        "## Rows by season",
        "",
        "| season | rows |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {season} | {count:,} |" for season, count in sorted(by_season.items()))
    lines.extend(
        [
            "",
            "## Selected feature coverage",
            "",
            "| feature | non-null coverage | null rate |",
            "| --- | ---: | ---: |",
        ]
    )
    for col in coverage_cols:
        if col in features:
            null_rate = float(features[col].isna().mean())
            lines.append(f"| `{col}` | {(1-null_rate)*100:.2f}% | {null_rate*100:.2f}% |")
    lines.extend(
        [
            "",
            "## Features with >50% missingness",
            "",
            "| feature | null rate |",
            "| --- | ---: |",
        ]
    )
    if len(high_missing):
        lines.extend(f"| `{col}` | {rate*100:.2f}% |" for col, rate in high_missing.items())
    else:
        lines.append("| None | 0.00% |")
    lines.extend(
        [
            "",
            "## Leakage verification",
            "",
            f"- Source-date columns checked: {leakage['source_date_columns_checked']}.",
            f"- Rolling/QB source-date violations (`source_date >= gameday`): {leakage['source_date_violations']}.",
            f"- Forbidden score columns in feature table: {leakage['forbidden_score_columns']}.",
            f"- Linear holdout score-margin reconstruction check (train <=2022, test 2023-2025): R²={leakage['holdout_margin_r2_2023_2025']:.3f}, exact rounded-margin reconstruction={leakage['holdout_exact_margin_reconstruction_rate']*100:.2f}%.",
            f"- Result: {'PASSED' if leakage['passed'] else 'FAILED'}.",
            "",
            "## Key correlations with home win",
            "",
            "| rank | feature | Pearson r | n |",
            "| ---: | --- | ---: | ---: |",
        ]
    )
    lines.extend(f"| {i} | `{name}` | {corr:.3f} | {n:,} |" for i, (name, corr, n) in enumerate(corr_rows[:15], 1))
    lines.extend(
        [
            "",
            "## Feature families",
            "",
            "- Team strength: pregame Elo, Elo differential, neutral-site-aware home-field adjustment.",
            "- Rolling EPA form: trailing 3/5/8 and season-to-date offense/defense EPA, pass/rush splits, success, third-down/red-zone, turnovers, and home-minus-away differentials.",
            "- Quarterback: listed starter rolling EPA/CPOE, starter-change flags, and prior-starts proxy.",
            "- Situational: rest, short week, post-bye, Thursday, division, neutral site, roof/weather, and timezone travel burden.",
            "- Market: spread, total, moneylines, raw and no-vig implied probabilities. These columns are explicitly named and can be excluded for non-market model runs.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    features, source_summary = build_features()
    write_table(features)
    leakage = leakage_checks(features)
    REPORT_PATH.write_text(summarize(features, source_summary, leakage), encoding="utf-8")
    print(f"Wrote {len(features):,} rows to nfl_features")
    print(f"Wrote report to {REPORT_PATH}")
    print(f"Leakage verification passed: {leakage}")


if __name__ == "__main__":
    main()
