"""Train, validate, and honestly evaluate the NBA live win-probability model.

The NBA snapshots table has no season column; always join through games and use
``games.season_start_year``. Selection is by a game-level validation split from
2023 only, and 2024 is touched only for final reporting.
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
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss as sklearn_log_loss
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

from app.services.espn_pbp import ot_frac_remaining_clock
from app.services.live_winprob import (
    FEATURE_NAMES,
    GameState,
    artifact_path,
    build_features,
    calibration_table,
    max_calibration_gap,
)

DB_PATH = ROOT / "data" / "live_wp" / "nba_snapshots.db"
SEED = 20260806
OLD_NORMAL_PARAMS = {"mu": 2.0987954533865993, "sigma": 18.81951172745765}
PUBLISHED_OLD_SAMPLE = {"brier": 0.167947, "log_loss": 0.491963}
CORE_FEATURES = ["margin", "margin_scaled", "frac_remaining", "is_overtime"]
GRID_FEATURES = [
    "margin",
    "frac_remaining",
    "is_overtime",
    "ot_frac_remaining",
    "ot_frac_known",
    "margin_scaled",
    "margin_scaled_ot",
]
POLY_FEATURES = ["margin", "frac_remaining", "is_overtime"]


@dataclass(frozen=True)
class CandidateResult:
    name: str
    kind: str
    brier: float
    log_loss: float
    max_calibration_gap: float
    monotone_margin: bool
    monotone_time: bool
    notes: str


class GridBlendModel:
    """Blend HGB with the refit normal baseline, then project to a monotone grid."""

    feature_names = GRID_FEATURES

    def __init__(
        self,
        base_model: Any,
        alpha: float,
        normal_mu: float,
        normal_sigma: float,
        margin_min: int = -80,
        margin_max: int = 80,
        time_grid_size: int = 101,
    ) -> None:
        self.base_model = base_model
        self.alpha = float(alpha)
        self.normal_mu = float(normal_mu)
        self.normal_sigma = float(normal_sigma)
        self.margin_min = int(margin_min)
        self.margin_max = int(margin_max)
        self.time_grid_size = int(time_grid_size)
        self.classes_ = np.array([0, 1])

    def fit(self, X: np.ndarray, y: np.ndarray) -> "GridBlendModel":
        arr = np.asarray(X, dtype=float)
        core = self._core_matrix(arr)
        self.base_model.fit(core, y)
        self._build_grid()
        return self

    def _normal_prob(self, margin: np.ndarray, frac: np.ndarray) -> np.ndarray:
        margin = np.asarray(margin, dtype=float)
        frac = np.clip(np.asarray(frac, dtype=float), 0.0, 1.0)
        live = frac > 1e-9
        out = np.where(margin > 0, 1.0, np.where(margin < 0, 0.0, 0.5)).astype(float)
        f = np.where(live, frac, 1.0)
        sd = np.maximum(self.normal_sigma * np.sqrt(f), 1e-9)
        out[live] = ndtr(((margin + self.normal_mu * f) / sd)[live])
        return np.clip(out, 1e-6, 1.0 - 1e-6)

    @staticmethod
    def _core_matrix(arr: np.ndarray) -> np.ndarray:
        arr = np.asarray(arr, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return arr

    def _raw_prob(self, features: np.ndarray) -> np.ndarray:
        core = self._core_matrix(features)
        learned = self.base_model.predict_proba(core)[:, 1]
        margin = core[:, 0]
        frac = core[:, 1]
        is_overtime = core[:, 2] >= 0.5
        ot_frac = core[:, 3]
        # NBA overtime is five minutes, so translate the overtime clock to the
        # equivalent share of regulation before blending with the regulation
        # normal baseline. Using zero would reintroduce the saturated bug.
        effective_frac = np.where(is_overtime, ot_frac * (5.0 / 48.0), frac)
        normal = self._normal_prob(margin, effective_frac)
        return np.clip((1.0 - self.alpha) * learned + self.alpha * normal, 1e-6, 1.0 - 1e-6)

    def _build_grid(self) -> None:
        self.margins_ = np.arange(self.margin_min, self.margin_max + 1, dtype=int)
        self.fracs_ = np.linspace(0.0, 1.0, self.time_grid_size)
        grids = []
        for overtime in (0.0, 1.0):
            mm, ff = np.meshgrid(self.margins_, self.fracs_, indexing="ij")
            features = []
            for margin, f in zip(mm.ravel(), ff.ravel()):
                if overtime:
                    state = GameState("nba", int(margin), 0.0, 5, True, ot_frac_remaining=float(f))
                else:
                    state = GameState("nba", int(margin), float(f), 4, False)
                feats = build_features(state)
                features.append([feats[name] for name in GRID_FEATURES])
            raw = self._raw_prob(np.asarray(features, dtype=float)).reshape(mm.shape)
            projected = np.maximum.accumulate(raw, axis=0)
            for idx, margin in enumerate(self.margins_):
                if margin > 0:
                    projected[idx] = np.maximum.accumulate(projected[idx, ::-1])[::-1]
                elif margin < 0:
                    projected[idx] = np.maximum.accumulate(projected[idx])
            projected = np.maximum.accumulate(projected, axis=0)
            grids.append(np.clip(projected, 1e-6, 1.0 - 1e-6))
        self.grid_ = np.stack(grids, axis=0)

    def predict_proba(self, X: Any) -> np.ndarray:
        arr = np.asarray(X, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        margin = np.rint(arr[:, 0]).astype(int)
        ot = (arr[:, 2] >= 0.5).astype(int) if arr.shape[1] > 2 else np.zeros(len(arr), dtype=int)
        if arr.shape[1] > 3:
            frac = np.clip(np.where(ot == 1, arr[:, 3], arr[:, 1]), 0.0, 1.0)
        else:
            frac = np.clip(arr[:, 1], 0.0, 1.0)
        margin_idx = np.clip(margin - self.margin_min, 0, len(self.margins_) - 1)
        out = np.empty(len(arr), dtype=float)
        for i, (overtime, mi, f) in enumerate(zip(ot, margin_idx, frac)):
            out[i] = np.interp(f, self.fracs_, self.grid_[overtime, mi])
        out = np.clip(out, 1e-6, 1.0 - 1e-6)
        return np.column_stack([1.0 - out, out])


class BaselinePolyCorrectionModel:
    """Smooth baseline correction used as a diagnostic; not guaranteed monotone."""

    feature_names = POLY_FEATURES

    def __init__(self, normal_mu: float, normal_sigma: float, alpha: float = 0.4, c: float = 0.2) -> None:
        self.normal_mu = float(normal_mu)
        self.normal_sigma = float(normal_sigma)
        self.alpha = float(alpha)
        self.c = float(c)
        self.classes_ = np.array([0, 1])
        self.pipe = Pipeline(
            [
                ("poly", PolynomialFeatures(degree=2, include_bias=False)),
                ("scale", StandardScaler()),
                ("lr", LogisticRegression(max_iter=3000, C=self.c, solver="lbfgs")),
            ]
        )

    def fit(self, X: np.ndarray, y: np.ndarray) -> "BaselinePolyCorrectionModel":
        arr = np.asarray(X, dtype=float)
        self.pipe.fit(self._matrix(arr[:, 0], arr[:, 1], arr[:, 2]), y)
        return self

    def _normal_prob(self, margin: np.ndarray, frac: np.ndarray) -> np.ndarray:
        margin = np.asarray(margin, dtype=float)
        frac = np.clip(np.asarray(frac, dtype=float), 0.0, 1.0)
        live = frac > 1e-9
        out = np.where(margin > 0, 1.0, np.where(margin < 0, 0.0, 0.5)).astype(float)
        f = np.where(live, frac, 1.0)
        sd = np.maximum(self.normal_sigma * np.sqrt(f), 1e-9)
        out[live] = ndtr(((margin + self.normal_mu * f) / sd)[live])
        return np.clip(out, 1e-6, 1.0 - 1e-6)

    def _matrix(self, margin: np.ndarray, frac: np.ndarray, is_overtime: np.ndarray) -> np.ndarray:
        margin = np.asarray(margin, dtype=float)
        frac = np.clip(np.asarray(frac, dtype=float), 0.0, 1.0)
        base = self._normal_prob(margin, frac)
        z = np.log(base / (1.0 - base))
        scaled = margin / np.sqrt(frac + 1e-6)
        return np.column_stack([z, margin, scaled, frac, z * frac, z * scaled, is_overtime])

    def predict_proba(self, X: Any) -> np.ndarray:
        arr = np.asarray(X, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        learned = self.pipe.predict_proba(self._matrix(arr[:, 0], arr[:, 1], arr[:, 2]))[:, 1]
        base = self._normal_prob(arr[:, 0], arr[:, 1])
        out = np.clip((1.0 - self.alpha) * learned + self.alpha * base, 1e-6, 1.0 - 1e-6)
        return np.column_stack([1.0 - out, out])


sys.modules.setdefault("scripts.live_wp.train_nba", sys.modules[__name__])
GridBlendModel.__module__ = "scripts.live_wp.train_nba"
BaselinePolyCorrectionModel.__module__ = "scripts.live_wp.train_nba"


def rows_from_db() -> list[dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT s.game_id, g.game_date, g.season_start_year, s.seq, s.period,
               s.clock_seconds, s.frac_remaining, s.margin, s.home_won, s.espn_home_wp
        FROM snapshots s
        JOIN games g ON g.game_id = s.game_id
        WHERE s.home_won IS NOT NULL AND g.n_snapshots > 0
        ORDER BY g.game_date, s.game_id, s.seq
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def state_for(row: dict[str, Any]) -> GameState:
    period = int(row["period"])
    is_overtime = period >= 5
    ot_frac = ot_frac_remaining_clock("nba", period, row.get("clock_seconds")) if is_overtime else None
    return GameState(
        league="nba",
        margin=int(row["margin"]),
        frac_remaining=float(row["frac_remaining"]),
        period=period,
        is_overtime=is_overtime,
        ot_frac_remaining=ot_frac,
    )


def matrix(rows: list[dict[str, Any]], feature_names: list[str]) -> np.ndarray:
    return np.asarray([[build_features(state_for(r))[name] for name in feature_names] for r in rows], dtype=float)


def labels(rows: Iterable[dict[str, Any]]) -> np.ndarray:
    return np.asarray([int(r["home_won"]) for r in rows], dtype=int)


def metric_row(name: str, probs: np.ndarray | list[float], y: np.ndarray | list[int]) -> dict[str, Any]:
    p = np.clip(np.asarray(probs, dtype=float), 1e-15, 1.0 - 1e-15)
    yy = np.asarray(y, dtype=int)
    return {
        "name": name,
        "n": int(len(p)),
        "brier": float(brier_score_loss(yy, p)),
        "log_loss": float(sklearn_log_loss(yy, p)),
    }


def game_outcomes(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        out[str(row["game_id"])] = int(row["home_won"])
    return out


def validation_split(train_rows: list[dict[str, Any]], seed: int) -> tuple[set[str], set[str]]:
    outcomes = game_outcomes(train_rows)
    game_ids = np.asarray(sorted(outcomes))
    game_y = np.asarray([outcomes[g] for g in game_ids], dtype=int)
    fit_ids, val_ids = train_test_split(game_ids, test_size=0.20, random_state=seed, stratify=game_y)
    return set(map(str, fit_ids)), set(map(str, val_ids))


def normal_vec(margin: np.ndarray, frac: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    margin = np.asarray(margin, dtype=float)
    frac = np.clip(np.asarray(frac, dtype=float), 0.0, 1.0)
    live = frac > 1e-9
    out = np.where(margin > 0, 1.0, np.where(margin < 0, 0.0, 0.5)).astype(float)
    f = np.where(live, frac, 1.0)
    sd = np.maximum(float(sigma) * np.sqrt(f), 1e-9)
    out[live] = ndtr(((margin + float(mu) * f) / sd)[live])
    return np.clip(out, 1e-6, 1.0 - 1e-6)


def fit_normal(margin: np.ndarray, frac: np.ndarray, y: np.ndarray, objective: str) -> dict[str, float]:
    def obj(theta: np.ndarray) -> float:
        probs = normal_vec(margin, frac, float(theta[0]), max(float(theta[1]), 1e-3))
        if objective == "brier":
            return float(brier_score_loss(y, probs))
        return float(sklearn_log_loss(y, np.clip(probs, 1e-15, 1.0 - 1e-15)))

    best = None
    for sigma0 in (7.0, 13.0, 18.0, 24.0):
        res = minimize(
            obj,
            x0=np.array([0.0, sigma0]),
            method="Nelder-Mead",
            options={"maxiter": 220, "xatol": 1e-4, "fatol": 1e-8},
        )
        if best is None or res.fun < best.fun:
            best = res
    assert best is not None
    return {"mu": float(best.x[0]), "sigma": float(max(best.x[1], 1e-3)), "train_objective": float(best.fun)}


def old_ols_params(train_rows: list[dict[str, Any]]) -> dict[str, float]:
    max_seq: dict[str, int] = {}
    final_margin: dict[str, float] = {}
    for row in train_rows:
        gid = str(row["game_id"])
        seq = int(row["seq"])
        if seq >= max_seq.get(gid, -1):
            max_seq[gid] = seq
            final_margin[gid] = float(row["margin"])
    xs: list[float] = []
    ys: list[float] = []
    for row in train_rows:
        frac = float(row["frac_remaining"])
        if frac <= 1e-6:
            continue
        xs.append(frac)
        ys.append(final_margin[str(row["game_id"])] - float(row["margin"]))
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    mu = float(np.sum(x * y) / np.sum(x * x))
    sigma = float(np.sqrt(np.mean(((y - mu * x) ** 2) / np.maximum(x, 1e-6))))
    return {"mu": mu, "sigma": sigma}


def monotonicity(model: Any, feature_names: list[str], full_margin: bool = True) -> dict[str, Any]:
    margin_failures: list[dict[str, Any]] = []
    margins = range(-60, 61) if full_margin else range(-4, 5)
    for frac in np.linspace(0.0, 1.0, 41):
        x = matrix_for_states(feature_names, margins, frac)
        probs = model.predict_proba(x)[:, 1]
        diffs = np.diff(probs)
        if np.any(diffs < -1e-12):
            idx = int(np.argmin(diffs))
            margin_failures.append({"frac_remaining": float(frac), "margin": int(list(margins)[idx]), "drop": float(diffs[idx])})
    time_failures: list[dict[str, Any]] = []
    for margin in (3, 5, 8, 12, -3, -5, -8, -12):
        fracs = np.asarray([1.0 - i / 40 for i in range(41)], dtype=float)
        x = matrix_for_states(feature_names, [margin] * len(fracs), fracs)
        probs = model.predict_proba(x)[:, 1]
        diffs = np.diff(probs)
        bad = diffs < -1e-12 if margin > 0 else diffs > 1e-12
        if np.any(bad):
            time_failures.append({"margin": margin, "bad_steps": int(np.sum(bad)), "worst": float(np.max(np.abs(diffs[bad])))})
    return {
        "margin": {"passed": not margin_failures, "checked_adjacent_pairs": 40 * (len(list(margins)) - 1), "failures": margin_failures[:5]},
        "time": {"passed": not time_failures, "checked_steps": 8 * 40, "failures": time_failures[:5]},
    }


def matrix_for_states(feature_names: list[str], margins: Iterable[int] | Iterable[float], frac: float | np.ndarray) -> np.ndarray:
    margin_list = list(margins)
    if np.isscalar(frac):
        frac_values = [float(frac)] * len(margin_list)
    else:
        frac_values = [float(v) for v in np.asarray(frac, dtype=float)]
    rows = []
    for margin, f in zip(margin_list, frac_values):
        state = GameState("nba", int(round(margin)), f, 4, False)
        feats = build_features(state)
        rows.append([feats[name] for name in feature_names])
    return np.asarray(rows, dtype=float)


def overtime_metric(rows: list[dict[str, Any]], probs: np.ndarray, name: str) -> dict[str, Any]:
    idx = [i for i, r in enumerate(rows) if int(r["period"]) >= 5]
    if not idx:
        return {"name": name, "n": 0, "brier": None, "log_loss": None}
    return metric_row(name, probs[idx], labels([rows[i] for i in idx]))


def overtime_margin_table(rows: list[dict[str, Any]], probs: np.ndarray) -> list[dict[str, Any]]:
    out = []
    margins = [-2, -1, 0, 1, 2, 3]
    for margin in margins:
        idx = [i for i, r in enumerate(rows) if int(r["period"]) >= 5 and int(r["margin"]) == margin]
        if not idx:
            out.append({"margin": margin, "n": 0})
            continue
        y = labels([rows[i] for i in idx])
        pred = np.asarray(probs[idx], dtype=float)
        out.append(
            {
                "margin": margin,
                "n": len(idx),
                "model_pred": float(np.mean(pred)),
                "actual": float(np.mean(y)),
                "gap": float(np.mean(y) - np.mean(pred)),
            }
        )
    return out


def phase_metrics(rows: list[dict[str, Any]], probs: np.ndarray) -> list[dict[str, Any]]:
    phases = [("1.00-0.75", 0.75, 1.000001), ("0.75-0.50", 0.50, 0.75), ("0.50-0.25", 0.25, 0.50), ("0.25-0.00", -1e-9, 0.25)]
    y = labels(rows)
    frac = np.asarray([float(r["frac_remaining"]) for r in rows])
    out = []
    for label, lo, hi in phases:
        idx = np.where((frac >= lo) & (frac < hi))[0]
        out.append({"phase": label, **metric_row("model", probs[idx], y[idx])})
    return out


def error_diagnostics(rows: list[dict[str, Any]], probs: np.ndarray) -> dict[str, Any]:
    usable = [(r, float(p)) for r, p in zip(rows, probs) if r["espn_home_wp"] is not None]
    y = np.asarray([int(r["home_won"]) for r, _ in usable], dtype=int)
    ours = np.asarray([p for _, p in usable], dtype=float)
    espn = np.asarray([float(r["espn_home_wp"]) for r, _ in usable], dtype=float)
    frac = np.asarray([float(r["frac_remaining"]) for r, _ in usable], dtype=float)
    margin = np.asarray([int(r["margin"]) for r, _ in usable], dtype=int)
    period = np.asarray([int(r["period"]) for r, _ in usable], dtype=int)

    def groups(labels: list[tuple[str, np.ndarray]]) -> list[dict[str, Any]]:
        out = []
        for label, mask in labels:
            if int(mask.sum()) < 100:
                continue
            ours_ll = sklearn_log_loss(y[mask], np.clip(ours[mask], 1e-15, 1 - 1e-15))
            espn_ll = sklearn_log_loss(y[mask], np.clip(espn[mask], 1e-15, 1 - 1e-15))
            out.append(
                {
                    "bucket": label,
                    "n": int(mask.sum()),
                    "ours_brier": float(brier_score_loss(y[mask], ours[mask])),
                    "espn_brier": float(brier_score_loss(y[mask], espn[mask])),
                    "ours_log_loss": float(ours_ll),
                    "espn_log_loss": float(espn_ll),
                    "log_loss_gap_vs_espn": float(ours_ll - espn_ll),
                }
            )
        return sorted(out, key=lambda r: r["log_loss_gap_vs_espn"], reverse=True)

    return {
        "by_time_remaining": groups(
            [
                ("1.00-0.75", (frac >= 0.75) & (frac <= 1.0)),
                ("0.75-0.50", (frac >= 0.50) & (frac < 0.75)),
                ("0.50-0.25", (frac >= 0.25) & (frac < 0.50)),
                ("0.25-0.00", (frac >= 0.0) & (frac < 0.25)),
            ]
        ),
        "by_abs_margin": groups(
            [
                ("0", np.abs(margin) == 0),
                ("1-3", (np.abs(margin) >= 1) & (np.abs(margin) <= 3)),
                ("4-7", (np.abs(margin) >= 4) & (np.abs(margin) <= 7)),
                ("8-12", (np.abs(margin) >= 8) & (np.abs(margin) <= 12)),
                ("13+", np.abs(margin) >= 13),
            ]
        ),
        "by_period": groups([(str(p), period == p) for p in sorted(set(period))]),
    }


def comparable_state(rows: list[dict[str, Any]], probs: np.ndarray) -> dict[str, Any]:
    idx = [
        i
        for i, r in enumerate(rows)
        if 9 <= int(r["margin"]) <= 11 and abs(float(r["frac_remaining"]) - 120 / 2880) <= 36 / 2880
    ]
    if not idx:
        return {"n": 0}
    y = labels([rows[i] for i in idx])
    espn = [float(rows[i]["espn_home_wp"]) for i in idx if rows[i]["espn_home_wp"] is not None]
    return {
        "n": len(idx),
        "actual_home_wins": int(y.sum()),
        "actual_rate": float(y.mean()),
        "model_mean": float(np.mean(probs[idx])),
        "espn_mean": float(np.mean(espn)) if espn else None,
    }


def rounded(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: rounded(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rounded(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def fresh_serving_check() -> dict[str, Any]:
    code = (
        "from app.services.live_winprob import GameState, predict_home_win_prob as f; "
        "print(f(GameState('nba',5,0.4)))"
    )
    raw = subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, text=True)
    return {"raw": raw.strip()}


def score_existing_artifact(test_rows: list[dict[str, Any]]) -> dict[str, Any]:
    path = artifact_path("nba")
    if not path.exists():
        return {"name": "current_artifact", "available": False}
    art = joblib.load(path)
    names = art["feature_names"]
    probs = art["model"].predict_proba(matrix(test_rows, names))[:, 1]
    y = labels(test_rows)
    out = metric_row("current_artifact_rescored_new_holdout", probs, y)
    out["overtime"] = overtime_metric(test_rows, probs, "current_artifact_overtime")
    out["max_calibration_gap"] = max_calibration_gap(probs.tolist(), y.tolist(), bins=10, min_n=100)
    out["artifact_claim_on_old_sample"] = PUBLISHED_OLD_SAMPLE
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-season", type=int, default=2023)
    parser.add_argument("--test-season", type=int, default=2024)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    rows = rows_from_db()
    train = [r for r in rows if int(r["season_start_year"]) == args.train_season]
    test = [r for r in rows if int(r["season_start_year"]) == args.test_season]
    train_ids = {str(r["game_id"]) for r in train}
    test_ids = {str(r["game_id"]) for r in test}
    overlap = train_ids & test_ids
    if not train or not test or overlap:
        raise SystemExit(f"Invalid split: train={len(train)} test={len(test)} overlap={len(overlap)}")

    y_train = labels(train)
    y_test = labels(test)
    x_train_grid = matrix(train, GRID_FEATURES)
    x_test_grid = matrix(test, GRID_FEATURES)
    margin_train = x_train_grid[:, 0]
    frac_train = x_train_grid[:, 1]
    margin_test = x_test_grid[:, 0]
    frac_test = x_test_grid[:, 1]

    current_artifact = score_existing_artifact(test)
    old_ols = old_ols_params(train)
    brier_base = fit_normal(margin_train, frac_train, y_train, "brier")
    log_base = fit_normal(margin_train, frac_train, y_train, "logloss")
    baseline_rows = []
    for name, params in (
        ("old_ols_normal_from_500_game_artifact", OLD_NORMAL_PARAMS),
        ("new_ols_normal_full_2023", old_ols),
        ("refit_normal_fit_by_brier", brier_base),
        ("refit_normal_fit_by_logloss", log_base),
    ):
        probs = normal_vec(margin_test, frac_test, params["mu"], params["sigma"])
        row = metric_row(name, probs, y_test)
        row.update({"mu": params["mu"], "sigma": params["sigma"]})
        baseline_rows.append(row)

    fit_ids, val_ids = validation_split(train, args.seed)
    fit = [r for r in train if str(r["game_id"]) in fit_ids]
    val = [r for r in train if str(r["game_id"]) in val_ids]
    y_fit = labels(fit)
    y_val = labels(val)
    x_fit_grid = matrix(fit, GRID_FEATURES)
    x_val_grid = matrix(val, GRID_FEATURES)

    candidates: list[tuple[str, Any, list[str], str]] = []
    hgb_configs = [
        ("hgb_grid_leaf7_alpha0.2", 0.04, 250, 1.0, 200, 7, 0.2),
        ("hgb_grid_leaf7_alpha0.4", 0.04, 250, 1.0, 200, 7, 0.4),
        ("hgb_grid_leaf15_alpha0.4", 0.03, 350, 0.5, 150, 15, 0.4),
        ("hgb_grid_leaf15_alpha0.6", 0.03, 350, 0.5, 150, 15, 0.6),
        ("hgb_grid_leaf31_alpha0.4", 0.05, 250, 0.1, 80, 31, 0.4),
    ]
    for name, lr, max_iter, l2, min_leaf, max_leaf, alpha in hgb_configs:
        hgb = HistGradientBoostingClassifier(
            max_iter=max_iter,
            learning_rate=lr,
            l2_regularization=l2,
            min_samples_leaf=min_leaf,
            max_leaf_nodes=max_leaf,
            random_state=args.seed,
            monotonic_cst=[1, 0, 0, 0, 0, 1, 1],
            early_stopping=False,
        )
        candidates.append(
            (
                name,
                GridBlendModel(hgb, alpha=alpha, normal_mu=brier_base["mu"], normal_sigma=brier_base["sigma"]),
                GRID_FEATURES,
                "regularized monotone HGB blended with the refit Brier normal baseline and projected to margin/time monotone grid",
            )
        )
    candidates.append(
        (
            "poly2_baseline_correction_alpha0.4_unshipped_diagnostic",
            BaselinePolyCorrectionModel(log_base["mu"], log_base["sigma"], alpha=0.4, c=0.2),
            POLY_FEATURES,
            "smooth polynomial correction to the log-loss normal baseline; included because it scores well but fails margin monotonicity",
        )
    )

    val_results: list[dict[str, Any]] = []
    for name, model, names, notes in candidates:
        model.fit(matrix(fit, names), y_fit)
        probs = model.predict_proba(matrix(val, names))[:, 1]
        m = metric_row(name, probs, y_val)
        mono = monotonicity(model, names)
        m.update(
            {
                "feature_names": names,
                "max_calibration_gap": max_calibration_gap(probs.tolist(), y_val.tolist(), bins=10, min_n=100),
                "monotone_margin": mono["margin"]["passed"],
                "monotone_time": mono["time"]["passed"],
                "monotonicity": mono,
                "notes": notes,
            }
        )
        val_results.append(m)

    val_baseline_logloss = metric_row(
        "validation_refit_normal_fit_by_logloss",
        normal_vec(x_val_grid[:, 0], x_val_grid[:, 1], log_base["mu"], log_base["sigma"]),
        y_val,
    )
    eligible = [r for r in val_results if r["monotone_margin"] and r["monotone_time"] and r["log_loss"] < val_baseline_logloss["log_loss"]]
    if not eligible:
        selected_name = "refit_normal_fit_by_logloss"
    else:
        # The known NBA weakness is Brier, so among validation candidates that clear
        # monotonicity and log-loss-vs-baseline, choose validation Brier first.
        selected_name = min(eligible, key=lambda r: (r["brier"], r["log_loss"]))["name"]
    selected_template = next((c for c in candidates if c[0] == selected_name), None)
    if selected_template is None:
        raise SystemExit("No learned model beat the refit baseline on validation log loss.")

    _, selected_model, selected_features, _ = selected_template
    selected_model.fit(x_train_grid if selected_features == GRID_FEATURES else matrix(train, selected_features), y_train)
    test_probs = selected_model.predict_proba(x_test_grid if selected_features == GRID_FEATURES else matrix(test, selected_features))[:, 1]
    final = metric_row("selected_model", test_probs, y_test)
    final["overtime"] = overtime_metric(test, test_probs, "selected_model_overtime")
    final["max_calibration_gap"] = max_calibration_gap(test_probs.tolist(), y_test.tolist(), bins=10, min_n=100)
    final_mono = monotonicity(selected_model, selected_features)

    espn_rows = [r for r in test if r["espn_home_wp"] is not None]
    espn_probs = np.asarray([float(r["espn_home_wp"]) for r in espn_rows], dtype=float)
    espn_metric = metric_row("espn", espn_probs, labels(espn_rows))

    logloss_baseline = next(r for r in baseline_rows if r["name"] == "refit_normal_fit_by_logloss")
    brier_baseline = next(r for r in baseline_rows if r["name"] == "refit_normal_fit_by_brier")
    should_ship = (
        final["log_loss"] < logloss_baseline["log_loss"]
        and final_mono["margin"]["passed"]
        and final_mono["time"]["passed"]
    )

    artifact = {
        "model": selected_model,
        "feature_names": list(selected_features),
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "train_seasons": [args.train_season],
        "test_seasons": [args.test_season],
        "n_games": {"train": len(train_ids), "test": len(test_ids), "total": len(train_ids | test_ids)},
        "n_snapshots": {"train": len(train), "test": len(test), "total": len(train) + len(test)},
        "brier": final["brier"],
        "log_loss": final["log_loss"],
        "max_calibration_gap": final["max_calibration_gap"],
        "notes": (
            "Trained on full 2023 NBA coverage and tested once on 2024. Model is a regularized HGB blended "
            "with the refit analytic normal baseline and projected on a precomputed margin/time monotone grid. "
            "It beats the refit analytic baseline on held-out log loss but not Brier."
        ),
        "validation": {
            "selection_rule": "Among candidates that beat the validation log-loss baseline and pass margin/time monotonicity, choose lowest validation Brier, then log loss.",
            "selected_model": selected_name,
            "validation_split": {
                "type": "stratified_game_level_split_within_2023",
                "seed": args.seed,
                "fit_games": len(fit_ids),
                "validation_games": len(val_ids),
                "fit_snapshots": len(fit),
                "validation_snapshots": len(val),
            },
            "fixed_holdout_split": {
                "train_seasons": [args.train_season],
                "test_seasons": [args.test_season],
                "train_games": len(train_ids),
                "test_games": len(test_ids),
                "train_snapshots": len(train),
                "test_snapshots": len(test),
                "game_id_overlap": len(overlap),
            },
            "current_artifact_rescored": current_artifact,
            "normal_baselines": baseline_rows,
            "validation_baseline": val_baseline_logloss,
            "candidates": val_results,
            "holdout_metrics": final,
            "overtime_margin_calibration": overtime_margin_table(test, test_probs),
            "espn": espn_metric,
            "monotonicity": final_mono,
            "phase_breakdown": phase_metrics(test, test_probs),
            "error_diagnostics_vs_espn": error_diagnostics(test, test_probs),
            "late_plus_9_to_11_correction_state": comparable_state(test, test_probs),
            "brier_gate_vs_refit_brier_baseline": {
                "passed": final["brier"] < brier_baseline["brier"],
                "model_brier": final["brier"],
                "baseline_brier": brier_baseline["brier"],
            },
            "overwrote_artifact": should_ship,
        },
    }

    path = artifact_path("nba")
    if should_ship:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(artifact, path)
        artifact["validation"]["serving_check"] = fresh_serving_check()
        joblib.dump(artifact, path)

    print(json.dumps(rounded(artifact["validation"]), indent=2, sort_keys=True))
    print(f"Saved improved artifact: {path}" if should_ship else f"Did not overwrite artifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
