from __future__ import annotations

import math

from app.services.live_winprob import GameState, artifact_path, load_model, predict_home_win_prob


def _prob(margin: int, frac_remaining: float, period: int | None = None, is_overtime: bool = False) -> float:
    prob, meta = predict_home_win_prob(
        GameState(
            league="nhl",
            margin=margin,
            frac_remaining=frac_remaining,
            period=period,
            is_overtime=is_overtime,
        )
    )
    assert meta["available"] is True
    assert prob is not None
    return prob


def test_nhl_artifact_loads() -> None:
    assert artifact_path("nhl").exists()
    bundle = load_model("nhl")
    assert isinstance(bundle, dict)
    assert "model" in bundle
    assert bundle.get("feature_names")


def test_nhl_output_in_open_interval() -> None:
    prob = _prob(margin=1, frac_remaining=0.2, period=3)
    assert 0.0 < prob < 1.0


def test_nhl_monotonic_in_margin() -> None:
    away_lead = _prob(margin=-1, frac_remaining=0.4, period=2)
    tied = _prob(margin=0, frac_remaining=0.4, period=2)
    home_lead = _prob(margin=1, frac_remaining=0.4, period=2)
    assert away_lead < tied < home_lead


def test_nhl_time_leverage_for_same_lead() -> None:
    early = _prob(margin=1, frac_remaining=0.8, period=1)
    late = _prob(margin=1, frac_remaining=0.05, period=3)
    assert late > early
    assert late < 0.98


def test_nhl_edge_states_are_finite() -> None:
    puck_drop = _prob(margin=0, frac_remaining=1.0, period=1)
    overtime_tied = _prob(margin=0, frac_remaining=0.0, period=4, is_overtime=True)
    assert math.isfinite(puck_drop)
    assert math.isfinite(overtime_tied)
    assert 0.0 < puck_drop < 1.0
    assert 0.0 < overtime_tied < 1.0
