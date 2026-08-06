from __future__ import annotations

import json
import importlib
import math
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
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

DB_PATH = ROOT / "data" / "live_wp" / "nfl_situation.db"
LEGACY_DB_PATH = ROOT / "data" / "live_wp" / "nfl_snapshots.db"
NORMAL_MU = 0.0
NORMAL_SIGMA = 13.5
ROUND1_BRIER = 0.166640
ROUND1_LOG_LOSS = 0.490719
PUBLISHED_BRIER = 0.164034
PUBLISHED_LOG_LOSS = 0.479629


@dataclass(frozen=True)
class Candidate:
    name: str
    feature_names: list[str]
    build: Callable[[], Any]
    calibration: str | None = None
    use_situation: bool = False
    augment_missing_situation: bool = False
    missing_situation_copies: int = 0
    wrapper_alpha: float = 0.5
    margin_window: int = 0


class MonotoneBlendModel:
    """Blend a learned model with the normal baseline, then monotone-envelope time."""

    def __init__(
        self,
        base_model: Any,
        feature_names: list[str],
        league: str,
        alpha: float,
        normal_mu: float,
        normal_sigma: float,
        time_grid_size: int = 41,
        margin_min: int | None = None,
        margin_max: int | None = None,
        margin_window: int = 4,
    ) -> None:
        self.base_model = base_model
        self.feature_names = list(feature_names)
        self.league = league
        self.alpha = float(alpha)
        self.normal_mu = float(normal_mu)
        self.normal_sigma = float(normal_sigma)
        self.time_grid = np.linspace(0.0, 1.0, int(time_grid_size))
        self.margin_min = margin_min
        self.margin_max = margin_max
        self.margin_window = int(margin_window)
        self.classes_ = np.array([0, 1])
        self._cache: dict[tuple[float, ...], float] = {}

    def _with_frac(self, row: np.ndarray, frac: float) -> list[float]:
        values = {name: float(row[i]) for i, name in enumerate(self.feature_names)}
        margin = values["margin"]
        values["frac_remaining"] = frac
        if "margin_scaled" in values:
            values["margin_scaled"] = margin / math.sqrt(frac + 1e-6)
        if "pregame_logit_decay" in values and "pregame_logit" in values:
            values["pregame_logit_decay"] = values["pregame_logit"] * frac
        return [values[name] for name in self.feature_names]

    def _blend_prob(self, row: np.ndarray, frac: float) -> float:
        values = {name: float(row[i]) for i, name in enumerate(self.feature_names)}
        vector = self._with_frac(row, frac)
        key = tuple(round(float(v), 8) for v in vector)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        base = float(self.base_model.predict_proba([vector])[0][1])
        margin = float(vector[self.feature_names.index("margin")])
        normal = baseline_normal(GameState(league=self.league, margin=int(round(margin)), frac_remaining=frac), self.normal_mu, self.normal_sigma)
        prob = (1.0 - self.alpha) * base + self.alpha * normal
        self._cache[key] = prob
        return prob

    def _time_envelope(self, row: np.ndarray, margin: int, frac: float) -> float:
        if margin == 0:
            return self._blend_prob(row, frac)
        grid = [frac, *[float(f) for f in self.time_grid if f >= frac - 1e-12]]
        vals = [self._blend_prob(row, f) for f in grid]
        return max(vals) if margin > 0 else min(vals)

    def _predict_one(self, row: np.ndarray) -> float:
        values = {name: float(row[i]) for i, name in enumerate(self.feature_names)}
        margin = int(round(values["margin"]))
        frac = min(max(float(values.get("frac_remaining", 1.0)), 0.0), 1.0)
        candidate_margins = range(margin - self.margin_window, margin + 1)

        margin_idx = self.feature_names.index("margin")
        vectors = []
        groups = []
        for candidate_margin in candidate_margins:
            candidate = row.copy()
            candidate[margin_idx] = float(candidate_margin)
            if candidate_margin == 0:
                fracs = [frac]
            else:
                fracs = [frac, *[float(f) for f in self.time_grid if f >= frac - 1e-12]]
            for candidate_frac in fracs:
                vectors.append(self._with_frac(candidate, candidate_frac))
                groups.append(candidate_margin)

        base_probs = self.base_model.predict_proba(vectors)[:, 1]
        blended: dict[int, list[float]] = {}
        for vector, group, base_prob in zip(vectors, groups, base_probs):
            vector_margin = float(vector[margin_idx])
            vector_frac = float(vector[self.feature_names.index("frac_remaining")])
            normal = baseline_normal(
                GameState(league=self.league, margin=int(round(vector_margin)), frac_remaining=vector_frac),
                self.normal_mu,
                self.normal_sigma,
            )
            blended.setdefault(group, []).append((1.0 - self.alpha) * float(base_prob) + self.alpha * normal)

        enveloped = []
        for candidate_margin, probs in blended.items():
            if candidate_margin > 0:
                enveloped.append(max(probs))
            elif candidate_margin < 0:
                enveloped.append(min(probs))
            else:
                enveloped.append(probs[0])
        return max(enveloped)

    def predict_proba(self, X: Any) -> np.ndarray:
        arr = np.asarray(X, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        chunks = [self._predict_batch(arr[i : i + 500]) for i in range(0, len(arr), 500)]
        probs = np.concatenate(chunks) if chunks else np.array([])
        probs = np.clip(probs, 1e-6, 1.0 - 1e-6)
        return np.column_stack([1.0 - probs, probs])

    def _predict_batch(self, arr: np.ndarray) -> np.ndarray:
        margin_idx = self.feature_names.index("margin")
        frac_idx = self.feature_names.index("frac_remaining")
        vectors: list[list[float]] = []
        meta: list[tuple[int, int]] = []
        for row_idx, row in enumerate(arr):
            margin = int(round(float(row[margin_idx])))
            frac = min(max(float(row[frac_idx]), 0.0), 1.0)
            for candidate_margin in range(margin - self.margin_window, margin + 1):
                candidate = row.copy()
                candidate[margin_idx] = float(candidate_margin)
                fracs = [frac] if candidate_margin == 0 else [
                    frac,
                    *[float(f) for f in self.time_grid if f >= frac - 1e-12],
                ]
                for candidate_frac in fracs:
                    vectors.append(self._with_frac(candidate, candidate_frac))
                    meta.append((row_idx, candidate_margin))
        base_probs = self.base_model.predict_proba(vectors)[:, 1]
        enveloped: dict[tuple[int, int], float] = {}
        for vector, (row_idx, candidate_margin), base_prob in zip(vectors, meta, base_probs):
            vector_frac = float(vector[frac_idx])
            normal = baseline_normal(
                GameState(league=self.league, margin=int(round(float(vector[margin_idx]))), frac_remaining=vector_frac),
                self.normal_mu,
                self.normal_sigma,
            )
            prob = (1.0 - self.alpha) * float(base_prob) + self.alpha * normal
            key = (row_idx, candidate_margin)
            if key not in enveloped:
                enveloped[key] = prob
            elif candidate_margin > 0:
                enveloped[key] = max(enveloped[key], prob)
            elif candidate_margin < 0:
                enveloped[key] = min(enveloped[key], prob)

        out = np.zeros(len(arr), dtype=float)
        grouped: dict[int, list[float]] = {}
        for (row_idx, _candidate_margin), prob in enveloped.items():
            grouped.setdefault(row_idx, []).append(prob)
        for row_idx, probs in grouped.items():
            out[row_idx] = max(probs)
        return out


def rows(path: Path = DB_PATH) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(snapshots)")}
    if "season" in cols:
        query = """
            SELECT s.*, g.game_date
            FROM snapshots s
            LEFT JOIN games g ON g.game_id = s.game_id
            ORDER BY s.season, s.game_id, s.frac_remaining DESC
        """
        out = [dict(r) for r in conn.execute(query)]
    else:
        out = [dict(r) for r in conn.execute("SELECT * FROM snapshots ORDER BY game_id, frac_remaining DESC")]
    conn.close()
    if not out:
        raise SystemExit(f"No snapshots found in {path}. Run the NFL harvest first.")
    return out


def game_state(row: dict, use_situation: bool = True) -> GameState:
    situation: dict[str, Any] = {}
    if use_situation and row.get("offense_is_home") is not None:
        situation = {
            "offense_is_home": bool(row["offense_is_home"]),
            "down": int(row["down"]) if row.get("down") is not None else None,
            "distance": int(row["distance"]) if row.get("distance") is not None else None,
            "yards_to_endzone": int(row["yards_to_endzone"]) if row.get("yards_to_endzone") is not None else None,
        }
    return GameState(
        league="nfl",
        margin=int(row["margin"]),
        frac_remaining=float(row["frac_remaining"]),
        period=int(row["period"]),
        is_overtime=int(row["period"]) > 4,
        **situation,
    )


def matrix(data: list[dict], feature_names: list[str], use_situation: bool = True) -> list[list[float]]:
    out = []
    for row in data:
        feats = build_features(game_state(row, use_situation=use_situation))
        out.append([feats[name] for name in feature_names])
    return out


def outcomes(data: list[dict]) -> list[int]:
    return [int(r["home_won"]) for r in data]


def model_probs(model: Any, data: list[dict], feature_names: list[str], use_situation: bool = True) -> list[float]:
    return [float(p) for p in model.predict_proba(matrix(data, feature_names, use_situation=use_situation))[:, 1]]


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
    fit_x = matrix(fit, candidate.feature_names, use_situation=candidate.use_situation)
    fit_y = outcomes(fit)
    if candidate.augment_missing_situation:
        missing_x = matrix(fit, candidate.feature_names, use_situation=False)
        for _ in range(candidate.missing_situation_copies):
            fit_x.extend(missing_x)
            fit_y.extend(outcomes(fit))
    model.fit(fit_x, fit_y)
    if candidate.calibration is None:
        return model
    if not calibration:
        raise ValueError(f"{candidate.name} requested calibration but no calibration data was supplied")
    calibrated = CalibratedClassifierCV(FrozenEstimator(model), method=candidate.calibration)
    calibrated.fit(matrix(calibration, candidate.feature_names, use_situation=candidate.use_situation), outcomes(calibration))
    return calibrated


def score_model(model: Any, data: list[dict], feature_names: list[str], use_situation: bool = True) -> dict[str, Any]:
    ys = outcomes(data)
    probs = model_probs(model, data, feature_names, use_situation=use_situation)
    return {
        **metric_block(probs, ys),
        "max_calibration_gap": round(max_calibration_gap(probs, ys, bins=10, min_n=30), 6),
        "calibration_table": calibration_table(probs, ys, bins=10),
    }


def predict_state(
    model: Any,
    feature_names: list[str],
    margin: int,
    frac_remaining: float,
    *,
    offense_is_home: bool | None = None,
    down: int | None = None,
    distance: int | None = None,
    yards_to_endzone: int | None = None,
) -> float:
    feats = build_features(
        GameState(
            league="nfl",
            margin=margin,
            frac_remaining=frac_remaining,
            offense_is_home=offense_is_home,
            down=down,
            distance=distance,
            yards_to_endzone=yards_to_endzone,
        )
    )
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


def monotonicity_checks(model: Any, feature_names: list[str]) -> dict[str, Any]:
    scenarios = {
        "unobserved": {},
        "home_1st_10_midfield": {
            "offense_is_home": True,
            "down": 1,
            "distance": 10,
            "yards_to_endzone": 50,
        },
        "away_1st_10_red_zone": {
            "offense_is_home": False,
            "down": 1,
            "distance": 10,
            "yards_to_endzone": 20,
        },
    }
    scenario_results = {name: _monotonicity_checks_one(model, feature_names, kwargs) for name, kwargs in scenarios.items()}
    return {
        "scenarios": scenario_results,
        "passed": all(result["passed"] for result in scenario_results.values()),
    }


def _monotonicity_checks_one(model: Any, feature_names: list[str], state_kwargs: dict[str, Any]) -> dict[str, Any]:
    time_margins = [1, 3, 4, 7, 10, 14, -1, -3, -4, -7, -10, -14]
    time_results = {}
    for margin in time_margins:
        vals = [predict_state(model, feature_names, margin, 1.0 - i / 40, **state_kwargs) for i in range(41)]
        deltas = [vals[i + 1] - vals[i] for i in range(40)]
        if margin > 0:
            bad = [d for d in deltas if d < -1e-12]
        else:
            bad = [d for d in deltas if d > 1e-12]
        time_results[str(margin)] = {
            "drops_or_wrong_way_steps": len(bad),
            "worst_wrong_way_delta": round((min(bad) if margin > 0 and bad else max(bad) if bad else 0.0), 8),
            "start": round(vals[0], 6),
            "end": round(vals[-1], 6),
        }

    margin_drops = 0
    worst_margin_drop = 0.0
    for i in range(41):
        frac = i / 40
        previous = None
        for margin in range(-28, 29):
            prob = predict_state(model, feature_names, margin, frac, **state_kwargs)
            if previous is not None and prob < previous - 1e-12:
                margin_drops += 1
                worst_margin_drop = min(worst_margin_drop, prob - previous)
            previous = prob

    return {
        "time": time_results,
        "margin": {"drops": margin_drops, "worst_drop": round(worst_margin_drop, 8)},
        "passed": margin_drops == 0 and all(row["drops_or_wrong_way_steps"] == 0 for row in time_results.values()),
    }


def phase_breakdown(model: Any, data: list[dict], feature_names: list[str], use_situation: bool = True) -> dict[str, Any]:
    ys = outcomes(data)
    probs = model_probs(model, data, feature_names, use_situation=use_situation)
    states = [game_state(r, use_situation=use_situation) for r in data]
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


def evaluate(model: Any, data: list[dict], feature_names: list[str], use_situation: bool = True) -> dict[str, Any]:
    ys = outcomes(data)
    probs = model_probs(model, data, feature_names, use_situation=use_situation)
    states = [game_state(r, use_situation=use_situation) for r in data]
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
        "phase_breakdown": phase_breakdown(model, data, feature_names, use_situation=use_situation),
        "sanity_checks": sanity_checks(model, feature_names),
        "monotonicity_checks": monotonicity_checks(model, feature_names),
    }


def candidates() -> list[Candidate]:
    return [
        Candidate(
            "legacy_poly3_margin_time_full_recipe",
            ["margin", "margin_scaled", "frac_remaining"],
            lambda: make_pipeline(
                StandardScaler(),
                PolynomialFeatures(degree=3, include_bias=False),
                StandardScaler(),
                LogisticRegression(max_iter=5000, C=0.1, solver="lbfgs"),
            ),
            wrapper_alpha=0.5,
        ),
        Candidate(
            "poly3_logistic_margin_time_situation_full_recipe_alpha_675",
            [
                "margin",
                "margin_scaled",
                "frac_remaining",
                "pregame_logit",
                "pregame_logit_decay",
                "offense_is_home",
                "down",
                "distance",
                "yards_to_endzone",
                "field_position_home",
                "situation_known",
            ],
            lambda: make_pipeline(
                StandardScaler(),
                PolynomialFeatures(degree=3, include_bias=False),
                StandardScaler(),
                LogisticRegression(max_iter=5000, C=0.01, solver="lbfgs"),
            ),
            use_situation=True,
            augment_missing_situation=True,
            missing_situation_copies=2,
            wrapper_alpha=0.675,
            margin_window=4,
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
    wrapper_cls = (
        MonotoneBlendModel
        if __name__ != "__main__"
        else importlib.import_module("scripts.live_wp.train_nfl").MonotoneBlendModel
    )
    for candidate in candidates():
        base_model = fit_candidate(candidate, fit, calibration)
        model = wrapper_cls(
            base_model,
            candidate.feature_names,
            league="nfl",
            alpha=candidate.wrapper_alpha,
            normal_mu=NORMAL_MU,
            normal_sigma=NORMAL_SIGMA,
            margin_window=candidate.margin_window,
        )
        validation = score_model(model, validation_rows, candidate.feature_names, use_situation=candidate.use_situation)
        dev_sanity = sanity_checks(model, candidate.feature_names)
        dev_monotonicity = monotonicity_checks(model, candidate.feature_names)
        full_base_model = fit_candidate(candidate, train, calibration if candidate.calibration else None)
        full_model = wrapper_cls(
            full_base_model,
            candidate.feature_names,
            league="nfl",
            alpha=candidate.wrapper_alpha,
            normal_mu=NORMAL_MU,
            normal_sigma=NORMAL_SIGMA,
            margin_window=candidate.margin_window,
        )
        full_sanity = sanity_checks(full_model, candidate.feature_names)
        full_monotonicity = monotonicity_checks(full_model, candidate.feature_names)
        rejected_reason = None
        if not all(dev_sanity["passed"].values()):
            rejected_reason = "failed development-split sanity checks"
        elif not dev_monotonicity["passed"]:
            rejected_reason = "failed development-split monotonicity checks"
        elif not all(full_sanity["passed"].values()):
            rejected_reason = "failed full-train sanity checks before test evaluation"
        elif not full_monotonicity["passed"]:
            rejected_reason = "failed full-train monotonicity checks before test evaluation"
        experiment_results.append(
            {
                "name": candidate.name,
                "feature_names": candidate.feature_names,
                "calibration": candidate.calibration,
                "use_situation": candidate.use_situation,
                "augment_missing_situation": candidate.augment_missing_situation,
                "missing_situation_copies": candidate.missing_situation_copies,
                "wrapper_alpha": candidate.wrapper_alpha,
                "margin_window": candidate.margin_window,
                "validation": validation,
                "development_sanity": dev_sanity,
                "development_monotonicity": dev_monotonicity,
                "full_train_sanity": full_sanity,
                "full_train_monotonicity": full_monotonicity,
                "rejected_reason": rejected_reason,
            }
        )
        if rejected_reason is None:
            full_train_models.append((candidate, full_model, validation))

    if not full_train_models:
        raise SystemExit("No candidate passed sanity checks.")

    # Select on the 2023-only development split before the 2024 holdout is
    # touched. Log loss is the primary shipping objective.
    selected_candidate, selected_model, selected_validation = min(
        full_train_models,
        key=lambda item: (
            not item[0].use_situation,
            item[2]["log_loss"],
            item[2]["brier"],
            item[2]["max_calibration_gap"],
        ),
    )
    final = evaluate(selected_model, test, selected_candidate.feature_names, use_situation=selected_candidate.use_situation)
    like_for_like = {
        candidate.name: evaluate(model, test, candidate.feature_names, use_situation=candidate.use_situation)["model"]
        for candidate, model, _validation in full_train_models
    }
    old_feature_scores = [
        score
        for candidate, _model, _validation in full_train_models
        if not candidate.use_situation
        for name, score in like_for_like.items()
        if name == candidate.name
    ]
    if not old_feature_scores:
        old_candidate = next(candidate for candidate in candidates() if not candidate.use_situation)
        old_base = fit_candidate(old_candidate, train, calibration if old_candidate.calibration else None)
        old_model = wrapper_cls(
            old_base,
            old_candidate.feature_names,
            league="nfl",
            alpha=old_candidate.wrapper_alpha,
            normal_mu=NORMAL_MU,
            normal_sigma=NORMAL_SIGMA,
            margin_window=old_candidate.margin_window,
        )
        old_score = evaluate(old_model, test, old_candidate.feature_names, use_situation=False)["model"]
        like_for_like[f"{old_candidate.name}_full_train_reference"] = old_score
        old_feature_scores.append(old_score)
    old_feature_log_loss = min(score["log_loss"] for score in old_feature_scores)
    legacy_data = rows(LEGACY_DB_PATH)
    legacy_test = [r for r in legacy_data if int(r["season"]) == 2024]
    original_db_evaluation = evaluate(selected_model, legacy_test, selected_candidate.feature_names, use_situation=False)
    better_than_published = (
        final["model"]["log_loss"] < PUBLISHED_LOG_LOSS
        and final["model"]["log_loss"] < old_feature_log_loss
        and all(final["sanity_checks"]["passed"].values())
        and final["monotonicity_checks"]["passed"]
    )

    bundle = {
        "model": selected_model,
        "feature_names": selected_candidate.feature_names,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_games": len({r["game_id"] for r in data}),
        "n_snapshots": len(data),
        "brier": original_db_evaluation["model"]["brier"],
        "log_loss": original_db_evaluation["model"]["log_loss"],
        "train_seasons": [2023],
        "test_seasons": [2024],
        "validation": {
            **final,
            "selected_model": selected_candidate.name,
            "post_processor": (
                f"{selected_candidate.wrapper_alpha:.0%} blend with normal baseline plus time monotone envelope"
            ),
            "selected_validation": selected_validation,
            "like_for_like_situation_db": like_for_like,
            "original_nfl_snapshots_db_evaluation": original_db_evaluation,
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
                "data": str(DB_PATH.relative_to(ROOT)),
                "legacy_comparison_data": str(LEGACY_DB_PATH.relative_to(ROOT)),
            },
        },
        "notes": (
            "NFL round-4 live WP adds observed possession, down, distance, and field position to the "
            "round-3 margin/time recipe. Training augments situational rows with missing-situation copies "
            "so live payloads without a situation block degrade to the legacy surface instead of extrapolating. "
            "ESPN WP is benchmark-only and remains better."
        ),
    }

    saved = False
    path = artifact_path("nfl")
    if better_than_published:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, path)
        saved = True

    print(json.dumps(bundle["validation"], indent=2, sort_keys=True))
    print(f"selected={selected_candidate.name}")
    print(f"better_than_published={better_than_published}")
    print(f"saved={saved} path={path}")
    if saved:
        prob, meta = predict_home_win_prob(GameState(league="nfl", margin=7, frac_remaining=0.2))
        print(f"same_process_serving_check_margin7_frac0.2={prob} available={meta.get('available')}")


if __name__ == "__main__":
    main()
