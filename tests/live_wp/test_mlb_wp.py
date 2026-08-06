from __future__ import annotations

import math

import pytest

from app.services.live_winprob import GameState, artifact_path, load_model, predict_home_win_prob


def _prob(margin: int, frac_remaining: float) -> float:
    prob, meta = predict_home_win_prob(GameState(league="mlb", margin=margin, frac_remaining=frac_remaining))
    assert meta["available"] is True
    assert prob is not None
    return prob


def test_mlb_artifact_loads():
    assert artifact_path("mlb").exists()
    bundle = load_model("mlb")
    assert isinstance(bundle, dict)
    assert bundle.get("model") is not None
    assert bundle.get("feature_names")


def test_mlb_output_is_probability():
    prob = _prob(1, 0.2)
    assert 0.0 < prob < 1.0


def test_mlb_monotonic_in_margin():
    away_leads = _prob(-1, 0.5)
    tied = _prob(0, 0.5)
    home_leads = _prob(1, 0.5)
    assert away_leads < tied < home_leads


def test_mlb_time_leverage_for_same_lead():
    early = _prob(1, 0.8)
    late = _prob(1, 0.2)
    assert late > early


@pytest.mark.parametrize("margin", [1, 2, 3, 5])
def test_mlb_time_monotonic_for_home_leads(margin: int):
    probs = [_prob(margin, 1.0 - i / 40) for i in range(41)]
    assert all(probs[i + 1] >= probs[i] for i in range(40))


@pytest.mark.parametrize("margin", [-1, -2, -3, -5])
def test_mlb_time_monotonic_for_home_trails(margin: int):
    probs = [_prob(margin, 1.0 - i / 40) for i in range(41)]
    assert all(probs[i + 1] <= probs[i] for i in range(40))


@pytest.mark.parametrize("margin,frac_remaining", [(0, 1.0), (0, 0.0), (1, 0.0), (-1, 0.0)])
def test_mlb_edge_states_are_finite(margin: int, frac_remaining: float):
    prob = _prob(margin, frac_remaining)
    assert math.isfinite(prob)
    assert 0.0 < prob < 1.0
