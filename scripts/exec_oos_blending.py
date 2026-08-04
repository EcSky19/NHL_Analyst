import argparse
import csv
import json
import math
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


EPS = 1e-6

MODEL_LOGISTIC = "logistic_engineered"
MODEL_IMPROVED = "improved_roster_aware"
MODEL_VALIDATED = "blend_fold_validated_logistic_improved"

DETERMINISTIC_WEIGHT_GRID: List[Tuple[str, float, float]] = [
    ("blend_fixed_50_50", 0.50, 0.50),
    ("blend_fixed_55_45", 0.55, 0.45),
    ("blend_fixed_60_40", 0.60, 0.40),
    ("blend_fixed_65_35", 0.65, 0.35),
    ("blend_fixed_70_30", 0.70, 0.30),
]


def clamp_probability(value: float) -> float:
    return max(EPS, min(1.0 - EPS, float(value)))


def season_label(season_id: int) -> str:
    raw = str(int(season_id))
    if len(raw) == 8:
        return f"{raw[:4]}-{raw[4:]}"
    return raw


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_logistic_predictions(path: Path) -> Dict[Tuple[int, int], Dict[str, object]]:
    rows = read_csv_rows(path)
    out: Dict[Tuple[int, int], Dict[str, object]] = {}
    for row in rows:
        season = int(float(row["season"]))
        game_id = int(float(row["game_id"]))
        key = (season, game_id)
        out[key] = {
            "season": season,
            "game_id": game_id,
            "game_date": row["game_date"],
            "home_team_abbrev": row["home_team_abbrev"],
            "away_team_abbrev": row["away_team_abbrev"],
            "actual_home_win": int(float(row["actual_home_win"])),
            "p_logistic": clamp_probability(float(row["home_win_probability"])),
            "fold_train_end_season": int(float(row["fold_train_end_season"])) if row.get("fold_train_end_season") else None,
        }
    return out


def load_improved_predictions(path: Path) -> Dict[Tuple[int, int], Dict[str, object]]:
    rows = read_csv_rows(path)
    out: Dict[Tuple[int, int], Dict[str, object]] = {}
    for row in rows:
        season = int(float(row["season"]))
        game_id = int(float(row["game_id"]))
        key = (season, game_id)
        out[key] = {
            "p_improved": clamp_probability(float(row["home_win_probability"])),
        }
    return out


def compute_metrics(rows: Sequence[Dict[str, object]], p_key: str) -> Dict[str, float]:
    n = len(rows)
    if n == 0:
        return {"games": 0.0, "accuracy": 0.0, "log_loss": 0.0, "brier_score": 0.0}
    correct = 0
    log_loss = 0.0
    brier = 0.0
    for row in rows:
        y = int(row["actual_home_win"])
        p = clamp_probability(float(row[p_key]))
        pred = 1 if p >= 0.5 else 0
        if pred == y:
            correct += 1
        log_loss += -(y * math.log(p) + (1 - y) * math.log(1.0 - p))
        brier += (p - y) ** 2
    return {
        "games": float(n),
        "accuracy": correct / n,
        "log_loss": log_loss / n,
        "brier_score": brier / n,
    }


def blend_probability(p_logistic: float, p_improved: float, w_logistic: float, w_improved: float) -> float:
    return clamp_probability((w_logistic * p_logistic + w_improved * p_improved) / (w_logistic + w_improved))


def metrics_sort_key(metrics: Dict[str, float], model_id: str) -> Tuple[float, float, float, str]:
    return (float(metrics["log_loss"]), float(metrics["brier_score"]), -float(metrics["accuracy"]), str(model_id))


def summarize_model(rows: Sequence[Dict[str, object]], model_id: str, p_key: str) -> Tuple[Dict[str, object], List[Dict[str, object]]]:
    overall = compute_metrics(rows, p_key)
    by_season: List[Dict[str, object]] = []
    seasons = sorted({int(r["season"]) for r in rows})
    for season in seasons:
        season_rows = [r for r in rows if int(r["season"]) == season]
        m = compute_metrics(season_rows, p_key)
        by_season.append(
            {
                "model_id": model_id,
                "season": season,
                "season_label": season_label(season),
                "games": int(m["games"]),
                "accuracy": round(float(m["accuracy"]), 6),
                "log_loss": round(float(m["log_loss"]), 6),
                "brier_score": round(float(m["brier_score"]), 6),
            }
        )
    overall_row = {
        "model_id": model_id,
        "games": int(overall["games"]),
        "accuracy": round(float(overall["accuracy"]), 6),
        "log_loss": round(float(overall["log_loss"]), 6),
        "brier_score": round(float(overall["brier_score"]), 6),
    }
    return overall_row, by_season


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_report(
    report_path: Path,
    best_row: Dict[str, object],
    overall_rows: List[Dict[str, object]],
    diagnostics: Dict[str, object],
    artifacts: Dict[str, str],
) -> None:
    lines = [
        "# Out-of-sample Blending: logistic_engineered + improved_roster_aware",
        "",
        "## Setup",
        "- Inputs:",
        "  - `data\\processed\\walk_forward_selected_logistic_engineered_predictions.csv`",
        "  - `data\\processed\\roster_aware_walk_forward_predictions.csv`",
        "- Overlap used: games present in both sources.",
        "- Fold-safe weighting: for each test season, blend weights are selected only from earlier-seasons validation games.",
        "- Deterministic candidates:",
        "  - fixed: 50/50, 55/45, 60/40, 65/35, 70/30 (logistic/improved)",
        "  - validated: per-season best from the same deterministic grid on prior-season validation only.",
        "",
        "## Best model",
        f"- Model: `{best_row['model_id']}`",
        f"- Games: {best_row['games']}",
        f"- Accuracy: {float(best_row['accuracy']):.6f}",
        f"- Log loss: {float(best_row['log_loss']):.6f}",
        f"- Brier score: {float(best_row['brier_score']):.6f}",
        "",
        "## Overall metrics (all candidates)",
        "| Model | Games | Accuracy | Log loss | Brier score |",
        "|---|---:|---:|---:|---:|",
    ]
    ranked = sorted(
        overall_rows,
        key=lambda r: (
            float(r["log_loss"]),
            float(r["brier_score"]),
            -float(r["accuracy"]),
            str(r["model_id"]),
        ),
    )
    for row in ranked:
        lines.append(
            f"| {row['model_id']} | {row['games']} | {float(row['accuracy']):.6f} | "
            f"{float(row['log_loss']):.6f} | {float(row['brier_score']):.6f} |"
        )

    lines.extend(
        [
            "",
            "## Fold-safe validation diagnostics",
            f"- Seasons evaluated: {', '.join(str(s) for s in diagnostics['seasons'])}",
            f"- First season fallback (no prior validation): `{diagnostics['first_season_default']}`",
            "- Per-season selected weights and validation sample sizes are stored in diagnostics JSON.",
            "",
            "## Artifacts",
        ]
    )
    for _, artifact_path in sorted(artifacts.items()):
        lines.append(f"- `{artifact_path}`")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute fold-safe OOS probability blending between logistic and improved roster-aware families.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()

    logistic_csv = repo_root / "data" / "processed" / "walk_forward_selected_logistic_engineered_predictions.csv"
    improved_csv = repo_root / "data" / "processed" / "roster_aware_walk_forward_predictions.csv"
    phase1_dir = repo_root / "data" / "processed" / "execution_plan" / "phase1"
    report_path = repo_root / "data" / "reports" / "exec_oos_blending.md"

    logistic = load_logistic_predictions(logistic_csv)
    improved = load_improved_predictions(improved_csv)

    merged_rows: List[Dict[str, object]] = []
    for key in sorted(set(logistic.keys()) & set(improved.keys())):
        base = dict(logistic[key])
        base.update(improved[key])
        merged_rows.append(base)
    if not merged_rows:
        raise SystemExit("No overlapping predictions found between logistic and improved models.")

    seasons = sorted({int(r["season"]) for r in merged_rows})

    for row in merged_rows:
        p_log = float(row["p_logistic"])
        p_imp = float(row["p_improved"])
        for blend_id, w_log, w_imp in DETERMINISTIC_WEIGHT_GRID:
            row[f"p_{blend_id}"] = blend_probability(p_log, p_imp, w_log, w_imp)

    fold_diagnostics: List[Dict[str, object]] = []
    first_season_default = "blend_fixed_50_50"
    season_to_selected_variant: Dict[int, str] = {}
    season_to_selected_weights: Dict[int, Dict[str, float]] = {}

    for idx, season in enumerate(seasons):
        if idx == 0:
            selected_variant = first_season_default
            selected_weights = {"logistic_engineered": 0.50, "improved_roster_aware": 0.50}
            validation_rows: List[Dict[str, object]] = []
            candidates = []
        else:
            validation_rows = [r for r in merged_rows if int(r["season"]) < season]
            candidates = []
            for blend_id, w_log, w_imp in DETERMINISTIC_WEIGHT_GRID:
                metrics = compute_metrics(validation_rows, f"p_{blend_id}")
                candidates.append(
                    {
                        "blend_id": blend_id,
                        "weights": {"logistic_engineered": w_log, "improved_roster_aware": w_imp},
                        "games": int(metrics["games"]),
                        "accuracy": round(float(metrics["accuracy"]), 6),
                        "log_loss": round(float(metrics["log_loss"]), 6),
                        "brier_score": round(float(metrics["brier_score"]), 6),
                    }
                )
            ranked = sorted(
                candidates,
                key=lambda c: (
                    float(c["log_loss"]),
                    float(c["brier_score"]),
                    -float(c["accuracy"]),
                    str(c["blend_id"]),
                ),
            )
            selected_variant = str(ranked[0]["blend_id"])
            selected_weights = dict(ranked[0]["weights"])

        season_to_selected_variant[season] = selected_variant
        season_to_selected_weights[season] = selected_weights
        fold_diagnostics.append(
            {
                "test_season": season,
                "test_season_label": season_label(season),
                "validation_games": len(validation_rows),
                "selected_variant": selected_variant,
                "selected_weights": selected_weights,
                "candidate_metrics": candidates,
            }
        )

    for row in merged_rows:
        season = int(row["season"])
        selected_variant = season_to_selected_variant[season]
        weights = season_to_selected_weights[season]
        row["validated_blend_variant"] = selected_variant
        row["validated_weight_logistic_engineered"] = round(float(weights["logistic_engineered"]), 6)
        row["validated_weight_improved_roster_aware"] = round(float(weights["improved_roster_aware"]), 6)
        row[f"p_{MODEL_VALIDATED}"] = float(row[f"p_{selected_variant}"])

    prediction_rows: List[Dict[str, object]] = []
    for row in merged_rows:
        for model_id, p_key in (
            (MODEL_LOGISTIC, "p_logistic"),
            (MODEL_IMPROVED, "p_improved"),
            *[(blend_id, f"p_{blend_id}") for blend_id, _, _ in DETERMINISTIC_WEIGHT_GRID],
            (MODEL_VALIDATED, f"p_{MODEL_VALIDATED}"),
        ):
            p_home = clamp_probability(float(row[p_key]))
            pred_home = 1 if p_home >= 0.5 else 0
            prediction_rows.append(
                {
                    "model_id": model_id,
                    "season": int(row["season"]),
                    "season_label": season_label(int(row["season"])),
                    "game_id": int(row["game_id"]),
                    "game_date": str(row["game_date"]),
                    "home_team_abbrev": str(row["home_team_abbrev"]),
                    "away_team_abbrev": str(row["away_team_abbrev"]),
                    "actual_home_win": int(row["actual_home_win"]),
                    "home_win_probability": round(p_home, 6),
                    "away_win_probability": round(1.0 - p_home, 6),
                    "predicted_winner_abbrev": str(row["home_team_abbrev"]) if pred_home == 1 else str(row["away_team_abbrev"]),
                    "is_correct_pick": 1 if pred_home == int(row["actual_home_win"]) else 0,
                    "validated_blend_variant": str(row["validated_blend_variant"]),
                    "validated_weight_logistic_engineered": row["validated_weight_logistic_engineered"],
                    "validated_weight_improved_roster_aware": row["validated_weight_improved_roster_aware"],
                }
            )

    model_ids = [
        MODEL_LOGISTIC,
        MODEL_IMPROVED,
        *[blend_id for blend_id, _, _ in DETERMINISTIC_WEIGHT_GRID],
        MODEL_VALIDATED,
    ]
    overall_rows: List[Dict[str, object]] = []
    by_season_rows: List[Dict[str, object]] = []
    for model_id in model_ids:
        model_rows = [r for r in prediction_rows if str(r["model_id"]) == model_id]
        overall_row, model_by_season = summarize_model(model_rows, model_id, "home_win_probability")
        overall_rows.append(overall_row)
        by_season_rows.extend(model_by_season)
    ranked_overall = sorted(overall_rows, key=lambda r: metrics_sort_key(r, str(r["model_id"])))
    best_row = ranked_overall[0]

    diagnostics_payload = {
        "deterministic": True,
        "focus_model_families": [MODEL_LOGISTIC, MODEL_IMPROVED],
        "overlap_games": len(merged_rows),
        "seasons": seasons,
        "first_season_default": first_season_default,
        "fold_safe_weight_selection": fold_diagnostics,
        "weight_grid": [
            {
                "blend_id": blend_id,
                "weights": {"logistic_engineered": w_log, "improved_roster_aware": w_imp},
            }
            for blend_id, w_log, w_imp in DETERMINISTIC_WEIGHT_GRID
        ],
        "ranking_rule": "lowest log_loss, then lowest brier_score, then highest accuracy",
        "best_model_overall": best_row,
    }

    artifacts = {
        "predictions_csv": str(phase1_dir / "blend_predictions.csv"),
        "overall_metrics_csv": str(phase1_dir / "blend_metrics_overall.csv"),
        "by_season_metrics_csv": str(phase1_dir / "blend_metrics_by_season.csv"),
        "diagnostics_json": str(phase1_dir / "blend_diagnostics.json"),
        "summary_json": str(phase1_dir / "blend_summary.json"),
        "report_md": str(report_path),
    }
    summary_payload = {
        "deterministic": True,
        "focus_model_families": [MODEL_LOGISTIC, MODEL_IMPROVED],
        "best_model_overall": best_row,
        "overall_metrics": overall_rows,
        "artifacts": artifacts,
    }

    write_csv(phase1_dir / "blend_predictions.csv", prediction_rows)
    write_csv(phase1_dir / "blend_metrics_overall.csv", overall_rows)
    write_csv(phase1_dir / "blend_metrics_by_season.csv", by_season_rows)
    write_json(phase1_dir / "blend_diagnostics.json", diagnostics_payload)
    write_json(phase1_dir / "blend_summary.json", summary_payload)
    write_report(report_path, best_row, overall_rows, diagnostics_payload, artifacts)

    print(f"overlap_games={len(merged_rows)}")
    print(f"seasons={','.join(str(s) for s in seasons)}")
    print(
        "best_model="
        f"{best_row['model_id']}(acc={best_row['accuracy']},ll={best_row['log_loss']},brier={best_row['brier_score']})"
    )
    print(f"predictions_csv={artifacts['predictions_csv']}")
    print(f"overall_metrics_csv={artifacts['overall_metrics_csv']}")
    print(f"by_season_metrics_csv={artifacts['by_season_metrics_csv']}")
    print(f"diagnostics_json={artifacts['diagnostics_json']}")
    print(f"summary_json={artifacts['summary_json']}")
    print(f"report_md={artifacts['report_md']}")


if __name__ == "__main__":
    main()
