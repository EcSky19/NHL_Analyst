"""Shared, frozen interface for live (in-game) win probability.

Design constraints, driven by this repo's retraction history
-----------------------------------------------------------
A live win probability is a number users will trust instantly, so the bar for
publishing one is high:

1. It must be CALIBRATED, not merely plausible. A model that says 70% must win
   about 70% of the time. Calibration is checked explicitly, not assumed.
2. It must be measured against honest baselines. Beating nothing is not a
   result. The baselines here are deliberately strong: a pure "who is ahead"
   rule, the pregame prior, and ESPN's own published curve.
3. When a league has no validated artifact, this module returns None. The API
   then says so. It never falls back to an uncalibrated guess, because a
   confident wrong number is worse than no number.

The feature builder is frozen so every league's artifact is interchangeable and
so the serving path cannot silently disagree with the training path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT

MODEL_DIR = REPO_ROOT / "models" / "live_wp"

FEATURE_NAMES = [
    "margin",
    "margin_scaled",
    "frac_remaining",
    "pregame_logit",
    "pregame_logit_decay",
    "is_overtime",
]
"""The original core feature set, kept for backward compatibility.

`build_features` returns a SUPERSET of these keys. Models select the columns
they need by name via their artifact's `feature_names`, so new keys can be
added to the map without disturbing any already-trained model.
"""

LEAGUES = ("nhl", "nfl", "nba", "mlb")

_EPS = 1e-6


@dataclass(frozen=True)
class GameState:
    """A single in-game situation to be scored.

    `frac_remaining` is the share of REGULATION still to play, in [0, 1].
    Overtime is flagged separately and carries frac_remaining == 0.0.
    """

    league: str
    margin: int
    frac_remaining: float
    period: int | None = None
    is_overtime: bool = False
    pregame_home_prob: float | None = None

    # Optional league-specific situational state. Every field defaults to None,
    # meaning "not observed", and every model declares in its artifact which
    # features it actually consumes -- so adding fields here can never disturb
    # an existing model. Only populate a field when it is genuinely known.
    outs: int | None = None                 # MLB: outs in the current half-inning, 0-2
    # Share of the CURRENT overtime period still to play, in [0, 1]. Only
    # meaningful when is_overtime is True. `frac_remaining` measures regulation
    # only and is pinned to 0.0 for every overtime snapshot, so without this
    # field an overtime game has no time coordinate at all: the first second and
    # the last second of overtime are indistinguishable to a model.
    ot_frac_remaining: float | None = None
    offense_is_home: bool | None = None     # NFL: which side has possession
    down: int | None = None                 # NFL: 1-4
    distance: int | None = None             # NFL: yards needed for a first down
    yards_to_endzone: int | None = None     # NFL: 1-99, from the offense's view


def logit(p: float) -> float:
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def inv_logit(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def build_features(state: GameState) -> dict[str, float]:
    """Frozen feature map shared by training and serving.

    `margin_scaled` divides the lead by sqrt(time remaining), which is the
    statistically meaningful quantity: the spread of the remaining scoring
    grows like sqrt(time), so a 5-point lead late is worth far more than the
    same lead early. Feeding raw margin alone forces the model to relearn this
    badly.
    """
    frac = min(max(float(state.frac_remaining), 0.0), 1.0)
    margin = float(state.margin)
    pregame = state.pregame_home_prob
    pregame_logit = logit(pregame) if pregame is not None else 0.0
    offense = state.offense_is_home
    yte = state.yards_to_endzone
    ot_frac_raw = state.ot_frac_remaining
    ot_known = state.is_overtime and ot_frac_raw is not None
    # Default 1.0 ("none of the extra period has elapsed") rather than 0.0, so
    # that a regulation snapshot -- where no overtime has begun -- is not
    # encoded as an overtime period that has already run out.
    ot_frac = min(max(float(ot_frac_raw), 0.0), 1.0) if ot_known else 1.0
    return {
        "margin": margin,
        "margin_scaled": margin / math.sqrt(frac + _EPS),
        "frac_remaining": frac,
        "pregame_logit": pregame_logit,
        # The pregame prior should fade as the game resolves itself.
        "pregame_logit_decay": pregame_logit * frac,
        "is_overtime": 1.0 if state.is_overtime else 0.0,
        # --- Overtime clock. -------------------------------------------------
        # `margin_scaled` divides by sqrt(frac_remaining), and frac_remaining is
        # 0.0 throughout overtime, so in overtime margin_scaled saturates at
        # margin/sqrt(1e-6) = 1000 * margin. Every overtime lead therefore looks
        # identical and enormous. These two keys restore the missing clock so a
        # model can tell the start of an extra period from its final seconds.
        "ot_frac_remaining": ot_frac,
        "ot_frac_known": 1.0 if ot_known else 0.0,
        # The overtime analogue of margin_scaled: a lead is worth far more with
        # 10 seconds of overtime left than with the full period to play. Zero
        # outside overtime, where the concept does not apply.
        "margin_scaled_ot": (margin / math.sqrt(ot_frac + _EPS)) if ot_known else 0.0,
        # --- Optional situational state. -----------------------------------
        # Each value is paired with a *_known flag so a model can tell a
        # genuine zero from an unobserved field instead of silently treating
        # "missing" as "first down on the goal line".
        "outs": float(state.outs) if state.outs is not None else 0.0,
        "outs_known": 1.0 if state.outs is not None else 0.0,
        # 0.5 encodes "possession unknown", which is neutral between the teams.
        "offense_is_home": 0.5 if offense is None else (1.0 if offense else 0.0),
        "down": float(state.down) if state.down is not None else 0.0,
        "distance": float(state.distance) if state.distance is not None else 0.0,
        "yards_to_endzone": float(yte) if yte is not None else 50.0,
        # Field position signed toward the home team: large positive means the
        # home offense is close to scoring, large negative means the away
        # offense is. Zero when possession or field position is unknown.
        "field_position_home": (
            0.0
            if (offense is None or yte is None)
            else (1.0 if offense else -1.0) * (100.0 - float(yte))
        ),
        "situation_known": (
            1.0 if (offense is not None and yte is not None and state.down is not None) else 0.0
        ),
    }


def feature_vector(state: GameState) -> list[float]:
    feats = build_features(state)
    return [feats[name] for name in FEATURE_NAMES]


# --------------------------------------------------------------------------
# Baselines. A model must be compared against these to count as a result.
# --------------------------------------------------------------------------


def baseline_leader(state: GameState) -> float:
    """"Whoever is ahead wins." Crude, but genuinely hard to beat late."""
    if state.margin > 0:
        return 0.85
    if state.margin < 0:
        return 0.15
    return 0.5


def baseline_pregame(state: GameState) -> float:
    """Ignore the live score entirely and keep the pregame prior."""
    if state.pregame_home_prob is None:
        return 0.5
    return float(state.pregame_home_prob)


def baseline_normal(state: GameState, mu: float, sigma: float) -> float:
    """Analytic random-walk model: a strong, interpretable reference.

    Treats the remaining scoring margin as Normal(mu * f, sigma^2 * f) and asks
    for P(final margin > 0). Two parameters per league, no learning required.
    """
    frac = min(max(float(state.frac_remaining), 0.0), 1.0)
    if frac <= _EPS:
        return 1.0 if state.margin > 0 else (0.0 if state.margin < 0 else 0.5)
    mean = state.margin + mu * frac
    sd = max(sigma * math.sqrt(frac), _EPS)
    return 0.5 * (1.0 + math.erf(mean / (sd * math.sqrt(2.0))))


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def brier_score(probs: list[float], outcomes: list[int]) -> float:
    if not probs:
        return float("nan")
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes)) / len(probs)


def log_loss(probs: list[float], outcomes: list[int]) -> float:
    if not probs:
        return float("nan")
    total = 0.0
    for p, y in zip(probs, outcomes):
        p = min(max(p, 1e-15), 1 - 1e-15)
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(probs)


def calibration_table(probs: list[float], outcomes: list[int], bins: int = 10) -> list[dict[str, Any]]:
    """Bucket predictions and compare predicted vs actual win rate."""
    buckets: list[dict[str, Any]] = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [j for j, p in enumerate(probs) if (p >= lo and (p < hi or (i == bins - 1 and p <= hi)))]
        if not idx:
            buckets.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": 0, "predicted": None, "actual": None, "gap": None})
            continue
        pred = sum(probs[j] for j in idx) / len(idx)
        act = sum(outcomes[j] for j in idx) / len(idx)
        buckets.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "n": len(idx),
                "predicted": round(pred, 4),
                "actual": round(act, 4),
                "gap": round(act - pred, 4),
            }
        )
    return buckets


def max_calibration_gap(probs: list[float], outcomes: list[int], bins: int = 10, min_n: int = 30) -> float:
    gaps = [
        abs(row["gap"])
        for row in calibration_table(probs, outcomes, bins)
        if row["n"] >= min_n and row["gap"] is not None
    ]
    return max(gaps) if gaps else float("nan")


# --------------------------------------------------------------------------
# Serving
# --------------------------------------------------------------------------


def artifact_path(league: str) -> Path:
    return MODEL_DIR / f"{league}_live_wp.joblib"


def has_model(league: str) -> bool:
    return artifact_path(league).exists()


_CACHE: dict[str, Any] = {}


def load_model(league: str) -> Any | None:
    if league in _CACHE:
        return _CACHE[league]
    path = artifact_path(league)
    if not path.exists():
        _CACHE[league] = None
        return None
    try:
        import joblib

        bundle = joblib.load(path)
    except Exception:
        bundle = None
    _CACHE[league] = bundle
    return bundle


def predict_home_win_prob(state: GameState) -> tuple[float | None, dict[str, Any]]:
    """Return (home win probability, meta).

    Returns (None, meta) when no validated artifact exists for the league. That
    is a deliberate, honest refusal: callers must surface "not available"
    instead of substituting an uncalibrated guess.
    """
    bundle = load_model(state.league)
    if bundle is None:
        return None, {
            "available": False,
            "reason": f"No validated live win-probability model exists for {state.league.upper()}.",
        }

    model = bundle.get("model") if isinstance(bundle, dict) else bundle
    names = bundle.get("feature_names", FEATURE_NAMES) if isinstance(bundle, dict) else FEATURE_NAMES
    feats = build_features(state)
    try:
        vector = [[feats[name] for name in names]]
        prob = float(model.predict_proba(vector)[0][1])
    except Exception as exc:
        return None, {"available": False, "reason": f"Live model failed to score this state: {exc}"}

    prob = min(max(prob, 0.001), 0.999)
    meta: dict[str, Any] = {"available": True}
    if isinstance(bundle, dict):
        for key in ("trained_at", "n_games", "n_snapshots", "brier", "log_loss", "validation", "notes"):
            if key in bundle:
                meta[key] = bundle[key]
    return prob, meta
