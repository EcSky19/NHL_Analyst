import argparse
import csv
import json
import math
import sqlite3
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Tuple


MODEL_VERSION = "weighted_win_model_v1"
SEASON_BLEND = 0.5
RECENT_BLEND_MAX = 0.22
PRIOR_BLEND = 0.33
LOGIT_TEMPERATURE = 1.8
LOGIT_DIFF_SHRINK = 0.6
HOME_ADVANTAGE_LOGIT = 0.18
LOCATION_POINTS_WEIGHT = 0.65
LOCATION_GOAL_DIFF_WEIGHT = 0.35


SEASON_FEATURE_WEIGHTS = {
    "off_goals_per_game": 1.15,
    "def_goals_against_per_game": -1.25,
    "def_save_pct_5v5": 1.05,
    "player_goalie_save_pct_weighted": 0.95,
    "st_special_teams_index": 0.9,
    "puck_sat_pct": 0.75,
    "off_shooting_pct_5v5": 0.7,
    "pressure_avg_shots_needed_per_goal": -0.35,
    "puck_faceoff_win_pct": 0.25,
    "puck_takeaways": 0.2,
    "puck_giveaways": -0.2,
    "player_top_scorer_points_share": -0.15,
}

RECENT_FEATURE_WEIGHTS = {
    "l10_points_pct": 1.05,
    "l10_goal_diff_per_game": 0.9,
    "trend_points_pct_l10_minus_season": 0.7,
    "trend_goal_diff_pg_l10_minus_season": 0.65,
    "streak_signed": 0.55,
}


def normalize_team_code(value: str) -> str:
    return (value or "").strip().lower()


def to_float(value: Optional[str]) -> Optional[float]:
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def logit(prob: float) -> float:
    p = safe_clip(prob, 1e-4, 1.0 - 1e-4)
    return math.log(p / (1.0 - p))


def percentile(sorted_values: List[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = (len(sorted_values) - 1) * pct
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_values[lo]
    frac = idx - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def population_std(values: List[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def robust_stats(values: List[float]) -> Tuple[float, float]:
    if not values:
        return 0.0, 1.0
    sorted_vals = sorted(values)
    med = median(sorted_vals)
    q1 = percentile(sorted_vals, 0.25)
    q3 = percentile(sorted_vals, 0.75)
    iqr = q3 - q1
    iqr_scale = iqr / 1.349 if iqr > 0 else 0.0
    stdev = population_std(sorted_vals)
    scale = max(iqr_scale, stdev * 0.5, 1e-6)
    return med, scale


def zscore(value: float, med: float, scale: float) -> float:
    return safe_clip((value - med) / scale, -3.0, 3.0)


def load_team_base(path: Path) -> Dict[str, Dict[str, Optional[float]]]:
    profiles: Dict[str, Dict[str, Optional[float]]] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            team_code = normalize_team_code(row["team_abbreviation"])
            profile: Dict[str, Optional[float]] = {"team_code": team_code, "team_name": row.get("team_name", team_code)}
            for feature in SEASON_FEATURE_WEIGHTS:
                profile[feature] = to_float(row.get(feature))
            goals_for_pg = to_float(row.get("off_goals_per_game")) or 0.0
            goals_against_pg = to_float(row.get("def_goals_against_per_game")) or 0.0
            gf_sq = goals_for_pg * goals_for_pg
            ga_sq = goals_against_pg * goals_against_pg
            pythag_points = gf_sq / (gf_sq + ga_sq) if (gf_sq + ga_sq) > 0 else 0.5
            profile["points_pct_prior"] = safe_clip(pythag_points, 0.1, 0.9)
            profile["goal_diff_per_game"] = goals_for_pg - goals_against_pg
            profile["games_played"] = to_float(row.get("games_played")) or 0.0
            profiles[team_code] = profile
    return profiles


def add_recent_record(
    team_recent: Dict[str, Dict[str, List[float]]],
    team_code: str,
    row: Dict[str, str],
    prefix: str,
) -> None:
    rec = team_recent.setdefault(team_code, {})
    keys = [
        "l10_points_pct",
        "l10_goal_diff_per_game",
        "trend_points_pct_l10_minus_season",
        "trend_goal_diff_pg_l10_minus_season",
        "streak_signed",
        "home_points_pct",
        "road_points_pct",
        "home_goal_diff_per_game",
        "road_goal_diff_per_game",
        "points_pct",
    ]
    for key in keys:
        value = to_float(row.get(f"{prefix}_{key}"))
        if value is None:
            continue
        rec.setdefault(key, []).append(value)


def load_matchups_and_recent(path: Path) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, Optional[float]]]]:
    rows: List[Dict[str, str]] = []
    team_recent_raw: Dict[str, Dict[str, List[float]]] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            add_recent_record(team_recent_raw, normalize_team_code(row["home_team_abbrev"]), row, "home")
            add_recent_record(team_recent_raw, normalize_team_code(row["away_team_abbrev"]), row, "away")

    team_recent: Dict[str, Dict[str, Optional[float]]] = {}
    for team_code, feature_map in team_recent_raw.items():
        team_recent[team_code] = {}
        for feature, values in feature_map.items():
            team_recent[team_code][feature] = sum(values) / len(values) if values else None
    return rows, team_recent


def merge_profiles(
    team_profiles: Dict[str, Dict[str, Optional[float]]], team_recent: Dict[str, Dict[str, Optional[float]]]
) -> Dict[str, Dict[str, Optional[float]]]:
    for team_code, profile in team_profiles.items():
        rec = team_recent.get(team_code, {})
        for feature in RECENT_FEATURE_WEIGHTS:
            profile[feature] = rec.get(feature)
        season_points = rec.get("points_pct")
        if season_points is not None:
            profile["points_pct_prior"] = safe_clip(float(season_points), 0.05, 0.95)
        else:
            profile["points_pct_prior"] = safe_clip(float(profile["points_pct_prior"] or 0.5), 0.05, 0.95)

        base_goal_diff = float(profile.get("goal_diff_per_game") or 0.0)
        points_prior = float(profile.get("points_pct_prior") or 0.5)
        profile["home_points_pct"] = (
            rec.get("home_points_pct") if rec.get("home_points_pct") is not None else safe_clip(points_prior + 0.04, 0.05, 0.95)
        )
        profile["road_points_pct"] = (
            rec.get("road_points_pct") if rec.get("road_points_pct") is not None else safe_clip(points_prior - 0.04, 0.05, 0.95)
        )
        profile["home_goal_diff_per_game"] = (
            rec.get("home_goal_diff_per_game")
            if rec.get("home_goal_diff_per_game") is not None
            else base_goal_diff + 0.12
        )
        profile["road_goal_diff_per_game"] = (
            rec.get("road_goal_diff_per_game")
            if rec.get("road_goal_diff_per_game") is not None
            else base_goal_diff - 0.12
        )
    return team_profiles


def build_feature_stats(
    team_profiles: Dict[str, Dict[str, Optional[float]]],
) -> Dict[str, Dict[str, float]]:
    feature_stats: Dict[str, Dict[str, float]] = {}
    all_features = list(SEASON_FEATURE_WEIGHTS.keys()) + list(RECENT_FEATURE_WEIGHTS.keys())
    for feature in all_features:
        values = [float(p[feature]) for p in team_profiles.values() if p.get(feature) is not None]
        med, scale = robust_stats(values)
        feature_stats[feature] = {"median": med, "scale": scale}
    return feature_stats


def feature_value(profile: Dict[str, Optional[float]], feature: str, feature_stats: Dict[str, Dict[str, float]]) -> float:
    raw = profile.get(feature)
    if raw is None:
        raw = feature_stats[feature]["median"]
    return float(raw)


def compute_team_strengths(
    team_profiles: Dict[str, Dict[str, Optional[float]]],
    feature_stats: Dict[str, Dict[str, float]],
) -> Dict[str, Dict[str, float]]:
    strengths: Dict[str, Dict[str, float]] = {}
    for team_code, profile in team_profiles.items():
        season_score = 0.0
        for feature, weight in SEASON_FEATURE_WEIGHTS.items():
            value = feature_value(profile, feature, feature_stats)
            stat = feature_stats[feature]
            season_score += weight * zscore(value, stat["median"], stat["scale"])

        recent_score = 0.0
        recent_present = 0
        for feature, weight in RECENT_FEATURE_WEIGHTS.items():
            raw = profile.get(feature)
            if raw is not None:
                recent_present += 1
            value = feature_value(profile, feature, feature_stats)
            stat = feature_stats[feature]
            recent_score += weight * zscore(value, stat["median"], stat["scale"])

        recent_coverage = recent_present / max(len(RECENT_FEATURE_WEIGHTS), 1)
        recent_blend = RECENT_BLEND_MAX * recent_coverage
        prior = logit(float(profile["points_pct_prior"]))
        strength = (SEASON_BLEND * season_score) + (recent_blend * recent_score) + (PRIOR_BLEND * prior)
        strengths[team_code] = {
            "season_score": season_score,
            "recent_score": recent_score,
            "recent_coverage": recent_coverage,
            "prior_logit": prior,
            "strength": strength,
        }
    return strengths


def location_adjustment(team_a: Dict[str, Optional[float]], team_b: Dict[str, Optional[float]], location: str) -> float:
    if location == "neutral":
        return 0.0

    if location == "home":
        edge_points = float(team_a["home_points_pct"]) - float(team_b["road_points_pct"])
        edge_goal = float(team_a["home_goal_diff_per_game"]) - float(team_b["road_goal_diff_per_game"])
        base = HOME_ADVANTAGE_LOGIT
    else:
        edge_points = float(team_a["road_points_pct"]) - float(team_b["home_points_pct"])
        edge_goal = float(team_a["road_goal_diff_per_game"]) - float(team_b["home_goal_diff_per_game"])
        base = -HOME_ADVANTAGE_LOGIT

    return base + (LOCATION_POINTS_WEIGHT * edge_points) + (LOCATION_GOAL_DIFF_WEIGHT * edge_goal)


def predict_probability(
    team_a: str,
    team_b: str,
    location: str,
    team_profiles: Dict[str, Dict[str, Optional[float]]],
    strengths: Dict[str, Dict[str, float]],
) -> Dict[str, float]:
    a = normalize_team_code(team_a)
    b = normalize_team_code(team_b)
    if a not in team_profiles or b not in team_profiles:
        raise KeyError(f"Unknown team code(s): {team_a}, {team_b}")

    base_diff = strengths[a]["strength"] - strengths[b]["strength"]
    loc_adj = location_adjustment(team_profiles[a], team_profiles[b], location)
    model_diff = (base_diff + loc_adj) * LOGIT_DIFF_SHRINK
    p_a_wins = sigmoid(model_diff / LOGIT_TEMPERATURE)
    confidence = abs(p_a_wins - 0.5) * 2.0
    return {
        "team_a_win_probability": p_a_wins,
        "team_b_win_probability": 1.0 - p_a_wins,
        "base_strength_diff": base_diff,
        "location_adjustment": loc_adj,
        "logit_diff": model_diff,
        "confidence_index_0_to_1": confidence,
    }


def confidence_bucket(confidence: float) -> str:
    if confidence >= 0.5:
        return "high"
    if confidence >= 0.3:
        return "medium"
    return "low"


def create_matchup_predictions(
    matchup_rows: List[Dict[str, str]],
    team_profiles: Dict[str, Dict[str, Optional[float]]],
    strengths: Dict[str, Dict[str, float]],
) -> List[Dict[str, object]]:
    preds: List[Dict[str, object]] = []
    for row in matchup_rows:
        home = normalize_team_code(row["home_team_abbrev"])
        away = normalize_team_code(row["away_team_abbrev"])
        location = "neutral" if row.get("is_neutral_site") == "1" else "home"
        pred = predict_probability(home, away, location, team_profiles, strengths)
        preds.append(
            {
                "model_version": MODEL_VERSION,
                "matchup_key": row.get("matchup_key"),
                "game_id": row.get("game_id"),
                "game_date_utc": row.get("game_date_utc"),
                "is_neutral_site": int(row.get("is_neutral_site") or 0),
                "home_team_abbrev": home.upper(),
                "away_team_abbrev": away.upper(),
                "home_win_probability": round(pred["team_a_win_probability"], 6),
                "away_win_probability": round(pred["team_b_win_probability"], 6),
                "strength_diff_home_minus_away": round(pred["base_strength_diff"], 6),
                "location_adjustment_home": round(pred["location_adjustment"], 6),
                "logit_diff_home_minus_away": round(pred["logit_diff"], 6),
                "confidence_index": round(pred["confidence_index_0_to_1"], 6),
                "confidence_bucket": confidence_bucket(pred["confidence_index_0_to_1"]),
            }
        )

    preds.sort(key=lambda r: ((r["game_date_utc"] or ""), (r["matchup_key"] or "")))
    return preds


def write_predictions_csv(preds: List[Dict[str, object]], output_csv: Path) -> None:
    if not preds:
        return
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(preds[0].keys()))
        writer.writeheader()
        writer.writerows(preds)


def write_predictions_sqlite(preds: List[Dict[str, object]], sqlite_db: Path, table_name: str) -> None:
    if not preds:
        return
    with sqlite3.connect(sqlite_db) as con:
        cur = con.cursor()
        cur.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        cur.execute(
            f"""
            CREATE TABLE "{table_name}" (
                model_version TEXT,
                matchup_key TEXT,
                game_id TEXT,
                game_date_utc TEXT,
                is_neutral_site INTEGER,
                home_team_abbrev TEXT,
                away_team_abbrev TEXT,
                home_win_probability REAL,
                away_win_probability REAL,
                strength_diff_home_minus_away REAL,
                location_adjustment_home REAL,
                logit_diff_home_minus_away REAL,
                confidence_index REAL,
                confidence_bucket TEXT
            )
            """
        )
        columns = list(preds[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        quoted_cols = ", ".join([f'"{c}"' for c in columns])
        sql = f'INSERT INTO "{table_name}" ({quoted_cols}) VALUES ({placeholders})'
        cur.executemany(sql, [[row[c] for c in columns] for row in preds])
        con.commit()


def pearson_corr(x_vals: List[float], y_vals: List[float]) -> float:
    if len(x_vals) != len(y_vals) or len(x_vals) <= 1:
        return 0.0
    x_mean = sum(x_vals) / len(x_vals)
    y_mean = sum(y_vals) / len(y_vals)
    x_var = sum((x - x_mean) ** 2 for x in x_vals)
    y_var = sum((y - y_mean) ** 2 for y in y_vals)
    if x_var <= 0 or y_var <= 0:
        return 0.0
    cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
    return cov / math.sqrt(x_var * y_var)


def write_summary(
    summary_path: Path,
    team_profiles: Dict[str, Dict[str, Optional[float]]],
    strengths: Dict[str, Dict[str, float]],
    preds: List[Dict[str, object]],
) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    ranked = sorted(
        [(team, scores["strength"], team_profiles[team]["team_name"]) for team, scores in strengths.items()],
        key=lambda x: x[1],
        reverse=True,
    )
    top5 = ranked[:5]
    bottom5 = ranked[-5:]
    p_home = [float(p["home_win_probability"]) for p in preds] if preds else []
    avg_home = sum(p_home) / len(p_home) if p_home else 0.0
    avg_conf = sum(abs(p - 0.5) for p in p_home) / len(p_home) if p_home else 0.0

    point_priors = [float(team_profiles[t]["points_pct_prior"]) for t in strengths]
    strength_vals = [float(strengths[t]["strength"]) for t in strengths]
    corr = pearson_corr(point_priors, strength_vals)

    lines = [
        "# Weighted Win Model Fit Summary",
        "",
        f"- Model version: `{MODEL_VERSION}`",
        f"- Teams scored: {len(strengths)}",
        f"- Matchup predictions generated: {len(preds)}",
        "",
        "## Method",
        "- Deterministic weighted rating model with logistic transform.",
        "- High-signal metrics use larger absolute weights: goal scoring/prevention rates, goalie save performance, special teams, shot share, recent form, and streak.",
        "- Volatile or sparse metrics are down-weighted (e.g., faceoff %, turnover-like counts, top-scorer share, pressure-rate proxy).",
        "- Missing values are imputed with league medians per feature, then robustly scaled (median + IQR-based scale), with z-scores clipped to reduce outlier instability.",
        "- Team priors are blended via logit(points_pct) proxy and recent-form impact is coverage-aware to avoid overreacting when context is sparse.",
        "- Home/away effect is explicit: base home-ice logit bonus plus home-vs-road points and goal-differential edge terms.",
        "",
        "## Stability and confidence notes",
        f"- Pearson correlation between blended team strengths and points priors: {corr:.3f}",
        f"- Mean predicted home win probability (scheduled games): {avg_home:.3f}",
        f"- Mean confidence distance from 50/50: {avg_conf:.3f}",
        "- No direct historical game-result labels are currently used in this fit, so calibration confidence is limited and probabilities should be treated as directional likelihoods.",
        "",
        "## Top 5 team strengths",
    ]
    lines.extend([f"- {name} ({team.upper()}): {score:.3f}" for team, score, name in top5])
    lines.extend(["", "## Bottom 5 team strengths"])
    lines.extend([f"- {name} ({team.upper()}): {score:.3f}" for team, score, name in bottom5])
    lines.extend(
        [
            "",
            "## Artifacts",
            "- `scripts\\train_weighted_win_model.py`",
            "- `data\\processed\\weighted_win_model_config.json`",
            "- `data\\processed\\weighted_win_predictions.csv`",
            "- SQLite table `weighted_win_predictions` in `data\\processed\\nhl_research.db`",
        ]
    )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_model_config(config_path: Path, feature_stats: Dict[str, Dict[str, float]]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_version": MODEL_VERSION,
        "constants": {
            "season_blend": SEASON_BLEND,
            "recent_blend_max": RECENT_BLEND_MAX,
            "prior_blend": PRIOR_BLEND,
            "logit_temperature": LOGIT_TEMPERATURE,
            "logit_diff_shrink": LOGIT_DIFF_SHRINK,
            "home_advantage_logit": HOME_ADVANTAGE_LOGIT,
            "location_points_weight": LOCATION_POINTS_WEIGHT,
            "location_goal_diff_weight": LOCATION_GOAL_DIFF_WEIGHT,
        },
        "season_feature_weights": SEASON_FEATURE_WEIGHTS,
        "recent_feature_weights": RECENT_FEATURE_WEIGHTS,
        "feature_stats": feature_stats,
        "notes": {
            "high_signal_examples": [
                "off_goals_per_game",
                "def_goals_against_per_game",
                "def_save_pct_5v5",
                "player_goalie_save_pct_weighted",
                "st_special_teams_index",
                "l10_points_pct",
                "streak_signed",
            ],
            "light_signal_examples": [
                "puck_faceoff_win_pct",
                "puck_takeaways",
                "puck_giveaways",
                "player_top_scorer_points_share",
                "pressure_avg_shots_needed_per_goal",
            ],
            "missing_value_strategy": "Per-feature median imputation, deterministic.",
        },
    }
    config_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train deterministic weighted NHL win-likelihood model and generate predictions.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--team-features", default=None, help="Defaults to data\\processed\\team_feature_base.csv")
    parser.add_argument("--matchup-features", default=None, help="Defaults to data\\processed\\matchup_context_features.csv")
    parser.add_argument("--output-config", default=None, help="Defaults to data\\processed\\weighted_win_model_config.json")
    parser.add_argument("--output-predictions-csv", default=None, help="Defaults to data\\processed\\weighted_win_predictions.csv")
    parser.add_argument("--sqlite-db", default=None, help="Defaults to data\\processed\\nhl_research.db")
    parser.add_argument("--sqlite-table", default="weighted_win_predictions")
    parser.add_argument("--summary-path", default=None, help="Defaults to data\\reports\\weighted_win_model_summary.md")
    parser.add_argument("--skip-sqlite", action="store_true")
    parser.add_argument("--team-a", default=None, help="Optional team A abbrev (e.g., BOS)")
    parser.add_argument("--team-b", default=None, help="Optional team B abbrev (e.g., NYR)")
    parser.add_argument("--location", choices=["home", "away", "neutral"], default="neutral")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    team_features = Path(args.team_features).resolve() if args.team_features else repo_root / "data" / "processed" / "team_feature_base.csv"
    matchup_features = (
        Path(args.matchup_features).resolve()
        if args.matchup_features
        else repo_root / "data" / "processed" / "matchup_context_features.csv"
    )
    output_config = (
        Path(args.output_config).resolve()
        if args.output_config
        else repo_root / "data" / "processed" / "weighted_win_model_config.json"
    )
    output_predictions_csv = (
        Path(args.output_predictions_csv).resolve()
        if args.output_predictions_csv
        else repo_root / "data" / "processed" / "weighted_win_predictions.csv"
    )
    sqlite_db = Path(args.sqlite_db).resolve() if args.sqlite_db else repo_root / "data" / "processed" / "nhl_research.db"
    summary_path = Path(args.summary_path).resolve() if args.summary_path else repo_root / "data" / "reports" / "weighted_win_model_summary.md"

    team_profiles = load_team_base(team_features)
    matchup_rows, team_recent = load_matchups_and_recent(matchup_features)
    team_profiles = merge_profiles(team_profiles, team_recent)
    feature_stats = build_feature_stats(team_profiles)
    strengths = compute_team_strengths(team_profiles, feature_stats)

    preds = create_matchup_predictions(matchup_rows, team_profiles, strengths)
    write_predictions_csv(preds, output_predictions_csv)
    if not args.skip_sqlite:
        write_predictions_sqlite(preds, sqlite_db, args.sqlite_table)
    write_model_config(output_config, feature_stats)
    write_summary(summary_path, team_profiles, strengths, preds)

    print(f"model_version={MODEL_VERSION}")
    print(f"teams_scored={len(strengths)}")
    print(f"scheduled_matchups_predicted={len(preds)}")
    print(f"config={output_config}")
    print(f"predictions_csv={output_predictions_csv}")
    if not args.skip_sqlite:
        print(f"sqlite_table={args.sqlite_table} db={sqlite_db}")
    print(f"summary={summary_path}")

    if args.team_a and args.team_b:
        single = predict_probability(args.team_a, args.team_b, args.location, team_profiles, strengths)
        print(
            json.dumps(
                {
                    "team_a": args.team_a.upper(),
                    "team_b": args.team_b.upper(),
                    "location_relative_to_team_a": args.location,
                    **{k: round(v, 6) for k, v in single.items()},
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
