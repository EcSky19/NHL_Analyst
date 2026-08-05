"""NFL baseline and evaluation harness.

This module intentionally contains no predictive model. It establishes honest
baselines, walk-forward fold boundaries, holdout enforcement, and comparison
statistics for future NFL models.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sqlite3
import sys
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "nfl"
REPORT_DIR = ROOT / "data" / "reports"
DB_PATH = DATA_DIR / "nfl_research.db"
GAMES_CSV = DATA_DIR / "games.csv"
GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
)
HOLDOUT_UNLOCK_TOKEN = "I_UNDERSTAND_THIS_TOUCHES_NFL_HOLDOUT_ONCE"


@dataclass(frozen=True)
class Game:
    game_id: str
    season: int
    game_type: str
    week: int | None
    away_team: str
    home_team: str
    away_score: int | None
    home_score: int | None
    away_moneyline: float | None
    home_moneyline: float | None
    spread_line: float | None


@dataclass(frozen=True)
class Metric:
    label: str
    correct: int
    total: int
    skipped: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else float("nan")


def parse_number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: object) -> int | None:
    number = parse_number(value)
    if number is None:
        return None
    return int(number)


def ensure_games_csv() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if GAMES_CSV.exists() and GAMES_CSV.stat().st_size > 0:
        return
    request = urllib.request.Request(GAMES_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        GAMES_CSV.write_bytes(response.read())


def ensure_games_table() -> None:
    """Create a schema-compatible games table when a companion loader is absent."""
    ensure_games_csv()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with GAMES_CSV.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = reader.fieldnames or []

    with sqlite3.connect(DB_PATH) as conn:
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='games'"
        ).fetchone()
        if existing:
            return
        column_sql = ", ".join([f'"{column}" TEXT' for column in columns])
        conn.execute(f'CREATE TABLE games ({column_sql}, PRIMARY KEY ("game_id"))')
        placeholders = ", ".join(["?"] * len(columns))
        quoted = ", ".join([f'"{column}"' for column in columns])
        conn.executemany(
            f"INSERT OR REPLACE INTO games ({quoted}) VALUES ({placeholders})",
            [[row.get(column, "") for column in columns] for row in rows],
        )
        conn.commit()


def load_games() -> list[Game]:
    ensure_games_table()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT game_id, season, game_type, week, away_team, home_team,
                   away_score, home_score, away_moneyline, home_moneyline,
                   spread_line
            FROM games
            ORDER BY CAST(season AS INTEGER), CAST(week AS INTEGER), game_id
            """
        ).fetchall()
    games: list[Game] = []
    for row in rows:
        games.append(
            Game(
                game_id=str(row["game_id"]),
                season=int(row["season"]),
                game_type=str(row["game_type"]),
                week=parse_int(row["week"]),
                away_team=str(row["away_team"]),
                home_team=str(row["home_team"]),
                away_score=parse_int(row["away_score"]),
                home_score=parse_int(row["home_score"]),
                away_moneyline=parse_number(row["away_moneyline"]),
                home_moneyline=parse_number(row["home_moneyline"]),
                spread_line=parse_number(row["spread_line"]),
            )
        )
    return games


def is_played(game: Game) -> bool:
    return game.away_score is not None and game.home_score is not None


def winner(game: Game) -> str | None:
    if not is_played(game):
        return None
    if game.home_score == game.away_score:
        return None
    return "home" if game.home_score > game.away_score else "away"


def analysis_games(games: Iterable[Game], include_postseason: bool = False) -> list[Game]:
    postseason_types = {"POST", "WC", "DIV", "CON", "SB"}
    allowed_types = {"REG", *postseason_types} if include_postseason else {"REG"}
    return [
        game
        for game in games
        if game.game_type in allowed_types and is_played(game) and game.season < 2026
    ]


def american_implied_probability(moneyline: float) -> float:
    if moneyline < 0:
        return abs(moneyline) / (abs(moneyline) + 100.0)
    return 100.0 / (moneyline + 100.0)


def moneyline_pick(game: Game) -> str | None:
    if game.home_moneyline is None or game.away_moneyline is None:
        return None
    home_prob = american_implied_probability(game.home_moneyline)
    away_prob = american_implied_probability(game.away_moneyline)
    if math.isclose(home_prob, away_prob, abs_tol=1e-12):
        return None
    return "home" if home_prob > away_prob else "away"


def spread_pick(game: Game) -> str | None:
    if game.spread_line is None or math.isclose(game.spread_line, 0.0, abs_tol=1e-12):
        return None
    # nflverse spread_line is from the away team's perspective:
    # negative means away favored; positive means home favored.
    return "away" if game.spread_line < 0 else "home"


def score_picker(games: Iterable[Game], label: str, picker) -> Metric:
    correct = total = skipped = 0
    for game in games:
        actual = winner(game)
        pick = picker(game)
        if actual is None or pick is None:
            skipped += 1
            continue
        total += 1
        correct += int(pick == actual)
    return Metric(label, correct, total, skipped)


def wilson_interval(correct: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return (float("nan"), float("nan"))
    p = correct / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denom
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / denom
    return (center - margin, center + margin)


def format_pct(value: float) -> str:
    return "NA" if math.isnan(value) else f"{value * 100:.2f}%"


def metric_row(metric: Metric) -> list[str]:
    low, high = wilson_interval(metric.correct, metric.total)
    return [
        metric.label,
        str(metric.total),
        str(metric.correct),
        format_pct(metric.accuracy),
        f"{format_pct(low)}-{format_pct(high)}",
        str(metric.skipped),
    ]


def baseline_metrics(games: list[Game]) -> tuple[list[Metric], dict[int, list[Metric]]]:
    base_games = analysis_games(games, include_postseason=False)
    overall = [
        score_picker(base_games, "Always pick home", lambda _game: "home"),
        score_picker(base_games, "Vegas moneyline favorite", moneyline_pick),
        score_picker(base_games, "Spread-implied favorite", spread_pick),
    ]
    seasons: dict[int, list[Metric]] = {}
    for season in sorted({game.season for game in base_games}):
        season_games = [game for game in base_games if game.season == season]
        seasons[season] = [
            score_picker(season_games, "Always pick home", lambda _game: "home"),
            score_picker(season_games, "Vegas moneyline favorite", moneyline_pick),
            score_picker(season_games, "Spread-implied favorite", spread_pick),
        ]
    return overall, seasons


def completed_regular_seasons(games: list[Game]) -> list[int]:
    seasons = sorted({game.season for game in games if game.game_type == "REG" and is_played(game)})
    return [season for season in seasons if season < 2026]


def holdout_seasons(games: list[Game], count: int = 2) -> list[int]:
    seasons = completed_regular_seasons(games)
    return seasons[-count:]


def walk_forward_folds(
    games: list[Game],
    min_train_seasons: int = 5,
    include_postseason: bool = False,
    unlock_holdout: str | None = None,
) -> list[dict[str, object]]:
    seasons = completed_regular_seasons(games)
    holdouts = set(holdout_seasons(games))
    evaluation_seasons = [
        season
        for season in seasons[min_train_seasons:]
        if season not in holdouts or unlock_holdout == HOLDOUT_UNLOCK_TOKEN
    ]
    folds = []
    for test_season in evaluation_seasons:
        train_seasons = [season for season in seasons if season < test_season]
        if len(train_seasons) < min_train_seasons:
            continue
        folds.append(
            {
                "test_season": test_season,
                "train_start": min(train_seasons),
                "train_end": max(train_seasons),
                "train_seasons": train_seasons,
                "is_holdout": test_season in holdouts,
                "game_types": "REG+POST" if include_postseason else "REG",
            }
        )
    return folds


def standard_error(p: float, n: int) -> float:
    return math.sqrt(p * (1.0 - p) / n)


def min_detectable_difference(p: float, n: int) -> float:
    """Approximate 95% two-model independent-proportion difference."""
    return 1.959963984540054 * math.sqrt(2.0 * p * (1.0 - p) / n)


def noise_floor_rows(games: list[Game], p: float = 0.67) -> list[tuple[str, int, float, float]]:
    base_games = [game for game in analysis_games(games) if winner(game) is not None]
    latest = max(game.season for game in base_games)
    latest_n = sum(1 for game in base_games if game.season == latest)
    three_n = sum(1 for game in base_games if latest - 2 <= game.season <= latest)
    modern_n = sum(1 for game in base_games if 2002 <= game.season <= latest)
    rows = [
        ("One recent regular season", latest_n, standard_error(p, latest_n), min_detectable_difference(p, latest_n)),
        ("Three recent regular seasons", three_n, standard_error(p, three_n), min_detectable_difference(p, three_n)),
        ("Full 2002-present regular-season era", modern_n, standard_error(p, modern_n), min_detectable_difference(p, modern_n)),
    ]
    return rows


def write_csv_outputs(games: list[Game]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    overall, seasons = baseline_metrics(games)
    with (DATA_DIR / "baseline_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["baseline", "games", "correct", "accuracy", "wilson_95_ci", "skipped"])
        for metric in overall:
            writer.writerow(metric_row(metric))
    with (DATA_DIR / "baseline_by_season.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["season", "baseline", "games", "correct", "accuracy", "wilson_95_ci", "skipped"])
        for season, metrics in seasons.items():
            for metric in metrics:
                writer.writerow([season, *metric_row(metric)])
    with (DATA_DIR / "walk_forward_folds.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["test_season", "train_start", "train_end", "train_seasons", "is_holdout", "game_types"])
        for fold in walk_forward_folds(games):
            writer.writerow(
                [
                    fold["test_season"],
                    fold["train_start"],
                    fold["train_end"],
                    " ".join(map(str, fold["train_seasons"])),
                    fold["is_holdout"],
                    fold["game_types"],
                ]
            )


def report_markdown(games: list[Game]) -> str:
    overall, seasons = baseline_metrics(games)
    holdouts = holdout_seasons(games)
    base_games = analysis_games(games)
    ties = sum(1 for game in base_games if is_played(game) and game.home_score == game.away_score)
    excluded_future = sum(1 for game in games if game.season >= 2026 or not is_played(game))
    excluded_pre = sum(1 for game in games if game.game_type == "PRE")
    postseason_types = {"POST", "WC", "DIV", "CON", "SB"}
    excluded_post = sum(
        1 for game in games if game.game_type in postseason_types and is_played(game) and game.season < 2026
    )

    lines = [
        "# NFL baselines and evaluation methodology",
        "",
        "Generated: 2026-08-05",
        "",
        "Source: nflverse `games.csv` loaded into `data\\nfl\\nfl_research.db` table `games`. "
        "Main numbers below use played regular-season games only: preseason is excluded, postseason is held out of the main benchmark because playoff fields and incentives differ from regular-season forecasting, and 2026/future or null-score rows are excluded.",
        "",
        f"Ties are not counted as wins or losses for straight-up winner accuracy; they are reported as skipped because the prediction target is a winner. Tied regular-season games skipped: **{ties}**. Played postseason games excluded from these bars: **{excluded_post}**. Preseason rows excluded: **{excluded_pre}**. Future/unplayed rows excluded: **{excluded_future}**.",
        "",
        "## Reference bars",
        "",
        "| Baseline | Games | Correct | Accuracy | Wilson 95% CI | Skipped |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for metric in overall:
        low, high = wilson_interval(metric.correct, metric.total)
        lines.append(
            f"| {metric.label} | {metric.total:,} | {metric.correct:,} | "
            f"{format_pct(metric.accuracy)} | {format_pct(low)}-{format_pct(high)} | {metric.skipped:,} |"
        )

    lines.extend(
        [
            "",
            "The Vegas moneyline favorite is the critical bar: it is the market's own straight-up forecast. A future model must be compared to this, not to 50% or to a trivial no-skill reference.",
            "",
            "### Per-season trend",
            "",
            "| Season | Home acc. (Wilson 95% CI) | Home n | Vegas ML favorite acc. (Wilson 95% CI) | ML n / coverage | Spread favorite acc. (Wilson 95% CI) | Spread n / coverage |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for season, metrics in seasons.items():
        home, ml, spread = metrics
        season_games = len([game for game in base_games if game.season == season and winner(game) is not None])
        ml_cov = ml.total / season_games if season_games else 0.0
        spread_cov = spread.total / season_games if season_games else 0.0
        home_low, home_high = wilson_interval(home.correct, home.total)
        ml_low, ml_high = wilson_interval(ml.correct, ml.total)
        spread_low, spread_high = wilson_interval(spread.correct, spread.total)
        lines.append(
            f"| {season} | {format_pct(home.accuracy)} ({format_pct(home_low)}-{format_pct(home_high)}) | {home.total:,} | "
            f"{format_pct(ml.accuracy)} ({format_pct(ml_low)}-{format_pct(ml_high)}) | {ml.total:,} / {format_pct(ml_cov)} | "
            f"{format_pct(spread.accuracy)} ({format_pct(spread_low)}-{format_pct(spread_high)}) | {spread.total:,} / {format_pct(spread_cov)} |"
        )

    home_by_season = [metrics[0].accuracy for _, metrics in sorted(seasons.items()) if metrics[0].total]
    early_home = sum(home_by_season[:10]) / len(home_by_season[:10])
    recent_home = sum(home_by_season[-5:]) / len(home_by_season[-5:])

    lines.extend(
        [
            "",
            f"Home-field accuracy declined from an average **{format_pct(early_home)}** across the first 10 seasons in this file to **{format_pct(recent_home)}** across the latest five completed seasons. Treat home advantage as time-varying.",
            "",
            "## Realistic ceiling",
            "",
            "Published NFL models and the betting market usually land in the mid-to-high 60s for straight-up winner accuracy. Matching the closing moneyline favorite is already an excellent result; consistently beating it out of sample is very hard. A one-season result a point or two above Vegas is not a breakthrough unless it survives the holdout policy and the noise-floor thresholds below.",
            "",
            "## Evaluation harness design",
            "",
            "- Use expanding-window walk-forward validation by season: train on all prior eligible seasons and predict the next season.",
            "- Main development folds use regular season only. Postseason can be evaluated as a separately labeled stress test, never mixed into headline regular-season accuracy.",
            "- Preseason is always excluded.",
            "- Future/unplayed games and any rows with null scores are always excluded.",
            "- Ties are excluded from winner-accuracy denominators and counted as skipped.",
            f"- Strict holdout seasons are **{', '.join(map(str, holdouts))}**. The harness excludes them by default and only includes them if the caller passes the explicit unlock token `{HOLDOUT_UNLOCK_TOKEN}`.",
            "- `data\\nfl\\walk_forward_folds.csv` records the currently available non-holdout folds.",
            "- `scripts\\nfl\\evaluation_harness.py compare` reports accuracy, Wilson 95% intervals, and pairwise indistinguishability flags for future model variants.",
            "",
            "## Noise floor",
            "",
            "Approximate standard errors and minimum detectable differences below use p=67%, close to the NFL market/model ceiling. The minimum detectable difference is the 95% two-model difference threshold under an independent-proportion approximation; paired tests may be more efficient, but claims smaller than these values should be presumed noise unless independently replicated.",
            "",
            "| Sample | Games | SE | Minimum detectable difference |",
            "|---|---:|---:|---:|",
        ]
    )
    for label, n, se, mdd in noise_floor_rows(games):
        lines.append(f"| {label} | {n:,} | {se * 100:.2f} pp | {mdd * 100:.2f} pp |")

    folds = walk_forward_folds(games)
    lines.extend(
        [
            "",
            "Practical rule: a single modern NFL season needs roughly an eight-point accuracy gap before two variants are clearly separated. Three seasons still need roughly five points. Over the full 2002-present regular-season sample, differences around 1.6-1.7 pp are the smallest worth discussing statistically; smaller selected-on-test gains should be treated as noise.",
            "",
            "## Current non-holdout walk-forward folds",
            "",
            "| Test season | Train seasons | Holdout? |",
            "|---:|---|---:|",
        ]
    )
    for fold in folds:
        lines.append(
            f"| {fold['test_season']} | {fold['train_start']}-{fold['train_end']} | {fold['is_holdout']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(games: list[Game]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "nfl_baselines_and_methodology.md"
    report_path.write_text(report_markdown(games), encoding="utf-8")
    return report_path


def command_baselines(_args: argparse.Namespace) -> int:
    games = load_games()
    write_csv_outputs(games)
    report_path = write_report(games)
    overall, _ = baseline_metrics(games)
    print(f"Wrote {report_path}")
    for metric in overall:
        low, high = wilson_interval(metric.correct, metric.total)
        print(
            f"{metric.label}: {metric.correct}/{metric.total} "
            f"{format_pct(metric.accuracy)} ({format_pct(low)}-{format_pct(high)})"
        )
    return 0


def command_folds(args: argparse.Namespace) -> int:
    games = load_games()
    folds = walk_forward_folds(
        games,
        min_train_seasons=args.min_train_seasons,
        include_postseason=args.include_postseason,
        unlock_holdout=args.unlock_holdout,
    )
    holdouts = set(holdout_seasons(games))
    if holdouts and args.unlock_holdout != HOLDOUT_UNLOCK_TOKEN:
        print(f"Holdout seasons withheld: {', '.join(map(str, sorted(holdouts)))}", file=sys.stderr)
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=["test_season", "train_start", "train_end", "train_seasons", "is_holdout", "game_types"],
    )
    writer.writeheader()
    for fold in folds:
        writer.writerow({**fold, "train_seasons": " ".join(map(str, fold["train_seasons"]))})
    return 0


def read_variant_metrics(path: Path) -> dict[str, Metric]:
    """Read future model comparison CSVs.

    Accepted schemas:
    - variant,correct,total
    - variant,predicted_winner,actual_winner[,season][,game_type]
    """
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        for row in reader:
            variant = row.get("variant") or row.get("model") or "model"
            if {"correct", "total"}.issubset(fields):
                totals[variant][0] += int(float(row["correct"]))
                totals[variant][1] += int(float(row["total"]))
            elif {"predicted_winner", "actual_winner"}.issubset(fields):
                predicted = (row.get("predicted_winner") or "").strip().lower()
                actual = (row.get("actual_winner") or "").strip().lower()
                if not predicted or not actual or actual == "tie":
                    continue
                totals[variant][0] += int(predicted == actual)
                totals[variant][1] += 1
            else:
                raise ValueError(
                    "Comparison CSV must contain either variant,correct,total or "
                    "variant,predicted_winner,actual_winner"
                )
    return {variant: Metric(variant, correct, total) for variant, (correct, total) in totals.items()}


def command_compare(args: argparse.Namespace) -> int:
    metrics = read_variant_metrics(Path(args.csv_path))
    print("variant,games,correct,accuracy,wilson_95_ci")
    for metric in metrics.values():
        print(",".join(metric_row(metric)[:5]))
    names = list(metrics)
    if len(names) > 1:
        print("\npair_a,pair_b,diff_pp,threshold_pp,statistically_indistinguishable")
    for i, left_name in enumerate(names):
        for right_name in names[i + 1 :]:
            left = metrics[left_name]
            right = metrics[right_name]
            pooled = (left.correct + right.correct) / (left.total + right.total)
            threshold = 1.959963984540054 * math.sqrt(
                pooled * (1 - pooled) * (1 / left.total + 1 / right.total)
            )
            diff = abs(left.accuracy - right.accuracy)
            print(
                f"{left_name},{right_name},{diff * 100:.2f},{threshold * 100:.2f},"
                f"{diff < threshold}"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NFL baselines and honest evaluation harness.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("baselines", help="Compute baseline bars and write the methodology report.").set_defaults(
        func=command_baselines
    )
    folds = subparsers.add_parser("folds", help="Emit walk-forward folds, excluding holdout by default.")
    folds.add_argument("--min-train-seasons", type=int, default=5)
    folds.add_argument("--include-postseason", action="store_true")
    folds.add_argument("--unlock-holdout", default=None)
    folds.set_defaults(func=command_folds)
    compare = subparsers.add_parser("compare", help="Compare future model variants with Wilson CIs.")
    compare.add_argument("csv_path")
    compare.set_defaults(func=command_compare)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
