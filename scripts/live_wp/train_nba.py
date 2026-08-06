"""Train, validate, and honestly evaluate the NBA live win-probability model.

The frozen serving layer accepts only features produced by
``app.services.live_winprob.build_features``. This script may choose a subset of
those features and may save any scikit-learn estimator/Pipeline that implements
``predict_proba``.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss as sklearn_log_loss
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, SplineTransformer, StandardScaler

from app.services.live_winprob import (
    FEATURE_NAMES,
    GameState,
    artifact_path,
    baseline_leader,
    baseline_normal,
    build_features,
    calibration_table,
    max_calibration_gap,
)

DB_PATH = ROOT / "data" / "live_wp" / "nba_snapshots.db"
CURRENT_REFERENCE = {
    "name": "published_current_artifact",
    "brier": 0.167947,
    "log_loss": 0.491963,
    "max_calibration_gap": 0.0656,
    "defect_home_plus_10_2min": 0.9980,
}
ESPN_REFERENCE = {"name": "espn_published_curve", "brier": 0.157319, "log_loss": 0.462902}
NORMAL_REFERENCE = {"name": "analytic_normal_reference", "brier": 0.166237, "log_loss": 0.509335}
DEFECT_FRAC = 120 / 2880
DEFECT_MAX_PROB = 0.98

CORE_FEATURES = ["margin", "margin_scaled", "frac_remaining", "is_overtime"]
ALL_FEATURES = list(FEATURE_NAMES)


@dataclass(frozen=True)
class Candidate:
    name: str
    feature_names: list[str]
    model: object
    description: str


class LogitBlendModel:
    """Blend a monotone HGB model with a smooth logistic model in logit space.

    The estimator expects columns ``[margin, margin_scaled, frac_remaining,
    is_overtime]``. Both submodels are monotone non-decreasing in margin on the
    grids used here, and a non-negative logit-space blend preserves that order.
    """

    def __init__(self, hgb_weight: float = 0.4, seed: int = 20260805) -> None:
        self.hgb_weight = float(hgb_weight)
        self.seed = int(seed)
        self.classes_ = np.array([0, 1])

    def fit(self, X, y):
        arr = np.asarray(X, dtype=float)
        self.hgb_ = HistGradientBoostingClassifier(
            max_iter=200,
            learning_rate=0.05,
            l2_regularization=0.1,
            max_leaf_nodes=31,
            min_samples_leaf=80,
            random_state=self.seed,
            monotonic_cst=[1, 1, -1, 0],
        )
        self.lr_ = Pipeline(
            [
                ("scale", StandardScaler()),
                ("lr", LogisticRegression(max_iter=3000, C=1.0, solver="lbfgs")),
            ]
        )
        self.hgb_.fit(arr, y)
        self.lr_.fit(arr[:, :2], y)
        return self

    def predict_proba(self, X) -> np.ndarray:
        arr = np.asarray(X, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        hgb = self.hgb_.predict_proba(arr)[:, 1]
        smooth = self.lr_.predict_proba(arr[:, :2])[:, 1]
        home = _inv_logit(self.hgb_weight * _logit(hgb) + (1.0 - self.hgb_weight) * _logit(smooth))
        home = np.clip(home, 1e-6, 1.0 - 1e-6)
        return np.column_stack([1.0 - home, home])


# If this script is executed directly and a blend ever passes the shipping gate,
# store an importable module path in the pickle so fresh-process serving can load it.
sys.modules.setdefault("scripts.live_wp.train_nba", sys.modules[__name__])
LogitBlendModel.__module__ = "scripts.live_wp.train_nba"


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1.0 - 1e-6)
    return np.log(p / (1.0 - p))


def _inv_logit(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def rows_from_db() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            s.game_id, g.game_date, g.season_start_year, s.seq, s.period,
            s.frac_remaining, s.margin, s.home_won, s.espn_home_wp
        FROM snapshots s
        JOIN games g ON g.game_id = s.game_id
        WHERE g.n_snapshots > 0
        ORDER BY g.game_date, s.game_id, s.seq
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def state_for(row: dict) -> GameState:
    period = int(row["period"])
    return GameState(
        league="nba",
        margin=int(row["margin"]),
        frac_remaining=float(row["frac_remaining"]),
        period=period,
        is_overtime=period > 4,
    )


def matrix(rows: list[dict], feature_names: list[str]) -> np.ndarray:
    return np.asarray([[build_features(state_for(r))[name] for name in feature_names] for r in rows], dtype=float)


def labels(rows: Iterable[dict]) -> np.ndarray:
    return np.asarray([int(r["home_won"]) for r in rows], dtype=int)


def metric_row(name: str, probs: np.ndarray | list[float], y: np.ndarray | list[int]) -> dict:
    p = np.asarray(probs, dtype=float)
    yy = np.asarray(y, dtype=int)
    return {
        "name": name,
        "n": int(len(p)),
        "brier": float(brier_score_loss(yy, p)),
        "log_loss": float(sklearn_log_loss(yy, np.clip(p, 1e-15, 1 - 1e-15))),
    }


def game_outcomes(rows: list[dict]) -> dict[str, int]:
    outcomes: dict[str, int] = {}
    for row in rows:
        outcomes[str(row["game_id"])] = int(row["home_won"])
    return outcomes


def validation_split(train_rows: list[dict], seed: int) -> tuple[set[str], set[str]]:
    outcomes = game_outcomes(train_rows)
    game_ids = np.asarray(sorted(outcomes))
    game_y = np.asarray([outcomes[g] for g in game_ids], dtype=int)
    fit_ids, val_ids = train_test_split(
        game_ids,
        test_size=0.20,
        random_state=seed,
        stratify=game_y,
    )
    return set(map(str, fit_ids)), set(map(str, val_ids))


def candidates(seed: int) -> list[Candidate]:
    return [
        Candidate(
            "round1_logistic_2feat",
            ["margin", "margin_scaled"],
            Pipeline(
                [
                    ("scale", StandardScaler()),
                    ("lr", LogisticRegression(max_iter=1000, C=0.2, solver="lbfgs")),
                ]
            ),
            "Round-1 shape: two features with scaled logistic regression.",
        ),
        Candidate(
            "logit_blend_hgb40_smooth60",
            CORE_FEATURES,
            LogitBlendModel(hgb_weight=0.4, seed=seed),
            "Validation-selected fix attempt: 40% monotone HGB and 60% smooth two-feature logistic in logit space.",
        ),
        Candidate(
            "logit_blend_hgb50_smooth50",
            CORE_FEATURES,
            LogitBlendModel(hgb_weight=0.5, seed=seed),
            "Equal logit-space blend of monotone HGB and smooth two-feature logistic.",
        ),
        Candidate(
            "logit_blend_hgb70_smooth30",
            CORE_FEATURES,
            LogitBlendModel(hgb_weight=0.7, seed=seed),
            "Higher-HGB logit-space blend; less defect shrinkage but better validation than the raw HGB.",
        ),
        Candidate(
            "poly3_logistic_all6",
            ALL_FEATURES,
            Pipeline(
                [
                    ("poly", PolynomialFeatures(degree=3, include_bias=False)),
                    ("scale", StandardScaler()),
                    ("lr", LogisticRegression(max_iter=5000, C=0.2, solver="lbfgs")),
                ]
            ),
            "Polynomial interactions over every frozen serving feature.",
        ),
        Candidate(
            "spline_logistic_core",
            CORE_FEATURES,
            Pipeline(
                [
                    ("spline", SplineTransformer(n_knots=8, degree=3, include_bias=False)),
                    ("scale", StandardScaler()),
                    ("lr", LogisticRegression(max_iter=3000, C=0.1, solver="lbfgs")),
                ]
            ),
            "Cubic spline basis over margin, time, and overtime.",
        ),
        Candidate(
            "hist_gradient_boosting_core",
            CORE_FEATURES,
            HistGradientBoostingClassifier(
                max_iter=200,
                learning_rate=0.05,
                l2_regularization=0.1,
                max_leaf_nodes=31,
                min_samples_leaf=80,
                random_state=seed,
                monotonic_cst=[1, 1, -1, 0],
            ),
            "Monotone histogram gradient boosting over margin/time interactions.",
        ),
        Candidate(
            "gradient_boosting_core",
            CORE_FEATURES,
            GradientBoostingClassifier(
                n_estimators=300,
                learning_rate=0.025,
                max_depth=2,
                min_samples_leaf=150,
                random_state=seed,
            ),
            "Classical gradient-boosted trees over the core serving features.",
        ),
    ]


def normal_params(rows: list[dict]) -> tuple[float, float]:
    by_game: dict[str, int] = {}
    for r in rows:
        by_game[str(r["game_id"])] = max(by_game.get(str(r["game_id"]), 0), int(r["seq"]))
    final_margin_by_game = {
        str(r["game_id"]): float(r["margin"])
        for r in rows
        if int(r["seq"]) == by_game[str(r["game_id"])]
    }

    xs: list[float] = []
    ys: list[float] = []
    for r in rows:
        frac = float(r["frac_remaining"])
        if frac <= 1e-6:
            continue
        final_margin = final_margin_by_game[str(r["game_id"])]
        xs.append(frac)
        ys.append(final_margin - float(r["margin"]))
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    mu = float(np.sum(x * y) / max(np.sum(x * x), 1e-9))
    residual = y - mu * x
    sigma = float(math.sqrt(max(float(np.mean((residual * residual) / np.maximum(x, 1e-6))), 1e-9)))
    return mu, sigma


def baseline_probs(rows: list[dict], mu: float, sigma: float) -> dict[str, list[float]]:
    states = [state_for(r) for r in rows]
    return {
        "leader": [baseline_leader(s) for s in states],
        "constant_0.5": [0.5 for _ in states],
        "normal_recomputed": [baseline_normal(s, mu, sigma) for s in states],
        "espn": [float(r["espn_home_wp"]) for r in rows if r["espn_home_wp"] is not None],
    }


def phase_metrics(rows: list[dict], probs: np.ndarray) -> list[dict]:
    phases = [
        ("1.00-0.75", 0.75, 1.000001),
        ("0.75-0.50", 0.50, 0.75),
        ("0.50-0.25", 0.25, 0.50),
        ("0.25-0.00", -0.000001, 0.25),
    ]
    out: list[dict] = []
    y_all = labels(rows)
    frac = np.asarray([float(r["frac_remaining"]) for r in rows], dtype=float)
    for label, lo, hi in phases:
        idx = np.where((frac >= lo) & (frac < hi))[0]
        out.append({"phase": label, **metric_row("model", probs[idx], y_all[idx])})
    return out


def score_state(model: object, feature_names: list[str], margin: int, frac: float, period: int = 4) -> float:
    state = GameState(league="nba", margin=margin, frac_remaining=frac, period=period, is_overtime=period > 4)
    vector = [[build_features(state)[name] for name in feature_names]]
    return float(model.predict_proba(vector)[0][1])


def monotone_grid_check(model: object, feature_names: list[str]) -> dict:
    frac_points = [1.0, 0.75, 0.5, 0.25, 0.10, DEFECT_FRAC, 30 / 2880, 0.0]
    margins = list(range(-60, 61))
    failures: list[dict] = []
    checked = 0
    for frac in frac_points:
        for period in (1, 2, 4, 5):
            probs = [score_state(model, feature_names, margin, frac, period) for margin in margins]
            diffs = np.diff(probs)
            checked += len(diffs)
            if np.any(diffs < -1e-12):
                idx = int(np.argmin(diffs))
                failures.append(
                    {
                        "frac_remaining": frac,
                        "period": period,
                        "margin": margins[idx],
                        "next_margin": margins[idx + 1],
                        "drop": float(diffs[idx]),
                    }
                )
    return {"passed": not failures, "checked_adjacent_pairs": checked, "failures": failures}


def tail_table(model: object, feature_names: list[str]) -> list[dict]:
    rows: list[dict] = []
    for label, frac in (("2:00", DEFECT_FRAC), ("0:30", 30 / 2880)):
        for margin in (5, 10, 15, 20):
            rows.append(
                {
                    "time_remaining": label,
                    "frac_remaining": frac,
                    "margin": margin,
                    "prob": score_state(model, feature_names, margin, frac, 4),
                }
            )
    return rows


def comparable_espn_state(rows: list[dict], margin: int = 10, frac: float = DEFECT_FRAC) -> dict:
    comparable = [
        r
        for r in rows
        if int(r["margin"]) == margin
        and r["espn_home_wp"] is not None
        and abs(float(r["frac_remaining"]) - frac) <= 30 / 2880
    ]
    if not comparable:
        return {"n": 0}
    probs = [float(r["espn_home_wp"]) for r in comparable]
    return {
        "n": len(probs),
        "mean": float(np.mean(probs)),
        "median": float(np.median(probs)),
        "min": float(np.min(probs)),
        "max": float(np.max(probs)),
    }


def sanity_checks(model: object, feature_names: list[str]) -> dict:
    margin_points = (-20, -10, 0, 10, 20)
    margin_probs = [score_state(model, feature_names, margin, 0.5, 2) for margin in margin_points]
    lead_early = score_state(model, feature_names, 8, 0.8, 1)
    lead_late = score_state(model, feature_names, 8, 0.2, 4)
    edge_states = {
        "tie_start": score_state(model, feature_names, 0, 1.0, 1),
        "tie_end": score_state(model, feature_names, 0, 0.0, 4),
        "big_home_end": score_state(model, feature_names, 60, 0.0, 4),
        "big_away_end": score_state(model, feature_names, -60, 0.0, 4),
    }
    strictly_inside = all(0.0 < p < 1.0 for p in [*margin_probs, lead_early, lead_late, *edge_states.values()])
    finite = all(math.isfinite(p) for p in [*margin_probs, lead_early, lead_late, *edge_states.values()])
    checks = {
        "margin_grid_frac_0_5": {str(m): p for m, p in zip(margin_points, margin_probs)},
        "probability_increases_with_home_margin": all(a < b for a, b in zip(margin_probs, margin_probs[1:])),
        "monotone_grid": monotone_grid_check(model, feature_names),
        "home_plus_10_2min": score_state(model, feature_names, 10, DEFECT_FRAC, 4),
        "late_tail_table": tail_table(model, feature_names),
        "home_plus_8_frac_0_8": lead_early,
        "home_plus_8_frac_0_2": lead_late,
        "same_lead_higher_with_less_time": lead_late > lead_early,
        "edge_states": edge_states,
        "finite_edge_predictions": finite,
        "strictly_inside_0_1": strictly_inside,
    }
    assert checks["probability_increases_with_home_margin"]
    assert checks["monotone_grid"]["passed"]
    assert checks["same_lead_higher_with_less_time"]
    assert checks["finite_edge_predictions"]
    assert checks["strictly_inside_0_1"]
    return checks


def rounded(obj):
    if isinstance(obj, dict):
        return {k: rounded(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rounded(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def fresh_serving_check() -> dict:
    code = (
        "import json; "
        "from app.services.live_winprob import GameState, predict_home_win_prob; "
        "p,m=predict_home_win_prob(GameState(league='nba', margin=8, frac_remaining=0.2, period=4)); "
        "print(json.dumps({'prob': p, 'available': m.get('available')}))"
    )
    raw = subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, text=True)
    return json.loads(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-season", type=int, default=2023)
    parser.add_argument("--test-season", type=int, default=2024)
    parser.add_argument("--seed", type=int, default=20260805)
    args = parser.parse_args()

    rows = rows_from_db()
    if not rows:
        raise SystemExit(f"No snapshots found in {DB_PATH}; data should already be harvested.")

    train = [r for r in rows if int(r["season_start_year"]) == args.train_season]
    test = [r for r in rows if int(r["season_start_year"]) == args.test_season]
    train_game_ids = {str(r["game_id"]) for r in train}
    test_game_ids = {str(r["game_id"]) for r in test}
    overlap = train_game_ids & test_game_ids
    if not train or not test or overlap:
        raise SystemExit(f"Invalid fixed split: train={len(train)}, test={len(test)}, overlap={len(overlap)}")

    fit_ids, val_ids = validation_split(train, args.seed)
    fit = [r for r in train if str(r["game_id"]) in fit_ids]
    val = [r for r in train if str(r["game_id"]) in val_ids]
    y_fit = labels(fit)
    y_val = labels(val)

    validation_results: list[dict] = []
    for cand in candidates(args.seed):
        cand.model.fit(matrix(fit, cand.feature_names), y_fit)
        val_probs = cand.model.predict_proba(matrix(val, cand.feature_names))[:, 1]
        monotone = monotone_grid_check(cand.model, cand.feature_names)
        defect_prob = score_state(cand.model, cand.feature_names, 10, DEFECT_FRAC, 4)
        row = metric_row(cand.name, val_probs, y_val)
        row.update(
            {
                "feature_names": cand.feature_names,
                "description": cand.description,
                "max_calibration_gap": max_calibration_gap(val_probs.tolist(), y_val.tolist(), bins=10, min_n=100),
                "monotone_grid_passed": monotone["passed"],
                "home_plus_10_2min": defect_prob,
                "fixes_overconfidence_gate": defect_prob <= DEFECT_MAX_PROB,
            }
        )
        validation_results.append(row)

    # Model selection happens here, before the 2024 holdout is scored. Because
    # this run targets a specific late-blowout overconfidence defect, candidates
    # must first be monotone and pull the +10/2:00 state below the data-justified
    # 0.98 sanity threshold; validation log loss is then the primary criterion.
    eligible = [r for r in validation_results if r["monotone_grid_passed"] and r["fixes_overconfidence_gate"]]
    if not eligible:
        raise SystemExit("No validation candidate both fixed the defect threshold and passed monotonicity.")
    selected_name = min(eligible, key=lambda r: (r["log_loss"], r["brier"]))["name"]
    selected_template = next(c for c in candidates(args.seed) if c.name == selected_name)
    selected_template.model.fit(matrix(train, selected_template.feature_names), labels(train))
    selected_model = selected_template.model
    selected_features = selected_template.feature_names

    test_probs = selected_model.predict_proba(matrix(test, selected_features))[:, 1]
    y_test = labels(test)
    final_metric = metric_row("selected_model", test_probs, y_test)
    final_metric["max_calibration_gap"] = max_calibration_gap(test_probs.tolist(), y_test.tolist(), bins=10, min_n=100)

    mu, sigma = normal_params(train)
    base = baseline_probs(test, mu, sigma)
    espn_y = labels([r for r in test if r["espn_home_wp"] is not None])
    test_frac = np.asarray([float(r["frac_remaining"]) for r in test], dtype=float)
    late_idx = np.where(test_frac <= 0.25)[0]
    espn_late_rows = [r for r in test if r["espn_home_wp"] is not None and float(r["frac_remaining"]) <= 0.25]
    espn_late_y = labels(espn_late_rows)
    comparisons = [
        final_metric,
        {**CURRENT_REFERENCE, "n": len(test)},
        {**NORMAL_REFERENCE, "n": len(test)},
        metric_row("normal_recomputed_in_script", base["normal_recomputed"], y_test),
        {**ESPN_REFERENCE, "n": int(len(espn_y))},
        metric_row("espn_recomputed_from_snapshots", base["espn"], espn_y),
        metric_row("leader", base["leader"], y_test),
        metric_row("constant_0.5", base["constant_0.5"], y_test),
    ]
    late_comparisons = [
        metric_row("selected_model_late_frac_le_0_25", test_probs[late_idx], y_test[late_idx]),
        metric_row(
            "espn_late_frac_le_0_25",
            [float(r["espn_home_wp"]) for r in espn_late_rows],
            espn_late_y,
        ),
    ]

    sanity = sanity_checks(selected_model, selected_features)
    calib = calibration_table(test_probs.tolist(), y_test.tolist(), bins=10)
    phases = phase_metrics(test, test_probs)
    should_overwrite = (
        final_metric["log_loss"] < CURRENT_REFERENCE["log_loss"]
        and sanity["monotone_grid"]["passed"]
        and sanity["home_plus_10_2min"] <= DEFECT_MAX_PROB
    )

    artifact = {
        "model": selected_model,
        "feature_names": list(selected_features),
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_games": len(train_game_ids | test_game_ids),
        "n_snapshots": len(train) + len(test),
        "brier": final_metric["brier"],
        "log_loss": final_metric["log_loss"],
        "train_seasons": [args.train_season],
        "test_seasons": [args.test_season],
        "max_calibration_gap": final_metric["max_calibration_gap"],
        "notes": (
            "NBA late-blowout calibration experiment. Candidate selected only from 2023 validation "
            "after passing monotonicity and +10/2:00 overconfidence gates; artifact is saved only if "
            "it beats the published model's held-out 2024 log loss."
        ),
        "validation": {
            "selection_rule": (
                "among 2023 validation candidates with monotone margin grid and home +10 at 2:00 <= "
                f"{DEFECT_MAX_PROB}, choose lowest validation log_loss, then Brier"
            ),
            "selected_model": selected_name,
            "validation_split": {
                "type": "stratified_game_level_split_within_train_season",
                "seed": args.seed,
                "fit_games": len(fit_ids),
                "validation_games": len(val_ids),
                "fit_snapshots": len(fit),
                "validation_snapshots": len(val),
            },
            "fixed_holdout_split": {
                "train_seasons": [args.train_season],
                "test_seasons": [args.test_season],
                "train_games": len(train_game_ids),
                "test_games": len(test_game_ids),
                "train_snapshots": len(train),
                "test_snapshots": len(test),
                "game_id_overlap": len(overlap),
            },
            "candidates": validation_results,
            "holdout_metrics": final_metric,
            "comparisons": comparisons,
            "late_comparisons": late_comparisons,
            "normal_baseline_params_recomputed": {"mu": mu, "sigma": sigma},
            "calibration_table": calib,
            "max_calibration_gap": final_metric["max_calibration_gap"],
            "phase_breakdown": phases,
            "sanity_checks": sanity,
            "espn_comparable_home_plus_10_2min": comparable_espn_state(test),
            "current_reference": CURRENT_REFERENCE,
            "espn_reference": ESPN_REFERENCE,
            "normal_reference_from_round1": NORMAL_REFERENCE,
            "overwrote_artifact": should_overwrite,
        },
    }

    path = artifact_path("nba")
    if should_overwrite:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(artifact, path)
        artifact["validation"]["serving_check"] = fresh_serving_check()
        joblib.dump(artifact, path)
    else:
        artifact["validation"]["serving_check"] = {
            "skipped": "candidate did not beat the published artifact's held-out log loss; artifact not overwritten"
        }

    print(json.dumps(rounded(artifact["validation"]), indent=2, sort_keys=True))
    if should_overwrite:
        print(f"Saved improved artifact: {path}")
    else:
        print(f"Did not overwrite artifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
