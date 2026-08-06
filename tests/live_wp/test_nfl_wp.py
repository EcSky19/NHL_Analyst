from __future__ import annotations

import math

import pytest

from app.services.live_winprob import GameState, artifact_path, load_model, predict_home_win_prob


def _prob(margin: int, frac_remaining: float) -> float:
    prob, meta = predict_home_win_prob(GameState(league="nfl", margin=margin, frac_remaining=frac_remaining))
    assert meta["available"] is True
    assert prob is not None
    return prob


def test_nfl_artifact_loads():
    assert artifact_path("nfl").exists()
    bundle = load_model("nfl")
    assert isinstance(bundle, dict)
    assert bundle.get("model") is not None
    assert bundle.get("feature_names")
    assert set(bundle["feature_names"]).issubset(
        {"margin", "margin_scaled", "frac_remaining", "pregame_logit", "pregame_logit_decay", "is_overtime"}
    )
    assert bundle.get("train_seasons") == [2023]
    assert bundle.get("test_seasons") == [2024]


def test_nfl_output_is_probability():
    prob = _prob(7, 0.2)
    assert 0.0 < prob < 1.0


def test_nfl_monotonic_in_margin():
    away_leads = _prob(-7, 0.5)
    tied = _prob(0, 0.5)
    home_leads = _prob(7, 0.5)
    assert away_leads < tied < home_leads


def test_nfl_time_leverage_for_same_lead():
    early = _prob(7, 0.8)
    late = _prob(7, 0.2)
    assert late > early


@pytest.mark.parametrize("margin,frac_remaining", [(0, 1.0), (0, 0.0), (14, 0.0), (-14, 0.0)])
def test_nfl_edge_states_are_finite(margin: int, frac_remaining: float):
    prob = _prob(margin, frac_remaining)
    assert math.isfinite(prob)
    assert 0.0 < prob < 1.0
