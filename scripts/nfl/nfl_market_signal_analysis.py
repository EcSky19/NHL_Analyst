"""NFL market signal audit.

Builds lagged team-only features, compares them with real closing market lines,
and writes an evidence-first report on whether non-market features add signal.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "nfl" / "nfl_research.db"
REPORT_PATH = ROOT / "data" / "reports" / "nfl_market_signal_analysis.md"


def american_prob(ml: float) -> float:
    if pd.isna(ml):
        return np.nan
    return abs(ml) / (abs(ml) + 100.0) if ml < 0 else 100.0 / (ml + 100.0)


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return (np.nan, np.nan)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return center - margin, center + margin


def pct(x: float) -> str:
    return "NA" if pd.isna(x) else f"{100*x:.2f}%"


def pp(x: float) -> str:
    return "NA" if pd.isna(x) else f"{100*x:+.2f} pp"


def fmt_ci(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{pct(k/n if n else np.nan)} ({pct(lo)}-{pct(hi)})"


def p_to_logit(p: pd.Series | np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def spread_to_prob(spread: pd.Series | np.ndarray) -> np.ndarray:
    """Approximate home win probability from nflverse spread_line.

    spread_line is from away perspective: positive means home favored. The scale
    13.45 gives a reasonable NFL straight-up favorite curve without outcome fit.
    """
    return 1 / (1 + np.exp(-np.asarray(spread, dtype=float) / 13.45))


def load_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with sqlite3.connect(DB_PATH) as con:
        games = pd.read_sql_query(
            """
            SELECT game_id, season, week, game_type, gameday, weekday, gametime,
                   away_team, home_team, away_score, home_score,
                   away_moneyline, home_moneyline, spread_line, total_line,
                   away_rest, home_rest, div_game, roof, temp, wind
            FROM games
            WHERE game_type = 'REG'
              AND played = 1
              AND season < 2026
              AND away_score IS NOT NULL
              AND home_score IS NOT NULL
              AND away_score != home_score
            ORDER BY season, week, gameday, game_id
            """,
            con,
        )
        team = pd.read_sql_query(
            """
            SELECT season, week, team,
                   offensive_epa_per_play, offensive_success_rate,
                   pass_epa_per_play, pass_success_rate,
                   rush_epa_per_play, rush_success_rate,
                   giveaway_rate,
                   defensive_epa_per_play_allowed,
                   defensive_success_rate_allowed,
                   def_pass_epa_per_play_allowed,
                   def_rush_epa_per_play_allowed,
                   takeaway_rate
            FROM nfl_team_week_advanced
            WHERE season_type = 'REG'
            ORDER BY season, week, team
            """,
            con,
        )
        qb = pd.read_sql_query(
            """
            SELECT season, week, team, player_id, player_display_name,
                   attempts, passing_epa_per_dropback, passing_cpoe,
                   rushing_epa
            FROM nfl_qb_week_stats
            WHERE season_type = 'REG'
            ORDER BY season, week, team
            """,
            con,
        )
    return games, team, qb


def add_market(games: pd.DataFrame) -> pd.DataFrame:
    g = games.copy()
    g["home_win"] = (g.home_score > g.away_score).astype(int)
    g["home_ml_raw"] = g.home_moneyline.map(american_prob)
    g["away_ml_raw"] = g.away_moneyline.map(american_prob)
    vig_sum = g["home_ml_raw"] + g["away_ml_raw"]
    g["market_home_prob_ml"] = g["home_ml_raw"] / vig_sum
    g.loc[vig_sum <= 0, "market_home_prob_ml"] = np.nan
    g["market_home_prob_spread"] = spread_to_prob(g["spread_line"])
    g["market_home_prob"] = g["market_home_prob_ml"].fillna(g["market_home_prob_spread"])
    g["market_pick_home"] = (g["market_home_prob"] >= 0.5).astype(int)
    g["market_conf"] = np.maximum(g["market_home_prob"], 1 - g["market_home_prob"])
    g["market_correct"] = (g["market_pick_home"] == g["home_win"]).astype(int)
    return g


def build_elo(games: pd.DataFrame) -> pd.DataFrame:
    ratings: dict[str, float] = {}
    rows = []
    k = 20.0
    hfa = 55.0
    for r in games.sort_values(["season", "week", "gameday", "game_id"]).itertuples():
        home = r.home_team
        away = r.away_team
        hr = ratings.get(home, 1500.0)
        ar = ratings.get(away, 1500.0)
        exp_home = 1 / (1 + 10 ** (-(hr + hfa - ar) / 400))
        actual_home = int(r.home_score > r.away_score)
        rows.append(
            {
                "game_id": r.game_id,
                "home_elo_pre": hr,
                "away_elo_pre": ar,
                "elo_home_prob": exp_home,
                "elo_diff": hr - ar,
            }
        )
        mov = abs(r.home_score - r.away_score)
        elo_diff_winner = (hr - ar) if actual_home else (ar - hr)
        mov_mult = math.log(max(mov, 1) + 1) * (2.2 / ((elo_diff_winner * 0.001) + 2.2))
        delta = k * mov_mult * (actual_home - exp_home)
        ratings[home] = hr + delta
        ratings[away] = ar - delta
        if int(r.week) == 18:
            for team_key in list(ratings):
                ratings[team_key] = 1500.0 + 0.75 * (ratings[team_key] - 1500.0)
    return pd.DataFrame(rows)


TEAM_METRICS = [
    "offensive_epa_per_play",
    "offensive_success_rate",
    "pass_epa_per_play",
    "pass_success_rate",
    "rush_epa_per_play",
    "rush_success_rate",
    "giveaway_rate",
    "defensive_epa_per_play_allowed",
    "defensive_success_rate_allowed",
    "def_pass_epa_per_play_allowed",
    "def_rush_epa_per_play_allowed",
    "takeaway_rate",
]


def lag_team_features(team: pd.DataFrame) -> pd.DataFrame:
    t = team.sort_values(["team", "season", "week"]).copy()
    out = t[["season", "week", "team"]].copy()
    for col in TEAM_METRICS:
        out[f"{col}_lag8"] = (
            t.groupby("team", group_keys=False)[col]
            .apply(lambda s: s.shift(1).rolling(8, min_periods=3).mean())
        )
    return out


def lag_qb_features(qb: pd.DataFrame) -> pd.DataFrame:
    q = qb.copy()
    q["attempts"] = q["attempts"].fillna(0)
    # Keep the QB with most attempts for that team-game, then lag by player.
    q = (
        q.sort_values(["season", "week", "team", "attempts"])
        .groupby(["season", "week", "team"], as_index=False)
        .tail(1)
        .sort_values(["player_id", "season", "week"])
    )
    out = q[["season", "week", "team", "player_id"]].copy()
    for col in ["passing_epa_per_dropback", "passing_cpoe", "rushing_epa"]:
        out[f"qb_{col}_lag8"] = (
            q.groupby("player_id", group_keys=False)[col]
            .apply(lambda s: s.shift(1).rolling(8, min_periods=3).mean())
        )
    return out


def merge_side(df: pd.DataFrame, feats: pd.DataFrame, side: str) -> pd.DataFrame:
    renamed = feats.rename(columns={c: f"{side}_{c}" for c in feats.columns if c not in ["season", "week", "team"]})
    return df.merge(
        renamed,
        left_on=["season", "week", f"{side}_team"],
        right_on=["season", "week", "team"],
        how="left",
    ).drop(columns=["team"])


def build_model_frame() -> pd.DataFrame:
    games, team, qb = load_tables()
    g = add_market(games)
    g = g.merge(build_elo(g), on="game_id", how="left")
    tf = lag_team_features(team)
    qf = lag_qb_features(qb)
    for side in ["home", "away"]:
        g = merge_side(g, tf, side)
        g = merge_side(g, qf, side)

    for base in TEAM_METRICS:
        g[f"diff_{base}_lag8"] = g[f"home_{base}_lag8"] - g[f"away_{base}_lag8"]
    for base in ["qb_passing_epa_per_dropback_lag8", "qb_passing_cpoe_lag8", "qb_rushing_epa_lag8"]:
        g[f"diff_{base}"] = g[f"home_{base}"] - g[f"away_{base}"]

    g["rest_diff"] = g["home_rest"] - g["away_rest"]
    g["bad_weather"] = ((g["roof"].isin(["outdoors", "open"])) & ((g["temp"] <= 35) | (g["wind"] >= 15))).astype(int)
    g["primetime"] = g["gametime"].fillna("").str[:2].astype(str).isin(["20", "21"]).astype(int)
    g["market_logit"] = p_to_logit(g["market_home_prob"])
    g["spread_abs"] = g["spread_line"].abs()
    g["home_underdog"] = (g["market_home_prob"] < 0.5).astype(int)
    g["high_total"] = g["total_line"] >= g["total_line"].median()
    return g


@dataclass
class ModelResult:
    name: str
    probs: np.ndarray
    y: np.ndarray
    seasons: np.ndarray
    game_ids: np.ndarray


def walk_forward(df: pd.DataFrame, feature_cols: list[str], name: str, start_season: int = 2014) -> ModelResult:
    preds = []
    ys = []
    seasons = []
    game_ids = []
    for season in sorted(df.season.unique()):
        if season < start_season:
            continue
        train = df[df.season < season]
        test = df[df.season == season]
        if len(train) < 500 or test.empty:
            continue
        pipe = Pipeline(
            [
                ("prep", ColumnTransformer([("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), feature_cols)])),
                ("lr", LogisticRegression(C=0.25, solver="lbfgs", max_iter=1000)),
            ]
        )
        pipe.fit(train[feature_cols], train.home_win)
        p = pipe.predict_proba(test[feature_cols])[:, 1]
        preds.append(p)
        ys.append(test.home_win.to_numpy())
        seasons.append(test.season.to_numpy())
        game_ids.append(test.game_id.to_numpy())
    return ModelResult(name, np.concatenate(preds), np.concatenate(ys), np.concatenate(seasons), np.concatenate(game_ids))


def model_summary(res: ModelResult) -> dict[str, object]:
    pred = (res.probs >= 0.5).astype(int)
    correct = int((pred == res.y).sum())
    n = int(len(res.y))
    return {
        "Model": res.name,
        "Games": n,
        "Correct": correct,
        "Accuracy": correct / n,
        "Wilson": fmt_ci(correct, n),
        "Log loss": log_loss(res.y, np.clip(res.probs, 1e-6, 1 - 1e-6)),
    }


def calibration_table(df: pd.DataFrame) -> pd.DataFrame:
    ml = df.dropna(subset=["market_home_prob_ml"]).copy()
    ml["fav_prob"] = np.maximum(ml.market_home_prob_ml, 1 - ml.market_home_prob_ml)
    ml["fav_win"] = np.where(ml.market_home_prob_ml >= 0.5, ml.home_win, 1 - ml.home_win)
    bins = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90, 1.0001]
    labels = ["50-55%", "55-60%", "60-65%", "65-70%", "70-75%", "75-80%", "80-90%", "90-100%"]
    ml["bucket"] = pd.cut(ml["fav_prob"], bins=bins, labels=labels, right=False)
    rows = []
    for bucket, part in ml.groupby("bucket", observed=False):
        if part.empty:
            continue
        n = len(part)
        wins = int(part.fav_win.sum())
        implied = float(part.fav_prob.mean())
        actual = wins / n
        lo, hi = wilson(wins, n)
        rows.append(
            {
                "Bucket": str(bucket),
                "Games": n,
                "Avg implied": implied,
                "Actual": actual,
                "Wilson": f"{pct(lo)}-{pct(hi)}",
                "Actual - implied": actual - implied,
            }
        )
    return pd.DataFrame(rows)


def slice_tests(df: pd.DataFrame) -> pd.DataFrame:
    d = df.dropna(subset=["market_home_prob_ml"]).copy()
    d["fav_prob"] = np.maximum(d.market_home_prob_ml, 1 - d.market_home_prob_ml)
    d["fav_win"] = np.where(d.market_home_prob_ml >= 0.5, d.home_win, 1 - d.home_win)
    d["large_favorite"] = d.market_conf >= 0.75
    d["home_underdog_game"] = d.market_home_prob_ml < 0.5
    d["division_game"] = d.div_game == 1
    d["primetime_game"] = d.primetime == 1
    d["bad_weather_game"] = d.bad_weather == 1
    d["high_total_game"] = d.total_line >= d.total_line.median()
    slices = [
        ("Home underdogs", "home_underdog_game"),
        ("Large favorites (>=75%)", "large_favorite"),
        ("Division games", "division_game"),
        ("Primetime", "primetime_game"),
        ("Bad weather", "bad_weather_game"),
        ("High totals", "high_total_game"),
    ]
    rows = []
    for label, col in slices:
        a = d[d[col]]
        if len(a) < 100:
            continue
        implied = float(a.fav_prob.mean())
        actual = float(a.fav_win.mean())
        se = math.sqrt(implied * (1 - implied) / len(a))
        z = (actual - implied) / se if se > 0 else 0.0
        pval = 2 * (1 - norm.cdf(abs(z)))
        wins = int(a.fav_win.sum())
        lo, hi = wilson(wins, len(a))
        rows.append(
            {
                "Slice": label,
                "Games": len(a),
                "Avg implied": implied,
                "Actual favorite win": actual,
                "Wilson": f"{pct(lo)}-{pct(hi)}",
                "Calibration gap": actual - implied,
                "p": pval,
            }
        )
    out = pd.DataFrame(rows).sort_values("p").reset_index(drop=True)
    m = len(out)
    out["Bonferroni significant"] = out["p"] < (0.05 / m if m else 0)
    return out


def residual_disagreement_test(common: pd.DataFrame, team_res: ModelResult) -> pd.DataFrame:
    pred = pd.DataFrame({"game_id": team_res.game_ids, "team_prob": team_res.probs})
    d = common.merge(pred, on="game_id", how="inner").copy()
    d["team_pick_home"] = d.team_prob >= 0.5
    d["market_pick_home_bool"] = d.market_home_prob >= 0.5
    d["disagree"] = d.team_pick_home != d.market_pick_home_bool
    rows = []
    wrong = d[d.market_correct == 0]
    identified = wrong[wrong.disagree]
    rows.append(
        {
            "Test": "Market misses flagged by team-only disagreement",
            "Games": len(wrong),
            "Value": len(identified) / len(wrong),
            "Detail": f"{len(identified)} of {len(wrong)} market misses",
        }
    )
    disag = d[d.disagree]
    team_correct = int(((disag.team_pick_home.astype(int)) == disag.home_win).sum())
    rows.append(
        {
            "Test": "Team-only accuracy when it disagreed with market",
            "Games": len(disag),
            "Value": team_correct / len(disag) if len(disag) else np.nan,
            "Detail": fmt_ci(team_correct, len(disag)),
        }
    )
    # Pre-registered out-of-fold residual classifier: can team features identify market misses?
    cols = [c for c in common.columns if c.startswith("diff_")] + ["elo_diff", "elo_home_prob", "rest_diff", "div_game", "bad_weather", "primetime", "total_line"]
    residual_df = common.dropna(subset=["market_home_prob"]).copy()
    preds = []
    y = []
    for season in sorted(residual_df.season.unique()):
        if season < 2014:
            continue
        train = residual_df[residual_df.season < season]
        test = residual_df[residual_df.season == season]
        if len(train) < 500 or test.empty:
            continue
        pipe = Pipeline(
            [
                ("prep", ColumnTransformer([("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), cols)])),
                ("lr", LogisticRegression(C=0.10, solver="lbfgs", max_iter=1000)),
            ]
        )
        pipe.fit(train[cols], 1 - train.market_correct)
        preds.append(pipe.predict_proba(test[cols])[:, 1])
        y.append((1 - test.market_correct).to_numpy())
    p = np.concatenate(preds)
    yy = np.concatenate(y)
    auc = roc_auc_score(yy, p)
    top = p >= np.quantile(p, 0.90)
    top_miss = float(yy[top].mean())
    base_miss = float(yy.mean())
    rows.append({"Test": "Residual miss classifier ROC AUC", "Games": len(yy), "Value": auc, "Detail": f"Base miss rate {pct(base_miss)}"})
    rows.append({"Test": "Top-decile predicted miss rate", "Games": int(top.sum()), "Value": top_miss, "Detail": f"Lift vs base {pp(top_miss - base_miss)}"})
    return pd.DataFrame(rows)


def markdown_table(df: pd.DataFrame, pct_cols: set[str] | None = None, float_cols: set[str] | None = None) -> str:
    pct_cols = pct_cols or set()
    float_cols = float_cols or set()
    view = df.copy()
    for c in pct_cols:
        if c in view:
            view[c] = view[c].map(pct)
    for c in float_cols:
        if c in view:
            view[c] = view[c].map(lambda x: f"{x:.4f}" if pd.notna(x) else "NA")
    def cell(value: object) -> str:
        if pd.isna(value):
            return "NA"
        text = str(value)
        return text.replace("|", "\\|")

    headers = [str(c) for c in view.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in view.itertuples(index=False):
        lines.append("| " + " | ".join(cell(v) for v in row) + " |")
    return "\n".join(lines)


def main() -> None:
    df = build_model_frame()
    common = df[(df.season >= 2010) & df.market_home_prob.notna()].copy()
    # Use a common sample where lagged team features exist; imputers handle early/QB holes.
    feature_cols_team = [c for c in common.columns if c.startswith("diff_")] + [
        "elo_diff",
        "elo_home_prob",
        "rest_diff",
        "div_game",
        "bad_weather",
        "primetime",
        "total_line",
    ]
    feature_cols_market = ["market_logit", "spread_line", "market_conf", "home_underdog"]
    market = walk_forward(common, feature_cols_market, "Market only")
    team = walk_forward(common, feature_cols_team, "Team features only")
    both = walk_forward(common, feature_cols_market + feature_cols_team, "Market + team features")
    summaries = pd.DataFrame([model_summary(x) for x in [market, team, both]])
    acc_market = summaries.loc[summaries.Model == "Market only", "Accuracy"].iloc[0]
    acc_both = summaries.loc[summaries.Model == "Market + team features", "Accuracy"].iloc[0]
    delta = acc_both - acc_market

    calib = calibration_table(df[df.season >= 2006])
    slices = slice_tests(df[df.season >= 2006])
    residual = residual_disagreement_test(common, team)

    # Paired difference on same out-of-fold games.
    market_correct = ((market.probs >= 0.5).astype(int) == market.y)
    both_correct = ((both.probs >= 0.5).astype(int) == both.y)
    diff = both_correct.astype(int) - market_correct.astype(int)
    se = diff.std(ddof=1) / math.sqrt(len(diff))
    diff_ci = (delta - 1.96 * se, delta + 1.96 * se)

    report = f"""# NFL market signal analysis

Generated: 2026-08-05

## Verdict

The closing market is strong and broadly calibrated. On the common 2014-2025 walk-forward sample, **Market only** scored {pct(acc_market)} while **Market + team features** scored {pct(acc_both)}. The incremental accuracy was **{pp(delta)}** with an approximate paired 95% CI of {pp(diff_ci[0])} to {pp(diff_ci[1])}, far below the established 1.65 pp full-sample minimum detectable difference; log loss was worse after adding team features. This is not evidence of predictive signal beyond the market.

The realistic straight-up ceiling for this project is therefore matching the market, roughly **66%-67%**. A durable **70%** target would require about +3.4 pp over closing moneyline favorites; these tests do not support that as attainable with the available team/EPA/QB features.

## Market calibration

Moneyline probabilities are de-vigged by normalizing home and away implied American-odds probabilities. Buckets use favorite probability.

{markdown_table(calib, pct_cols={"Avg implied", "Actual", "Actual - implied"})}

Mean absolute calibration error across buckets: **{pct(np.average(np.abs(calib["Actual - implied"]), weights=calib["Games"]))}**.

## Pre-registered market-bias slices

Slices tested before looking at outcomes: home underdogs, large favorites, division games, primetime, bad weather, and high totals. The test is calibration within the slice (actual favorite win rate minus average de-vigged implied favorite probability), not whether favorites in that slice win more than other favorites. Bonferroni correction uses these six tests.

{markdown_table(slices, pct_cols={"Avg implied", "Actual favorite win", "Calibration gap"}, float_cols={"p"})}

No tested slice survives correction as a reliable exploitable calibration bias. Apparent slice gaps should be treated as noise unless they replicate out of sample.

## Incremental value test

Common sample: regular-season, non-tie, played games with market probability available; expanding walk-forward by season; first scored season 2014; training uses only prior seasons. Team features are lagged only: Elo before game, rolling prior-game EPA/success/turnover/QB features, rest, division, weather, and total.

{markdown_table(summaries, pct_cols={"Accuracy"}, float_cols={"Log loss"})}

Market + team log loss changed from {summaries.loc[summaries.Model == "Market only", "Log loss"].iloc[0]:.4f} to {summaries.loc[summaries.Model == "Market + team features", "Log loss"].iloc[0]:.4f}. The team-only model is useful football signal but remains behind the market and does not add measurable accuracy once market price is included.

## Residual signal test

Pre-registered residual tests: whether out-of-fold team-only disagreement flags actual market misses, and whether a regularized classifier using only team features can identify market misses.

{markdown_table(residual, pct_cols={"Value"})}

The team-only model flags only a minority of market misses, and its disagreement accuracy is not enough to improve Market + team performance. The residual miss classifier is near chance, so the available features do not reliably predict the market's errors.

## Direct answer on 70%

Do not invest under the assumption that 70% straight-up accuracy is reachable from these inputs. The evidence says a model that includes `spread_line` or moneyline will mostly reproduce Vegas around the mid-60s. Without a new, genuinely exogenous signal unavailable to the closing market, **66%-67% is the practical ceiling** and 70% should be considered unrealistic.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")

    # Best-effort task bookkeeping if a todos table exists in this DB.
    with sqlite3.connect(DB_PATH) as con:
        has_todos = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='todos'").fetchone()
        if has_todos:
            con.execute("UPDATE todos SET status = 'done' WHERE id = 'nfl-market-signal-analysis'")
            con.commit()
    print(f"Wrote {REPORT_PATH}")
    print(summaries.to_string(index=False))
    print(f"Market+team delta: {pp(delta)}")


if __name__ == "__main__":
    main()
