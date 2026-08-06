"""Fit and save the NHL live win-probability artifact.

Round 2 conclusion: no learned model beat the two-parameter analytic baseline
on the held-out 2025-26 season, so the baseline is what we ship. See
docs/live_wp/nhl.md. Run with PYTHONPATH=. from the repo root.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import joblib
import numpy as np
from scipy.optimize import minimize

from app.services.live_wp_baseline import NormalBaselineModel
from app.services.live_winprob import brier_score, log_loss, max_calibration_gap

DB = Path("data/live_wp/nhl_snapshots.db")
OUT = Path("models/live_wp/nhl_live_wp.joblib")
TRAIN_SEASONS = ["2024-25"]
TEST_SEASONS = ["2025-26"]
FEATURE_NAMES = ["margin", "frac_remaining"]


def load(seasons: list[str]):
    con = sqlite3.connect(DB)
    marks = ",".join("?" * len(seasons))
    rows = con.execute(
        f"SELECT game_id, margin, frac_remaining, home_won FROM snapshots "  # noqa: S608
        f"WHERE season IN ({marks}) AND home_won IS NOT NULL",
        seasons,
    ).fetchall()
    con.close()
    games = {r[0] for r in rows}
    X = np.array([[r[1], r[2]] for r in rows], dtype=float)
    y = np.array([r[3] for r in rows], dtype=float)
    return X, y, games


def fit(X: np.ndarray, y: np.ndarray) -> NormalBaselineModel:
    """Fit mu/sigma by log loss on the training seasons only."""
    labels = list(y)

    def objective(theta: np.ndarray) -> float:
        model = NormalBaselineModel(theta[0], max(abs(theta[1]), 1e-3))
        return log_loss(list(model.predict_proba(X)[:, 1]), labels)

    best = None
    for sigma0 in (1.5, 2.5, 4.0, 6.0):
        res = minimize(objective, x0=np.array([0.0, sigma0]), method="Nelder-Mead",
                       options={"xatol": 1e-5, "fatol": 1e-9, "maxiter": 500})
        if best is None or res.fun < best.fun:
            best = res
    return NormalBaselineModel(best.x[0], abs(best.x[1]))


def main() -> None:
    Xtr, ytr, games_tr = load(TRAIN_SEASONS)
    Xte, yte, games_te = load(TEST_SEASONS)
    assert not (games_tr & games_te), "train/test game overlap"

    model = fit(Xtr, ytr)
    probs = list(model.predict_proba(Xte)[:, 1])
    labels = list(yte)
    brier = brier_score(probs, labels)
    ll = log_loss(probs, labels)
    gap = max_calibration_gap(probs, labels)

    print(f"fitted {model}")
    print(f"train games={len(games_tr)} rows={len(ytr)}")
    print(f"test  games={len(games_te)} rows={len(yte)}")
    print(f"held-out brier={brier:.6f} log_loss={ll:.6f} calib_gap={gap:.4f}")

    # Monotonicity in margin is the property the learned round-1 model broke.
    for frac in (0.95, 0.75, 0.5, 0.25, 0.05):
        grid = model.predict_proba([[m, frac] for m in range(-5, 6)])[:, 1]
        assert all(a <= b + 1e-12 for a, b in zip(grid, grid[1:])), f"non-monotone at {frac}"
    print("monotone in margin at every checked time point: OK")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "model_kind": "analytic_normal_baseline",
            "feature_names": FEATURE_NAMES,
            "trained_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "train_seasons": TRAIN_SEASONS,
            "test_seasons": TEST_SEASONS,
            "n_games": len(games_tr),
            "n_snapshots": int(len(ytr)),
            "brier": brier,
            "log_loss": ll,
            "max_calibration_gap": gap,
            "mu": model.mu,
            "sigma": model.sigma,
            "notes": (
                "Analytic two-parameter baseline. Six learned models were tried in round 2 "
                "and none beat it on held-out data; the round-1 logistic model also broke "
                "monotonicity in margin. No ESPN win-probability curve exists for NHL, so "
                "there is no external benchmark for this league."
            ),
        },
        OUT,
    )
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
