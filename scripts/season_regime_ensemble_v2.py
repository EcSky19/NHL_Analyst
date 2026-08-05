import argparse
import csv
import json
import math
from collections import OrderedDict, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np


EPS = 1e-6
SPLIT_STEP = 0.10
PHASE1_WINNER_ACCURACY = 0.616616

BASE_MODELS = [
    "elo_form_tuned",
    "logistic_engineered",
    "weighted_calibrated_isotonic",
    "blend_logistic_weighted_70_30",
]

REGIMES = ("early", "mid", "late")


def clamp_probability(value: float) -> float:
    return max(EPS, min(1.0 - EPS, float(value)))


def season_label(season_id: str) -> str:
    raw = str(int(season_id))
    if len(raw) == 8:
        return f"{raw[:4]}-{raw[4:]}"
    return raw


def regime_for_index(index: int, total: int) -> str:
    fraction = (index + 1) / max(total, 1)
    if fraction <= 1 / 3:
        return "early"
    if fraction <= 2 / 3:
        return "mid"
    return "late"


def read_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def metrics(rows: Sequence[Dict[str, object]], prob_key: str) -> Dict[str, float]:
    if not rows:
        return {"games": 0.0, "accuracy": 0.0, "log_loss": 0.0, "brier_score": 0.0}

    correct = 0
    log_loss = 0.0
    brier = 0.0
    for row in rows:
        y = int(row["actual_home_win"])
        p = clamp_probability(float(row[prob_key]))
        correct += (p >= 0.5) == bool(y)
        log_loss += -(y * math.log(p) + (1 - y) * math.log(1.0 - p))
        brier += (p - y) ** 2
    n = len(rows)
    return {
        "games": float(n),
        "accuracy": correct / n,
        "log_loss": log_loss / n,
        "brier_score": brier / n,
    }


def weight_grid(step: float) -> List[Dict[str, float]]:
    values = [round(i * step, 10) for i in range(int(round(1.0 / step)) + 1)]
    candidates: List[Dict[str, float]] = []
    # Simplex grid for 4 models.
    for a in values:
        for b in values:
            for c in values:
                d = round(1.0 - a - b - c, 10)
                if d < -EPS:
                    continue
                if abs(round(d / step) * step - d) > 1e-9:
                    continue
                candidates.append(
                    {
                        BASE_MODELS[0]: a,
                        BASE_MODELS[1]: b,
                        BASE_MODELS[2]: c,
                        BASE_MODELS[3]: d,
                    }
                )
    return candidates


def build_indexes(rows: Sequence[Dict[str, str]]) -> Tuple[
    OrderedDict[str, List[Dict[str, str]]],
    Dict[Tuple[str, str], Dict[str, str]],
    Dict[Tuple[str, str], Dict[str, float]],
]:
    games_by_season: OrderedDict[str, List[Dict[str, str]]] = OrderedDict()
    meta: Dict[Tuple[str, str], Dict[str, str]] = {}
    probs: Dict[Tuple[str, str], Dict[str, float]] = {}

    seasons = sorted({row["season"] for row in rows})
    for row in rows:
        key = (row["season"], row["game_id"])
        meta.setdefault(key, row)
        probs.setdefault(key, {})[row["model_id"]] = float(row["home_win_probability"])

    for season in seasons:
        games = [row for (row_season, _), row in meta.items() if row_season == season]
        games.sort(key=lambda row: (row["game_date"], row["game_id"]))
        games_by_season[season] = games

    return games_by_season, meta, probs


def select_weights(
    train_rows: Sequence[Dict[str, str]],
    probs: Dict[Tuple[str, str], Dict[str, float]],
    candidate_weights: Sequence[Dict[str, float]],
) -> Tuple[Dict[str, float], Dict[str, float]]:
    if not train_rows:
        weights = {
            BASE_MODELS[0]: 0.40,
            BASE_MODELS[1]: 0.20,
            BASE_MODELS[2]: 0.10,
            BASE_MODELS[3]: 0.30,
        }
        return weights, metrics([], "_unused")

    best_score = None
    best_weights = None
    best_metrics = None

    x_train = np.array(
        [[probs[(row["season"], row["game_id"])][model_id] for model_id in BASE_MODELS] for row in train_rows],
        dtype=float,
    )
    y_train = np.array([int(row["actual_home_win"]) for row in train_rows], dtype=float)
    weight_matrix = np.array([[weights[model_id] for model_id in BASE_MODELS] for weights in candidate_weights], dtype=float)
    probs_matrix = np.clip(x_train @ weight_matrix.T, EPS, 1.0 - EPS)
    preds_matrix = probs_matrix >= 0.5
    accuracy_vector = (preds_matrix == y_train[:, None]).mean(axis=0)
    log_loss_vector = -(y_train[:, None] * np.log(probs_matrix) + (1.0 - y_train[:, None]) * np.log(1.0 - probs_matrix)).mean(axis=0)
    brier_vector = ((probs_matrix - y_train[:, None]) ** 2).mean(axis=0)

    for idx, weights in enumerate(candidate_weights):
        c_metrics = {
            "games": float(len(train_rows)),
            "accuracy": float(accuracy_vector[idx]),
            "log_loss": float(log_loss_vector[idx]),
            "brier_score": float(brier_vector[idx]),
        }
        score = (c_metrics["accuracy"], -c_metrics["log_loss"], -c_metrics["brier_score"])
        if best_score is None or score > best_score:
            best_score = score
            best_weights = weights
            best_metrics = c_metrics

    assert best_weights is not None and best_metrics is not None
    return best_weights, best_metrics


def build_training_rows(
    season_index: int,
    regime: str,
    games_by_season: OrderedDict[str, List[Dict[str, str]]],
    current_season: str,
) -> List[Dict[str, str]]:
    allowed_by_regime = {
        "early": {"early"},
        "mid": {"early", "mid"},
        "late": {"early", "mid", "late"},
    }

    train_rows: List[Dict[str, str]] = []
    seasons = list(games_by_season.keys())

    for prior_season in seasons[:season_index]:
        season_games = games_by_season[prior_season]
        for idx, row in enumerate(season_games):
            if regime_for_index(idx, len(season_games)) in allowed_by_regime[regime]:
                train_rows.append(row)

    current_games = games_by_season[current_season]
    for idx, row in enumerate(current_games):
        current_regime = regime_for_index(idx, len(current_games))
        if regime == "mid" and current_regime == "early":
            train_rows.append(row)
        elif regime == "late" and current_regime in {"early", "mid"}:
            train_rows.append(row)

    return train_rows


def summarize_by_regime(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["regime"])].append(row)

    summary: List[Dict[str, object]] = []
    for regime in REGIMES:
        subset = grouped.get(regime, [])
        m = metrics(subset, "predicted_probability")
        summary.append(
            {
                "regime": regime,
                "games": int(m["games"]),
                "accuracy": round(m["accuracy"], 6),
                "log_loss": round(m["log_loss"], 6),
                "brier_score": round(m["brier_score"], 6),
            }
        )
    return summary


def write_report(
    report_path: Path,
    overall: Dict[str, object],
    best_season_regime: Dict[str, object],
    season_rows: Sequence[Dict[str, object]],
    regime_rows: Sequence[Dict[str, object]],
    benchmark_accuracy: float,
    artifacts: Dict[str, str],
) -> None:
    lines = [
        "# Season Regime Ensemble v2",
        "",
        "## Result",
        f"- Best accuracy: {float(best_season_regime['accuracy']):.6f}",
        f"- Overall accuracy: {float(overall['accuracy']):.6f}",
        f"- Phase 1 winner benchmark: {benchmark_accuracy:.6f}",
        f"- Drift help: {'Yes' if float(best_season_regime['accuracy']) > float(regime_rows[0]['accuracy']) else 'Partial'}",
        "",
        "## Notes",
        "- Early/mid/late regimes are defined by within-season terciles.",
        "- Weights are selected fold-safely from prior seasons plus only earlier games in the same season.",
        "- Candidate pool: `elo_form_tuned`, `logistic_engineered`, `weighted_calibrated_isotonic`, `blend_logistic_weighted_70_30`.",
        "",
        "## Season metrics",
        "| Season | Games | Accuracy | Log loss | Brier |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in season_rows:
        lines.append(
            f"| {row['season_label']} | {row['games']} | {float(row['accuracy']):.6f} | {float(row['log_loss']):.6f} | {float(row['brier_score']):.6f} |"
        )

    lines.extend(
        [
            "",
            "## Regime metrics",
            "| Regime | Games | Accuracy | Log loss | Brier |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in regime_rows:
        lines.append(
            f"| {row['regime']} | {row['games']} | {float(row['accuracy']):.6f} | {float(row['log_loss']):.6f} | {float(row['brier_score']):.6f} |"
        )

    lines.extend(
        [
            "",
            "## Artifacts",
        ]
    )
    for key in sorted(artifacts):
        lines.append(f"- `{artifacts[key]}`")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a season-regime-specific ensemble.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()

    source_csv = repo_root / "data" / "processed" / "execution_plan" / "phase1_eval_final" / "predictions.csv"
    output_dir = repo_root / "data" / "processed" / "execution_plan" / "season_regime_ensemble_v2"
    report_path = repo_root / "data" / "reports" / "season_regime_ensemble_v2_results.md"

    rows = read_rows(source_csv)
    games_by_season, meta, probs = build_indexes(rows)
    candidate_weights = weight_grid(SPLIT_STEP)

    output_rows: List[Dict[str, object]] = []
    regime_weight_rows: List[Dict[str, object]] = []
    selected_weights: Dict[Tuple[str, str], Dict[str, float]] = {}
    selected_train_metrics: Dict[Tuple[str, str], Dict[str, float]] = {}

    seasons = list(games_by_season.keys())
    for season_index, season in enumerate(seasons):
        for regime in REGIMES:
            train_rows = build_training_rows(season_index, regime, games_by_season, season)
            weights, train_metrics = select_weights(train_rows, probs, candidate_weights)
            selected_weights[(season, regime)] = weights
            selected_train_metrics[(season, regime)] = train_metrics
            regime_weight_rows.append(
                {
                    "season": season,
                    "season_label": season_label(season),
                    "regime": regime,
                    "games_used_for_training": len(train_rows),
                    "train_accuracy": round(float(train_metrics["accuracy"]), 6),
                    "train_log_loss": round(float(train_metrics["log_loss"]), 6),
                    "train_brier_score": round(float(train_metrics["brier_score"]), 6),
                    **{f"weight_{model_id}": round(float(weights[model_id]), 6) for model_id in BASE_MODELS},
                }
            )

        season_games = games_by_season[season]
        for idx, row in enumerate(season_games):
            regime = regime_for_index(idx, len(season_games))
            weights = selected_weights[(season, regime)]
            key = (row["season"], row["game_id"])
            p = 0.0
            for model_id, weight in weights.items():
                p += weight * probs[key][model_id]
            p = clamp_probability(p)

            output_rows.append(
                {
                    "season": row["season"],
                    "season_label": season_label(row["season"]),
                    "game_id": row["game_id"],
                    "game_date": row["game_date"],
                    "actual_home_win": int(row["actual_home_win"]),
                    "regime": regime,
                    "predicted_probability": round(p, 6),
                    "predicted_winner": 1 if p >= 0.5 else 0,
                    "selected_weights_json": json.dumps(weights, sort_keys=True),
                }
            )

    overall_metrics = metrics(output_rows, "predicted_probability")
    season_metrics: List[Dict[str, object]] = []
    for season in seasons:
        subset = [row for row in output_rows if row["season"] == season]
        m = metrics(subset, "predicted_probability")
        season_metrics.append(
            {
                "season": season,
                "season_label": season_label(season),
                "games": int(m["games"]),
                "accuracy": round(float(m["accuracy"]), 6),
                "log_loss": round(float(m["log_loss"]), 6),
                "brier_score": round(float(m["brier_score"]), 6),
            }
        )

    regime_metrics = summarize_by_regime(output_rows)

    best_season_regime = max(regime_metrics, key=lambda row: float(row["accuracy"]))

    overall_row = {
        "games": int(overall_metrics["games"]),
        "accuracy": round(float(overall_metrics["accuracy"]), 6),
        "log_loss": round(float(overall_metrics["log_loss"]), 6),
        "brier_score": round(float(overall_metrics["brier_score"]), 6),
        "phase1_winner_accuracy": PHASE1_WINNER_ACCURACY,
        "accuracy_delta_vs_phase1_winner": round(float(overall_metrics["accuracy"]) - PHASE1_WINNER_ACCURACY, 6),
    }

    summary = {
        "source": str(source_csv.relative_to(repo_root)).replace("/", "\\"),
        "benchmark_phase1_winner_accuracy": PHASE1_WINNER_ACCURACY,
        "overall_metrics": overall_row,
        "best_regime_metric": best_season_regime,
        "season_metrics": season_metrics,
        "regime_metrics": regime_metrics,
        "candidate_models": BASE_MODELS,
        "regime_definition": "within-season terciles",
        "fold_safe_training": "prior seasons + earlier games in the same season",
        "artifacts": {
            "predictions_csv": str((output_dir / "predictions.csv").relative_to(repo_root)).replace("/", "\\"),
            "overall_metrics_csv": str((output_dir / "overall_metrics.csv").relative_to(repo_root)).replace("/", "\\"),
            "season_metrics_csv": str((output_dir / "season_metrics.csv").relative_to(repo_root)).replace("/", "\\"),
            "regime_metrics_csv": str((output_dir / "regime_metrics.csv").relative_to(repo_root)).replace("/", "\\"),
            "regime_weights_csv": str((output_dir / "regime_weights.csv").relative_to(repo_root)).replace("/", "\\"),
            "summary_json": str((output_dir / "summary.json").relative_to(repo_root)).replace("/", "\\"),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "predictions.csv", output_rows)
    write_csv(output_dir / "overall_metrics.csv", [overall_row])
    write_csv(output_dir / "season_metrics.csv", season_metrics)
    write_csv(output_dir / "regime_metrics.csv", regime_metrics)
    write_csv(output_dir / "regime_weights.csv", regime_weight_rows)
    write_json(output_dir / "summary.json", summary)

    write_report(
        report_path,
        overall_row,
        best_season_regime,
        season_metrics,
        regime_metrics,
        PHASE1_WINNER_ACCURACY,
        summary["artifacts"],
    )


if __name__ == "__main__":
    main()
