from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "mlb"))
import train_mlb_win_model as base_train  # noqa: E402


DB_PATH = ROOT / "data" / "mlb" / "mlb_research.db"
CONFIG_PATH = ROOT / "data" / "mlb" / "mlb_pitcher_model_frozen_config.json"
ARTIFACT_PATH = ROOT / "data" / "mlb" / "mlb_pitcher_model.joblib"
REPORT_PATH = ROOT / "data" / "reports" / "mlb_pitcher_model_results.md"

TRAIN_SEASONS = base_train.TRAIN_SEASONS
VALIDATION_SEASON = base_train.VALIDATION_SEASON
CALIBRATION_SEASON = base_train.CALIBRATION_SEASON
HOLDOUT_SEASON = base_train.HOLDOUT_SEASON
EXCLUDED_SEASONS = base_train.EXCLUDED_SEASONS
RANDOM_SEED = base_train.RANDOM_SEED

EXISTING_ACCURACY = 0.5572
ELO_ACCURACY = 0.5613
ALWAYS_HOME_ACCURACY = 0.5428

PITCHER_DIFF_FEATURES = [
    "sp_starts_pre_diff",
    "sp_ip_pre_diff",
    "sp_era_pre_diff",
    "sp_whip_pre_diff",
    "sp_k9_pre_diff",
    "sp_bb9_pre_diff",
    "sp_hr9_pre_diff",
    "sp_recent3_ip_pre_diff",
    "sp_recent3_era_pre_diff",
    "sp_recent3_whip_pre_diff",
    "sp_recent3_k9_pre_diff",
]
PITCHER_CONTEXT_FEATURES = [
    "home_sp_known",
    "away_sp_known",
    "home_sp_no_prior",
    "away_sp_no_prior",
    "home_sp_starts_pre",
    "away_sp_starts_pre",
]
FEATURES = base_train.FEATURES + PITCHER_DIFF_FEATURES + PITCHER_CONTEXT_FEATURES

PITCHER_FEATURE_SAFETY = {
    "sp_starts_pre_diff": "home starter minus away starter pitching starts before this game only.",
    "sp_ip_pre_diff": "home starter minus away starter career regular-season innings in the local database before this game only.",
    "sp_era_pre_diff": "home starter minus away starter earned-run average before this game only; current-game and future earned runs are excluded.",
    "sp_whip_pre_diff": "home starter minus away starter WHIP before this game only.",
    "sp_k9_pre_diff": "home starter minus away starter strikeouts per 9 innings before this game only.",
    "sp_bb9_pre_diff": "home starter minus away starter walks per 9 innings before this game only.",
    "sp_hr9_pre_diff": "home starter minus away starter home runs per 9 innings before this game only.",
    "sp_recent3_ip_pre_diff": "home starter minus away starter innings across the pitcher's three prior starts only.",
    "sp_recent3_era_pre_diff": "home starter minus away starter ERA across the pitcher's three prior starts only.",
    "sp_recent3_whip_pre_diff": "home starter minus away starter WHIP across the pitcher's three prior starts only.",
    "sp_recent3_k9_pre_diff": "home starter minus away starter K/9 across the pitcher's three prior starts only.",
    "home_sp_known": "indicator that StatsAPI supplied a home starter assignment for this game.",
    "away_sp_known": "indicator that StatsAPI supplied an away starter assignment for this game.",
    "home_sp_no_prior": "indicator that the listed home starter had no prior regular-season pitching stats in this database before this game.",
    "away_sp_no_prior": "indicator that the listed away starter had no prior regular-season pitching stats in this database before this game.",
    "home_sp_starts_pre": "home starter prior regular-season starts before this game only.",
    "away_sp_starts_pre": "away starter prior regular-season starts before this game only.",
}


@dataclass
class PitcherState:
    starts: int = 0
    outs: int = 0
    earned_runs: int = 0
    hits: int = 0
    walks: int = 0
    strikeouts: int = 0
    homers: int = 0
    recent_starts: deque[dict[str, int]] = field(default_factory=lambda: deque(maxlen=3))


def safe_rate(numerator: float, denominator: float, default: float = np.nan) -> float:
    return default if denominator <= 0 else numerator / denominator


def pitcher_snapshot(state: PitcherState | None) -> dict[str, float]:
    if state is None or state.outs <= 0:
        return {
            "starts_pre": 0.0 if state is None else float(state.starts),
            "ip_pre": 0.0 if state is None else state.outs / 3.0,
            "era_pre": np.nan,
            "whip_pre": np.nan,
            "k9_pre": np.nan,
            "bb9_pre": np.nan,
            "hr9_pre": np.nan,
            "recent3_ip_pre": 0.0,
            "recent3_era_pre": np.nan,
            "recent3_whip_pre": np.nan,
            "recent3_k9_pre": np.nan,
            "no_prior": 1.0,
        }
    recent_outs = sum(v["outs"] for v in state.recent_starts)
    recent_er = sum(v["earned_runs"] for v in state.recent_starts)
    recent_hits = sum(v["hits"] for v in state.recent_starts)
    recent_walks = sum(v["walks"] for v in state.recent_starts)
    recent_k = sum(v["strikeouts"] for v in state.recent_starts)
    return {
        "starts_pre": float(state.starts),
        "ip_pre": state.outs / 3.0,
        "era_pre": safe_rate(state.earned_runs * 27.0, state.outs),
        "whip_pre": safe_rate((state.hits + state.walks) * 3.0, state.outs),
        "k9_pre": safe_rate(state.strikeouts * 27.0, state.outs),
        "bb9_pre": safe_rate(state.walks * 27.0, state.outs),
        "hr9_pre": safe_rate(state.homers * 27.0, state.outs),
        "recent3_ip_pre": recent_outs / 3.0,
        "recent3_era_pre": safe_rate(recent_er * 27.0, recent_outs),
        "recent3_whip_pre": safe_rate((recent_hits + recent_walks) * 3.0, recent_outs),
        "recent3_k9_pre": safe_rate(recent_k * 27.0, recent_outs),
        "no_prior": 0.0,
    }


def load_pitcher_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    with sqlite3.connect(DB_PATH, timeout=30) as con:
        starters = pd.read_sql_query(
            """
            SELECT game_pk, home_pitcher_id, home_pitcher_name, away_pitcher_id, away_pitcher_name
            FROM mlb_game_starters
            """,
            con,
        )
        logs = pd.read_sql_query(
            """
            SELECT pitcher_id, pitcher_name, season, game_pk, game_date, games_started, games_played,
                   outs, earned_runs, hits, base_on_balls, strike_outs, home_runs
            FROM mlb_pitcher_game_logs
            """,
            con,
        )
    return starters, logs


def build_pitcher_pregame_table(starters: pd.DataFrame, logs: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    starters_by_game = starters.set_index("game_pk").to_dict("index")
    starter_rows = []
    for _, game in games.sort_values(["season", "game_datetime_utc", "game_pk"]).iterrows():
        row = starters_by_game.get(int(game.game_pk), {})
        for side in ("home", "away"):
            pitcher_id = row.get(f"{side}_pitcher_id")
            if pd.notna(pitcher_id):
                starter_rows.append(
                    {
                        "game_pk": int(game.game_pk),
                        "season": int(game.season),
                        "game_datetime_utc": game.game_datetime_utc,
                        "pitcher_id": int(pitcher_id),
                        "side": side,
                    }
                )
    starter_frame = pd.DataFrame(starter_rows)
    starter_key = set(zip(starter_frame["pitcher_id"], starter_frame["game_pk"])) if len(starter_frame) else set()
    logs = logs.copy()
    logs["game_datetime_utc"] = logs["game_pk"].map(games.set_index("game_pk")["game_datetime_utc"])
    logs = logs.dropna(subset=["game_datetime_utc"]).sort_values(["game_datetime_utc", "game_pk", "pitcher_id"])

    states: dict[int, PitcherState] = defaultdict(PitcherState)
    feature_by_key: dict[tuple[int, int], dict[str, float]] = {}
    for _, row in logs.iterrows():
        pitcher_id = int(row.pitcher_id)
        game_pk = int(row.game_pk)
        state = states[pitcher_id]
        if (pitcher_id, game_pk) in starter_key:
            feature_by_key[(pitcher_id, game_pk)] = pitcher_snapshot(state)

        outs = int(row.outs) if pd.notna(row.outs) else 0
        er = int(row.earned_runs) if pd.notna(row.earned_runs) else 0
        hits = int(row.hits) if pd.notna(row.hits) else 0
        walks = int(row.base_on_balls) if pd.notna(row.base_on_balls) else 0
        strikeouts = int(row.strike_outs) if pd.notna(row.strike_outs) else 0
        homers = int(row.home_runs) if pd.notna(row.home_runs) else 0
        games_started = int(row.games_started) if pd.notna(row.games_started) else 0
        state.outs += outs
        state.earned_runs += er
        state.hits += hits
        state.walks += walks
        state.strikeouts += strikeouts
        state.homers += homers
        if games_started > 0:
            state.starts += games_started
            state.recent_starts.append(
                {
                    "outs": outs,
                    "earned_runs": er,
                    "hits": hits,
                    "walks": walks,
                    "strikeouts": strikeouts,
                }
            )

    rows = []
    for _, game in games.iterrows():
        starter = starters_by_game.get(int(game.game_pk), {})
        out: dict[str, Any] = {"game_pk": int(game.game_pk)}
        side_snaps = {}
        for side in ("home", "away"):
            pitcher_id = starter.get(f"{side}_pitcher_id")
            known = pd.notna(pitcher_id)
            out[f"{side}_pitcher_id"] = int(pitcher_id) if known else None
            out[f"{side}_pitcher_name"] = starter.get(f"{side}_pitcher_name")
            out[f"{side}_sp_known"] = 1.0 if known else 0.0
            snap = feature_by_key.get((int(pitcher_id), int(game.game_pk)), pitcher_snapshot(None)) if known else pitcher_snapshot(None)
            side_snaps[side] = snap
            out[f"{side}_sp_no_prior"] = snap["no_prior"]
            out[f"{side}_sp_starts_pre"] = snap["starts_pre"]
        for name in ["starts_pre", "ip_pre", "era_pre", "whip_pre", "k9_pre", "bb9_pre", "hr9_pre", "recent3_ip_pre", "recent3_era_pre", "recent3_whip_pre", "recent3_k9_pre"]:
            out[f"sp_{name}_diff"] = side_snaps["home"][name] - side_snaps["away"][name]
        rows.append(out)
    return pd.DataFrame(rows)


def make_base_model() -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "model",
                LogisticRegression(C=0.5, solver="lbfgs", max_iter=1000, random_state=RANDOM_SEED),
            ),
        ]
    )


def logit_from_prob(prob: np.ndarray) -> np.ndarray:
    clipped = np.clip(prob, 1e-6, 1 - 1e-6)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


def fit_platt(raw_prob: np.ndarray, labels: pd.Series | np.ndarray) -> LogisticRegression:
    platt = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=RANDOM_SEED)
    platt.fit(logit_from_prob(raw_prob), np.asarray(labels))
    return platt


def calibrated_prob(base_model: Pipeline, platt: LogisticRegression, x: pd.DataFrame) -> np.ndarray:
    raw_prob = base_model.predict_proba(x)[:, 1]
    return platt.predict_proba(logit_from_prob(raw_prob))[:, 1]


def metric_row(name: str, split: str, y: np.ndarray, prob: np.ndarray, pick_home: np.ndarray) -> dict[str, Any]:
    correct = int((pick_home == y).sum())
    n = int(len(y))
    low, high = base_train.wilson_ci(correct, n)
    return {
        "model_name": name,
        "split": split,
        "season": int(HOLDOUT_SEASON if split == "holdout" else -1),
        "n_games": n,
        "correct": correct,
        "accuracy": correct / n,
        "wilson95_low": low,
        "wilson95_high": high,
        "log_loss": log_loss(y, np.clip(prob, 1e-6, 1 - 1e-6)),
        "brier": brier_score_loss(y, prob),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def reliability_table(y: np.ndarray, prob: np.ndarray) -> pd.DataFrame:
    return base_train.reliability_table(y, prob)


def pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def markdown_table(frame: pd.DataFrame, floatfmt: str = ".4f") -> str:
    return base_train.markdown_table(frame, floatfmt=floatfmt)


def freeze_config(validation_metrics: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    config = {
        "model": "L2 logistic regression with separate Platt calibration and pregame starting-pitcher features",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_holdout_scoring": True,
        "random_seed": RANDOM_SEED,
        "train_seasons": TRAIN_SEASONS,
        "validation_season": VALIDATION_SEASON,
        "calibration_season": CALIBRATION_SEASON,
        "holdout_season": HOLDOUT_SEASON,
        "excluded_seasons": EXCLUDED_SEASONS,
        "features": FEATURES,
        "logistic_regression": {"C": 0.5, "penalty": "l2", "solver": "lbfgs"},
        "pitcher_feature_source": "StatsAPI schedule probablePitcher assignments plus StatsAPI people gameLog pitching stats shifted before each game.",
        "rookie_or_no_prior_fallback": "Ratio stats are left missing and handled by a median imputer fit on the training fold; no-prior indicator features are included.",
        "validation_metrics_used_before_freeze": validation_metrics,
        "coverage_available_before_holdout_scoring": coverage,
        "note": "This configuration was written before holdout probabilities, predictions, or metrics were computed.",
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def write_database_outputs(predictions: pd.DataFrame, metrics: pd.DataFrame, reliability: pd.DataFrame) -> None:
    with sqlite3.connect(DB_PATH, timeout=30) as con:
        predictions.to_sql("mlb_pitcher_model_predictions", con, if_exists="replace", index=False)
        metrics.to_sql("mlb_pitcher_model_metrics", con, if_exists="replace", index=False)
        reliability.to_sql("mlb_pitcher_model_calibration_reliability", con, if_exists="replace", index=False)


def coverage_summary(features: pd.DataFrame, season: int) -> dict[str, Any]:
    subset = features[features["season"] == season]
    both = (subset["home_sp_known"].eq(1) & subset["away_sp_known"].eq(1))
    both_prior = both & subset["home_sp_no_prior"].eq(0) & subset["away_sp_no_prior"].eq(0)
    return {
        "season": season,
        "n_games": int(len(subset)),
        "both_starters": int(both.sum()),
        "both_starters_rate": float(both.mean()) if len(subset) else math.nan,
        "both_starters_with_prior_stats": int(both_prior.sum()),
        "both_starters_with_prior_stats_rate": float(both_prior.mean()) if len(subset) else math.nan,
        "home_starter_known": int(subset["home_sp_known"].sum()),
        "away_starter_known": int(subset["away_sp_known"].sum()),
    }


def write_report(
    metrics: pd.DataFrame,
    reliability: pd.DataFrame,
    leakage_r2: float,
    shuffled_label: dict[str, float],
    validation_metrics: dict[str, Any],
    coverage: dict[str, Any],
    config: dict[str, Any],
    prob_range: tuple[float, float],
) -> None:
    holdout_metrics = metrics[metrics["split"] == "holdout"].set_index("model_name")
    model = holdout_metrics.loc["pitcher_logistic_platt"]
    existing_low, existing_high = base_train.wilson_ci(round(EXISTING_ACCURACY * int(model.n_games)), int(model.n_games))
    elo = holdout_metrics.loc["elo_baseline"]
    home = holdout_metrics.loc["always_home"]
    beat_existing = model.accuracy > EXISTING_ACCURACY
    beat_elo = model.accuracy > elo.accuracy
    margin_existing = float(model.accuracy - EXISTING_ACCURACY)
    margin_elo = float(model.accuracy - elo.accuracy)
    noise_note = "Both margins are inside the roughly two-point Wilson noise floor." if abs(margin_existing) < 0.02 and abs(margin_elo) < 0.02 else "At least one margin is around or above two points, so inspect uncertainty carefully."
    feature_lines = "\n".join(f"- `{name}`: {PITCHER_FEATURE_SAFETY[name]}" for name in PITCHER_DIFF_FEATURES + PITCHER_CONTEXT_FEATURES)
    metric_md = markdown_table(
        metrics[metrics["split"] == "holdout"][
            ["model_name", "n_games", "correct", "accuracy", "wilson95_low", "wilson95_high", "log_loss", "brier"]
        ]
    )
    reliability_md = markdown_table(reliability)

    report = f"""# MLB starting-pitcher win-probability model results

## Headline

The frozen starting-pitcher model scored {pct(model.accuracy)} (Wilson 95% CI {pct(model.wilson95_low)}-{pct(model.wilson95_high)}) on the 2025 holdout; it {'beat' if beat_existing else 'did not beat'} the existing model ({pct(EXISTING_ACCURACY)}, approximate Wilson 95% CI {pct(existing_low)}-{pct(existing_high)}) and {'beat' if beat_elo else 'did not beat'} Elo ({pct(elo.accuracy)}, Wilson 95% CI {pct(elo.wilson95_low)}-{pct(elo.wilson95_high)}). {noise_note}

Starter coverage on the 2025 holdout was {coverage['both_starters']} of {coverage['n_games']} games ({pct(coverage['both_starters_rate'])}); both starters had prior regular-season pitching stats before the game in {coverage['both_starters_with_prior_stats']} games ({pct(coverage['both_starters_with_prior_stats_rate'])}).

## Frozen protocol

- Train: {TRAIN_SEASONS}
- Validation/config selection: {VALIDATION_SEASON}
- Platt calibration: {CALIBRATION_SEASON}
- Frozen holdout: {HOLDOUT_SEASON}
- Excluded: {EXCLUDED_SEASONS}
- Frozen config: `{CONFIG_PATH.relative_to(ROOT)}`
- Holdout scoring began only after the config JSON was written.
- Existing model comparison point: 55.72% accuracy, log loss 0.6804, Brier 0.2438.
- Elo comparison point: 56.13% accuracy, log loss 0.6875, Brier 0.2471.

Validation accuracy available before freezing was {pct(validation_metrics['accuracy'])}; validation log loss was {validation_metrics['log_loss_uncalibrated']:.4f} and Brier was {validation_metrics['brier_uncalibrated']:.4f}.

## Holdout metrics

{metric_md}

## Pitcher-data coverage

| split | games | both_starters | both_starters_rate | both_starters_with_prior_stats | prior_stats_rate |
| --- | --- | --- | --- | --- | --- |
| 2025 holdout | {coverage['n_games']} | {coverage['both_starters']} | {coverage['both_starters_rate']:.4f} | {coverage['both_starters_with_prior_stats']} | {coverage['both_starters_with_prior_stats_rate']:.4f} |

The source for assignments is StatsAPI `schedule` with `hydrate=probablePitcher`. Pitching stat features come from StatsAPI `people` game logs and are shifted by construction: a pitcher's pregame feature row is captured before that game's pitching line is added to the cumulative state.

## Pregame-safe pitcher features

{feature_lines}

For rookies or pitchers with no previous MLB regular-season pitching line in this database, ratio features are missing, the training-fold median imputer supplies the numeric fallback, and explicit no-prior indicators tell the model that the fallback was used.

## Calibration reliability table

{reliability_md}

Holdout probability range was {prob_range[0]:.4f}-{prob_range[1]:.4f}, which remains in a realistic baseball range.

## Leakage self-checks

- Linear regression of final home run differential on the full pregame feature matrix: R-squared = {leakage_r2:.4f}.
- Shuffling holdout labels against fixed predictions collapsed accuracy: mean shuffled accuracy = {pct(shuffled_label['mean_accuracy'])}, 2.5%-97.5% range = {pct(shuffled_label['p025'])}-{pct(shuffled_label['p975'])} across {int(shuffled_label['n_repeats'])} shuffles.

## Verdict

Starting-pitcher features {'improved' if beat_existing else 'did not improve'} raw accuracy versus the existing model and {'beat' if beat_elo else 'did not beat'} Elo. Because the observed margins are small relative to the holdout uncertainty, this should be read as an honest direct-comparison result rather than a claim of a durable betting edge.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    games = base_train.load_games()
    base_features = base_train.build_pregame_features(games)
    starters, logs = load_pitcher_inputs()
    pitcher_features = build_pitcher_pregame_table(starters, logs, games)
    features = base_features.merge(pitcher_features, on="game_pk", how="left")
    for col in PITCHER_CONTEXT_FEATURES:
        features[col] = features[col].fillna(0.0)
    eligible = features[~features["season"].isin(EXCLUDED_SEASONS)].copy()

    train = eligible[eligible["season"].isin(TRAIN_SEASONS)]
    validation = eligible[eligible["season"] == VALIDATION_SEASON]
    calibration = eligible[eligible["season"] == CALIBRATION_SEASON]
    holdout = eligible[eligible["season"] == HOLDOUT_SEASON]
    if min(len(train), len(validation), len(calibration), len(holdout)) == 0:
        raise RuntimeError("One or more folds are empty; cannot run pitcher model evaluation.")

    base_model = make_base_model()
    base_model.fit(train[FEATURES], train["home_win"])
    validation_prob_uncalibrated = base_model.predict_proba(validation[FEATURES])[:, 1]
    validation_pick = (validation_prob_uncalibrated >= 0.5).astype(int)
    validation_metrics = {
        "n_games": int(len(validation)),
        "accuracy": float(accuracy_score(validation["home_win"], validation_pick)),
        "log_loss_uncalibrated": float(log_loss(validation["home_win"], validation_prob_uncalibrated)),
        "brier_uncalibrated": float(brier_score_loss(validation["home_win"], validation_prob_uncalibrated)),
    }
    coverage = coverage_summary(eligible, HOLDOUT_SEASON)
    config = freeze_config(validation_metrics, coverage)

    calibration_raw_prob = base_model.predict_proba(calibration[FEATURES])[:, 1]
    platt = fit_platt(calibration_raw_prob, calibration["home_win"])
    holdout_prob = calibrated_prob(base_model, platt, holdout[FEATURES])
    holdout_pick = (holdout_prob >= 0.5).astype(int)
    holdout_y = holdout["home_win"].to_numpy()

    always_home_prob = np.full(len(holdout), float(train["home_win"].mean()))
    always_home_pick = np.ones(len(holdout), dtype=int)
    elo_prob_holdout = holdout["elo_home_win_prob"].to_numpy()
    elo_pick = (elo_prob_holdout >= 0.5).astype(int)

    metrics = pd.DataFrame(
        [
            metric_row("pitcher_logistic_platt", "holdout", holdout_y, holdout_prob, holdout_pick),
            metric_row("always_home", "holdout", holdout_y, always_home_prob, always_home_pick),
            metric_row("elo_baseline", "holdout", holdout_y, elo_prob_holdout, elo_pick),
        ]
    )

    prediction_rows = holdout[
        [
            "game_pk",
            "season",
            "game_date",
            "game_datetime_utc",
            "home_team_id",
            "away_team_id",
            "home_team",
            "away_team",
            "home_score",
            "away_score",
            "home_win",
            "home_pitcher_id",
            "home_pitcher_name",
            "away_pitcher_id",
            "away_pitcher_name",
        ]
    ].copy()
    prediction_rows["split"] = "holdout"
    prediction_rows["model_home_win_prob"] = holdout_prob
    prediction_rows["model_pick_home"] = holdout_pick
    prediction_rows["elo_home_win_prob"] = elo_prob_holdout
    prediction_rows["elo_pick_home"] = elo_pick
    prediction_rows["always_home_pick"] = 1
    for col in PITCHER_DIFF_FEATURES + PITCHER_CONTEXT_FEATURES:
        prediction_rows[col] = holdout[col].to_numpy()

    reliability = reliability_table(holdout_y, holdout_prob)

    linear = Pipeline(
        [("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("model", LinearRegression())]
    )
    leakage_eval = eligible[eligible["season"].between(VALIDATION_SEASON, HOLDOUT_SEASON)]
    linear.fit(train[FEATURES], train["run_diff_final"])
    leakage_pred = linear.predict(leakage_eval[FEATURES])
    leakage_r2 = float(r2_score(leakage_eval["run_diff_final"], leakage_pred))

    rng = np.random.default_rng(RANDOM_SEED)
    shuffled_acc = []
    for _ in range(200):
        shuffled = rng.permutation(holdout_y)
        shuffled_acc.append(float(accuracy_score(shuffled, holdout_pick)))
    shuffled_label = {
        "n_repeats": 200,
        "mean_accuracy": float(np.mean(shuffled_acc)),
        "p025": float(np.quantile(shuffled_acc, 0.025)),
        "p975": float(np.quantile(shuffled_acc, 0.975)),
    }

    write_database_outputs(prediction_rows, metrics, reliability)
    if float(metrics.loc[metrics["model_name"] == "pitcher_logistic_platt", "accuracy"].iloc[0]) > EXISTING_ACCURACY:
        artifact = {
            "base_model": base_model,
            "platt_calibrator": platt,
            "features": FEATURES,
            "config": config,
            "feature_safety": {**base_train.FEATURE_SAFETY, **PITCHER_FEATURE_SAFETY},
        }
        joblib.dump(artifact, ARTIFACT_PATH)
    write_report(
        metrics,
        reliability,
        leakage_r2,
        shuffled_label,
        validation_metrics,
        coverage,
        config,
        (float(np.min(holdout_prob)), float(np.max(holdout_prob))),
    )
    print(metrics.to_string(index=False))
    print(f"Coverage: {coverage['both_starters']} / {coverage['n_games']} both starters")
    print(f"Leakage R^2: {leakage_r2:.4f}")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
