from __future__ import annotations

import math

import pytest

from app.services.live_winprob import GameState, artifact_path, build_features, load_model, predict_home_win_prob


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


def test_mlb_output_accepts_known_and_missing_outs():
    for outs in (2, None):
        prob, meta = predict_home_win_prob(GameState(league="mlb", margin=1, frac_remaining=0.2, outs=outs))
        assert meta["available"] is True
        assert prob is not None
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


def test_mlb_bottom_ninth_home_lead_is_walkoff():
    assert _prob(1, 1.0 / 18.0) == pytest.approx(0.999)
    assert _prob(3, 1.0 / 18.0) == pytest.approx(0.999)


def test_mlb_walkoff_artifact_probability_is_bounded_below_one():
    bundle = load_model("mlb")
    model = bundle["model"]
    names = bundle["feature_names"]
    state = GameState(league="mlb", margin=1, frac_remaining=1.0 / 18.0, period=9)
    feats = build_features(state)
    prob = float(model.predict_proba([[feats[name] for name in names]])[0][1])
    assert prob == pytest.approx(1.0 - 1e-9)


def test_mlb_walkoff_rule_does_not_apply_before_bottom_ninth_or_tied():
    assert _prob(1, 1.0 / 9.0) < 1.0 - 1e-4
    assert _prob(0, 1.0 / 18.0) < 1.0 - 1e-4


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


@pytest.mark.parametrize("points", [401, 1601, 4001])
@pytest.mark.parametrize("is_overtime", [False, True])
def test_mlb_high_resolution_time_monotonicity(points: int, is_overtime: bool):
    for margin in (1, 2, 3, -1, -2, -3):
        probs = []
        for i in range(points):
            frac = 1.0 - i / (points - 1)
            prob, meta = predict_home_win_prob(
                GameState(league="mlb", margin=margin, frac_remaining=frac, is_overtime=is_overtime)
            )
            assert meta["available"] is True
            assert prob is not None
            probs.append(prob)
        if margin > 0:
            assert all(probs[i + 1] >= probs[i] - 1e-9 for i in range(points - 1))
        else:
            assert all(probs[i + 1] <= probs[i] + 1e-9 for i in range(points - 1))


@pytest.mark.parametrize("points", [401, 1601, 4001])
@pytest.mark.parametrize("is_overtime", [False, True])
def test_mlb_high_resolution_margin_monotonicity(points: int, is_overtime: bool):
    for i in range(points):
        frac = i / (points - 1)
        probs = [
            predict_home_win_prob(GameState(league="mlb", margin=margin, frac_remaining=frac, is_overtime=is_overtime))[0]
            for margin in range(-15, 16)
        ]
        assert all(prob is not None for prob in probs)
        assert all(probs[j + 1] >= probs[j] - 1e-9 for j in range(len(probs) - 1))
