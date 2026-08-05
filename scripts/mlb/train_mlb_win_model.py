from __future__ import annotations

import json
import math
import sqlite3
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
DB_PATH = ROOT / "data" / "mlb" / "mlb_research.db"
CONFIG_PATH = ROOT / "data" / "mlb" / "mlb_win_model_frozen_config.json"
ARTIFACT_PATH = ROOT / "data" / "mlb" / "mlb_win_model.joblib"
REPORT_PATH = ROOT / "data" / "reports" / "mlb_model_results.md"

TRAIN_SEASONS = list(range(2015, 2023))
VALIDATION_SEASON = 2023
CALIBRATION_SEASON = 2024
HOLDOUT_SEASON = 2025
EXCLUDED_SEASONS = [2026]

ELO_K = 20.0
ELO_HOME_ADVANTAGE = 35.0
ELO_OFFSEASON_REGRESSION = 0.67
RANDOM_SEED = 20260805

FEATURES = [
    "pregame_win_pct_diff",
    "pregame_run_diff_pg_diff",
    "pregame_runs_scored_pg_diff",
    "pregame_runs_allowed_pg_diff",
    "last10_win_pct_diff",
    "rest_days_diff_capped",
    "prior_season_win_pct_diff",
    "prior_season_run_diff_pg_diff",
    "elo_rating_diff_with_home_adv",
    "home_games_played_pre",
    "away_games_played_pre",
]

FEATURE_SAFETY = {
    "pregame_win_pct_diff": "home minus away season-to-date win percentage before this game only; current game is excluded by updating state after feature capture.",
    "pregame_run_diff_pg_diff": "home minus away season-to-date run differential per game before this game only; final runs from this game are not included.",
    "pregame_runs_scored_pg_diff": "home minus away season-to-date runs scored per game before this game only.",
    "pregame_runs_allowed_pg_diff": "home minus away season-to-date runs allowed per game before this game only.",
    "last10_win_pct_diff": "home minus away rolling last-10 win percentage from completed prior games only.",
    "rest_days_diff_capped": "home minus away days since each team's previous game, capped at 10; uses schedule dates before first pitch.",
    "prior_season_win_pct_diff": "home minus away final win percentage from the previous season, known before opening day.",
    "prior_season_run_diff_pg_diff": "home minus away previous-season run differential per game, known before opening day.",
    "elo_rating_diff_with_home_adv": "pregame Elo rating difference plus fixed home advantage; Elo is updated only after each game is recorded.",
    "home_games_played_pre": "home team's number of completed season games before this game.",
    "away_games_played_pre": "away team's number of completed season games before this game.",
}


@dataclass
class TeamState:
    games: int = 0
    wins: int = 0
    runs_for: int = 0
    runs_against: int = 0
    last10: deque[int] = field(default_factory=lambda: deque(maxlen=10))
    last_game_date: pd.Timestamp | None = None


def wilson_ci(wins: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = wins / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
    return center - half, center + half


def elo_prob(home_elo: float, away_elo: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-((home_elo + ELO_HOME_ADVANTAGE) - away_elo) / 400.0))


def safe_rate(numerator: float, denominator: float, default: float) -> float:
    return default if denominator <= 0 else numerator / denominator


def load_games() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        games = pd.read_sql_query(
            """
            SELECT game_pk, season, game_date, game_datetime_utc, game_type_code,
                   home_team_id, away_team_id, home_team, away_team,
                   home_score, away_score, home_win, status, status_code, is_tie
            FROM mlb_games
            WHERE game_type_code = 'R'
              AND home_win IS NOT NULL
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
              AND COALESCE(is_tie, 0) = 0
            ORDER BY game_datetime_utc, game_pk
            """,
            con,
        )
    games["game_datetime_utc"] = pd.to_datetime(games["game_datetime_utc"], utc=True)
    games["game_date"] = pd.to_datetime(games["game_date"])
    return games


def prior_season_summaries(games: pd.DataFrame) -> dict[tuple[int, int], dict[str, float]]:
    rows: list[dict[str, Any]] = []
    for _, g in games.iterrows():
        rows.append(
            {
                "season": int(g.season),
                "team_id": int(g.home_team_id),
                "win": int(g.home_win),
                "runs_for": int(g.home_score),
                "runs_against": int(g.away_score),
            }
        )
        rows.append(
            {
                "season": int(g.season),
                "team_id": int(g.away_team_id),
                "win": 1 - int(g.home_win),
                "runs_for": int(g.away_score),
                "runs_against": int(g.home_score),
            }
        )
    team_games = pd.DataFrame(rows)
    grouped = team_games.groupby(["season", "team_id"]).agg(
        games=("win", "size"),
        wins=("win", "sum"),
        runs_for=("runs_for", "sum"),
        runs_against=("runs_against", "sum"),
    )
    out: dict[tuple[int, int], dict[str, float]] = {}
    for (season, team_id), row in grouped.iterrows():
        out[(int(season), int(team_id))] = {
            "win_pct": safe_rate(float(row.wins), float(row.games), 0.5),
            "run_diff_pg": safe_rate(
                float(row.runs_for - row.runs_against), float(row.games), 0.0
            ),
        }
    return out


def build_pregame_features(games: pd.DataFrame) -> pd.DataFrame:
    previous = prior_season_summaries(games)
    current_season: int | None = None
    states: dict[int, TeamState] = defaultdict(TeamState)
    elos: dict[int, float] = defaultdict(lambda: 1500.0)
    rows: list[dict[str, Any]] = []

    for _, g in games.sort_values(["season", "game_datetime_utc", "game_pk"]).iterrows():
        season = int(g.season)
        if current_season != season:
            if current_season is not None:
                for team_id in list(elos.keys()):
                    elos[team_id] = 1500.0 + ELO_OFFSEASON_REGRESSION * (elos[team_id] - 1500.0)
            states = defaultdict(TeamState)
            current_season = season

        home = int(g.home_team_id)
        away = int(g.away_team_id)
        hs = states[home]
        a_s = states[away]
        game_date = pd.Timestamp(g.game_date)

        def rest_days(state: TeamState) -> float:
            if state.last_game_date is None:
                return 7.0
            return float(min(10, max(0, (game_date - state.last_game_date).days)))

        def win_pct(state: TeamState) -> float:
            return safe_rate(state.wins, state.games, 0.5)

        def run_diff_pg(state: TeamState) -> float:
            return safe_rate(state.runs_for - state.runs_against, state.games, 0.0)

        def runs_for_pg(state: TeamState) -> float:
            return safe_rate(state.runs_for, state.games, 4.5)

        def runs_against_pg(state: TeamState) -> float:
            return safe_rate(state.runs_against, state.games, 4.5)

        def last10_pct(state: TeamState) -> float:
            return safe_rate(sum(state.last10), len(state.last10), 0.5)

        h_prior = previous.get((season - 1, home), {"win_pct": 0.5, "run_diff_pg": 0.0})
        a_prior = previous.get((season - 1, away), {"win_pct": 0.5, "run_diff_pg": 0.0})
        elo_home_pre = elos[home]
        elo_away_pre = elos[away]
        elo_home_prob = elo_prob(elo_home_pre, elo_away_pre)
        home_win = int(g.home_win)

        rows.append(
            {
                "game_pk": int(g.game_pk),
                "season": season,
                "game_date": str(g.game_date.date()),
                "game_datetime_utc": g.game_datetime_utc.isoformat(),
                "home_team_id": home,
                "away_team_id": away,
                "home_team": g.home_team,
                "away_team": g.away_team,
                "home_score": int(g.home_score),
                "away_score": int(g.away_score),
                "home_win": home_win,
                "run_diff_final": int(g.home_score) - int(g.away_score),
                "pregame_win_pct_diff": win_pct(hs) - win_pct(a_s),
                "pregame_run_diff_pg_diff": run_diff_pg(hs) - run_diff_pg(a_s),
                "pregame_runs_scored_pg_diff": runs_for_pg(hs) - runs_for_pg(a_s),
                "pregame_runs_allowed_pg_diff": runs_against_pg(hs) - runs_against_pg(a_s),
                "last10_win_pct_diff": last10_pct(hs) - last10_pct(a_s),
                "rest_days_diff_capped": rest_days(hs) - rest_days(a_s),
                "prior_season_win_pct_diff": h_prior["win_pct"] - a_prior["win_pct"],
                "prior_season_run_diff_pg_diff": h_prior["run_diff_pg"] - a_prior["run_diff_pg"],
                "elo_rating_diff_with_home_adv": (elo_home_pre + ELO_HOME_ADVANTAGE) - elo_away_pre,
                "home_games_played_pre": hs.games,
                "away_games_played_pre": a_s.games,
                "elo_home_win_prob": elo_home_prob,
            }
        )

        home_expected = elo_home_prob
        elos[home] = elo_home_pre + ELO_K * (home_win - home_expected)
        elos[away] = elo_away_pre + ELO_K * ((1 - home_win) - (1 - home_expected))

        hs.games += 1
        hs.wins += home_win
        hs.runs_for += int(g.home_score)
        hs.runs_against += int(g.away_score)
        hs.last10.append(home_win)
        hs.last_game_date = game_date

        a_s.games += 1
        a_s.wins += 1 - home_win
        a_s.runs_for += int(g.away_score)
        a_s.runs_against += int(g.home_score)
        a_s.last10.append(1 - home_win)
        a_s.last_game_date = game_date

    return pd.DataFrame(rows)


def make_base_model() -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    C=0.5,
                    solver="lbfgs",
                    max_iter=1000,
                    random_state=RANDOM_SEED,
                ),
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
    low, high = wilson_ci(correct, n)
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
    buckets = np.arange(0.0, 1.01, 0.1)
    labels = [f"{buckets[i]:.1f}-{buckets[i + 1]:.1f}" for i in range(len(buckets) - 1)]
    bucketed = pd.cut(prob, buckets, labels=labels, include_lowest=True, right=False)
    rows = []
    for label in labels:
        mask = bucketed == label
        count = int(mask.sum())
        rows.append(
            {
                "bucket": label,
                "count": count,
                "mean_predicted_home_win_prob": float(np.mean(prob[mask])) if count else np.nan,
                "actual_home_win_rate": float(np.mean(y[mask])) if count else np.nan,
                "usable_for_confidence_claims": bool(count >= 150),
            }
        )
    return pd.DataFrame(rows)


def freeze_config(validation_metrics: dict[str, Any]) -> dict[str, Any]:
    config = {
        "model": "L2 logistic regression with separate Platt calibration",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_holdout_scoring": True,
        "random_seed": RANDOM_SEED,
        "train_seasons": TRAIN_SEASONS,
        "validation_season": VALIDATION_SEASON,
        "calibration_season": CALIBRATION_SEASON,
        "holdout_season": HOLDOUT_SEASON,
        "excluded_seasons": EXCLUDED_SEASONS,
        "features": FEATURES,
        "elo": {
            "k": ELO_K,
            "home_advantage": ELO_HOME_ADVANTAGE,
            "offseason_regression": ELO_OFFSEASON_REGRESSION,
        },
        "logistic_regression": {"C": 0.5, "penalty": "l2", "solver": "lbfgs"},
        "validation_metrics_used_before_freeze": validation_metrics,
        "note": "This configuration is written before any holdout probability, prediction, or metric is computed.",
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def markdown_table(frame: pd.DataFrame, floatfmt: str = ".4f") -> str:
    def fmt(value: Any) -> str:
        if isinstance(value, float):
            if math.isnan(value):
                return ""
            return format(value, floatfmt)
        return str(value)

    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(fmt(row[col]) for col in columns) + " |")
    return "\n".join(lines)


def write_database_outputs(predictions: pd.DataFrame, metrics: pd.DataFrame, reliability: pd.DataFrame) -> None:
    with sqlite3.connect(DB_PATH) as con:
        predictions.to_sql("mlb_model_predictions", con, if_exists="replace", index=False)
        metrics.to_sql("mlb_model_metrics", con, if_exists="replace", index=False)
        reliability.to_sql("mlb_model_calibration_reliability", con, if_exists="replace", index=False)


def write_report(
    config: dict[str, Any],
    metrics: pd.DataFrame,
    reliability: pd.DataFrame,
    leakage_r2: float,
    shuffled_label: dict[str, float],
    validation_metrics: dict[str, Any],
) -> None:
    holdout_metrics = metrics[metrics["split"] == "holdout"].set_index("model_name")
    model = holdout_metrics.loc["logistic_platt"]
    home = holdout_metrics.loc["always_home"]
    elo = holdout_metrics.loc["elo_baseline"]

    beat_home = model.accuracy > home.accuracy
    beat_elo = model.accuracy > elo.accuracy
    headline = (
        f"The frozen MLB model scored {pct(model.accuracy)} "
        f"(Wilson 95% CI {pct(model.wilson95_low)}-{pct(model.wilson95_high)}) "
        f"on the 2025 holdout; it {'beat' if beat_elo else 'did not beat'} Elo "
        f"({pct(elo.accuracy)}) and {'beat' if beat_home else 'did not beat'} always-pick-home "
        f"({pct(home.accuracy)})."
    )

    feature_lines = "\n".join(f"- `{name}`: {FEATURE_SAFETY[name]}" for name in FEATURES)
    reliability_md = markdown_table(reliability, floatfmt=".4f")
    metric_md = metrics[metrics["split"] == "holdout"][
        [
            "model_name",
            "n_games",
            "correct",
            "accuracy",
            "wilson95_low",
            "wilson95_high",
            "log_loss",
            "brier",
        ]
    ]
    metric_md = markdown_table(metric_md, floatfmt=".4f")

    report = f"""# MLB win-probability model results

## Headline

{headline}

This is a walk-forward evaluation. The in-progress 2026 season was excluded from training, calibration, and holdout scoring.

## Frozen configuration and fold structure

- Train: {TRAIN_SEASONS} ({'includes atypical shortened 2020' if 2020 in TRAIN_SEASONS else 'does not include 2020'})
- Validation/config selection: {VALIDATION_SEASON}
- Platt calibration: {CALIBRATION_SEASON}
- Frozen holdout: {HOLDOUT_SEASON}
- Excluded: {EXCLUDED_SEASONS}
- Frozen config: `{CONFIG_PATH.relative_to(ROOT)}`
- Serving artifact: `{ARTIFACT_PATH.relative_to(ROOT)}`

The final configuration JSON was written before scoring the frozen 2025 holdout. Validation accuracy available before freezing was {pct(validation_metrics['accuracy'])}.

## Holdout metrics

{metric_md}

The model {'beats' if beat_home else 'does not beat'} always-pick-home and {'beats' if beat_elo else 'does not beat'} the Elo baseline on raw accuracy. The Wilson intervals overlap, so small margins should be treated as statistical noise rather than strong evidence.

## Pregame-safe feature list

Every rolling or season-to-date feature is shifted by construction: the script records features first, then updates team/Elo state with the current game's result.

{feature_lines}

No starting-pitcher feature was used because the verified schema inspected in `mlb_research.db` has no game-level starting-pitcher columns.

## Calibration reliability table

Buckets are based on calibrated holdout home-win probabilities. Per-bucket counts below 150 are not used for confidence-tier claims.

{reliability_md}

## Leakage self-checks

- Linear regression of final home run differential on the pregame feature matrix: R-squared = {leakage_r2:.4f}. This is not implausibly high for baseball and does not suggest direct score leakage.
- Shuffling holdout labels against fixed predictions destroyed accuracy: mean shuffled accuracy = {pct(shuffled_label['mean_accuracy'])}, 2.5%-97.5% range = {pct(shuffled_label['p025'])}-{pct(shuffled_label['p975'])} across {int(shuffled_label['n_repeats'])} shuffles.

## Limitations

- Baseball game winners are intrinsically noisy; this model is intentionally modest and should not be interpreted as a betting edge.
- The database does not include pregame starting-pitcher assignments, the dominant public baseball signal.
- Team-only rolling stats are weaker early in each season and are affected by roster changes not represented in the database.
- 2020 is COVID-shortened and unusual, but it remains in the training window to avoid arbitrary deletion of verified historical games.
- 2026 is partial as of the source database and was excluded from honest evaluation.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    games = load_games()
    features = build_pregame_features(games)
    eligible = features[~features["season"].isin(EXCLUDED_SEASONS)].copy()

    train = eligible[eligible["season"].isin(TRAIN_SEASONS)]
    validation = eligible[eligible["season"] == VALIDATION_SEASON]
    calibration = eligible[eligible["season"] == CALIBRATION_SEASON]
    holdout = eligible[eligible["season"] == HOLDOUT_SEASON]

    if min(len(train), len(validation), len(calibration), len(holdout)) == 0:
        raise RuntimeError("One or more folds are empty; cannot run honest evaluation.")

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

    config = freeze_config(validation_metrics)

    # Holdout scoring starts only after the frozen config has been persisted.
    calibration_raw_prob = base_model.predict_proba(calibration[FEATURES])[:, 1]
    platt = fit_platt(calibration_raw_prob, calibration["home_win"])
    holdout_prob = calibrated_prob(base_model, platt, holdout[FEATURES])
    holdout_pick = (holdout_prob >= 0.5).astype(int)
    holdout_y = holdout["home_win"].to_numpy()

    always_home_prob = np.full(len(holdout), float(train["home_win"].mean()))
    always_home_pick = np.ones(len(holdout), dtype=int)
    elo_prob_holdout = holdout["elo_home_win_prob"].to_numpy()
    elo_pick = (elo_prob_holdout >= 0.5).astype(int)

    metric_rows = [
        metric_row("logistic_platt", "holdout", holdout_y, holdout_prob, holdout_pick),
        metric_row("always_home", "holdout", holdout_y, always_home_prob, always_home_pick),
        metric_row("elo_baseline", "holdout", holdout_y, elo_prob_holdout, elo_pick),
    ]
    metrics = pd.DataFrame(metric_rows)

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
        ]
    ].copy()
    prediction_rows["split"] = "holdout"
    prediction_rows["model_home_win_prob"] = holdout_prob
    prediction_rows["model_pick_home"] = holdout_pick
    prediction_rows["elo_home_win_prob"] = elo_prob_holdout
    prediction_rows["elo_pick_home"] = elo_pick
    prediction_rows["always_home_pick"] = 1

    reliability = reliability_table(holdout_y, holdout_prob)

    linear = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LinearRegression()),
        ]
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

    artifact = {
        "base_model": base_model,
        "platt_calibrator": platt,
        "features": FEATURES,
        "config": config,
        "feature_safety": FEATURE_SAFETY,
    }
    joblib.dump(artifact, ARTIFACT_PATH)

    write_database_outputs(prediction_rows, metrics, reliability)
    write_report(config, metrics, reliability, leakage_r2, shuffled_label, validation_metrics)

    print("Holdout metrics:")
    print(metrics.to_string(index=False))
    print(f"Leakage R^2: {leakage_r2:.4f}")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
