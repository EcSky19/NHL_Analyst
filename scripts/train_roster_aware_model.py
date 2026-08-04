import argparse
import csv
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np


MODEL_VERSION = "roster_aware_logreg_v2_interactions"
BASELINE_ACCURACY = 0.578811
EPS = 1e-9
INTERACTION_PRIOR_STRENGTH = 8.0


FEATURE_SPECS: List[Tuple[str, str]] = [
    ("delta_goalie_save_pct", "delta_pregame_goalie_save_pct_home_minus_away"),
    ("delta_skater_points_last5", "delta_pregame_skater_points_pg_last5_home_minus_away"),
    ("delta_skater_two_way_last5", "delta_pregame_skater_two_way_idx_last5_home_minus_away"),
    ("delta_roster_quality", "delta_pregame_roster_quality_idx_home_minus_away"),
    ("delta_injuries", "delta_pregame_injury_count_home_minus_away"),
    ("delta_roster_coverage_pct", "__derived__"),
    ("delta_roster_games_covered", "__derived__"),
    ("home_streak", "home_pregame_streak_signed"),
    ("away_streak", "away_pregame_streak_signed"),
    ("delta_last10_points_pct", "delta_pregame_last10_points_pct_home_minus_away"),
    ("delta_last10_goal_diff_pg", "delta_pregame_last10_goal_diff_pg_home_minus_away"),
    ("delta_season_points_pct", "delta_pregame_season_points_pct_home_minus_away"),
    ("delta_season_goal_diff_pg", "delta_pregame_season_goal_diff_pg_home_minus_away"),
    ("home_location_edge_points_pct", "home_location_edge_points_pct"),
    ("rest_days_delta", "rest_days_delta_home_minus_away"),
    ("home_back_to_back", "home_back_to_back"),
    ("away_back_to_back", "away_back_to_back"),
    ("delta_prev_season_points_pct", "__derived__"),
    ("delta_prev_season_goal_diff_pg", "__derived__"),
    ("min_prev_season_games", "__derived__"),
    ("roster_continuity_edge", "__derived__"),
    ("goalie_x_continuity", "__derived__"),
    ("quality_x_form", "__derived__"),
]

INTERACTION_FEATURE_NAMES = [
    "matchup_home_win_rate_prior",
    "matchup_home_games_prior_log",
    "team_vs_opponent_win_rate_prior",
    "team_vs_opponent_games_prior_log",
]


@dataclass
class GameRow:
    season: int
    game_id: int
    game_date: str
    home_team: str
    away_team: str
    y_home_win: int
    features: Dict[str, float]


@dataclass
class Transform:
    median: Dict[str, float]
    scale: Dict[str, float]
    feature_names: List[str]


def to_float(value: str | None, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def safe_prob(p: float) -> float:
    return max(1e-6, min(1.0 - 1e-6, p))


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def percentile(sorted_vals: Sequence[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * pct
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def median_iqr_scale(values: Sequence[float]) -> Tuple[float, float]:
    if not values:
        return 0.0, 1.0
    sorted_vals = sorted(values)
    med = percentile(sorted_vals, 0.5)
    q1 = percentile(sorted_vals, 0.25)
    q3 = percentile(sorted_vals, 0.75)
    iqr = q3 - q1
    scale = max(iqr / 1.349 if iqr > 0 else 0.0, 1e-6)
    return med, scale


def build_features(raw: Dict[str, str]) -> Dict[str, float]:
    home_cov = to_float(raw.get("home_pregame_roster_data_coverage_pct"))
    away_cov = to_float(raw.get("away_pregame_roster_data_coverage_pct"))
    home_cov_games = to_float(raw.get("home_pregame_roster_games_covered"))
    away_cov_games = to_float(raw.get("away_pregame_roster_games_covered"))
    home_roster_q = to_float(raw.get("home_pregame_roster_quality_idx"))
    away_roster_q = to_float(raw.get("away_pregame_roster_quality_idx"))
    delta_quality = to_float(raw.get("delta_pregame_roster_quality_idx_home_minus_away"))
    delta_goalie = to_float(raw.get("delta_pregame_goalie_save_pct_home_minus_away"))
    delta_last10_pts = to_float(raw.get("delta_pregame_last10_points_pct_home_minus_away"))
    delta_prev_points = to_float(raw.get("home_prior_prev_season_points_pct")) - to_float(
        raw.get("away_prior_prev_season_points_pct")
    )
    delta_prev_goal = to_float(raw.get("home_prior_prev_season_goal_diff_pg")) - to_float(
        raw.get("away_prior_prev_season_goal_diff_pg")
    )
    min_prev_games = min(
        to_float(raw.get("home_prior_prev_season_games")),
        to_float(raw.get("away_prior_prev_season_games")),
    )
    roster_continuity = (home_cov - away_cov) + 0.005 * (home_cov_games - away_cov_games)
    goalie_x_cont = delta_goalie * (1.0 + 0.35 * roster_continuity)
    quality_x_form = delta_quality * (1.0 + 0.5 * delta_last10_pts)
    features: Dict[str, float] = {}
    for output_name, source_col in FEATURE_SPECS:
        if source_col == "__derived__":
            continue
        features[output_name] = to_float(raw.get(source_col))
    features["delta_roster_coverage_pct"] = home_cov - away_cov
    features["delta_roster_games_covered"] = home_cov_games - away_cov_games
    features["delta_prev_season_points_pct"] = delta_prev_points
    features["delta_prev_season_goal_diff_pg"] = delta_prev_goal
    features["min_prev_season_games"] = min_prev_games
    features["roster_continuity_edge"] = roster_continuity
    features["goalie_x_continuity"] = goalie_x_cont
    features["quality_x_form"] = quality_x_form
    features["home_streak"] = to_float(raw.get("home_pregame_streak_signed"))
    features["away_streak"] = to_float(raw.get("away_pregame_streak_signed"))
    features["delta_roster_quality"] = home_roster_q - away_roster_q
    return features


def read_games_from_csv(input_csv: Path) -> List[GameRow]:
    rows: List[GameRow] = []
    with input_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            season = int(raw["season"])
            row = GameRow(
                season=season,
                game_id=int(raw["game_id"]),
                game_date=str(raw["game_date"]),
                home_team=str(raw["home_team_abbrev"]).upper(),
                away_team=str(raw["away_team_abbrev"]).upper(),
                y_home_win=int(float(raw["home_win"])),
                features=build_features(raw),
            )
            rows.append(row)
    rows.sort(key=lambda r: (r.game_date, r.game_id))
    return rows


def read_games_from_sqlite(sqlite_db: Path, table_name: str) -> List[GameRow]:
    with sqlite3.connect(sqlite_db) as con:
        cur = con.execute(f'SELECT * FROM "{table_name}" ORDER BY game_date ASC, game_id ASC')
        columns = [d[0] for d in cur.description]
        rows_raw = [dict(zip(columns, row)) for row in cur.fetchall()]
    rows: List[GameRow] = []
    for raw_obj in rows_raw:
        raw = {k: "" if v is None else str(v) for k, v in raw_obj.items()}
        rows.append(
            GameRow(
                season=int(raw["season"]),
                game_id=int(raw["game_id"]),
                game_date=str(raw["game_date"]),
                home_team=str(raw["home_team_abbrev"]).upper(),
                away_team=str(raw["away_team_abbrev"]).upper(),
                y_home_win=int(float(raw["home_win"])),
                features=build_features(raw),
            )
        )
    return rows


def build_transform(train_rows: Sequence[GameRow], feature_names: Sequence[str]) -> Transform:
    med: Dict[str, float] = {}
    scale: Dict[str, float] = {}
    for name in feature_names:
        vals = [r.features[name] for r in train_rows]
        m, s = median_iqr_scale(vals)
        med[name] = m
        scale[name] = s
    return Transform(median=med, scale=scale, feature_names=list(feature_names))


def vectorize(rows: Sequence[GameRow], transform: Transform) -> Tuple[np.ndarray, np.ndarray]:
    x_data: List[List[float]] = []
    y_data: List[int] = []
    for row in rows:
        vec: List[float] = []
        for name in transform.feature_names:
            centered = row.features[name] - transform.median[name]
            scaled = centered / transform.scale[name]
            if scaled > 6.0:
                scaled = 6.0
            elif scaled < -6.0:
                scaled = -6.0
            vec.append(scaled)
        x_data.append(vec)
        y_data.append(row.y_home_win)
    return np.array(x_data, dtype=np.float64), np.array(y_data, dtype=np.float64)


def fit_logreg(
    x_data: np.ndarray,
    y_data: np.ndarray,
    learning_rate: float,
    l2: float,
    epochs: int,
) -> Tuple[np.ndarray, float]:
    n = int(x_data.shape[0])
    d = int(x_data.shape[1]) if n else 0
    w = np.zeros(d, dtype=np.float64)
    b = 0.0
    for _ in range(epochs):
        logits = x_data @ w + b
        logits = np.clip(logits, -35.0, 35.0)
        probs = 1.0 / (1.0 + np.exp(-logits))
        err = probs - y_data
        grad_w = (x_data.T @ err) / max(n, 1) + l2 * w
        grad_b = float(np.mean(err))
        w -= learning_rate * grad_w
        b -= learning_rate * grad_b
    return w, b


def predict_proba(x_data: np.ndarray, w: np.ndarray, b: float) -> List[float]:
    logits = x_data @ w + b
    logits = np.clip(logits, -35.0, 35.0)
    probs = 1.0 / (1.0 + np.exp(-logits))
    return [float(p) for p in probs]


def metrics(y_true: Sequence[int], p_home: Sequence[float]) -> Dict[str, float]:
    n = len(y_true)
    if n == 0:
        return {"games": 0.0, "accuracy": 0.0, "log_loss": 0.0, "brier_score": 0.0}
    correct = 0
    ll = 0.0
    brier = 0.0
    for y, p in zip(y_true, p_home):
        p_safe = safe_prob(p)
        pick = 1 if p >= 0.5 else 0
        if pick == y:
            correct += 1
        ll += -(y * math.log(p_safe) + (1 - y) * math.log(1.0 - p_safe))
        brier += (p - y) ** 2
    return {
        "games": float(n),
        "accuracy": correct / n,
        "log_loss": ll / n,
        "brier_score": brier / n,
    }


def split_by_season(rows: Sequence[GameRow]) -> Dict[int, List[GameRow]]:
    grouped: Dict[int, List[GameRow]] = {}
    for r in rows:
        grouped.setdefault(r.season, []).append(r)
    return grouped


def smoothed_rate(wins: float, games: int, prior: float, prior_strength: float = INTERACTION_PRIOR_STRENGTH) -> float:
    return (wins + prior_strength * prior) / max(games + prior_strength, 1e-9)


def attach_interaction_features(rows: Sequence[GameRow]) -> None:
    grouped = split_by_season(rows)
    seasons = sorted(grouped.keys())
    ordered_matchup_wins: Dict[Tuple[str, str], float] = {}
    ordered_matchup_games: Dict[Tuple[str, str], int] = {}
    focal_matchup_wins: Dict[Tuple[str, str], float] = {}
    focal_matchup_games: Dict[Tuple[str, str], int] = {}
    cumulative_games = 0
    cumulative_home_wins = 0.0

    for season in seasons:
        season_rows = grouped[season]
        global_home_prior = (cumulative_home_wins / cumulative_games) if cumulative_games > 0 else 0.5
        for row in season_rows:
            ordered_key = (row.home_team, row.away_team)
            ordered_games = ordered_matchup_games.get(ordered_key, 0)
            ordered_wins = ordered_matchup_wins.get(ordered_key, 0.0)
            row.features["matchup_home_win_rate_prior"] = (
                smoothed_rate(ordered_wins, ordered_games, global_home_prior) - 0.5
            )
            row.features["matchup_home_games_prior_log"] = math.log1p(ordered_games)

            focal_key = (row.home_team, row.away_team)
            focal_games = focal_matchup_games.get(focal_key, 0)
            focal_wins = focal_matchup_wins.get(focal_key, 0.0)
            row.features["team_vs_opponent_win_rate_prior"] = smoothed_rate(focal_wins, focal_games, 0.5) - 0.5
            row.features["team_vs_opponent_games_prior_log"] = math.log1p(focal_games)

        for row in season_rows:
            home_win = float(row.y_home_win)
            ordered_key = (row.home_team, row.away_team)
            ordered_matchup_games[ordered_key] = ordered_matchup_games.get(ordered_key, 0) + 1
            ordered_matchup_wins[ordered_key] = ordered_matchup_wins.get(ordered_key, 0.0) + home_win

            home_focal_key = (row.home_team, row.away_team)
            away_focal_key = (row.away_team, row.home_team)
            focal_matchup_games[home_focal_key] = focal_matchup_games.get(home_focal_key, 0) + 1
            focal_matchup_wins[home_focal_key] = focal_matchup_wins.get(home_focal_key, 0.0) + home_win
            focal_matchup_games[away_focal_key] = focal_matchup_games.get(away_focal_key, 0) + 1
            focal_matchup_wins[away_focal_key] = focal_matchup_wins.get(away_focal_key, 0.0) + (1.0 - home_win)

            cumulative_games += 1
            cumulative_home_wins += home_win


def tuning_grid() -> List[Dict[str, float]]:
    configs: List[Dict[str, float]] = []
    for lr in (0.02, 0.03, 0.05):
        for l2 in (0.01, 0.03, 0.08, 0.15, 0.30):
            for epochs in (250.0, 400.0):
                configs.append({"lr": lr, "l2": l2, "epochs": epochs})
    return configs


def walk_forward_tuning(rows: Sequence[GameRow], feature_names: Sequence[str]) -> Dict[str, float]:
    grouped = split_by_season(rows)
    seasons = sorted(grouped.keys())
    if len(seasons) < 4:
        raise ValueError("Need at least 4 seasons for robust walk-forward tuning.")
    folds = []
    for idx in range(2, len(seasons)):
        train_seasons = seasons[:idx]
        val_season = seasons[idx]
        train_rows = [r for s in train_seasons for r in grouped[s]]
        val_rows = list(grouped[val_season])
        folds.append((train_rows, val_rows))
    best = None
    for cfg in tuning_grid():
        fold_metrics = []
        for train_rows, val_rows in folds:
            transform = build_transform(train_rows, feature_names)
            x_train, y_train = vectorize(train_rows, transform)
            x_val, y_val = vectorize(val_rows, transform)
            w, b = fit_logreg(
                x_train,
                y_train,
                learning_rate=float(cfg["lr"]),
                l2=float(cfg["l2"]),
                epochs=int(cfg["epochs"]),
            )
            p_val = predict_proba(x_val, w, b)
            fold_metrics.append(metrics(y_val, p_val))
        mean_acc = sum(m["accuracy"] for m in fold_metrics) / len(fold_metrics)
        mean_ll = sum(m["log_loss"] for m in fold_metrics) / len(fold_metrics)
        mean_brier = sum(m["brier_score"] for m in fold_metrics) / len(fold_metrics)
        candidate = {
            **cfg,
            "cv_accuracy": mean_acc,
            "cv_log_loss": mean_ll,
            "cv_brier_score": mean_brier,
        }
        if best is None:
            best = candidate
            continue
        if candidate["cv_log_loss"] < best["cv_log_loss"] - 1e-12:
            best = candidate
        elif abs(candidate["cv_log_loss"] - best["cv_log_loss"]) <= 1e-12 and candidate["cv_accuracy"] > best["cv_accuracy"]:
            best = candidate
    if best is None:
        raise ValueError("Failed to tune model.")
    return best


def walk_forward_backtest(
    rows: Sequence[GameRow], feature_names: Sequence[str], best_cfg: Dict[str, float]
) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, float]], Dict[str, float]]:
    grouped = split_by_season(rows)
    seasons = sorted(grouped.keys())
    all_predictions: List[Dict[str, object]] = []
    weight_abs_sum = {name: 0.0 for name in feature_names}
    fold_count = 0
    by_season_metrics: Dict[str, Dict[str, float]] = {}
    for idx in range(1, len(seasons)):
        train_seasons = seasons[:idx]
        test_season = seasons[idx]
        train_rows = [r for s in train_seasons for r in grouped[s]]
        test_rows = list(grouped[test_season])
        transform = build_transform(train_rows, feature_names)
        x_train, y_train = vectorize(train_rows, transform)
        x_test, y_test = vectorize(test_rows, transform)
        w, b = fit_logreg(
            x_train,
            y_train,
            learning_rate=float(best_cfg["lr"]),
            l2=float(best_cfg["l2"]),
            epochs=int(best_cfg["epochs"]),
        )
        fold_count += 1
        for i, name in enumerate(feature_names):
            weight_abs_sum[name] += abs(w[i])
        p_test = predict_proba(x_test, w, b)
        s_metrics = metrics(y_test, p_test)
        by_season_metrics[str(test_season)] = s_metrics
        for row, p in zip(test_rows, p_test):
            pred_winner = row.home_team if p >= 0.5 else row.away_team
            all_predictions.append(
                {
                    "season": row.season,
                    "game_id": row.game_id,
                    "game_date": row.game_date,
                    "home_team_abbrev": row.home_team,
                    "away_team_abbrev": row.away_team,
                    "home_win_probability": round(p, 6),
                    "away_win_probability": round(1.0 - p, 6),
                    "predicted_winner_abbrev": pred_winner,
                    "actual_home_win": row.y_home_win,
                    "actual_winner_abbrev": row.home_team if row.y_home_win == 1 else row.away_team,
                    "is_correct_pick": 1 if (1 if p >= 0.5 else 0) == row.y_home_win else 0,
                }
            )
    overall_metrics = metrics(
        [int(r["actual_home_win"]) for r in all_predictions],
        [float(r["home_win_probability"]) for r in all_predictions],
    )
    mean_abs_weights = {k: (v / max(fold_count, 1)) for k, v in weight_abs_sum.items()}
    return all_predictions, by_season_metrics, {"folds": float(fold_count), **overall_metrics, **mean_abs_weights}


def train_final_model(
    rows: Sequence[GameRow], feature_names: Sequence[str], best_cfg: Dict[str, float]
) -> Tuple[Transform, List[float], float]:
    transform = build_transform(rows, feature_names)
    x_data, y_data = vectorize(rows, transform)
    w, b = fit_logreg(
        x_data,
        y_data,
        learning_rate=float(best_cfg["lr"]),
        l2=float(best_cfg["l2"]),
        epochs=int(best_cfg["epochs"]),
    )
    return transform, w, b


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_report(
    path: Path,
    tuned_cfg: Dict[str, float],
    overall: Dict[str, float],
    by_season: Dict[str, Dict[str, float]],
    feature_importance_rows: List[Dict[str, object]],
    baseline_accuracy: float,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    improvement = overall["accuracy"] - baseline_accuracy
    lines = [
        "# Roster-aware Pregame Model Training Summary",
        "",
        f"- Model version: `{MODEL_VERSION}`",
        "- Model type: deterministic logistic regression with robust-scaled features.",
        "- Tuning/training protocol: leakage-safe walk-forward by season (train on prior seasons only).",
        "",
        "## Selected hyperparameters",
        f"- learning_rate: {tuned_cfg['lr']}",
        f"- l2: {tuned_cfg['l2']}",
        f"- epochs: {int(tuned_cfg['epochs'])}",
        f"- CV accuracy: {tuned_cfg['cv_accuracy']:.4f}",
        f"- CV log loss: {tuned_cfg['cv_log_loss']:.4f}",
        "",
        "## Walk-forward backtest metrics (out-of-sample seasons)",
        f"- Games evaluated: {int(overall['games'])}",
        f"- Accuracy: {overall['accuracy']:.4f}",
        f"- Log loss: {overall['log_loss']:.4f}",
        f"- Brier score: {overall['brier_score']:.4f}",
        f"- Baseline accuracy: {baseline_accuracy:.4f}",
        f"- Accuracy delta vs baseline: {improvement:+.4f}",
        "",
        "## Per-season metrics",
        "| Season | Games | Accuracy | Log loss | Brier score |",
        "|---|---:|---:|---:|---:|",
    ]
    for season in sorted(by_season.keys()):
        m = by_season[season]
        lines.append(
            f"| {season} | {int(m['games'])} | {m['accuracy']:.4f} | {m['log_loss']:.4f} | {m['brier_score']:.4f} |"
        )
    lines.extend(["", "## Top feature signals (mean abs fold weight)", "| Feature | Mean abs weight |", "|---|---:|"])
    for row in feature_importance_rows[:12]:
        lines.append(f"| {row['feature']} | {float(row['mean_abs_weight']):.6f} |")
    lines.extend(
        [
            "",
            "## Feature coverage highlights",
            "- Goalie signal: `delta_goalie_save_pct`, `goalie_x_continuity`.",
            "- Skater production/two-way: `delta_skater_points_last5`, `delta_skater_two_way_last5`, `quality_x_form`.",
            "- Roster quality/continuity: `delta_roster_quality`, `delta_roster_coverage_pct`, `delta_roster_games_covered`, `roster_continuity_edge`.",
            "- Streak/location/team-strength priors: streak features, `home_location_edge_points_pct`, rest/B2B, prior-season deltas.",
            "- Team-opponent interactions (regularized): `matchup_home_win_rate_prior`, `matchup_home_games_prior_log`, `team_vs_opponent_win_rate_prior`, `team_vs_opponent_games_prior_log`.",
            "",
            "## Artifacts",
            "- `data\\processed\\roster_aware_model_config.json`",
            "- `data\\processed\\roster_aware_feature_importance.csv`",
            "- `data\\processed\\roster_aware_walk_forward_predictions.csv`",
            "- `data\\reports\\roster_aware_model_training_summary.md`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train deterministic roster-aware pregame model with leakage-safe walk-forward evaluation.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--input-csv", default=None, help="Defaults to data\\processed\\backtest_features_last5_roster.csv")
    parser.add_argument("--sqlite-db", default=None, help="Optional SQLite source db. Defaults to data\\processed\\nhl_research.db")
    parser.add_argument("--input-table", default="backtest_features_last5_roster")
    parser.add_argument("--output-config", default=None, help="Defaults to data\\processed\\roster_aware_model_config.json")
    parser.add_argument("--output-feature-importance", default=None, help="Defaults to data\\processed\\roster_aware_feature_importance.csv")
    parser.add_argument("--output-predictions", default=None, help="Defaults to data\\processed\\roster_aware_walk_forward_predictions.csv")
    parser.add_argument("--output-report", default=None, help="Defaults to data\\reports\\roster_aware_model_training_summary.md")
    parser.add_argument("--baseline-accuracy", type=float, default=BASELINE_ACCURACY)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    input_csv = (
        Path(args.input_csv).resolve()
        if args.input_csv
        else repo_root / "data" / "processed" / "backtest_features_last5_roster.csv"
    )
    sqlite_db = Path(args.sqlite_db).resolve() if args.sqlite_db else repo_root / "data" / "processed" / "nhl_research.db"
    output_config = (
        Path(args.output_config).resolve()
        if args.output_config
        else repo_root / "data" / "processed" / "roster_aware_model_config.json"
    )
    output_importance = (
        Path(args.output_feature_importance).resolve()
        if args.output_feature_importance
        else repo_root / "data" / "processed" / "roster_aware_feature_importance.csv"
    )
    output_predictions = (
        Path(args.output_predictions).resolve()
        if args.output_predictions
        else repo_root / "data" / "processed" / "roster_aware_walk_forward_predictions.csv"
    )
    output_report = (
        Path(args.output_report).resolve()
        if args.output_report
        else repo_root / "data" / "reports" / "roster_aware_model_training_summary.md"
    )

    if input_csv.exists():
        games = read_games_from_csv(input_csv)
        data_source = f"csv:{input_csv}"
    else:
        games = read_games_from_sqlite(sqlite_db, args.input_table)
        data_source = f"sqlite:{sqlite_db}::{args.input_table}"
    if not games:
        raise SystemExit("No rows available for training.")

    attach_interaction_features(games)
    feature_names = [name for name, _ in FEATURE_SPECS] + INTERACTION_FEATURE_NAMES
    best_cfg = walk_forward_tuning(games, feature_names)
    predictions, by_season, rollup = walk_forward_backtest(games, feature_names, best_cfg)

    transform, final_w, final_b = train_final_model(games, feature_names, best_cfg)
    importance_rows = [
        {"feature": name, "mean_abs_weight": round(float(rollup.get(name, 0.0)), 8)}
        for name in feature_names
    ]
    importance_rows.sort(key=lambda r: float(r["mean_abs_weight"]), reverse=True)
    write_csv(output_importance, importance_rows)
    write_csv(output_predictions, predictions)

    config_payload = {
        "model_version": MODEL_VERSION,
        "data_source": data_source,
        "deterministic": True,
        "feature_names": feature_names,
        "hyperparameters": {
            "learning_rate": best_cfg["lr"],
            "l2": best_cfg["l2"],
            "epochs": int(best_cfg["epochs"]),
        },
        "cv_metrics": {
            "accuracy": best_cfg["cv_accuracy"],
            "log_loss": best_cfg["cv_log_loss"],
            "brier_score": best_cfg["cv_brier_score"],
        },
        "final_model": {
            "intercept": final_b,
            "weights": {name: final_w[i] for i, name in enumerate(feature_names)},
            "robust_center": transform.median,
            "robust_scale": transform.scale,
        },
        "walk_forward_backtest": {
            "games": int(rollup["games"]),
            "accuracy": rollup["accuracy"],
            "log_loss": rollup["log_loss"],
            "brier_score": rollup["brier_score"],
            "baseline_accuracy": args.baseline_accuracy,
            "accuracy_delta_vs_baseline": rollup["accuracy"] - args.baseline_accuracy,
        },
    }
    write_json(output_config, config_payload)

    overall = {
        "games": rollup["games"],
        "accuracy": rollup["accuracy"],
        "log_loss": rollup["log_loss"],
        "brier_score": rollup["brier_score"],
    }
    write_report(output_report, best_cfg, overall, by_season, importance_rows, args.baseline_accuracy)

    print(f"model_version={MODEL_VERSION}")
    print(f"data_source={data_source}")
    print(f"games_total={len(games)}")
    print(f"walk_forward_games={int(rollup['games'])}")
    print(f"walk_forward_accuracy={rollup['accuracy']:.6f}")
    print(f"walk_forward_log_loss={rollup['log_loss']:.6f}")
    print(f"walk_forward_brier_score={rollup['brier_score']:.6f}")
    print(f"baseline_accuracy={args.baseline_accuracy:.6f}")
    print(f"accuracy_delta_vs_baseline={rollup['accuracy'] - args.baseline_accuracy:+.6f}")
    print(f"config={output_config}")
    print(f"feature_importance={output_importance}")
    print(f"predictions={output_predictions}")
    print(f"report={output_report}")


if __name__ == "__main__":
    main()
