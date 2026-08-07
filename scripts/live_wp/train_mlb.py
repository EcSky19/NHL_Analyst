from __future__ import annotations

import json
import importlib
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.live_winprob import (
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
    predict_home_win_prob,
)

DB_PATH = ROOT / "data" / "live_wp" / "mlb_snapshots.db"
NORMAL_MU = 0.25
NORMAL_SIGMA = 4.5
BLEND_ALPHA = 0.5
BLEND_ALPHA_POWER = 0.5
MAX_TRAIN_SNAPSHOTS_PER_GAME = 120
CURRENT_BRIER = 0.157857
CURRENT_LOG_LOSS = 0.470732
MLB_FEATURE_NAMES = list(FEATURE_NAMES)


class MonotoneBlendModel:
    """Blend a learned model with the normal baseline, then enforce monotone grids."""

    def __init__(
        self,
        base_model,
        feature_names: list[str],
        league: str,
        alpha: float,
        normal_mu: float,
        normal_sigma: float,
        alpha_power: float = 0.0,
        time_grid_size: int = 401,
        margin_min: int | None = None,
        margin_max: int | None = None,
    ) -> None:
        self.base_model = base_model
        self.feature_names = list(feature_names)
        self.league = league
        self.alpha = float(alpha)
        self.alpha_power = float(alpha_power)
        self.normal_mu = float(normal_mu)
        self.normal_sigma = float(normal_sigma)
        self.time_grid = np.linspace(0.0, 1.0, int(time_grid_size))
        self.margin_min = margin_min
        self.margin_max = margin_max
        self.classes_ = np.array([0, 1])
        self._cache: dict[tuple[float, ...], float] = {}
        self._surface_cache: dict[tuple[float, tuple[float, ...]], np.ndarray] = {}

    def _normal_prob(self, margin: int, frac: float) -> float:
        frac = min(max(float(frac), 0.0), 1.0)
        if frac <= 1e-6:
            return 1.0 if margin > 0 else (0.0 if margin < 0 else 0.5)
        mean = margin + self.normal_mu * frac
        sd = max(self.normal_sigma * math.sqrt(frac), 1e-6)
        return 0.5 * (1.0 + math.erf(mean / (sd * math.sqrt(2.0))))

    def _alpha_for_frac(self, frac: float) -> float:
        frac = min(max(float(frac), 0.0), 1.0)
        alpha_power = float(getattr(self, "alpha_power", 0.0))
        if alpha_power <= 0.0:
            return self.alpha
        return self.alpha * (frac**alpha_power)

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
        vector = self._with_frac(row, frac)
        key = tuple(round(float(v), 8) for v in vector)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        base = float(self.base_model.predict_proba([vector])[0][1])
        margin = float(vector[self.feature_names.index("margin")])
        normal = self._normal_prob(int(round(margin)), frac)
        alpha = self._alpha_for_frac(frac)
        prob = (1.0 - alpha) * base + alpha * normal
        self._cache[key] = prob
        return prob

    def _time_envelope(self, row: np.ndarray, margin: int, frac: float) -> float:
        if margin == 0:
            return self._blend_prob(row, frac)
        grid = [float(f) for f in self.time_grid if f >= frac - 1e-12]
        vals = [self._blend_prob(row, f) for f in grid]
        return max(vals) if margin > 0 else min(vals)

    def _batch_time_envelopes(self, candidates: list[tuple[np.ndarray, int]], frac: float) -> list[float]:
        matrix = []
        slices = []
        normal_inputs = []
        start = 0
        for row, margin in candidates:
            grid = [frac] if margin == 0 else [float(f) for f in self.time_grid if f >= frac - 1e-12]
            for grid_frac in grid:
                matrix.append(self._with_frac(row, grid_frac))
                normal_inputs.append((margin, grid_frac))
            stop = start + len(grid)
            slices.append((margin, start, stop))
            start = stop

        base_probs = self.base_model.predict_proba(matrix)[:, 1]
        normal_probs = np.array(
            [self._normal_prob(int(round(margin)), grid_frac) for margin, grid_frac in normal_inputs],
            dtype=float,
        )
        alphas = np.array([self._alpha_for_frac(grid_frac) for _margin, grid_frac in normal_inputs], dtype=float)
        blended = (1.0 - alphas) * base_probs + alphas * normal_probs

        out = []
        for margin, start, stop in slices:
            vals = blended[start:stop]
            if margin > 0:
                out.append(float(np.max(vals)))
            elif margin < 0:
                out.append(float(np.min(vals)))
            else:
                out.append(float(vals[0]))
        return out

    def _predict_one(self, row: np.ndarray) -> float:
        values = {name: float(row[i]) for i, name in enumerate(self.feature_names)}
        margin = int(round(values["margin"]))
        frac = min(max(float(values.get("frac_remaining", 1.0)), 0.0), 1.0)
        surface_prob = self._surface_predict(values, margin, frac)
        if surface_prob is not None:
            return surface_prob
        if self.margin_min is None or self.margin_max is None:
            return self._batch_time_envelopes([(row, margin)], frac)[0]

        candidates = []
        for candidate_margin in range(self.margin_min, min(margin, self.margin_max) + 1):
            candidate = row.copy()
            candidate[self.feature_names.index("margin")] = float(candidate_margin)
            candidates.append((candidate, candidate_margin))
        if margin > self.margin_max:
            candidates.append((row, margin))
        if not candidates:
            candidates.append((row, margin))
        probs = self._batch_time_envelopes(candidates, frac)
        return max(probs)

    def _surface_predict(self, values: dict[str, float], margin: int, frac: float) -> float | None:
        if self.margin_min is None or self.margin_max is None:
            return None
        if margin < self.margin_min or margin > self.margin_max:
            return None
        if self.feature_names != FEATURE_NAMES:
            return None
        if abs(values.get("pregame_logit", 0.0)) > 1e-12:
            return None

        grid = tuple(float(f) for f in self.time_grid)
        grid_idx = int(np.searchsorted(grid, frac - 1e-12, side="left"))
        if grid_idx >= len(grid):
            return None

        overtime = float(values.get("is_overtime", 0.0))
        key = (overtime, grid)
        surface_cache = getattr(self, "_surface_cache", None)
        if surface_cache is None:
            self._surface_cache = {}
            surface_cache = self._surface_cache
        surface = surface_cache.get(key)
        if surface is None:
            surface = self._build_surface(overtime)
            surface_cache[key] = surface

        margin_idx = margin - self.margin_min
        return float(surface[margin_idx, grid_idx])

    def _build_surface(self, overtime: float) -> np.ndarray:
        margins = list(range(int(self.margin_min), int(self.margin_max) + 1))
        grid = [float(f) for f in self.time_grid]
        matrix = []
        normal_inputs = []
        for margin in margins:
            for frac in grid:
                values = {
                    "margin": float(margin),
                    "margin_scaled": float(margin) / math.sqrt(frac + 1e-6),
                    "frac_remaining": frac,
                    "pregame_logit": 0.0,
                    "pregame_logit_decay": 0.0,
                    "is_overtime": overtime,
                }
                matrix.append([values[name] for name in self.feature_names])
                normal_inputs.append((margin, frac))

        base_probs = self.base_model.predict_proba(matrix)[:, 1]
        normal_probs = np.array(
            [self._normal_prob(margin, frac) for margin, frac in normal_inputs],
            dtype=float,
        )
        alphas = np.array([self._alpha_for_frac(frac) for _margin, frac in normal_inputs], dtype=float)
        blended = ((1.0 - alphas) * base_probs + alphas * normal_probs).reshape(len(margins), len(grid))

        time_enveloped = np.empty_like(blended)
        for i, margin in enumerate(margins):
            if margin > 0:
                time_enveloped[i] = np.maximum.accumulate(blended[i, ::-1])[::-1]
            elif margin < 0:
                time_enveloped[i] = np.minimum.accumulate(blended[i, ::-1])[::-1]
            else:
                time_enveloped[i] = blended[i]

        return np.maximum.accumulate(time_enveloped, axis=0)

    def predict_proba(self, X) -> np.ndarray:
        arr = np.asarray(X, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        probs = np.empty(arr.shape[0], dtype=float)
        seen: dict[tuple[float, ...], float] = {}
        for i, row in enumerate(arr):
            key = tuple(float(v) for v in row)
            prob = seen.get(key)
            if prob is None:
                prob = self._predict_one(row)
                seen[key] = prob
            probs[i] = prob
        probs = np.clip(probs, 1e-6, 1.0 - 1e-6)
        return np.column_stack([1.0 - probs, probs])


def rows() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    out = [
        dict(r)
        for r in conn.execute(
            """
            SELECT * FROM snapshots
            ORDER BY season, game_id, snapshot_index
            """
        )
    ]
    conn.close()
    if not out:
        raise SystemExit(f"No snapshots found in {DB_PATH}. Run harvest_mlb.py first.")
    return out


def state(row: dict) -> GameState:
    period = int(row["period"])
    raw_outs = row.get("outs")
    try:
        raw_outs_int = int(raw_outs) if raw_outs is not None else None
    except (TypeError, ValueError):
        raw_outs_int = None
    outs = raw_outs_int if raw_outs_int in (0, 1, 2) else None
    return GameState(
        league="mlb",
        margin=int(row["margin"]),
        frac_remaining=float(row["frac_remaining"]),
        period=period,
        is_overtime=period > 9,
        outs=outs,
    )


def vector(row: dict, feature_names: list[str] = MLB_FEATURE_NAMES) -> list[float]:
    feats = build_features(state(row))
    return [feats[name] for name in feature_names]


def outcomes(data: list[dict]) -> list[int]:
    return [int(r["home_won"]) for r in data]


def probs_for_model(model, data: list[dict]) -> list[float]:
    return [float(p) for p in model.predict_proba([vector(r, model.feature_names) for r in data])[:, 1]]


def metric_block(probs: list[float], ys: list[int]) -> dict:
    return {
        "brier": round(brier_score(probs, ys), 6),
        "log_loss": round(log_loss(probs, ys), 6),
    }


def predict_state(model, margin: int, frac_remaining: float) -> float:
    feats = build_features(GameState(league="mlb", margin=margin, frac_remaining=frac_remaining))
    return float(model.predict_proba([[feats[name] for name in model.feature_names]])[0][1])


def monotonicity_checks(model) -> dict:
    time_margins = [1, 2, 3, 5, -1, -2, -3, -5]
    time_results = {}
    for margin in time_margins:
        vals = [predict_state(model, margin, 1.0 - i / 40) for i in range(41)]
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
        for margin in range(-10, 11):
            prob = predict_state(model, margin, frac)
            if previous is not None and prob < previous - 1e-12:
                margin_drops += 1
                worst_margin_drop = min(worst_margin_drop, prob - previous)
            previous = prob

    return {
        "time": time_results,
        "margin": {"drops": margin_drops, "worst_drop": round(worst_margin_drop, 8)},
        "passed": margin_drops == 0 and all(row["drops_or_wrong_way_steps"] == 0 for row in time_results.values()),
    }


def sampled_training_rows(data: list[dict]) -> list[dict]:
    by_game: dict[str, list[dict]] = defaultdict(list)
    for row in data:
        by_game[str(row["game_id"])].append(row)

    sampled: list[dict] = []
    for game_id in sorted(by_game):
        game = by_game[game_id]
        if len(game) <= MAX_TRAIN_SNAPSHOTS_PER_GAME:
            sampled.extend(game)
            continue
        picks = np.linspace(0, len(game) - 1, MAX_TRAIN_SNAPSHOTS_PER_GAME, dtype=int)
        sampled.extend(game[int(i)] for i in picks)
    return sampled


def evaluate(model, data: list[dict]) -> dict:
    ys = outcomes(data)
    st = [state(r) for r in data]
    model_probs = probs_for_model(model, data)
    leader_probs = [baseline_leader(s) for s in st]
    constant_probs = [0.5 for _ in st]
    normal_probs = [baseline_normal(s, NORMAL_MU, NORMAL_SIGMA) for s in st]
    espn_rows = [(float(r["espn_home_wp"]), int(r["home_won"])) for r in data if r["espn_home_wp"] is not None]
    espn_probs = [p for p, _y in espn_rows]
    espn_ys = [y for _p, y in espn_rows]

    phase_breakdown = {}
    buckets = [
        ("innings_1_3", 0.666666, 1.000001),
        ("innings_4_6", 0.333333, 0.666666),
        ("innings_7_9", 0.000001, 0.333333),
        ("extra_or_no_regulation_left", -0.000001, 0.000001),
    ]
    for name, lo, hi in buckets:
        idx = [i for i, r in enumerate(data) if lo < float(r["frac_remaining"]) <= hi]
        espn_idx = [i for i in idx if data[i]["espn_home_wp"] is not None]
        phase_breakdown[name] = {
            "n": len(idx),
            "model": metric_block([model_probs[i] for i in idx], [ys[i] for i in idx]) if idx else None,
            "leader": metric_block([leader_probs[i] for i in idx], [ys[i] for i in idx]) if idx else None,
            "constant_0_5": metric_block([0.5 for _ in idx], [ys[i] for i in idx]) if idx else None,
            "normal": metric_block([normal_probs[i] for i in idx], [ys[i] for i in idx]) if idx else None,
            "espn": metric_block([float(data[i]["espn_home_wp"]) for i in espn_idx], [ys[i] for i in espn_idx])
            if espn_idx
            else None,
            "espn_coverage": f"{len(espn_idx)}/{len(idx)}",
        }

    sanity_states = {
        "tied_top_1st": GameState(league="mlb", margin=0, frac_remaining=1.0, period=1),
        "early_home_plus_1": GameState(league="mlb", margin=1, frac_remaining=0.85, period=2),
        "late_home_plus_1": GameState(league="mlb", margin=1, frac_remaining=0.10, period=9),
        "late_home_minus_1": GameState(league="mlb", margin=-1, frac_remaining=0.10, period=9),
        "bottom_9_tied_proxy": GameState(league="mlb", margin=0, frac_remaining=1.0 / 18.0, period=9),
        "bottom_9_home_plus_1_proxy": GameState(league="mlb", margin=1, frac_remaining=1.0 / 18.0, period=9),
        "extra_tied": GameState(league="mlb", margin=0, frac_remaining=0.0, period=10, is_overtime=True),
    }
    sanity = {
        k: round(float(model.predict_proba([[build_features(s)[n] for n in model.feature_names]])[0][1]), 6)
        for k, s in sanity_states.items()
    }

    return {
        "model": metric_block(model_probs, ys),
        "baselines": {
            "leader": metric_block(leader_probs, ys),
            "constant_0_5": metric_block(constant_probs, ys),
            f"normal_mu_{NORMAL_MU}_sigma_{NORMAL_SIGMA}": metric_block(normal_probs, ys),
            "espn_home_wp": {
                **metric_block(espn_probs, espn_ys),
                "coverage": f"{len(espn_probs)}/{len(data)}",
            },
        },
        "calibration_table": calibration_table(model_probs, ys, bins=10),
        "max_calibration_gap": round(max_calibration_gap(model_probs, ys, bins=10, min_n=30), 6),
        "phase_breakdown": phase_breakdown,
        "sanity_checks": sanity,
        "monotonicity_checks": monotonicity_checks(model),
    }


def main() -> None:
    data = rows()
    seasons = sorted({int(r["season"]) for r in data})
    if len(seasons) < 2:
        raise SystemExit(f"Need at least two seasons; found {seasons}")

    test_season = max(seasons)
    train_all = [r for r in data if int(r["season"]) < test_season]
    test = [r for r in data if int(r["season"]) == test_season]
    if not train_all or not test:
        raise SystemExit("Train/test split produced an empty side.")
    train = sampled_training_rows(train_all)

    base_model = make_pipeline(
        StandardScaler(),
        GradientBoostingClassifier(n_estimators=120, learning_rate=0.05, max_depth=2, random_state=42),
    )
    model = CalibratedClassifierCV(base_model, method="sigmoid", cv=3)
    model.fit([vector(r, MLB_FEATURE_NAMES) for r in train], outcomes(train))
    wrapper_cls = (
        MonotoneBlendModel
        if __name__ != "__main__"
        else importlib.import_module("scripts.live_wp.train_mlb").MonotoneBlendModel
    )
    model = wrapper_cls(
        model,
        MLB_FEATURE_NAMES,
        league="mlb",
        alpha=BLEND_ALPHA,
        normal_mu=NORMAL_MU,
        normal_sigma=NORMAL_SIGMA,
        alpha_power=BLEND_ALPHA_POWER,
        margin_min=-15,
        margin_max=15,
    )

    validation = evaluate(model, test)
    all_games = len({r["game_id"] for r in data})
    train_games = len({r["game_id"] for r in train_all})
    test_games = len({r["game_id"] for r in test})
    bundle = {
        "model": model,
        "feature_names": MLB_FEATURE_NAMES,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_games": all_games,
        "n_snapshots": len(data),
        "brier": validation["model"]["brier"],
        "log_loss": validation["model"]["log_loss"],
        "train_seasons": [s for s in seasons if s < test_season],
        "test_seasons": [test_season],
        "validation": {
            **validation,
            "protocol": {
                "split": f"game-level chronological season holdout: train seasons < {test_season}, test season {test_season}",
                "train_games": train_games,
                "train_snapshots_available": len(train_all),
                "train_snapshots_used": len(train),
                "max_train_snapshots_per_game": MAX_TRAIN_SNAPSHOTS_PER_GAME,
                "test_games": test_games,
                "test_snapshots": len(test),
                "train_seasons": [s for s in seasons if s < test_season],
                "test_season": test_season,
                "normal_baseline": {"mu": NORMAL_MU, "sigma": NORMAL_SIGMA},
                "estimator": "GradientBoostingClassifier calibrated with 3-fold sigmoid calibration on training games only",
                "post_processor": (
                    f"{BLEND_ALPHA:.0%} normal-baseline blend"
                    f"{'' if BLEND_ALPHA_POWER == 0 else f' decaying as frac_remaining^{BLEND_ALPHA_POWER:g}'} "
                    "plus time and margin monotone envelopes"
                ),
                "outs_handling": "transient outs=3 is normalized to unknown; the shipped core-feature artifact does not consume outs",
            },
        },
        "notes": (
            "MLB live WP trained only on frozen live_winprob.build_features fields and post-processed "
            f"with a {BLEND_ALPHA:.0%} normal-baseline blend"
            f"{'' if BLEND_ALPHA_POWER == 0 else f' decaying as frac_remaining^{BLEND_ALPHA_POWER:g}'} "
            "plus monotone envelopes. "
            "No test-set tuning; the latest harvested season is a held-out game-level season. "
            "Top/bottom half-inning is represented through frac_remaining. Transient outs=3 is "
            "treated as unobserved to avoid extrapolating outside the active half-inning range; "
            "the shipped core-feature artifact does not consume outs. "
            "ESPN WP remains better on its partial-coverage benchmark."
        ),
    }

    path = artifact_path("mlb")
    should_save = (
        validation["model"]["brier"] < CURRENT_BRIER
        and validation["model"]["log_loss"] < CURRENT_LOG_LOSS
        and validation["monotonicity_checks"]["passed"]
    )
    if should_save:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, path)

    prob, meta = predict_home_win_prob(GameState(league="mlb", margin=1, frac_remaining=0.1))
    print(json.dumps(bundle["validation"], indent=2, sort_keys=True))
    print(f"saved={should_save} path={path}")
    print(f"serving_check_margin1_frac0.1={prob} available={meta.get('available')}")


if __name__ == "__main__":
    main()
