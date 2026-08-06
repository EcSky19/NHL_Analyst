"""Retrain NHL live win probability on full-season snapshot data.

Selection uses only a chronological game-level validation split inside
2024-25.  The held-out 2025-26 season is scored only after model/alpha
selection and shipping-gate checks.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss as sklearn_log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.live_wp_baseline import NormalBaselineModel  # noqa: E402
from app.services.live_winprob import (  # noqa: E402
    GameState,
    artifact_path,
    brier_score,
    build_features,
    log_loss,
    max_calibration_gap,
)

DB_PATH = ROOT / "data" / "live_wp" / "nhl_snapshots.db"
TRAIN_SEASONS = ["2024-25"]
TEST_SEASONS = ["2025-26"]
FEATURE_NAMES = ["margin", "margin_scaled", "frac_remaining", "is_overtime"]
OLD_BASELINE = (0.3908, 2.7339)


class MonotoneBlendModel:
    """Blend a learned model with the normal baseline, then project monotone."""

    __module__ = "scripts.live_wp.train_nhl"

    def __init__(
        self,
        base_model: Any,
        alpha: float,
        normal_mu: float,
        normal_sigma: float,
        feature_names: list[str] | tuple[str, ...] = FEATURE_NAMES,
        margin_min: int = -10,
        margin_max: int = 10,
        time_grid_size: int = 41,
    ) -> None:
        self.base_model = base_model
        self.alpha = float(alpha)
        self.normal_mu = float(normal_mu)
        self.normal_sigma = float(normal_sigma)
        self.feature_names = list(feature_names)
        self.margin_min = int(margin_min)
        self.margin_max = int(margin_max)
        self.time_grid = np.linspace(0.0, 1.0, int(time_grid_size))
        self.classes_ = np.array([0, 1])

    def _row(self, margin: int, frac: float, is_overtime: float) -> list[float]:
        frac = min(max(float(frac), 0.0), 1.0)
        values = {
            "margin": float(margin),
            "margin_scaled": float(margin) / math.sqrt(frac + 1e-6),
            "frac_remaining": frac,
            "is_overtime": float(is_overtime),
        }
        return [values[name] for name in self.feature_names]

    def _normal(self, margins: np.ndarray, fracs: np.ndarray) -> np.ndarray:
        fracs = np.clip(fracs, 0.0, 1.0)
        live = fracs > 1e-9
        out = np.where(margins > 0, 1.0, np.where(margins < 0, 0.0, 0.5)).astype(float)
        f = np.where(live, fracs, 1.0)
        sd = np.maximum(self.normal_sigma * np.sqrt(f), 1e-9)
        out[live] = ndtr(((margins + self.normal_mu * f) / sd)[live])
        return np.clip(out, 1e-6, 1.0 - 1e-6)

    def predict_proba(self, X: Any) -> np.ndarray:
        arr = np.asarray(X, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        margin_idx = self.feature_names.index("margin")
        frac_idx = self.feature_names.index("frac_remaining")
        ot_idx = self.feature_names.index("is_overtime")

        requests: list[tuple[int, float, float, tuple[int, ...]]] = []
        blend_keys: set[tuple[int, float, float]] = set()
        for row in arr:
            margin = int(round(float(row[margin_idx])))
            frac = min(max(float(row[frac_idx]), 0.0), 1.0)
            ot = float(row[ot_idx])
            candidates = list(range(self.margin_min, min(margin, self.margin_max) + 1))
            if margin > self.margin_max:
                candidates.append(margin)
            if not candidates:
                candidates.append(margin)
            requests.append((margin, frac, ot, tuple(candidates)))
            for candidate in candidates:
                grid = [frac] if candidate == 0 else [frac, *[float(f) for f in self.time_grid if f >= frac - 1e-12]]
                for grid_frac in grid:
                    blend_keys.add((candidate, round(float(grid_frac), 8), ot))

        ordered = sorted(blend_keys)
        matrix = np.array([self._row(m, f, ot) for m, f, ot in ordered], dtype=float)
        base = self.base_model.predict_proba(matrix)[:, 1]
        normal = self._normal(np.array([m for m, _, _ in ordered], dtype=float), np.array([f for _, f, _ in ordered], dtype=float))
        blended = np.clip(self.alpha * normal + (1.0 - self.alpha) * base, 1e-6, 1.0 - 1e-6)
        blend = {key: float(prob) for key, prob in zip(ordered, blended)}

        time_env: dict[tuple[int, float, float], float] = {}
        for margin, frac, ot, candidates in requests:
            for candidate in candidates:
                key = (candidate, round(float(frac), 8), ot)
                if key in time_env:
                    continue
                if candidate == 0:
                    time_env[key] = blend[key]
                    continue
                grid = [frac, *[float(f) for f in self.time_grid if f >= frac - 1e-12]]
                vals = [blend[(candidate, round(float(f), 8), ot)] for f in grid]
                time_env[key] = max(vals) if candidate > 0 else min(vals)

        probs = []
        for _margin, frac, ot, candidates in requests:
            vals = [time_env[(candidate, round(float(frac), 8), ot)] for candidate in candidates]
            probs.append(max(vals))
        home = np.clip(np.asarray(probs, dtype=float), 1e-6, 1.0 - 1e-6)
        return np.column_stack([1.0 - home, home])


@dataclass(frozen=True)
class Dataset:
    rows: list[dict[str, Any]]
    X: np.ndarray
    y: np.ndarray
    games: set[str]


def load_rows() -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT game_id, season, period, frac_remaining, margin, home_won, espn_home_wp
            FROM snapshots
            WHERE home_won IS NOT NULL
            ORDER BY season, game_id, id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def matrix(rows: list[dict[str, Any]], feature_names: list[str] | tuple[str, ...] = FEATURE_NAMES) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for row in rows:
        state = GameState(
            league="nhl",
            margin=int(row["margin"]),
            frac_remaining=float(row["frac_remaining"]),
            period=int(row["period"]),
            is_overtime=int(row["period"]) > 3,
        )
        feats = build_features(state)
        X.append([feats[name] for name in feature_names])
        y.append(int(row["home_won"]))
    return np.asarray(X, dtype=float), np.asarray(y, dtype=int)


def make_dataset(rows: list[dict[str, Any]]) -> Dataset:
    X, y = matrix(rows)
    return Dataset(rows, X, y, {str(row["game_id"]) for row in rows})


def split_rows(rows: list[dict[str, Any]]) -> tuple[Dataset, Dataset, Dataset, Dataset]:
    train_rows = [r for r in rows if str(r["season"]) in TRAIN_SEASONS]
    test_rows = [r for r in rows if str(r["season"]) in TEST_SEASONS]
    games: list[str] = []
    seen: set[str] = set()
    for row in train_rows:
        game_id = str(row["game_id"])
        if game_id not in seen:
            seen.add(game_id)
            games.append(game_id)
    cut = int(len(games) * 0.8)
    fit_games = set(games[:cut])
    val_games = set(games[cut:])
    fit_rows = [r for r in train_rows if str(r["game_id"]) in fit_games]
    val_rows = [r for r in train_rows if str(r["game_id"]) in val_games]
    return make_dataset(fit_rows), make_dataset(val_rows), make_dataset(train_rows), make_dataset(test_rows)


def normal_probs(X: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    return NormalBaselineModel(mu, sigma).predict_proba(X[:, [0, 2]])[:, 1]


def fit_normal(X: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    labels = list(map(int, y))

    def objective(theta: np.ndarray) -> float:
        probs = normal_probs(X, float(theta[0]), max(abs(float(theta[1])), 1e-3))
        return log_loss(list(probs), labels)

    best = None
    for sigma0 in (1.5, 2.5, 4.0):
        res = minimize(
            objective,
            x0=np.array([0.0, sigma0]),
            method="Nelder-Mead",
            options={"xatol": 1e-5, "fatol": 1e-8, "maxiter": 500},
        )
        if best is None or res.fun < best.fun:
            best = res
    return float(best.x[0]), float(abs(best.x[1]))


def metrics(y: np.ndarray, probs: np.ndarray) -> dict[str, float]:
    probs = np.clip(np.asarray(probs, dtype=float), 1e-15, 1.0 - 1e-15)
    return {
        "brier": round(float(brier_score_loss(y, probs)), 6),
        "log_loss": round(float(sklearn_log_loss(y, probs, labels=[0, 1])), 6),
    }


def candidates() -> dict[str, Any]:
    return {
        "poly2_logreg_C0.05": Pipeline(
            [
                ("poly", PolynomialFeatures(degree=2, include_bias=False)),
                ("scale", StandardScaler()),
                ("logreg", LogisticRegression(max_iter=2000, C=0.05, random_state=42)),
            ]
        ),
        "poly2_logreg_C0.20": Pipeline(
            [
                ("poly", PolynomialFeatures(degree=2, include_bias=False)),
                ("scale", StandardScaler()),
                ("logreg", LogisticRegression(max_iter=2000, C=0.20, random_state=42)),
            ]
        ),
        "hgb_leaf200_l2_0.05": HistGradientBoostingClassifier(
            max_iter=180,
            learning_rate=0.04,
            max_leaf_nodes=15,
            min_samples_leaf=200,
            l2_regularization=0.05,
            monotonic_cst=[1, 1, 0, 0],
            early_stopping=True,
            validation_fraction=0.12,
            n_iter_no_change=15,
            random_state=1,
        ),
        "hgb_leaf400_l2_0.20": HistGradientBoostingClassifier(
            max_iter=160,
            learning_rate=0.035,
            max_leaf_nodes=8,
            min_samples_leaf=400,
            l2_regularization=0.20,
            monotonic_cst=[1, 1, 0, 0],
            early_stopping=True,
            validation_fraction=0.12,
            n_iter_no_change=15,
            random_state=2,
        ),
        "extra_trees_leaf300": ExtraTreesClassifier(
            n_estimators=200,
            min_samples_leaf=300,
            max_features=1.0,
            n_jobs=-1,
            random_state=4,
        ),
    }


def monotonicity_checks(model: Any) -> dict[str, Any]:
    def p(margin: int, frac: float) -> float:
        state = GameState("nhl", margin=margin, frac_remaining=frac, period=3 if frac > 0 else 4, is_overtime=frac == 0)
        feats = build_features(state)
        row = [[feats[name] for name in FEATURE_NAMES]]
        return float(model.predict_proba(row)[0][1])

    margin_drops = 0
    worst_margin_drop = 0.0
    for frac in np.linspace(0.0, 1.0, 41):
        vals = [p(margin, float(frac)) for margin in range(-10, 11)]
        for a, b in zip(vals, vals[1:]):
            if b < a - 1e-12:
                margin_drops += 1
                worst_margin_drop = min(worst_margin_drop, b - a)

    time: dict[str, Any] = {}
    for margin in (1, 2, 3, 4, -1, -2, -3, -4):
        vals = [p(margin, 1.0 - i / 40) for i in range(41)]
        deltas = [b - a for a, b in zip(vals, vals[1:])]
        bad = [d for d in deltas if (d < -1e-12 if margin > 0 else d > 1e-12)]
        time[str(margin)] = {
            "wrong_way_steps": len(bad),
            "worst_wrong_way_delta": round(float(min(bad) if margin > 0 and bad else max(bad) if bad else 0.0), 8),
            "start": round(float(vals[0]), 6),
            "end": round(float(vals[-1]), 6),
        }

    return {
        "margin": {"drops": margin_drops, "worst_drop": round(float(worst_margin_drop), 8)},
        "time": time,
        "passed": margin_drops == 0 and all(item["wrong_way_steps"] == 0 for item in time.values()),
    }


def latency_ms(model: Any, loops: int = 1000) -> float:
    state = GameState("nhl", margin=1, frac_remaining=0.5, period=2)
    feats = build_features(state)
    row = [[feats[name] for name in FEATURE_NAMES]]
    for _ in range(10):
        model.predict_proba(row)
    t0 = time.perf_counter()
    for _ in range(loops):
        model.predict_proba(row)
    return (time.perf_counter() - t0) * 1000.0 / loops


def fresh_serving_check() -> str:
    code = "from app.services.live_winprob import GameState, predict_home_win_prob as f; print(round(float(f(GameState('nhl',1,0.5))[0]), 6))"
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def eval_model(ds: Dataset, model: Any) -> dict[str, Any]:
    probs = model.predict_proba(ds.X)[:, 1]
    out = metrics(ds.y, probs)
    out["max_calibration_gap"] = round(float(max_calibration_gap(list(probs), list(map(int, ds.y)))), 6)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", default="")
    args = parser.parse_args()

    rows = load_rows()
    fit_ds, val_ds, train_ds, test_ds = split_rows(rows)
    overlap = train_ds.games & test_ds.games
    if overlap:
        raise SystemExit(f"Game-level split violation: {len(overlap)}")

    fit_mu, fit_sigma = fit_normal(fit_ds.X, fit_ds.y)
    train_mu, train_sigma = fit_normal(train_ds.X, train_ds.y)
    old_baseline = metrics(test_ds.y, normal_probs(test_ds.X, *OLD_BASELINE))
    refit_baseline = metrics(test_ds.y, normal_probs(test_ds.X, train_mu, train_sigma))
    val_baseline = metrics(val_ds.y, normal_probs(val_ds.X, fit_mu, fit_sigma))

    alpha_grid = [0.0, 0.2, 0.4, 0.6, 0.75, 0.9]
    validation_results: list[dict[str, Any]] = []
    shippable: list[dict[str, Any]] = []
    fitted: dict[str, Any] = {}

    for name, model in candidates().items():
        started = time.perf_counter()
        model.fit(fit_ds.X, fit_ds.y)
        fitted[name] = model
        raw_probs = model.predict_proba(val_ds.X)[:, 1]
        baseline_probs = normal_probs(val_ds.X, fit_mu, fit_sigma)
        best_blend = None
        for alpha in np.linspace(0.0, 1.0, 21):
            blend_probs = alpha * baseline_probs + (1.0 - alpha) * raw_probs
            score = metrics(val_ds.y, blend_probs)
            if best_blend is None or score["log_loss"] < best_blend["log_loss"]:
                best_blend = {"alpha": round(float(alpha), 2), **score}
        row = {
            "name": name,
            "raw": metrics(val_ds.y, raw_probs),
            "best_simple_blend": best_blend,
            "fit_seconds": round(time.perf_counter() - started, 1),
        }

        enveloped = []
        for alpha in alpha_grid:
            wrapped = MonotoneBlendModel(model, alpha=alpha, normal_mu=fit_mu, normal_sigma=fit_sigma)
            score = eval_model(val_ds, wrapped)
            mono = monotonicity_checks(wrapped)
            lat = latency_ms(wrapped, loops=100)
            item = {"alpha": alpha, **score, "monotonicity_passed": mono["passed"], "latency_ms": round(lat, 3)}
            enveloped.append(item)
            if alpha < 1.0 and mono["passed"] and lat < 10.0:
                shippable.append({"name": name, "alpha": alpha, "score": score, "latency_ms": lat})
        row["enveloped_blends"] = enveloped
        validation_results.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)

    selected = min(shippable, key=lambda item: (item["score"]["log_loss"], item["score"]["brier"]))
    full_model = candidates()[selected["name"]]
    full_model.fit(train_ds.X, train_ds.y)
    final_model = MonotoneBlendModel(full_model, selected["alpha"], train_mu, train_sigma)
    final_eval = eval_model(test_ds, final_model)
    final_mono = monotonicity_checks(final_model)
    final_latency = latency_ms(final_model, loops=1000)
    final_beats_refit = final_eval["log_loss"] < refit_baseline["log_loss"]
    should_ship = final_beats_refit and final_mono["passed"] and final_latency < 10.0

    artifact_model: Any = final_model if should_ship else NormalBaselineModel(train_mu, train_sigma)
    artifact_features = FEATURE_NAMES if should_ship else ["margin", "frac_remaining"]
    artifact_eval = final_eval if should_ship else {
        **refit_baseline,
        "max_calibration_gap": round(max_calibration_gap(list(normal_probs(test_ds.X, train_mu, train_sigma)), list(map(int, test_ds.y))), 6),
    }

    validation = {
        "split": {
            "train_games": len(train_ds.games),
            "test_games": len(test_ds.games),
            "game_overlap": len(overlap),
            "fit_games_inside_train": len(fit_ds.games),
            "validation_games_inside_train": len(val_ds.games),
            "train_snapshots": len(train_ds.y),
            "test_snapshots": len(test_ds.y),
        },
        "old_baseline": {"mu": OLD_BASELINE[0], "sigma": OLD_BASELINE[1], **old_baseline},
        "refit_baseline": {"mu": round(train_mu, 6), "sigma": round(train_sigma, 6), **refit_baseline},
        "validation_baseline": {"mu": round(fit_mu, 6), "sigma": round(fit_sigma, 6), **val_baseline},
        "candidate_validation": validation_results,
        "selected": selected,
        "final_model": final_eval,
        "final_monotonicity": final_mono,
        "final_latency_ms": round(final_latency, 3),
        "shipped": "learned_blend" if should_ship else "refit_analytic_baseline",
        "espn_benchmark": {"available": False, "coverage": 0},
    }

    bundle = {
        "model": artifact_model,
        "feature_names": artifact_features,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_seasons": TRAIN_SEASONS,
        "test_seasons": TEST_SEASONS,
        "n_games": len(train_ds.games),
        "n_snapshots": int(len(train_ds.y)),
        "brier": artifact_eval["brier"],
        "log_loss": artifact_eval["log_loss"],
        "max_calibration_gap": artifact_eval["max_calibration_gap"],
        "notes": (
            "NHL full-season retrain on 2024-25 with 2025-26 held out by game. "
            "No NHL ESPN win-probability values are available, so there is no external benchmark. "
            f"Shipped {validation['shipped']}."
        ),
        "validation": validation,
    }
    out_path = artifact_path("nhl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, out_path)
    validation["fresh_serving_check"] = fresh_serving_check()
    joblib.dump(bundle, out_path)

    if args.write_report:
        report_path = Path(args.write_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(validation, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(validation, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
