from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, SplineTransformer, StandardScaler

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.live_winprob import (
    GameState,
    artifact_path,
    baseline_leader,
    baseline_normal,
    brier_score,
    build_features,
    calibration_table,
    log_loss,
    max_calibration_gap,
    predict_home_win_prob,
)

DB_PATH = ROOT / "data" / "live_wp" / "nfl_snapshots.db"
NORMAL_MU = 0.0
NORMAL_SIGMA = 13.5
ROUND1_BRIER = 0.166640
ROUND1_LOG_LOSS = 0.490719


@dataclass(frozen=True)
class Candidate:
    name: str
    feature_names: list[str]
    build: Callable[[], Any]
    calibration: str | None = None


def rows() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    out = [dict(r) for r in conn.execute("SELECT * FROM snapshots ORDER BY season, game_id, frac_remaining DESC")]
    conn.close()
    if not out:
        raise SystemExit(f"No snapshots found in {DB_PATH}. Run harvest_nfl.py first.")
    return out


def game_state(row: dict) -> GameState:
    return GameState(
        league="nfl",
        margin=int(row["margin"]),
        frac_remaining=float(row["frac_remaining"]),
        period=int(row["period"]),
        is_overtime=int(row["period"]) > 4,
    )


def matrix(data: list[dict], feature_names: list[str]) -> list[list[float]]:
    out = []
    for row in data:
        feats = build_features(game_state(row))
        out.append([feats[name] for name in feature_names])
    return out


def outcomes(data: list[dict]) -> list[int]:
    return [int(r["home_won"]) for r in data]


def model_probs(model: Any, data: list[dict], feature_names: list[str]) -> list[float]:
    return [float(p) for p in model.predict_proba(matrix(data, feature_names))[:, 1]]


def metric_block(probs: list[float], ys: list[int]) -> dict[str, float]:
    return {
        "brier": round(brier_score(probs, ys), 6),
        "log_loss": round(log_loss(probs, ys), 6),
    }


def games_by_date(data: list[dict]) -> list[str]:
    seen = set()
    games = []
    for row in sorted(data, key=lambda r: (r.get("game_date") or "", r["game_id"])):
        if row["game_id"] not in seen:
            seen.add(row["game_id"])
            games.append(row["game_id"])
    return games


def development_split(train: list[dict]) -> tuple[list[dict], list[dict], list[dict], dict[str, Any]]:
    games = games_by_date(train)
    fit_cut = int(len(games) * 0.70)
    cal_cut = int(len(games) * 0.80)
    fit_games = set(games[:fit_cut])
    calibration_games = set(games[fit_cut:cal_cut])
    validation_games = set(games[cal_cut:])
    fit = [r for r in train if r["game_id"] in fit_games]
    calibration = [r for r in train if r["game_id"] in calibration_games]
    validation = [r for r in train if r["game_id"] in validation_games]
    return fit, calibration, validation, {
        "split": "2023 game-level chronological development split",
        "fit_games": len(fit_games),
        "fit_snapshots": len(fit),
        "calibration_games": len(calibration_games),
        "calibration_snapshots": len(calibration),
        "validation_games": len(validation_games),
        "validation_snapshots": len(validation),
    }


def fit_candidate(candidate: Candidate, fit: list[dict], calibration: list[dict] | None = None) -> Any:
    model = candidate.build()
    model.fit(matrix(fit, candidate.feature_names), outcomes(fit))
    if candidate.calibration is None:
        return model
    if not calibration:
        raise ValueError(f"{candidate.name} requested calibration but no calibration data was supplied")
    calibrated = CalibratedClassifierCV(FrozenEstimator(model), method=candidate.calibration)
    calibrated.fit(matrix(calibration, candidate.feature_names), outcomes(calibration))
    return calibrated


def score_model(model: Any, data: list[dict], feature_names: list[str]) -> dict[str, Any]:
    ys = outcomes(data)
    probs = model_probs(model, data, feature_names)
    return {
        **metric_block(probs, ys),
        "max_calibration_gap": round(max_calibration_gap(probs, ys, bins=10, min_n=30), 6),
        "calibration_table": calibration_table(probs, ys, bins=10),
    }


def predict_state(model: Any, feature_names: list[str], margin: int, frac_remaining: float) -> float:
    feats = build_features(GameState(league="nfl", margin=margin, frac_remaining=frac_remaining))
    return float(model.predict_proba([[feats[name] for name in feature_names]])[0][1])


def sanity_checks(model: Any, feature_names: list[str]) -> dict[str, Any]:
    margin_probs = {str(m): round(predict_state(model, feature_names, m, 0.5), 6) for m in (-14, -7, 0, 7, 14)}
    early_plus_7 = predict_state(model, feature_names, 7, 0.8)
    late_plus_7 = predict_state(model, feature_names, 7, 0.2)
    edge_probs = {
        "kickoff_tied": predict_state(model, feature_names, 0, 1.0),
        "end_regulation_tied": predict_state(model, feature_names, 0, 0.0),
        "end_regulation_home_plus_14": predict_state(model, feature_names, 14, 0.0),
        "end_regulation_home_minus_14": predict_state(model, feature_names, -14, 0.0),
    }
    strict_inside = all(0.0 < p < 1.0 for p in [*margin_probs.values(), early_plus_7, late_plus_7, *edge_probs.values()])
    finite = all(p == p and abs(p) != float("inf") for p in [*margin_probs.values(), early_plus_7, late_plus_7, *edge_probs.values()])
    margin_values = [margin_probs[str(m)] for m in (-14, -7, 0, 7, 14)]
    return {
        "probabilities": {
            "margin_at_half_remaining": margin_probs,
            "home_plus_7_80pct_remaining": round(early_plus_7, 6),
            "home_plus_7_20pct_remaining": round(late_plus_7, 6),
            **{k: round(v, 6) for k, v in edge_probs.items()},
        },
        "passed": {
            "probability_increases_with_home_margin": all(
                margin_values[i] < margin_values[i + 1] for i in range(len(margin_values) - 1)
            ),
            "same_lead_worth_more_late": late_plus_7 > early_plus_7,
            "strictly_inside_0_1": strict_inside,
            "finite_edge_states": finite,
        },
    }


def phase_breakdown(model: Any, data: list[dict], feature_names: list[str]) -> dict[str, Any]:
    ys = outcomes(data)
    probs = model_probs(model, data, feature_names)
    states = [game_state(r) for r in data]
    normal_probs = [baseline_normal(s, NORMAL_MU, NORMAL_SIGMA) for s in states]
    leader_probs = [baseline_leader(s) for s in states]
    buckets = [
        ("1.00-0.75", 0.75, 1.000001),
        ("0.75-0.50", 0.50, 0.75),
        ("0.50-0.25", 0.25, 0.50),
        ("0.25-0.00", -0.000001, 0.25),
    ]
    out = {}
    for name, lo, hi in buckets:
        idx = [i for i, r in enumerate(data) if lo < float(r["frac_remaining"]) <= hi]
        espn_idx = [i for i in idx if data[i]["espn_home_wp"] is not None]
        out[name] = {
            "n": len(idx),
            "model": metric_block([probs[i] for i in idx], [ys[i] for i in idx]),
            "normal": metric_block([normal_probs[i] for i in idx], [ys[i] for i in idx]),
            "leader": metric_block([leader_probs[i] for i in idx], [ys[i] for i in idx]),
            "constant_0_5": metric_block([0.5 for _ in idx], [ys[i] for i in idx]),
            "espn": metric_block([float(data[i]["espn_home_wp"]) for i in espn_idx], [ys[i] for i in espn_idx]),
        }
    return out


def evaluate(model: Any, data: list[dict], feature_names: list[str]) -> dict[str, Any]:
    ys = outcomes(data)
    probs = model_probs(model, data, feature_names)
    states = [game_state(r) for r in data]
    normal_probs = [baseline_normal(s, NORMAL_MU, NORMAL_SIGMA) for s in states]
    leader_probs = [baseline_leader(s) for s in states]
    espn_rows = [(float(r["espn_home_wp"]), int(r["home_won"])) for r in data if r["espn_home_wp"] is not None]
    return {
        "model": metric_block(probs, ys),
        "baselines": {
            "round1_current_artifact": {"brier": ROUND1_BRIER, "log_loss": ROUND1_LOG_LOSS},
            "normal_mu_0_sigma_13_5": metric_block(normal_probs, ys),
            "espn_home_wp": {
                **metric_block([p for p, _ in espn_rows], [y for _, y in espn_rows]),
                "coverage": f"{len(espn_rows)}/{len(data)}",
            },
            "leader": metric_block(leader_probs, ys),
            "constant_0_5": metric_block([0.5 for _ in data], ys),
        },
        "calibration_table": calibration_table(probs, ys, bins=10),
        "max_calibration_gap": round(max_calibration_gap(probs, ys, bins=10, min_n=30), 6),
        "phase_breakdown": phase_breakdown(model, data, feature_names),
        "sanity_checks": sanity_checks(model, feature_names),
    }


def candidates() -> list[Candidate]:
    return [
        Candidate(
            "round1_logistic_margin",
            ["margin", "margin_scaled"],
            lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=10.0, solver="lbfgs")),
        ),
        Candidate(
            "logistic_add_frac_remaining",
            ["margin", "margin_scaled", "frac_remaining"],
            lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=10.0, solver="lbfgs")),
        ),
        Candidate(
            "poly3_logistic_margin_time",
            ["margin", "margin_scaled", "frac_remaining"],
            lambda: make_pipeline(
                StandardScaler(),
                PolynomialFeatures(degree=3, include_bias=False),
                StandardScaler(),
                LogisticRegression(max_iter=5000, C=0.1, solver="lbfgs"),
            ),
        ),
        Candidate(
            "spline_logistic_margin_time",
            ["margin", "frac_remaining"],
            lambda: make_pipeline(
                SplineTransformer(n_knots=8, degree=3, include_bias=False),
                StandardScaler(),
                LogisticRegression(max_iter=5000, C=3.0, solver="lbfgs"),
            ),
        ),
        Candidate(
            "monotonic_hist_gradient_boosting",
            ["margin", "margin_scaled", "frac_remaining", "is_overtime"],
            lambda: HistGradientBoostingClassifier(
                max_iter=150,
                learning_rate=0.02,
                max_leaf_nodes=5,
                min_samples_leaf=500,
                l2_regularization=1.0,
                monotonic_cst=[1, 1, 0, 0],
                early_stopping=False,
                random_state=1,
            ),
        ),
        Candidate(
            "calibrated_hgb_sigmoid",
            ["margin", "margin_scaled", "frac_remaining", "is_overtime"],
            lambda: HistGradientBoostingClassifier(
                max_iter=250,
                learning_rate=0.035,
                max_leaf_nodes=15,
                min_samples_leaf=80,
                l2_regularization=0.05,
                early_stopping=False,
                random_state=1,
            ),
            calibration="sigmoid",
        ),
    ]


def main() -> None:
    data = rows()
    train = [r for r in data if int(r["season"]) == 2023]
    test = [r for r in data if int(r["season"]) == 2024]
    if not train or not test:
        raise SystemExit("Expected fixed NFL split with 2023 train and 2024 test seasons.")

    fit, calibration, validation_rows, dev_protocol = development_split(train)
    experiment_results = []
    full_train_models = []
    for candidate in candidates():
        model = fit_candidate(candidate, fit, calibration)
        validation = score_model(model, validation_rows, candidate.feature_names)
        dev_sanity = sanity_checks(model, candidate.feature_names)
        full_model = fit_candidate(candidate, train, calibration if candidate.calibration else None)
        full_sanity = sanity_checks(full_model, candidate.feature_names)
        rejected_reason = None
        if not all(dev_sanity["passed"].values()):
            rejected_reason = "failed development-split sanity checks"
        elif not all(full_sanity["passed"].values()):
            rejected_reason = "failed full-train sanity checks before test evaluation"
        experiment_results.append(
            {
                "name": candidate.name,
                "feature_names": candidate.feature_names,
                "calibration": candidate.calibration,
                "validation": validation,
                "development_sanity": dev_sanity,
                "full_train_sanity": full_sanity,
                "rejected_reason": rejected_reason,
            }
        )
        if rejected_reason is None:
            full_train_models.append((candidate, full_model, validation))

    if not full_train_models:
        raise SystemExit("No candidate passed sanity checks.")

    # Round 1's largest weakness was calibration. Select on validation calibration
    # gap first, then Brier/log loss, without looking at the 2024 holdout.
    selected_candidate, selected_model, selected_validation = min(
        full_train_models,
        key=lambda item: (
            item[2]["max_calibration_gap"],
            item[2]["brier"],
            item[2]["log_loss"],
        ),
    )
    final = evaluate(selected_model, test, selected_candidate.feature_names)
    better_than_round1 = (
        final["model"]["brier"] < ROUND1_BRIER
        and final["model"]["log_loss"] < ROUND1_LOG_LOSS
        and all(final["sanity_checks"]["passed"].values())
    )

    bundle = {
        "model": selected_model,
        "feature_names": selected_candidate.feature_names,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_games": len({r["game_id"] for r in data}),
        "n_snapshots": len(data),
        "brier": final["model"]["brier"],
        "log_loss": final["model"]["log_loss"],
        "train_seasons": [2023],
        "test_seasons": [2024],
        "validation": {
            **final,
            "selected_model": selected_candidate.name,
            "selected_validation": selected_validation,
            "experiments": experiment_results,
            "protocol": {
                "split": "fixed game-level chronological holdout: train 2023, test 2024",
                "train_games": len({r["game_id"] for r in train}),
                "train_snapshots": len(train),
                "test_games": len({r["game_id"] for r in test}),
                "test_snapshots": len(test),
                "train_seasons": [2023],
                "test_seasons": [2024],
                "development": dev_protocol,
                "normal_baseline": {"mu": NORMAL_MU, "sigma": NORMAL_SIGMA},
            },
        },
        "notes": (
            "NFL round-2 live WP selected using only a 2023 game-level development split. "
            "The 2024 season remained a held-out final evaluation. ESPN WP is benchmark-only."
        ),
    }

    saved = False
    path = artifact_path("nfl")
    if better_than_round1:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, path)
        saved = True

    print(json.dumps(bundle["validation"], indent=2, sort_keys=True))
    print(f"selected={selected_candidate.name}")
    print(f"better_than_round1={better_than_round1}")
    print(f"saved={saved} path={path}")
    if saved:
        prob, meta = predict_home_win_prob(GameState(league="nfl", margin=7, frac_remaining=0.2))
        print(f"same_process_serving_check_margin7_frac0.2={prob} available={meta.get('available')}")


if __name__ == "__main__":
    main()
