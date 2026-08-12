"""One shared implementation of the live win-probability payload.

Every league router used to carry its own near-identical copy of this logic.
They drifted: the MLB router learned to read half-inning labels correctly and
to pass `outs`, the NBA router learned to thread the overtime clock, and the
NHL and NFL routers kept a stale copy of the *MLB* branch that could never run
from where it sat. Dead code that looks live is a trap, and four copies of a
serving path means a fix applied to one is silently absent from three.

This module holds the union of the correct behaviour. The routers delegate to
it and keep only their own thin wrappers.
"""

from __future__ import annotations

from typing import Any

from app.services.espn_pbp import (
    MLB_REGULATION_INNINGS,
    REGULATION,
    frac_remaining_clock,
    frac_remaining_innings,
    ot_frac_remaining_clock,
    parse_clock_seconds,
)
from app.services.live_winprob import GameState, predict_home_win_prob

__all__ = [
    "wp_int",
    "mlb_half_inning_state",
    "nfl_situation_inputs",
    "nfl_yards_to_endzone",
    "build_game_state",
    "live_win_probability",
    "with_live_win_probability",
]


def wp_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def nfl_yards_to_endzone(yard_line: Any, offense_is_home: bool | None) -> int | None:
    yard = wp_int(yard_line)
    if yard is None or offense_is_home is None:
        return None
    yard = min(max(yard, 0), 100)
    return 100 - yard if offense_is_home else yard


def nfl_situation_inputs(row: dict[str, Any]) -> dict[str, Any]:
    """Extract possession/down/distance/field position for the NFL model."""
    live = row.get("live") if isinstance(row.get("live"), dict) else {}
    situation = live.get("situation") if isinstance(live.get("situation"), dict) else {}
    possession = situation.get("possession") or situation.get("possession_team_id")
    home_id = situation.get("home_team_id") or row.get("home_team_id")
    offense_is_home = None
    if possession is not None and home_id is not None:
        offense_is_home = str(possession) == str(home_id)
    elif live.get("possession") is not None and row.get("home") is not None:
        offense_is_home = str(live.get("possession")) == str(row.get("home"))

    down = wp_int(situation.get("down"))
    distance = wp_int(situation.get("distance"))
    yards_to_endzone = wp_int(situation.get("yardsToEndzone") or situation.get("yards_to_endzone"))
    if yards_to_endzone is None:
        yards_to_endzone = nfl_yards_to_endzone(situation.get("yardLine"), offense_is_home)

    return {
        "offense_is_home": offense_is_home,
        "down": down,
        "distance": distance,
        "yards_to_endzone": yards_to_endzone,
    }


def mlb_half_inning_state(period: int, label: str, raw_outs: Any) -> tuple[int, bool, int | None]:
    """Resolve an MLB live label into (inning, is_top, outs).

    `_period_label` emits T5 / M5 (middle) / B5 / E5 (end) / bare "5".
    "M" (top over, bottom not started) is equivalent to the bottom of the same
    inning, but "E" means the inning is COMPLETE, so the live state is the top
    of the NEXT inning. Folding E into the bottom case leaves the model half an
    inning behind the real game.

    Outs are only meaningful during an active top/bottom half-inning. MLB can
    transiently publish outs=3 at the M/E boundaries; treat that, and any
    non-T/B state, as unobserved rather than extrapolating beyond 0-2.
    """
    text = str(label or "").strip().upper()
    inning, is_top, outs = period, False, None
    if text.startswith("T"):
        is_top = True
        parsed = wp_int(raw_outs)
        outs = parsed if parsed in (0, 1, 2) else None
    elif text.startswith("E"):
        inning, is_top = period + 1, True
    elif text.startswith("B"):
        parsed = wp_int(raw_outs)
        outs = parsed if parsed in (0, 1, 2) else None
    return inning, is_top, outs


def build_game_state(row: dict[str, Any], league: str) -> GameState | None:
    """Build the model input for one live row, or None if the state is incomplete."""
    if row.get("status") != "live":
        return None
    live = row.get("live") if isinstance(row.get("live"), dict) else {}
    home_score = wp_int(row.get("home_score"))
    away_score = wp_int(row.get("away_score"))
    period = wp_int(live.get("period"))
    if home_score is None or away_score is None or period is None:
        return None

    extra: dict[str, Any] = {}
    if league == "mlb":
        label = live.get("period_label") or row.get("detailed_status") or ""
        inning, is_top, outs = mlb_half_inning_state(period, label, live.get("outs"))
        is_overtime = inning > MLB_REGULATION_INNINGS
        frac_remaining = 0.0 if is_overtime else frac_remaining_innings(inning, is_top)
        # Report the corrected inning as the period too. `period` is not a
        # feature of today's MLB artifact, so this is inert right now, but
        # passing a period that disagrees with the frac_remaining and
        # is_overtime derived beside it is a trap primed to fire the moment
        # anything starts reading it.
        period = inning
        extra["outs"] = outs
    else:
        is_overtime = period > int(REGULATION[league]["periods"])
        clock_seconds = parse_clock_seconds(live.get("clock"))
        frac_remaining = frac_remaining_clock(league, period, clock_seconds)
        # Thread the overtime clock for every clock league, not just the one
        # whose model happens to consume it today. Models select their own
        # feature subset, so this is inert for artifacts that ignore it and
        # correct for any that later do not.
        extra["ot_frac_remaining"] = ot_frac_remaining_clock(league, period, clock_seconds)
        if league == "nfl":
            extra.update(nfl_situation_inputs(row))

    return GameState(
        league=league,
        margin=home_score - away_score,
        frac_remaining=frac_remaining,
        period=period,
        is_overtime=is_overtime,
        **extra,
    )


def live_win_probability(row: dict[str, Any], league: str) -> dict[str, Any]:
    """Return the honest live win-probability payload for one live row."""
    state = build_game_state(row, league)
    if state is None:
        return {
            "available": False,
            "home": None,
            "away": None,
            "model": f"{league}_live_wp",
            "reason": "Live win probability unavailable because live game state is incomplete.",
        }

    prob, meta = predict_home_win_prob(state)
    if prob is None:
        return {
            "available": False,
            "home": None,
            "away": None,
            "model": f"{league}_live_wp",
            "reason": str(meta.get("reason") or "Live win-probability model is unavailable."),
        }
    home_prob = round(float(prob), 6)
    return {
        "available": True,
        "home": home_prob,
        "away": round(1.0 - home_prob, 6),
        "model": f"{league}_live_wp",
        "reason": None,
    }


def with_live_win_probability(row: dict[str, Any], league: str) -> dict[str, Any]:
    if row.get("status") != "live":
        return row
    return {**row, "win_probability": live_win_probability(row, league)}
