import argparse
import csv
import json
import sqlite3
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from train_weighted_win_model import (
    LOCATION_GOAL_DIFF_WEIGHT,
    LOCATION_POINTS_WEIGHT,
    MODEL_VERSION,
    HOME_ADVANTAGE_LOGIT,
    build_feature_stats,
    compute_team_strengths,
    confidence_bucket,
    load_matchups_and_recent,
    load_team_base,
    merge_profiles,
    normalize_team_code,
    predict_probability,
)


def load_model_context(repo_root: Path) -> Tuple[Dict[str, Dict[str, Optional[float]]], Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
    team_features = repo_root / "data" / "processed" / "team_feature_base.csv"
    matchup_features = repo_root / "data" / "processed" / "matchup_context_features.csv"
    team_profiles = load_team_base(team_features)
    _, team_recent = load_matchups_and_recent(matchup_features)
    team_profiles = merge_profiles(team_profiles, team_recent)
    feature_stats = build_feature_stats(team_profiles)
    strengths = compute_team_strengths(team_profiles, feature_stats)
    return team_profiles, feature_stats, strengths


def apply_streak_adjustments(
    team_profiles: Dict[str, Dict[str, Optional[float]]],
    home_team: str,
    away_team: str,
    home_streak_adjust: float,
    away_streak_adjust: float,
) -> Dict[str, Dict[str, Optional[float]]]:
    adjusted = {team: dict(profile) for team, profile in team_profiles.items()}
    for team_code, adjustment in ((home_team, home_streak_adjust), (away_team, away_streak_adjust)):
        current = float(adjusted[team_code].get("streak_signed") or 0.0)
        adjusted[team_code]["streak_signed"] = current + adjustment
    return adjusted


def _normalize_team_text(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def resolve_team_identifier(team_input: str, team_profiles: Dict[str, Dict[str, Optional[float]]]) -> str:
    normalized_code = normalize_team_code(team_input)
    if normalized_code in team_profiles:
        return normalized_code

    target = _normalize_team_text(team_input)
    for code, profile in team_profiles.items():
        if target == _normalize_team_text(str(profile.get("team_name") or "")):
            return code

    if target:
        prefix_matches = [
            code
            for code, profile in team_profiles.items()
            if _normalize_team_text(str(profile.get("team_name") or "")).startswith(target)
        ]
        if len(prefix_matches) == 1:
            return prefix_matches[0]

    known = sorted(
        [f"{code.upper()} ({str(profile.get('team_name') or code.upper())})" for code, profile in team_profiles.items()]
    )
    raise KeyError(f"Unknown team input(s). Got: {team_input}. Known teams: {', '.join(known)}")


def predict_matchup(
    home_team: str,
    away_team: str,
    location_override: str,
    home_streak_adjust: float,
    away_streak_adjust: float,
    team_profiles: Dict[str, Dict[str, Optional[float]]],
    feature_stats: Dict[str, Dict[str, float]],
) -> Dict[str, object]:
    home_code = resolve_team_identifier(home_team, team_profiles)
    away_code = resolve_team_identifier(away_team, team_profiles)

    adjusted_profiles = apply_streak_adjustments(team_profiles, home_code, away_code, home_streak_adjust, away_streak_adjust)
    strengths = compute_team_strengths(adjusted_profiles, feature_stats)
    pred = predict_probability(home_code, away_code, location_override, adjusted_profiles, strengths)

    home_base_streak = float(team_profiles[home_code].get("streak_signed") or 0.0)
    away_base_streak = float(team_profiles[away_code].get("streak_signed") or 0.0)
    confidence = float(pred["confidence_index_0_to_1"])
    return {
        "model_version": MODEL_VERSION,
        "home_team": home_code.upper(),
        "away_team": away_code.upper(),
        "location_relative_to_home_team": location_override,
        "home_streak_base": round(home_base_streak, 4),
        "away_streak_base": round(away_base_streak, 4),
        "home_streak_adjustment": round(home_streak_adjust, 4),
        "away_streak_adjustment": round(away_streak_adjust, 4),
        "home_streak_applied": round(home_base_streak + home_streak_adjust, 4),
        "away_streak_applied": round(away_base_streak + away_streak_adjust, 4),
        "home_win_probability": round(float(pred["team_a_win_probability"]), 6),
        "away_win_probability": round(float(pred["team_b_win_probability"]), 6),
        "strength_diff_home_minus_away": round(float(pred["base_strength_diff"]), 6),
        "location_adjustment_home": round(float(pred["location_adjustment"]), 6),
        "logit_diff_home_minus_away": round(float(pred["logit_diff"]), 6),
        "confidence_index": round(confidence, 6),
        "confidence_bucket": confidence_bucket(confidence),
    }


def read_baseline_predictions(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_examples(
    baseline_predictions: List[Dict[str, str]],
    team_profiles: Dict[str, Dict[str, Optional[float]]],
    feature_stats: Dict[str, Dict[str, float]],
    count: int,
) -> List[Dict[str, object]]:
    examples: List[Dict[str, object]] = []
    for i, row in enumerate(baseline_predictions[:count], start=1):
        location = "neutral" if int(row.get("is_neutral_site") or 0) == 1 else "home"
        examples.append(
            {
                "example_id": f"baseline_{i:02d}",
                "source": "weighted_win_predictions",
                "matchup_key": row.get("matchup_key", ""),
                "home_team": row["home_team_abbrev"],
                "away_team": row["away_team_abbrev"],
                "location_relative_to_home_team": location,
                "home_streak_adjustment": 0.0,
                "away_streak_adjustment": 0.0,
                "home_win_probability": float(row["home_win_probability"]),
                "away_win_probability": float(row["away_win_probability"]),
                "confidence_index": float(row["confidence_index"]),
                "confidence_bucket": row["confidence_bucket"],
            }
        )

    if baseline_predictions:
        demo = baseline_predictions[0]
        demo_pred = predict_matchup(
            home_team=demo["home_team_abbrev"],
            away_team=demo["away_team_abbrev"],
            location_override=("neutral" if int(demo.get("is_neutral_site") or 0) == 1 else "home"),
            home_streak_adjust=2.0,
            away_streak_adjust=-2.0,
            team_profiles=team_profiles,
            feature_stats=feature_stats,
        )
        examples.append(
            {
                "example_id": "streak_demo_plus2_minus2",
                "source": "interactive_override",
                "matchup_key": demo.get("matchup_key", ""),
                "home_team": demo["home_team_abbrev"],
                "away_team": demo["away_team_abbrev"],
                "location_relative_to_home_team": demo_pred["location_relative_to_home_team"],
                "home_streak_adjustment": demo_pred["home_streak_adjustment"],
                "away_streak_adjustment": demo_pred["away_streak_adjustment"],
                "home_win_probability": demo_pred["home_win_probability"],
                "away_win_probability": demo_pred["away_win_probability"],
                "confidence_index": demo_pred["confidence_index"],
                "confidence_bucket": demo_pred["confidence_bucket"],
            }
        )
    return examples


def write_examples_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_examples_sqlite(sqlite_db: Path, table_name: str, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    with sqlite3.connect(sqlite_db) as con:
        cur = con.cursor()
        cur.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        cur.execute(
            f"""
            CREATE TABLE "{table_name}" (
                example_id TEXT,
                source TEXT,
                matchup_key TEXT,
                home_team TEXT,
                away_team TEXT,
                location_relative_to_home_team TEXT,
                home_streak_adjustment REAL,
                away_streak_adjustment REAL,
                home_win_probability REAL,
                away_win_probability REAL,
                confidence_index REAL,
                confidence_bucket TEXT
            )
            """
        )
        columns = list(rows[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        quoted_cols = ", ".join([f'"{c}"' for c in columns])
        sql = f'INSERT INTO "{table_name}" ({quoted_cols}) VALUES ({placeholders})'
        cur.executemany(sql, [[row[c] for c in columns] for row in rows])
        con.commit()


def build_weight_summary(config: Dict[str, object]) -> Tuple[List[str], List[str]]:
    season_weights = dict(config.get("season_feature_weights", {}))
    recent_weights = dict(config.get("recent_feature_weights", {}))
    merged: Dict[str, float] = {}
    merged.update({k: float(v) for k, v in season_weights.items()})
    merged.update({k: float(v) for k, v in recent_weights.items()})
    heavy = sorted([f"{k} ({v:+.2f})" for k, v in merged.items() if abs(v) >= 0.9])
    light = sorted([f"{k} ({v:+.2f})" for k, v in merged.items() if abs(v) <= 0.35])
    return heavy, light


def write_report(report_path: Path, config: Dict[str, object], examples: List[Dict[str, object]]) -> None:
    constants = dict(config.get("constants", {}))
    heavy, light = build_weight_summary(config)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Weighted Win Prediction Guide",
        "",
        f"- Model version: `{config.get('model_version', MODEL_VERSION)}`",
        "- Purpose: estimate home-vs-away win likelihood using weighted team quality, recent trend/streak context, and location edge.",
        "",
        "## Final weighting scheme and rationale",
        "- Heavy features (high impact, stronger signal):",
    ]
    lines.extend([f"  - {item}" for item in heavy] or ["  - (none)"])
    lines.extend(
        [
            "- Light features (kept but intentionally down-weighted due to volatility/sparsity):",
        ]
    )
    lines.extend([f"  - {item}" for item in light] or ["  - (none)"])
    lines.extend(
        [
            "- Rationale: scoring/defense/save%, special teams, and short-horizon form carry more stable predictive value than noisier puck-battle or concentrated-player share proxies.",
            "",
            "## Streak and location application",
            "- Streak is a signed recent-form feature (`streak_signed`) in the recent component; optional CLI adjustments add directly to each team's streak before scoring.",
            f"- Location adjustment uses: base_home_ice={float(constants.get('home_advantage_logit', HOME_ADVANTAGE_LOGIT)):.2f}, points_edge_weight={float(constants.get('location_points_weight', LOCATION_POINTS_WEIGHT)):.2f}, goal_diff_edge_weight={float(constants.get('location_goal_diff_weight', LOCATION_GOAL_DIFF_WEIGHT)):.2f}.",
            "- Location override options:",
            "  - `home`: listed home team keeps home-ice context (default)",
            "  - `away`: listed home team treated as away (away team gets home-like edge)",
            "  - `neutral`: removes location edge terms",
            "",
            "## Example predictions",
        ]
    )
    for row in examples:
        lines.append(
            f"- {row['example_id']}: {row['home_team']} vs {row['away_team']} ({row['location_relative_to_home_team']}), "
            f"home={float(row['home_win_probability']):.3f}, away={float(row['away_win_probability']):.3f}, "
            f"confidence={float(row['confidence_index']):.3f} ({row['confidence_bucket']})"
        )
    lines.extend(
        [
            "",
            "## Confidence interpretation and limitations",
            "- Confidence index is distance from 50/50; it is directional certainty, not guaranteed calibration.",
            "- Use low-confidence outputs as coin-flip tiers; treat medium/high as stronger lean, not certainty.",
            "- Model is deterministic and feature-based; it does not ingest game-day injuries/line changes unless upstream features are refreshed.",
            "- Best practice: re-run upstream feature and training scripts before production use when new data arrives.",
            "",
            "## Reproducibility",
            "- Rebuild these artifacts with:",
            "  - `python scripts\\weighted_win_predictor.py --build-artifacts`",
            "",
            "## Artifact outputs",
            "- `scripts\\weighted_win_predictor.py`",
            "- `data\\processed\\matchup_predictions_examples.csv`",
            "- SQLite table `matchup_predictions_examples` in `data\\processed\\nhl_research.db`",
            f"- `{report_path.relative_to(report_path.parents[2]).as_posix().replace('/', '\\')}`",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive weighted win predictor and artifact generator.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--home-team", default=None, help="Home team abbreviation/code or full name, e.g. BOS or Boston Bruins")
    parser.add_argument("--away-team", default=None, help="Away team abbreviation/code or full name, e.g. NYR or New York Rangers")
    parser.add_argument("--home-streak-adjust", type=float, default=0.0, help="Optional additive adjustment to home streak.")
    parser.add_argument("--away-streak-adjust", type=float, default=0.0, help="Optional additive adjustment to away streak.")
    parser.add_argument("--location-override", choices=["home", "away", "neutral"], default="home")
    parser.add_argument("--build-artifacts", action="store_true", help="Create report + examples CSV + examples SQLite table.")
    parser.add_argument("--examples-count", type=int, default=5)
    parser.add_argument("--predictions-csv", default=None, help="Defaults to data\\processed\\weighted_win_predictions.csv")
    parser.add_argument("--examples-csv", default=None, help="Defaults to data\\processed\\matchup_predictions_examples.csv")
    parser.add_argument("--report-path", default=None, help="Defaults to data\\reports\\weighted_win_prediction_guide.md")
    parser.add_argument("--config-path", default=None, help="Defaults to data\\processed\\weighted_win_model_config.json")
    parser.add_argument("--sqlite-db", default=None, help="Defaults to data\\processed\\nhl_research.db")
    parser.add_argument("--examples-table", default="matchup_predictions_examples")
    parser.add_argument("--skip-sqlite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    predictions_csv = (
        Path(args.predictions_csv).resolve()
        if args.predictions_csv
        else repo_root / "data" / "processed" / "weighted_win_predictions.csv"
    )
    config_path = (
        Path(args.config_path).resolve()
        if args.config_path
        else repo_root / "data" / "processed" / "weighted_win_model_config.json"
    )
    examples_csv = (
        Path(args.examples_csv).resolve()
        if args.examples_csv
        else repo_root / "data" / "processed" / "matchup_predictions_examples.csv"
    )
    report_path = (
        Path(args.report_path).resolve()
        if args.report_path
        else repo_root / "data" / "reports" / "weighted_win_prediction_guide.md"
    )
    sqlite_db = Path(args.sqlite_db).resolve() if args.sqlite_db else repo_root / "data" / "processed" / "nhl_research.db"

    team_profiles, feature_stats, _ = load_model_context(repo_root)

    if args.home_team and args.away_team:
        output = predict_matchup(
            home_team=args.home_team,
            away_team=args.away_team,
            location_override=args.location_override,
            home_streak_adjust=args.home_streak_adjust,
            away_streak_adjust=args.away_streak_adjust,
            team_profiles=team_profiles,
            feature_stats=feature_stats,
        )
        print(json.dumps(output, sort_keys=True))

    if args.build_artifacts:
        baseline_predictions = read_baseline_predictions(predictions_csv)
        examples = build_examples(baseline_predictions, team_profiles, feature_stats, max(args.examples_count, 5))
        write_examples_csv(examples_csv, examples)
        if not args.skip_sqlite:
            write_examples_sqlite(sqlite_db, args.examples_table, examples)

        model_config = json.loads(config_path.read_text(encoding="utf-8"))
        write_report(report_path, model_config, examples)
        print(f"examples_csv={examples_csv}")
        if not args.skip_sqlite:
            print(f"examples_table={args.examples_table} db={sqlite_db}")
        print(f"report={report_path}")

    if not (args.build_artifacts or (args.home_team and args.away_team)):
        raise SystemExit("Provide --home-team/--away-team for prediction and/or --build-artifacts to generate deliverables.")


if __name__ == "__main__":
    main()
