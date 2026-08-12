"""The live win-probability path must exist in exactly one place.

Every league router used to carry its own copy of this logic and they drifted:
the MLB copy learned to read half-inning labels and pass `outs`, the NBA copy
learned to thread the overtime clock, and NHL/NFL kept a stale copy of the MLB
branch that could never execute from where it sat. A fix applied to one copy
was silently absent from the other three.

These tests pin the properties that made that drift possible, so it cannot
quietly come back.
"""

from __future__ import annotations

import inspect

import pytest

import app.routers.mlb as mlb_router
import app.routers.nba as nba_router
import app.routers.nfl as nfl_router
import app.routers.nhl as nhl_router
from app.services import live_wp_state
from app.services.live_wp_state import build_game_state, mlb_half_inning_state

ROUTERS = {"nhl": nhl_router, "nfl": nfl_router, "mlb": mlb_router, "nba": nba_router}


@pytest.mark.parametrize("league", sorted(ROUTERS))
def test_router_delegates_to_shared_implementation(league: str) -> None:
    """No router may re-implement the scoring path."""
    source = inspect.getsource(ROUTERS[league]._live_win_probability)
    assert "_shared_live_win_probability" in source
    # The league-specific derivations must not reappear in the routers.
    for leaked in ("frac_remaining_innings(", "frac_remaining_clock(", "GameState("):
        assert leaked not in source, f"{league} router re-derives state: {leaked}"


def test_no_router_carries_a_dead_copy_of_another_leagues_branch() -> None:
    """A stale `league == "mlb"` branch sat unreachable in three routers."""
    for league, module in ROUTERS.items():
        source = inspect.getsource(module._live_win_probability)
        assert 'league == "mlb"' not in source
        assert 'league == "nba"' not in source


@pytest.mark.parametrize("league", ["nhl", "nfl", "nba"])
def test_overtime_clock_is_threaded_for_every_clock_league(league: str) -> None:
    """The overtime clock used to be threaded for NBA only.

    Models select their own feature subset, so supplying it everywhere is inert
    for artifacts that ignore it, and correct for any that later do not. The
    point is that no league is left silently blind to it again.
    """
    row = {
        "status": "live",
        "home_score": 100,
        "away_score": 98,
        "live": {"period": 6, "clock": "2:30"},
    }
    state = build_game_state(row, league)
    assert state is not None
    assert state.is_overtime is True
    assert state.ot_frac_remaining is not None
    assert 0.0 <= state.ot_frac_remaining <= 1.0


def test_mlb_end_of_inning_advances_to_the_next_half_inning() -> None:
    """"E9" means the 9th is COMPLETE, so the live state is the top of the 10th."""
    inning, is_top, outs = mlb_half_inning_state(9, "E9", None)
    assert (inning, is_top) == (10, True)
    assert outs is None


def test_mlb_middle_is_the_bottom_of_the_same_inning() -> None:
    inning, is_top, _ = mlb_half_inning_state(5, "M5", None)
    assert (inning, is_top) == (5, False)


@pytest.mark.parametrize("raw,expected", [(0, 0), (1, 1), (2, 2), (3, None), (None, None), ("x", None)])
def test_mlb_outs_outside_zero_to_two_are_unobserved(raw, expected) -> None:
    """MLB transiently publishes outs=3 at half-inning boundaries."""
    _, _, outs = mlb_half_inning_state(5, "T5", raw)
    assert outs == expected


def test_mlb_period_agrees_with_the_inning_used_for_the_other_fields() -> None:
    """The router corrected the inning for frac_remaining but passed the raw period.

    `period` is not a feature of today's MLB artifact so nothing was scored
    wrongly, but a state whose period disagrees with the frac_remaining beside
    it is a trap primed to fire the moment anything reads it.
    """
    row = {
        "status": "live",
        "home_score": 4,
        "away_score": 4,
        "live": {"period": 9, "period_label": "E9", "outs": None},
    }
    state = build_game_state(row, "mlb")
    assert state is not None
    assert state.period == 10
    assert state.is_overtime is True


def test_incomplete_state_is_reported_unavailable_not_guessed() -> None:
    for row in (
        {"status": "live", "home_score": None, "away_score": 2, "live": {"period": 1}},
        {"status": "live", "home_score": 3, "away_score": 2, "live": {}},
        {"status": "final", "home_score": 3, "away_score": 2, "live": {"period": 4}},
    ):
        assert build_game_state(row, "nba") is None
        payload = live_wp_state.live_win_probability(row, "nba")
        assert payload["available"] is False
        assert payload["home"] is None and payload["away"] is None
        assert payload["reason"]


def test_nfl_situation_is_supplied_only_to_nfl() -> None:
    row = {
        "status": "live",
        "home_score": 17,
        "away_score": 21,
        "home_team_id": "12",
        "live": {
            "period": 4,
            "clock": "1:30",
            "situation": {"possession": "33", "home_team_id": "12", "down": 2,
                          "distance": 6, "yardLine": 20},
        },
    }
    nfl_state = build_game_state(row, "nfl")
    assert nfl_state is not None
    assert nfl_state.offense_is_home is False
    assert nfl_state.down == 2
    # Away possession on their own 20 is 80 yards from the opponent end zone.
    assert nfl_state.yards_to_endzone == 20

    nba_state = build_game_state(row, "nba")
    assert nba_state is not None
    assert getattr(nba_state, "down", None) is None
