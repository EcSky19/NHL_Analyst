"""Train and evaluate NHL live win-probability experiments.

The frozen serving interface only supplies the six features emitted by
``build_features``.  This script may transform them inside an sklearn model,
but it must not add serving-time inputs.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss as sklearn_log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, SplineTransformer, StandardScaler

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.live_winprob import (  # noqa: E402
    FEATURE_NAMES,
    GameState,
    artifact_path,
    baseline_leader,
    baseline_normal,
    brier_score,
    build_features,
    calibration_table,
    log_loss,
    max_calibration_gap,
)

DB_PATH = ROOT / "data" / "live_wp" / "nhl_snapshots.db"
TRAIN_SEASONS = ["2024-25"]
TEST_SEASONS = ["2025-26"]
ROUND1_BRIER = 0.175683
ROUND1_LOG_LOSS = 0.517337


def load_rows() -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT s.game_id, s.season, g.game_date, s.period, s.frac_remaining, s.margin,
                   s.home_won, s.espn_home_wp
            FROM snapshots s
            JOIN games g ON g.game_id = s.game_id
            WHERE g.status = 'final'
            ORDER BY s.season, g.game_date, s.game_id, s.id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def state(row: dict[str, Any]) -> GameState:
    period = int(row["period"])
    return GameState(
        league="nhl",
        margin=int(row["margin"]),
        frac_remaining=float(row["frac_remaining"]),
        period=period,
        is_overtime=period > 3,
    )


def matrix(rows: list[dict[str, Any]], feature_names: list[str] | tuple[str, ...] = FEATURE_NAMES) -> tuple[np.ndarray, np.ndarray]:
    x = []
    y = []
    for row in rows:
        feats = build_features(state(row))
        x.append([feats[name] for name in feature_names])
        y.append(int(row["home_won"]))
    return np.asarray(x, dtype=float), np.asarray(y, dtype=int)


def metric_block(probs: list[float] | np.ndarray, outcomes: list[int] | np.ndarray) -> dict[str, float]:
    probs_list = [float(p) for p in probs]
    outcomes_list = [int(y) for y in outcomes]
    return {
        "n": len(probs_list),
        "brier": round(brier_score(probs_list, outcomes_list), 6),
        "log_loss": round(log_loss(probs_list, outcomes_list), 6),
    }


def fit_normal_baseline(rows: list[dict[str, Any]]) -> tuple[float, float]:
    outcomes = [int(r["home_won"]) for r in rows]
    margins = np.asarray([float(r["margin"]) for r in rows], dtype=float)
    fracs = np.asarray([float(r["frac_remaining"]) for r in rows], dtype=float)
    y = np.asarray(outcomes, dtype=float)
    best = (float("inf"), 0.0, 1.0)
    for mu in np.linspace(-0.6, 0.6, 49):
        for sigma in np.linspace(0.8, 4.0, 65):
            probs = normal_probs(margins, fracs, float(mu), float(sigma))
            clipped = np.clip(probs, 1e-15, 1 - 1e-15)
            loss = float(np.mean(-(y * np.log(clipped) + (1 - y) * np.log(1 - clipped))))
            if loss < best[0]:
                best = (loss, float(mu), float(sigma))
    return best[1], best[2]


def normal_probs(margins: np.ndarray, fracs: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    probs = np.empty_like(fracs, dtype=float)
    no_time = fracs <= 1e-6
    probs[no_time] = np.where(margins[no_time] > 0, 1.0, np.where(margins[no_time] < 0, 0.0, 0.5))
    active = ~no_time
    z = (margins[active] + mu * fracs[active]) / (sigma * np.sqrt(fracs[active]))
    probs[active] = norm_cdf(z)
    return probs


def norm_cdf(x: np.ndarray) -> np.ndarray:
    """Fast vectorized standard Normal CDF approximation."""
    sign = np.where(x < 0, -1.0, 1.0)
    ax = np.abs(x) / np.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * ax)
    erf = 1.0 - (
        (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592)
        * t
        * np.exp(-(ax * ax))
    )
    return 0.5 * (1.0 + sign * erf)


def split_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    train_rows = [r for r in rows if str(r["season"]) in TRAIN_SEASONS]
    test_rows = [r for r in rows if str(r["season"]) in TEST_SEASONS]
    train_games_seen = set()
    train_games = []
    for row in train_rows:
        game_id = str(row["game_id"])
        if game_id not in train_games_seen:
            train_games_seen.add(game_id)
            train_games.append((str(row["game_date"]), game_id))
    train_games = sorted(train_games)
    cut = int(len(train_games) * 0.8)
    fit_games = {game_id for _, game_id in train_games[:cut]}
    validation_games = {game_id for _, game_id in train_games[cut:]}
    fit_rows = [r for r in train_rows if str(r["game_id"]) in fit_games]
    validation_rows = [r for r in train_rows if str(r["game_id"]) in validation_games]
    return fit_rows, validation_rows, test_rows


def candidates() -> dict[str, Any]:
    spline_features = ColumnTransformer(
        [
            ("margin_spline", SplineTransformer(n_knots=7, degree=3, include_bias=False, extrapolation="constant"), [0]),
            ("scaled_spline", SplineTransformer(n_knots=7, degree=3, include_bias=False, extrapolation="constant"), [1]),
            ("frac_spline", SplineTransformer(n_knots=6, degree=3, include_bias=False, extrapolation="constant"), [2]),
            ("rest", "passthrough", [3, 4, 5]),
        ]
    )
    return {
        "poly2_logreg": Pipeline(
            [
                ("poly", PolynomialFeatures(degree=2, include_bias=False)),
                ("scale", StandardScaler()),
                ("logreg", LogisticRegression(max_iter=1000, C=0.2, random_state=42)),
            ]
        ),
        "poly3_logreg": Pipeline(
            [
                ("poly", PolynomialFeatures(degree=3, include_bias=False)),
                ("scale", StandardScaler()),
                ("logreg", LogisticRegression(max_iter=2000, C=0.05, random_state=42)),
            ]
        ),
        "spline_logreg": Pipeline(
            [
                ("spline", spline_features),
                ("interactions", PolynomialFeatures(degree=2, include_bias=False, interaction_only=True)),
                ("scale", StandardScaler()),
                ("logreg", LogisticRegression(max_iter=3000, C=0.05, random_state=42)),
            ]
        ),
        "hgb_depth3": HistGradientBoostingClassifier(
            max_iter=250,
            learning_rate=0.05,
            max_depth=3,
            min_samples_leaf=50,
            l2_regularization=0.02,
            monotonic_cst=[1, 1, 0, 0, 0, 0],
            early_stopping=False,
            random_state=43,
        ),
        "extra_trees": ExtraTreesClassifier(
            n_estimators=300,
            min_samples_leaf=100,
            max_features=1.0,
            random_state=42,
            n_jobs=-1,
        ),
    }


def validation_experiments(fit_rows: list[dict[str, Any]], validation_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Any, str]:
    x_fit, y_fit = matrix(fit_rows)
    x_val, y_val = matrix(validation_rows)
    results = []
    fitted: dict[str, Any] = {}
    for name, model in candidates().items():
        model.fit(x_fit, y_fit)
        probs = np.clip(model.predict_proba(x_val)[:, 1], 1e-15, 1 - 1e-15)
        tied = x_val[:, 0] == 0
        row = {
            "name": name,
            "brier": round(float(brier_score_loss(y_val, probs)), 6),
            "log_loss": round(float(sklearn_log_loss(y_val, probs)), 6),
            "tied_brier": round(float(brier_score_loss(y_val[tied], probs[tied])), 6),
            "tied_log_loss": round(float(sklearn_log_loss(y_val[tied], probs[tied])), 6),
            "tied_mean_pred": round(float(np.mean(probs[tied])), 6),
            "tied_actual": round(float(np.mean(y_val[tied])), 6),
        }
        results.append(row)
        fitted[name] = model

    best_name = min(results, key=lambda item: (item["log_loss"], item["brier"]))["name"]
    calibrator = CalibratedClassifierCV(FrozenEstimator(fitted[best_name]), method="isotonic")
    calibrator.fit(x_val, y_val)
    calibrated_probs = np.clip(calibrator.predict_proba(x_val)[:, 1], 1e-15, 1 - 1e-15)
    tied = x_val[:, 0] == 0
    results.append(
        {
            "name": f"{best_name}_isotonic_calibrated_on_validation",
            "brier": round(float(brier_score_loss(y_val, calibrated_probs)), 6),
            "log_loss": round(float(sklearn_log_loss(y_val, calibrated_probs)), 6),
            "tied_brier": round(float(brier_score_loss(y_val[tied], calibrated_probs[tied])), 6),
            "tied_log_loss": round(float(sklearn_log_loss(y_val[tied], calibrated_probs[tied])), 6),
            "tied_mean_pred": round(float(np.mean(calibrated_probs[tied])), 6),
            "tied_actual": round(float(np.mean(y_val[tied])), 6),
            "calibration_note": "Calibration transform is fit on this validation split; held-out test is the honest score.",
        }
    )
    return results, calibrator, f"{best_name}_isotonic_calibrated_on_validation"


def evaluate(rows: list[dict[str, Any]], probs: list[float], normal_params: tuple[float, float]) -> dict[str, Any]:
    outcomes = [int(r["home_won"]) for r in rows]
    leader = [baseline_leader(state(r)) for r in rows]
    constant = [0.5 for _ in rows]
    normal = [baseline_normal(state(r), *normal_params) for r in rows]
    espn_pairs = [(float(r["espn_home_wp"]), int(r["home_won"])) for r in rows if r["espn_home_wp"] is not None]

    phases: dict[str, Any] = {}
    buckets = [
        ("1.00-0.75", 0.75, 1.000001),
        ("0.75-0.50", 0.50, 0.75),
        ("0.50-0.25", 0.25, 0.50),
        ("0.25-0.00", -0.000001, 0.25),
    ]
    for name, lo, hi in buckets:
        idx = [i for i, r in enumerate(rows) if lo <= float(r["frac_remaining"]) < hi]
        phases[name] = metric_block([probs[i] for i in idx], [outcomes[i] for i in idx])

    tied_idx = [i for i, r in enumerate(rows) if int(r["margin"]) == 0]
    tied_probs = [probs[i] for i in tied_idx]
    tied_outcomes = [outcomes[i] for i in tied_idx]

    out: dict[str, Any] = {
        "model": metric_block(probs, outcomes),
        "baselines": {
            "leader": metric_block(leader, outcomes),
            "constant_0_5": metric_block(constant, outcomes),
            "normal": {
                **metric_block(normal, outcomes),
                "mu": round(normal_params[0], 4),
                "sigma": round(normal_params[1], 4),
            },
        },
        "espn_benchmark": {
            "available": bool(espn_pairs),
            "coverage": len(espn_pairs),
        },
        "calibration_table": calibration_table(probs, outcomes),
        "max_calibration_gap": round(max_calibration_gap(probs, outcomes), 6),
        "phase_breakdown": phases,
        "tied_states": {
            **metric_block(tied_probs, tied_outcomes),
            "mean_pred": round(float(np.mean(tied_probs)), 6),
            "actual": round(float(np.mean(tied_outcomes)), 6),
        },
    }
    if espn_pairs:
        espn_probs = [p for p, _ in espn_pairs]
        espn_outcomes = [y for _, y in espn_pairs]
        out["espn_benchmark"].update(metric_block(espn_probs, espn_outcomes))
    return out


def sanity_checks(model: Any) -> dict[str, float | bool]:
    def p(margin: int, frac: float, period: int = 2, ot: bool = False) -> float:
        gs = GameState("nhl", margin=margin, frac_remaining=frac, period=period, is_overtime=ot)
        feats = build_features(gs)
        return float(model.predict_proba([[feats[name] for name in FEATURE_NAMES]])[0][1])

    checks = {
        "puck_drop_tied": p(0, 1.0, 1),
        "home_down_1_mid": p(-1, 0.5, 2),
        "tied_mid": p(0, 0.5, 2),
        "home_up_1_mid": p(1, 0.5, 2),
        "home_up_1_early": p(1, 0.8, 1),
        "home_up_1_late": p(1, 0.05, 3),
        "ot_tied": p(0, 0.0, 4, True),
    }
    rounded: dict[str, float | bool] = {key: round(value, 4) for key, value in checks.items()}
    rounded.update(
        {
            "margin_monotonic_mid": checks["home_down_1_mid"] < checks["tied_mid"] < checks["home_up_1_mid"],
            "same_lead_more_valuable_late": checks["home_up_1_late"] > checks["home_up_1_early"],
            "late_one_goal_not_near_certain": checks["home_up_1_late"] < 0.98,
            "edge_states_finite_open_interval": all(np.isfinite(v) and 0.0 < v < 1.0 for v in checks.values()),
        }
    )
    return rounded


def fresh_serving_check() -> dict[str, Any]:
    code = (
        "from app.services.live_winprob import GameState, predict_home_win_prob; "
        "p, m = predict_home_win_prob(GameState(league='nhl', margin=1, frac_remaining=0.2)); "
        "print({'prob': round(float(p), 6), 'available': bool(m.get('available'))})"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True, text=True)
    return {"command": "fresh python live_winprob check", "output": proc.stdout.strip()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", default="")
    args = parser.parse_args()

    rows = load_rows()
    if not rows:
        raise SystemExit(f"No snapshots found in {DB_PATH}; run harvest_nhl.py first.")
    train_rows = [r for r in rows if str(r["season"]) in TRAIN_SEASONS]
    test_rows = [r for r in rows if str(r["season"]) in TEST_SEASONS]
    if not train_rows or not test_rows:
        raise SystemExit(f"Expected train={TRAIN_SEASONS}, test={TEST_SEASONS}; found {sorted({r['season'] for r in rows})}")
    train_games = {str(r["game_id"]) for r in train_rows}
    test_games = {str(r["game_id"]) for r in test_rows}
    overlap = train_games & test_games
    if overlap:
        raise SystemExit(f"Game-level split violation: {len(overlap)} games in both train and test")

    fit_rows, validation_rows, _ = split_rows(rows)
    validation_results, model, selected_name = validation_experiments(fit_rows, validation_rows)
    _, y_test = matrix(test_rows)
    x_test, _ = matrix(test_rows)
    probs = [float(p) for p in model.predict_proba(x_test)[:, 1]]
    normal_params = fit_normal_baseline(train_rows)
    test_eval = evaluate(test_rows, probs, normal_params)
    sanity = sanity_checks(model)
    improved = test_eval["model"]["brier"] < ROUND1_BRIER and test_eval["model"]["log_loss"] < ROUND1_LOG_LOSS

    validation = {
        **test_eval,
        "selected_model": selected_name,
        "approaches_tried_on_train_validation": validation_results,
        "round1_artifact": {"brier": ROUND1_BRIER, "log_loss": ROUND1_LOG_LOSS, "tied_brier": 0.250887},
        "split": {
            "type": "fixed_game_level_holdout_by_season_with_train_only_chrono_validation",
            "train_seasons": TRAIN_SEASONS,
            "test_seasons": TEST_SEASONS,
            "fit_games_inside_train": len({str(r["game_id"]) for r in fit_rows}),
            "validation_games_inside_train": len({str(r["game_id"]) for r in validation_rows}),
            "train_games": len(train_games),
            "test_games": len(test_games),
            "fit_snapshots_inside_train": len(fit_rows),
            "validation_snapshots_inside_train": len(validation_rows),
            "train_snapshots": len(train_rows),
            "test_snapshots": len(test_rows),
            "game_overlap": len(overlap),
        },
        "sanity_checks": sanity,
        "artifact_overwritten": improved,
    }

    bundle = {
        "model": model,
        "feature_names": FEATURE_NAMES,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_games": len(train_games | test_games),
        "n_snapshots": len(rows),
        "brier": test_eval["model"]["brier"],
        "log_loss": test_eval["model"]["log_loss"],
        "validation": validation,
        "train_seasons": TRAIN_SEASONS,
        "test_seasons": TEST_SEASONS,
        "notes": {
            "selection": "Model approaches were selected using only a chronological game-level validation split carved from 2024-25.",
            "espn_wp": "ESPN publishes no NHL win-probability curve in this harvest; espn_home_wp coverage is 0.",
        },
    }

    out_path = artifact_path("nhl")
    if improved:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, out_path)
        validation["serving_check"] = fresh_serving_check()
        joblib.dump(bundle, out_path)
        print(f"Saved improved artifact to {out_path}")
    else:
        validation["serving_check_existing_artifact"] = fresh_serving_check()
        print(
            "Selected model did not beat the round-1 artifact on held-out 2025-26; "
            f"left {out_path} unchanged."
        )

    if args.write_report:
        report_path = Path(args.write_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(validation, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(validation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
