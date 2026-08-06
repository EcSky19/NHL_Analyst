"""Analytic random-walk win-probability model, packaged for serving.

Round 2 of the NHL live win-probability work tried six learned models
(poly2/poly3 logistic, splines, monotone HGB, ExtraTrees, isotonic-calibrated
poly2). None beat the two-parameter analytic baseline on held-out data, and the
round-1 logistic artifact was additionally NON-MONOTONE in margin: at 75%
of regulation remaining it rated a 4-goal lead (0.809) as worse than a 3-goal
lead (0.821), which is indefensible to show a user.

So for NHL we serve the baseline itself. It wins on both Brier and log loss,
it is monotone in margin by construction, and it has two parameters instead of
thousands. This class exists purely so that a fitted baseline can be pickled
into the same artifact shape as a scikit-learn model and loaded by the frozen
`predict_home_win_prob` interface, which only requires `.predict_proba`.
"""

from __future__ import annotations

import math

import numpy as np

_EPS = 1e-9


class NormalBaselineModel:
    """P(home wins) treating the remaining margin as Normal(mu*f, sigma^2*f).

    Exposes the scikit-learn `predict_proba` surface so it is a drop-in for a
    learned estimator. Expects columns ``[margin, frac_remaining]``.
    """

    #: Column order this model expects; mirrored by the artifact feature_names.
    feature_names = ("margin", "frac_remaining")

    def __init__(self, mu: float, sigma: float) -> None:
        self.mu = float(mu)
        self.sigma = float(sigma)
        self.classes_ = np.array([0, 1])

    def predict_proba(self, X) -> np.ndarray:
        arr = np.asarray(X, dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        margin = arr[:, 0]
        frac = np.clip(arr[:, 1], 0.0, 1.0)

        live = frac > _EPS
        # With no time left the result is settled; a tie heads to overtime,
        # which the training labels resolve as a coin flip.
        home = np.where(margin > 0, 1.0, np.where(margin < 0, 0.0, 0.5)).astype(float)
        f = np.where(live, frac, 1.0)
        sd = np.maximum(self.sigma * np.sqrt(f), _EPS)
        z = (margin + self.mu * f) / (sd * math.sqrt(2.0))
        home[live] = (0.5 * (1.0 + _erf(z)))[live]

        home = np.clip(home, 1e-6, 1.0 - 1e-6)
        return np.column_stack([1.0 - home, home])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"NormalBaselineModel(mu={self.mu:.4f}, sigma={self.sigma:.4f})"


def _erf(z: np.ndarray) -> np.ndarray:
    try:
        from scipy.special import erf
    except ImportError:  # pragma: no cover - scipy ships with scikit-learn
        return np.array([math.erf(v) for v in np.ravel(z)]).reshape(np.shape(z))
    return erf(z)
