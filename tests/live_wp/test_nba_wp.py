from __future__ import annotations

import math

import pytest

from app.services.live_winprob import GameState, has_model, load_model, predict_home_win_prob


def score(margin: int, frac_remaining: float, period: int = 4, ot_frac_remaining: float | None = None) -> float:
    prob, meta = predict_home_win_prob(
        GameState(
            league="nba",
            margin=margin,
            frac_remaining=frac_remaining,
            period=period,
            is_overtime=period > 4,
            ot_frac_remaining=ot_frac_remaining,
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
    assert set(bundle["feature_names"]).issubset(
        {
            "margin",
            "margin_scaled",
            "frac_remaining",
            "pregame_logit",
            "pregame_logit_decay",
            "is_overtime",
            "ot_frac_remaining",
            "ot_frac_known",
            "margin_scaled_ot",
        }
    )
    assert bundle["validation"]["fixed_holdout_split"]["game_id_overlap"] == 0


def test_nba_probability_is_monotone_in_margin():
    for frac, period in ((1.0, 1), (0.75, 2), (0.5, 2), (0.25, 4), (120 / 2880, 4), (30 / 2880, 4)):
        probs = [score(margin, frac, period=period) for margin in range(-30, 31, 5)]
        assert probs == sorted(probs)


def test_nba_late_blowout_matches_observed_outcome_rate():
    """A 10-point lead with 2:00 left really is nearly decided.

    This state was investigated as a suspected overconfidence bug because the
    model returns ~0.998. Measuring the held-out 2024 season settled it: of the
    193 snapshots with a home margin of +9..+11 and roughly 1:26-2:38 left, the
    home team won 192, an actual rate of 0.9948. ESPN's published curve averages
    0.9865 for the same states, i.e. slightly UNDER-confident. So a high number
    here is correct, and an earlier attempt to "fix" it down to ~0.968 was
    rejected for making held-out log loss worse.

    The assertion is therefore a floor, not a ceiling.
    """
    prob = score(10, 120 / 2880, period=4)
    assert prob > 0.95, "a +10 lead with 2:00 left should be near-decided"
    assert prob < 1.0


def test_nba_same_lead_is_more_valuable_late():
    early = score(8, 0.8, period=1)
    late = score(8, 0.2, period=4)
    assert late > early


def test_nba_overtime_clock_changes_fixed_margin_probability():
    start = score(2, 0.0, period=5, ot_frac_remaining=1.0)
    final_seconds = score(2, 0.0, period=5, ot_frac_remaining=5 / 300)
    assert abs(start - 0.5) < abs(final_seconds - 0.5)
    assert start < final_seconds


def test_nba_time_monotonicity_grid():
    for margin in (3, 5, 8, 12):
        probs = [score(margin, 1.0 - i / 40, period=4) for i in range(41)]
        assert probs == sorted(probs)
    for margin in (-3, -5, -8, -12):
        probs = [score(margin, 1.0 - i / 40, period=4) for i in range(41)]
        assert probs == sorted(probs, reverse=True)


def test_nba_edge_states_are_finite():
    for margin, frac in ((0, 1.0), (0, 0.0), (40, 0.0), (-40, 0.0)):
        prob = score(margin, frac)
        assert math.isfinite(prob)
        assert 0.0 < prob < 1.0
