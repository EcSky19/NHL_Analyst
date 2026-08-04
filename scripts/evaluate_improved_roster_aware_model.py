import argparse
import csv
import json
import math
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


BASELINE_ACCURACY = 0.578811
EPS = 1e-6


def clamp_probability(value: float) -> float:
    return max(EPS, min(1.0 - EPS, value))


def season_label(season_id: int) -> str:
    raw = str(int(season_id))
    if len(raw) == 8:
        return f"{raw[:4]}-{raw[4:]}"
    return raw


def to_int(value: str) -> int:
    return int(float(value))


def to_float(value: str) -> float:
    return float(value)


def maybe_regenerate_predictions(repo_root: Path, predictions_csv: Path, enabled: bool) -> bool:
    if predictions_csv.exists():
        return False
    if not enabled:
        raise FileNotFoundError(f"Missing predictions file: {predictions_csv}")
    cmd = [sys.executable, str(repo_root / "scripts" / "train_roster_aware_model.py"), "--repo-root", str(repo_root)]
    subprocess.run(cmd, check=True)
    if not predictions_csv.exists():
        raise FileNotFoundError(f"Predictions were not generated: {predictions_csv}")
    return True


def read_predictions(path: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            season = to_int(raw["season"])
            home_prob = clamp_probability(to_float(raw["home_win_probability"]))
            away_prob = clamp_probability(to_float(raw["away_win_probability"]))
            actual_home_win = to_int(raw["actual_home_win"])
            rows.append(
                {
                    "season": season,
                    "season_label": season_label(season),
                    "game_id": to_int(raw["game_id"]),
                    "game_date": raw["game_date"],
                    "home_team_abbrev": raw["home_team_abbrev"],
                    "away_team_abbrev": raw["away_team_abbrev"],
                    "actual_home_win": actual_home_win,
                    "home_win_probability": home_prob,
                    "away_win_probability": away_prob,
                    "predicted_winner_abbrev": raw["predicted_winner_abbrev"],
                    "actual_winner_abbrev": raw["actual_winner_abbrev"],
                    "is_correct_pick": 1 if (1 if home_prob >= 0.5 else 0) == actual_home_win else 0,
                }
            )
    rows.sort(key=lambda r: (str(r["game_date"]), int(r["game_id"])))
    if not rows:
        raise ValueError("No prediction rows found.")
    return rows


def summarize(rows: List[Dict[str, object]]) -> Dict[str, float]:
    n = len(rows)
    accuracy = sum(int(r["is_correct_pick"]) for r in rows) / n
    log_loss = -sum(
        int(r["actual_home_win"]) * math.log(clamp_probability(float(r["home_win_probability"])))
        + (1 - int(r["actual_home_win"])) * math.log(clamp_probability(float(r["away_win_probability"])))
        for r in rows
    ) / n
    brier = sum((float(r["home_win_probability"]) - int(r["actual_home_win"])) ** 2 for r in rows) / n
    return {"games": float(n), "accuracy": accuracy, "log_loss": log_loss, "brier_score": brier}


def compute_metrics(rows: List[Dict[str, object]]) -> Dict[str, object]:
    overall = summarize(rows)
    grouped: Dict[int, List[Dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(int(row["season"]), []).append(row)
    by_season: List[Dict[str, object]] = []
    for season in sorted(grouped.keys()):
        s = summarize(grouped[season])
        by_season.append(
            {
                "season": season,
                "season_label": season_label(season),
                "games": int(s["games"]),
                "accuracy": round(float(s["accuracy"]), 6),
                "log_loss": round(float(s["log_loss"]), 6),
                "brier_score": round(float(s["brier_score"]), 6),
                "baseline_accuracy": BASELINE_ACCURACY,
                "accuracy_delta_vs_baseline": round(float(s["accuracy"]) - BASELINE_ACCURACY, 6),
            }
        )
    overall_comp = {
        "games": int(overall["games"]),
        "accuracy": round(float(overall["accuracy"]), 6),
        "log_loss": round(float(overall["log_loss"]), 6),
        "brier_score": round(float(overall["brier_score"]), 6),
        "baseline_accuracy": BASELINE_ACCURACY,
        "accuracy_delta_vs_baseline": round(float(overall["accuracy"]) - BASELINE_ACCURACY, 6),
        "accuracy_delta_vs_baseline_pct_points": round((float(overall["accuracy"]) - BASELINE_ACCURACY) * 100.0, 4),
    }
    return {"overall": overall_comp, "by_season": by_season}


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_report(path: Path, summary: Dict[str, object], regenerated: bool) -> None:
    overall = summary["overall"]
    by_season = summary["by_season"]
    lines = [
        "# Improved Roster-aware Model Evaluation",
        "",
        "## Methodology",
        "- Source: `data\\processed\\roster_aware_walk_forward_predictions.csv`.",
        f"- Predictions regenerated during this run: {'yes' if regenerated else 'no'}.",
        "- Deterministic metric definitions:",
        "  - Accuracy = mean(is_correct_pick) with 0.5 threshold on home_win_probability.",
        "  - Log loss = mean(-[y*ln(p_home)+(1-y)*ln(p_away)]), with probability clamp to [1e-6, 1-1e-6].",
        "  - Brier score = mean((p_home - y)^2).",
        "",
        "## Overall",
        f"- Games: {overall['games']}",
        f"- Accuracy: {overall['accuracy']:.4f}",
        f"- Log loss: {overall['log_loss']:.4f}",
        f"- Brier score: {overall['brier_score']:.4f}",
        f"- Baseline accuracy: {overall['baseline_accuracy']:.4f}",
        f"- Delta vs baseline: {overall['accuracy_delta_vs_baseline']:+.4f} ({overall['accuracy_delta_vs_baseline_pct_points']:+.2f} pp)",
        "",
        "## Per-season",
        "| Season | Games | Accuracy | Log loss | Brier score | Delta vs baseline |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in by_season:
        lines.append(
            f"| {row['season_label']} | {row['games']} | {float(row['accuracy']):.4f} | "
            f"{float(row['log_loss']):.4f} | {float(row['brier_score']):.4f} | {float(row['accuracy_delta_vs_baseline']):+.4f} |"
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "- `data\\processed\\improved_roster_aware_evaluation_summary.json`",
            "- `data\\processed\\improved_roster_aware_evaluation_by_season.csv`",
            "- `data\\processed\\improved_roster_aware_vs_baseline_comparison.csv`",
            "- `data\\reports\\improved_roster_aware_evaluation_report.md`",
            "- SQLite tables in `data\\processed\\nhl_research.db`: `improved_roster_aware_evaluation_summary`, `improved_roster_aware_evaluation_by_season`",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_sqlite_tables(sqlite_db: Path, overall: Dict[str, object], by_season: List[Dict[str, object]]) -> None:
    with sqlite3.connect(sqlite_db) as con:
        con.execute("DROP TABLE IF EXISTS improved_roster_aware_evaluation_summary")
        con.execute(
            """
            CREATE TABLE improved_roster_aware_evaluation_summary (
                games INTEGER,
                accuracy REAL,
                log_loss REAL,
                brier_score REAL,
                baseline_accuracy REAL,
                accuracy_delta_vs_baseline REAL,
                accuracy_delta_vs_baseline_pct_points REAL
            )
            """
        )
        con.execute(
            """
            INSERT INTO improved_roster_aware_evaluation_summary
            (games, accuracy, log_loss, brier_score, baseline_accuracy, accuracy_delta_vs_baseline, accuracy_delta_vs_baseline_pct_points)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(overall["games"]),
                float(overall["accuracy"]),
                float(overall["log_loss"]),
                float(overall["brier_score"]),
                float(overall["baseline_accuracy"]),
                float(overall["accuracy_delta_vs_baseline"]),
                float(overall["accuracy_delta_vs_baseline_pct_points"]),
            ),
        )
        con.execute("DROP TABLE IF EXISTS improved_roster_aware_evaluation_by_season")
        con.execute(
            """
            CREATE TABLE improved_roster_aware_evaluation_by_season (
                season INTEGER,
                season_label TEXT,
                games INTEGER,
                accuracy REAL,
                log_loss REAL,
                brier_score REAL,
                baseline_accuracy REAL,
                accuracy_delta_vs_baseline REAL
            )
            """
        )
        con.executemany(
            """
            INSERT INTO improved_roster_aware_evaluation_by_season
            (season, season_label, games, accuracy, log_loss, brier_score, baseline_accuracy, accuracy_delta_vs_baseline)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    int(row["season"]),
                    str(row["season_label"]),
                    int(row["games"]),
                    float(row["accuracy"]),
                    float(row["log_loss"]),
                    float(row["brier_score"]),
                    float(row["baseline_accuracy"]),
                    float(row["accuracy_delta_vs_baseline"]),
                )
                for row in by_season
            ],
        )
        con.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate improved roster-aware predictions against baseline metrics.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--predictions-csv", default=None, help="Defaults to data\\processed\\roster_aware_walk_forward_predictions.csv")
    parser.add_argument("--sqlite-db", default=None, help="Defaults to data\\processed\\nhl_research.db")
    parser.add_argument("--regenerate-if-missing", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    predictions_csv = (
        Path(args.predictions_csv).resolve()
        if args.predictions_csv
        else repo_root / "data" / "processed" / "roster_aware_walk_forward_predictions.csv"
    )
    sqlite_db = Path(args.sqlite_db).resolve() if args.sqlite_db else repo_root / "data" / "processed" / "nhl_research.db"
    out_summary_json = repo_root / "data" / "processed" / "improved_roster_aware_evaluation_summary.json"
    out_by_season_csv = repo_root / "data" / "processed" / "improved_roster_aware_evaluation_by_season.csv"
    out_comparison_csv = repo_root / "data" / "processed" / "improved_roster_aware_vs_baseline_comparison.csv"
    out_report = repo_root / "data" / "reports" / "improved_roster_aware_evaluation_report.md"

    regenerated = maybe_regenerate_predictions(repo_root, predictions_csv, args.regenerate_if_missing)
    prediction_rows = read_predictions(predictions_csv)
    metrics = compute_metrics(prediction_rows)

    summary_payload = {
        "model_name": "improved_roster_aware",
        "prediction_source": str(predictions_csv),
        "predictions_regenerated_this_run": regenerated,
        "deterministic_metrics": {
            "accuracy_threshold": 0.5,
            "probability_clamp_min": EPS,
            "probability_clamp_max": 1.0 - EPS,
            "log_loss_formula": "-mean(y*ln(p_home) + (1-y)*ln(p_away))",
            "brier_score_formula": "mean((p_home - y)^2)",
        },
        **metrics,
    }
    write_json(out_summary_json, summary_payload)
    write_csv(out_by_season_csv, metrics["by_season"])
    comparison_rows = [
        {"model": "baseline", "games": "", "accuracy": BASELINE_ACCURACY, "log_loss": "", "brier_score": ""},
        {
            "model": "improved_roster_aware",
            "games": int(metrics["overall"]["games"]),
            "accuracy": metrics["overall"]["accuracy"],
            "log_loss": metrics["overall"]["log_loss"],
            "brier_score": metrics["overall"]["brier_score"],
        },
        {
            "model": "delta_improved_minus_baseline",
            "games": "",
            "accuracy": metrics["overall"]["accuracy_delta_vs_baseline"],
            "log_loss": "",
            "brier_score": "",
        },
    ]
    write_csv(out_comparison_csv, comparison_rows)
    write_report(out_report, metrics, regenerated=regenerated)
    write_sqlite_tables(sqlite_db, metrics["overall"], metrics["by_season"])

    print(f"overall_accuracy={metrics['overall']['accuracy']:.6f}")
    print(f"overall_log_loss={metrics['overall']['log_loss']:.6f}")
    print(f"overall_brier_score={metrics['overall']['brier_score']:.6f}")
    print(f"baseline_accuracy={BASELINE_ACCURACY:.6f}")
    print(f"accuracy_delta_vs_baseline={metrics['overall']['accuracy_delta_vs_baseline']:+.6f}")
    print(f"summary_json={out_summary_json}")
    print(f"by_season_csv={out_by_season_csv}")
    print(f"comparison_csv={out_comparison_csv}")
    print(f"report={out_report}")
    print(f"sqlite_tables=improved_roster_aware_evaluation_summary,improved_roster_aware_evaluation_by_season db={sqlite_db}")


if __name__ == "__main__":
    main()
