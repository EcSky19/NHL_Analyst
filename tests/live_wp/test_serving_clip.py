"""What we publish must be what we serve.

`predict_home_win_prob` clips every served value into SERVE_CLIP. Evaluation
that scores the raw model measures something no user receives. Measured on the
held-out seasons the difference is tiny -- at most 0.000477 log loss (NHL) and
0.000000 Brier -- but 4-6% of snapshots are affected, so it is not nothing, and
"tiny" is a measurement rather than a licence to ignore it.

These tests pin the clip itself and the fact that the audit tool consumes the
same constant, so the published and served configurations cannot drift apart.
"""

from __future__ import annotations

import inspect

import pytest

from app.services.live_winprob import SERVE_CLIP, GameState, predict_home_win_prob, has_model

LEAGUES = ("nhl", "nba", "nfl", "mlb")


def test_serve_clip_is_a_sane_two_sided_bound() -> None:
    lo, hi = SERVE_CLIP
    assert 0.0 < lo < hi < 1.0
    # Symmetric, so the clip does not quietly favour the home team.
    assert lo == pytest.approx(1.0 - hi)


@pytest.mark.parametrize("league", LEAGUES)
@pytest.mark.parametrize("margin", [-60, -20, -5, 0, 5, 20, 60])
@pytest.mark.parametrize("frac", [0.0, 1e-9, 0.05, 0.5, 1.0])
def test_served_probability_never_leaves_the_clip(league: str, margin: int, frac: float) -> None:
    """A blowout with no time left is where raw models run off to 1e-6."""
    if not has_model(league):
        pytest.skip(f"no validated artifact for {league}")
    prob, meta = predict_home_win_prob(
        GameState(league=league, margin=margin, frac_remaining=frac)
    )
    if prob is None:
        assert meta["available"] is False
        return
    lo, hi = SERVE_CLIP
    assert lo <= prob <= hi


@pytest.mark.parametrize("league", LEAGUES)
def test_served_probability_never_prints_as_flat_certainty(league: str) -> None:
    """The UI treats 0.0 and 1.0 as an invalid payload and hides the model.

    app/static/app.js requires `homeProb > 0 && homeProb < 1`, so a served
    value of exactly 1.0 would render a correct, confident answer as "Live win
    probability unavailable". The clip is what prevents that.
    """
    if not has_model(league):
        pytest.skip(f"no validated artifact for {league}")
    prob, _ = predict_home_win_prob(
        GameState(league=league, margin=50, frac_remaining=0.0, period=9)
    )
    if prob is None:
        return
    home = round(float(prob), 6)
    away = round(1.0 - home, 6)
    assert 0.0 < home < 1.0
    assert 0.0 < away < 1.0


def test_audit_tool_uses_the_same_clip_constant() -> None:
    """The audit tool must import the constant, not restate the numbers."""
    source = (inspect.getsourcefile(predict_home_win_prob) or "")
    assert source  # sanity
    from pathlib import Path

    verify = Path(__file__).resolve().parents[2] / "scripts" / "live_wp" / "verify_artifacts.py"
    text = verify.read_text(encoding="utf-8")
    assert "SERVE_CLIP" in text, "verify_artifacts.py must import the serving clip"
    assert "AS-SERVED" in text, "verify_artifacts.py must report the as-served metrics"
    # No hardcoded duplicate of the bound.
    assert "0.001), 0.999" not in text
