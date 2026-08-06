from __future__ import annotations

import math

from app.services.live_winprob import FEATURE_NAMES, GameState, has_model, load_model, predict_home_win_prob


def score(margin: int, frac_remaining: float, period: int = 4) -> float:
    prob, meta = predict_home_win_prob(
        GameState(
            league="nba",
            margin=margin,
            frac_remaining=frac_remaining,
            period=period,
            is_overtime=period > 4,
        )
    )
    assert meta["available"] is True
    assert prob is not None
    return prob


def test_nba_artifact_loads_and_scores_in_unit_interval():
    assert has_model("nba")
    prob = score(8, 0.2)
    assert 0.0 < prob < 1.0


def test_nba_artifact_declares_fixed_split_and_serving_features():
    bundle = load_model("nba")
    assert isinstance(bundle, dict)
    assert bundle["train_seasons"] == [2023]
    assert bundle["test_seasons"] == [2024]
    assert set(bundle["feature_names"]).issubset(FEATURE_NAMES)
    assert bundle["validation"]["fixed_holdout_split"]["game_id_overlap"] == 0


def test_nba_probability_is_monotone_in_margin():
    probs = [score(margin, 0.5, period=2) for margin in (-15, -5, 0, 5, 15)]
    assert probs == sorted(probs)
    assert len(set(probs)) == len(probs)


def test_nba_same_lead_is_more_valuable_late():
    early = score(8, 0.8, period=1)
    late = score(8, 0.2, period=4)
    assert late > early


def test_nba_edge_states_are_finite():
    for margin, frac in ((0, 1.0), (0, 0.0), (40, 0.0), (-40, 0.0)):
        prob = score(margin, frac)
        assert math.isfinite(prob)
        assert 0.0 < prob < 1.0
