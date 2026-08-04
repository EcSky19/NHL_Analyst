import argparse
import csv
import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


ELO_MEAN = 1500.0
ELO_REGRESSION = 0.75
ELO_HOME_ADVANTAGE = 55.0
ELO_K_FACTOR = 18.0
FORM_WIN_PCT_ELO_WEIGHT = 120.0
FORM_GOAL_DIFF_ELO_WEIGHT = 35.0


@dataclass
class SeasonTeamStats:
    games: int = 0
    wins: int = 0
    goal_diff: int = 0


def season_label(season_id: int) -> str:
    raw = str(int(season_id))
    if len(raw) == 8:
        return f"{raw[:4]}-{raw[4:]}"
    return raw


def clamp_probability(value: float) -> float:
    return max(1e-6, min(1.0 - 1e-6, value))


def win_probability_from_rating_diff(rating_diff: float) -> float:
    return clamp_probability(1.0 / (1.0 + math.pow(10.0, -rating_diff / 400.0)))


def table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    cur = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    )
    return cur.fetchone() is not None


def load_historical_games(con: sqlite3.Connection) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    cur = con.execute(
        """
        SELECT
            season,
            game_id,
            game_date,
            home_team_abbrev,
            away_team_abbrev,
            home_goals,
            away_goals,
            winner_abbrev
        FROM historical_games_last5
        WHERE is_final = 1
        ORDER BY game_date ASC, game_id ASC
        """
    )
    for (
        season,
        game_id,
        game_date,
        home_team_abbrev,
        away_team_abbrev,
        home_goals,
        away_goals,
        winner_abbrev,
    ) in cur.fetchall():
        rows.append(
            {
                "season": int(season),
                "season_label": season_label(int(season)),
                "game_id": int(game_id),
                "game_date": str(game_date),
                "home_team_abbrev": str(home_team_abbrev).upper(),
                "away_team_abbrev": str(away_team_abbrev).upper(),
                "home_goals": int(home_goals),
                "away_goals": int(away_goals),
                "winner_abbrev": str(winner_abbrev).upper(),
            }
        )
    return rows


def maybe_wait_for_backtest_features(
    con: sqlite3.Connection,
    retries: int,
    wait_seconds: int,
) -> str:
    for _ in range(retries + 1):
        if table_exists(con, "backtest_features_last5"):
            return "backtest_features_available"
        if table_exists(con, "historical_games_features_last5"):
            return "historical_games_features_available"
        if wait_seconds > 0:
            import time

            time.sleep(wait_seconds)
    return "backtest_features_unavailable_fallback_used"


def evaluate_games(games: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    carry_elo: Dict[str, float] = {}
    season_stats: Dict[str, SeasonTeamStats] = {}
    current_season: int | None = None
    rows: List[Dict[str, object]] = []

    for game in games:
        season = int(game["season"])
        home_team = str(game["home_team_abbrev"])
        away_team = str(game["away_team_abbrev"])
        home_goals = int(game["home_goals"])
        away_goals = int(game["away_goals"])

        if current_season != season:
            if current_season is not None:
                for team, elo_value in list(carry_elo.items()):
                    carry_elo[team] = ELO_MEAN + ELO_REGRESSION * (elo_value - ELO_MEAN)
            season_stats = {}
            current_season = season

        home_elo_pre = carry_elo.get(home_team, ELO_MEAN)
        away_elo_pre = carry_elo.get(away_team, ELO_MEAN)

        home_state = season_stats.get(home_team, SeasonTeamStats())
        away_state = season_stats.get(away_team, SeasonTeamStats())
        home_win_pct_pre = home_state.wins / home_state.games if home_state.games else 0.5
        away_win_pct_pre = away_state.wins / away_state.games if away_state.games else 0.5
        home_goal_diff_pg_pre = home_state.goal_diff / home_state.games if home_state.games else 0.0
        away_goal_diff_pg_pre = away_state.goal_diff / away_state.games if away_state.games else 0.0

        rating_diff = (
            (home_elo_pre - away_elo_pre)
            + ELO_HOME_ADVANTAGE
            + FORM_WIN_PCT_ELO_WEIGHT * (home_win_pct_pre - away_win_pct_pre)
            + FORM_GOAL_DIFF_ELO_WEIGHT * (home_goal_diff_pg_pre - away_goal_diff_pg_pre)
        )
        home_win_probability = win_probability_from_rating_diff(rating_diff)
        away_win_probability = 1.0 - home_win_probability
        actual_home_win = 1 if home_goals > away_goals else 0
        predicted_winner = home_team if home_win_probability >= 0.5 else away_team
        actual_winner = home_team if actual_home_win == 1 else away_team

        goal_margin = abs(home_goals - away_goals)
        k_adjusted = ELO_K_FACTOR * (1.0 + min(goal_margin, 5) * 0.1)
        elo_delta = k_adjusted * (actual_home_win - home_win_probability)
        home_elo_post = home_elo_pre + elo_delta
        away_elo_post = away_elo_pre - elo_delta

        carry_elo[home_team] = home_elo_post
        carry_elo[away_team] = away_elo_post

        home_state.games += 1
        away_state.games += 1
        home_state.wins += actual_home_win
        away_state.wins += 1 - actual_home_win
        home_state.goal_diff += home_goals - away_goals
        away_state.goal_diff += away_goals - home_goals
        season_stats[home_team] = home_state
        season_stats[away_team] = away_state

        rows.append(
            {
                "season": season,
                "season_label": str(game["season_label"]),
                "game_id": int(game["game_id"]),
                "game_date": str(game["game_date"]),
                "home_team_abbrev": home_team,
                "away_team_abbrev": away_team,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "winner_abbrev_actual": actual_winner,
                "predicted_winner_abbrev": predicted_winner,
                "is_correct_pick": 1 if predicted_winner == actual_winner else 0,
                "actual_home_win": actual_home_win,
                "home_win_probability": round(home_win_probability, 6),
                "away_win_probability": round(away_win_probability, 6),
                "home_elo_pre": round(home_elo_pre, 3),
                "away_elo_pre": round(away_elo_pre, 3),
                "home_elo_post": round(home_elo_post, 3),
                "away_elo_post": round(away_elo_post, 3),
                "home_games_played_pre": home_state.games - 1,
                "away_games_played_pre": away_state.games - 1,
                "home_win_pct_pre": round(home_win_pct_pre, 6),
                "away_win_pct_pre": round(away_win_pct_pre, 6),
                "home_goal_diff_pg_pre": round(home_goal_diff_pg_pre, 6),
                "away_goal_diff_pg_pre": round(away_goal_diff_pg_pre, 6),
                "rating_diff_pre": round(rating_diff, 6),
                "k_factor_used": round(k_adjusted, 6),
            }
        )

    return rows


def compute_metrics(rows: List[Dict[str, object]]) -> Dict[str, object]:
    if not rows:
        raise ValueError("No evaluated rows available for metrics.")

    def summarize(scope_rows: List[Dict[str, object]]) -> Dict[str, float | int]:
        n = len(scope_rows)
        accuracy = sum(int(r["is_correct_pick"]) for r in scope_rows) / n
        log_loss = -sum(
            (
                int(r["actual_home_win"]) * math.log(clamp_probability(float(r["home_win_probability"])))
                + (1 - int(r["actual_home_win"])) * math.log(clamp_probability(float(r["away_win_probability"])))
            )
            for r in scope_rows
        ) / n
        brier_score = sum(
            (float(r["home_win_probability"]) - int(r["actual_home_win"])) ** 2 for r in scope_rows
        ) / n
        return {
            "games": n,
            "accuracy": round(accuracy, 6),
            "log_loss": round(log_loss, 6),
            "brier_score": round(brier_score, 6),
        }

    overall = summarize(rows)
    by_season: List[Dict[str, object]] = []
    grouped: Dict[int, List[Dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(int(row["season"]), []).append(row)

    for season in sorted(grouped.keys()):
        season_rows = grouped[season]
        season_metrics = summarize(season_rows)
        by_season.append(
            {
                "season": season,
                "season_label": str(season_rows[0]["season_label"]),
                **season_metrics,
            }
        )

    return {"overall": overall, "by_season": by_season}


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"No rows to write to {path}")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_summary_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_report(path: Path, summary: Dict[str, object], dependency_status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    overall = summary["overall"]
    by_season = summary["by_season"]

    lines = [
        "# Last 5 NHL Regular Seasons Evaluation",
        "",
        "## Methodology",
        "- Strict pregame walk-forward evaluation over `historical_games_last5`.",
        "- Per game, probability is generated before outcome using only information available before puck drop:",
        "  - carry-over Elo-like team strength",
        "  - season-to-date pregame win percentage",
        "  - season-to-date pregame goal differential per game",
        "- Deterministic setup (no random seeds or stochastic training).",
        f"- Backtest-feature dependency status: `{dependency_status}`.",
        "",
        "## Model parameters",
        f"- ELO_MEAN={ELO_MEAN}",
        f"- ELO_REGRESSION={ELO_REGRESSION}",
        f"- ELO_HOME_ADVANTAGE={ELO_HOME_ADVANTAGE}",
        f"- ELO_K_FACTOR={ELO_K_FACTOR}",
        f"- FORM_WIN_PCT_ELO_WEIGHT={FORM_WIN_PCT_ELO_WEIGHT}",
        f"- FORM_GOAL_DIFF_ELO_WEIGHT={FORM_GOAL_DIFF_ELO_WEIGHT}",
        "",
        "## Overall metrics",
        f"- Games: {overall['games']}",
        f"- Accuracy: {overall['accuracy']:.4f}",
        f"- Log loss: {overall['log_loss']:.4f}",
        f"- Brier score: {overall['brier_score']:.4f}",
        "",
        "## Per-season metrics",
        "| Season | Games | Accuracy | Log loss | Brier score |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in by_season:
        lines.append(
            f"| {row['season_label']} | {row['games']} | {float(row['accuracy']):.4f} | "
            f"{float(row['log_loss']):.4f} | {float(row['brier_score']):.4f} |"
        )

    lines.extend(
        [
            "",
            "## Artifacts",
            "- `data\\processed\\last5seasons_game_predictions.csv`",
            "- `data\\processed\\last5seasons_evaluation_summary.json`",
            "- `data\\processed\\last5seasons_evaluation_by_season.csv`",
            "- `data\\reports\\last5seasons_evaluation_report.md`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    write_csv(path, rows)


def write_sqlite_tables(
    con: sqlite3.Connection,
    prediction_rows: List[Dict[str, object]],
    season_rows: List[Dict[str, object]],
    overall: Dict[str, object],
) -> None:
    con.execute("DROP TABLE IF EXISTS last5seasons_game_predictions")
    con.execute(
        """
        CREATE TABLE last5seasons_game_predictions (
            season INTEGER,
            season_label TEXT,
            game_id INTEGER PRIMARY KEY,
            game_date TEXT,
            home_team_abbrev TEXT,
            away_team_abbrev TEXT,
            home_goals INTEGER,
            away_goals INTEGER,
            winner_abbrev_actual TEXT,
            predicted_winner_abbrev TEXT,
            is_correct_pick INTEGER,
            actual_home_win INTEGER,
            home_win_probability REAL,
            away_win_probability REAL,
            home_elo_pre REAL,
            away_elo_pre REAL,
            home_elo_post REAL,
            away_elo_post REAL,
            home_games_played_pre INTEGER,
            away_games_played_pre INTEGER,
            home_win_pct_pre REAL,
            away_win_pct_pre REAL,
            home_goal_diff_pg_pre REAL,
            away_goal_diff_pg_pre REAL,
            rating_diff_pre REAL,
            k_factor_used REAL
        )
        """
    )
    pred_cols = list(prediction_rows[0].keys())
    pred_values = [[row[col] for col in pred_cols] for row in prediction_rows]
    con.executemany(
        f"INSERT INTO last5seasons_game_predictions ({', '.join(pred_cols)}) VALUES ({', '.join(['?'] * len(pred_cols))})",
        pred_values,
    )

    con.execute("DROP TABLE IF EXISTS last5seasons_evaluation_summary")
    con.execute(
        """
        CREATE TABLE last5seasons_evaluation_summary (
            scope TEXT,
            season INTEGER,
            season_label TEXT,
            games INTEGER,
            accuracy REAL,
            log_loss REAL,
            brier_score REAL
        )
        """
    )
    con.execute(
        """
        INSERT INTO last5seasons_evaluation_summary (scope, season, season_label, games, accuracy, log_loss, brier_score)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("overall", None, "overall", overall["games"], overall["accuracy"], overall["log_loss"], overall["brier_score"]),
    )
    for season_row in season_rows:
        con.execute(
            """
            INSERT INTO last5seasons_evaluation_summary (scope, season, season_label, games, accuracy, log_loss, brier_score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "season",
                season_row["season"],
                season_row["season_label"],
                season_row["games"],
                season_row["accuracy"],
                season_row["log_loss"],
                season_row["brier_score"],
            ),
        )
    con.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate NHL winner prediction accuracy over the last five completed regular seasons.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--sqlite-db", default=None, help="Defaults to data\\processed\\nhl_research.db")
    parser.add_argument(
        "--output-predictions-csv",
        default=None,
        help="Defaults to data\\processed\\last5seasons_game_predictions.csv",
    )
    parser.add_argument(
        "--output-summary-json",
        default=None,
        help="Defaults to data\\processed\\last5seasons_evaluation_summary.json",
    )
    parser.add_argument(
        "--output-summary-csv",
        default=None,
        help="Defaults to data\\processed\\last5seasons_evaluation_by_season.csv",
    )
    parser.add_argument(
        "--output-report",
        default=None,
        help="Defaults to data\\reports\\last5seasons_evaluation_report.md",
    )
    parser.add_argument("--skip-sqlite-write", action="store_true")
    parser.add_argument("--dependency-retries", type=int, default=2)
    parser.add_argument("--dependency-wait-seconds", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    sqlite_db = Path(args.sqlite_db).resolve() if args.sqlite_db else repo_root / "data" / "processed" / "nhl_research.db"
    output_predictions_csv = (
        Path(args.output_predictions_csv).resolve()
        if args.output_predictions_csv
        else repo_root / "data" / "processed" / "last5seasons_game_predictions.csv"
    )
    output_summary_json = (
        Path(args.output_summary_json).resolve()
        if args.output_summary_json
        else repo_root / "data" / "processed" / "last5seasons_evaluation_summary.json"
    )
    output_summary_csv = (
        Path(args.output_summary_csv).resolve()
        if args.output_summary_csv
        else repo_root / "data" / "processed" / "last5seasons_evaluation_by_season.csv"
    )
    output_report = (
        Path(args.output_report).resolve()
        if args.output_report
        else repo_root / "data" / "reports" / "last5seasons_evaluation_report.md"
    )

    with sqlite3.connect(sqlite_db) as con:
        dependency_status = maybe_wait_for_backtest_features(
            con=con,
            retries=max(0, int(args.dependency_retries)),
            wait_seconds=max(0, int(args.dependency_wait_seconds)),
        )
        games = load_historical_games(con)
        if not games:
            raise SystemExit("historical_games_last5 is empty; cannot evaluate.")
        prediction_rows = evaluate_games(games)
        metrics = compute_metrics(prediction_rows)
        summary_payload = {
            "evaluation_target": "historical_games_last5",
            "dependency_status": dependency_status,
            "model": {
                "type": "deterministic_walk_forward_elo_form_blend",
                "parameters": {
                    "ELO_MEAN": ELO_MEAN,
                    "ELO_REGRESSION": ELO_REGRESSION,
                    "ELO_HOME_ADVANTAGE": ELO_HOME_ADVANTAGE,
                    "ELO_K_FACTOR": ELO_K_FACTOR,
                    "FORM_WIN_PCT_ELO_WEIGHT": FORM_WIN_PCT_ELO_WEIGHT,
                    "FORM_GOAL_DIFF_ELO_WEIGHT": FORM_GOAL_DIFF_ELO_WEIGHT,
                },
            },
            **metrics,
        }

        write_csv(output_predictions_csv, prediction_rows)
        write_summary_json(output_summary_json, summary_payload)
        write_summary_csv(output_summary_csv, metrics["by_season"])
        write_report(output_report, metrics, dependency_status=dependency_status)

        if not args.skip_sqlite_write:
            write_sqlite_tables(con, prediction_rows, metrics["by_season"], metrics["overall"])

    print(f"dependency_status={dependency_status}")
    print(f"games_evaluated={len(prediction_rows)}")
    print(f"overall_accuracy={metrics['overall']['accuracy']}")
    print(f"overall_log_loss={metrics['overall']['log_loss']}")
    print(f"overall_brier_score={metrics['overall']['brier_score']}")
    print(f"predictions_csv={output_predictions_csv}")
    print(f"summary_json={output_summary_json}")
    print(f"summary_csv={output_summary_csv}")
    print(f"report={output_report}")
    if not args.skip_sqlite_write:
        print(f"sqlite_tables=last5seasons_game_predictions,last5seasons_evaluation_summary db={sqlite_db}")


if __name__ == "__main__":
    main()
