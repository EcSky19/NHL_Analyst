"""Harvest in-game score snapshots from ESPN game summaries.

Why this exists
---------------
Live win probability needs to answer "given the score right now and the time
left, who wins?". Answering that honestly requires historical examples of
in-game states paired with the eventual result. This repo's databases store
FINAL scores only, so that training signal did not exist anywhere locally.

ESPN's summary endpoint supplies it: each completed game returns a `plays` list
where every play carries the running `homeScore`/`awayScore`, the `clock`, and
the `period`. One request per game yields hundreds of labelled states.

The same payload also carries ESPN's own `winprobability` curve. We deliberately
do NOT use it as our prediction; it is kept only as an independent benchmark to
check our model against, because grading ourselves against our own output would
be meaningless.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterator

import httpx

from app.config import BROWSER_USER_AGENT
from app.services.espn_client import SPORT_PATHS, map_abbrev

SUMMARY_URL = "https://site.web.api.espn.com/apis/site/v2/sports/{path}/summary?event={event}"

# Regulation shape per league. Used to convert (period, clock) into a single
# "fraction of regulation remaining" number.
#
# `counts_up` is the trap here: NBA and NFL clocks count DOWN from the period
# length to zero, but ESPN's NHL clock counts UP from 0:00 as time elapses.
# Applying the count-down formula to NHL scores the opening face-off as though
# a third of the game were already gone, which would quietly train a wrong
# model rather than fail loudly.
REGULATION = {
    "nba": {"periods": 4, "period_minutes": 12.0, "ot_minutes": 5.0, "counts_up": False},
    "nfl": {"periods": 4, "period_minutes": 15.0, "ot_minutes": 10.0, "counts_up": False},
    "nhl": {"periods": 3, "period_minutes": 20.0, "ot_minutes": 5.0, "counts_up": True},
}

# Baseball has no clock; innings are the unit of remaining game.
MLB_REGULATION_INNINGS = 9.0


@dataclass(frozen=True)
class Snapshot:
    """One labelled in-game state."""

    game_id: str
    league: str
    period: int
    clock_seconds: float | None
    frac_remaining: float
    home_score: int
    away_score: int
    margin: int
    home_won: int
    espn_home_wp: float | None = None
    outs: int | None = None


def _headers() -> dict[str, str]:
    return {"User-Agent": BROWSER_USER_AGENT}


def fetch_summary(league: str, event_id: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    url = SUMMARY_URL.format(path=SPORT_PATHS[league], event=event_id)
    if client is not None:
        response = client.get(url)
    else:
        with httpx.Client(headers=_headers(), timeout=30.0, follow_redirects=True) as owned:
            response = owned.get(url)
    response.raise_for_status()
    return response.json()


def parse_clock_seconds(clock: Any) -> float | None:
    """ESPN clocks arrive as "9:51", sometimes "0.0" or already numeric."""
    if clock is None:
        return None
    if isinstance(clock, (int, float)):
        return float(clock)
    text = str(clock).strip()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            minutes = float(parts[0])
            seconds = float(parts[1])
        except (TypeError, ValueError):
            return None
        return minutes * 60.0 + seconds
    try:
        return float(text)
    except ValueError:
        return None


def frac_remaining_clock(league: str, period: int, clock_seconds: float | None) -> float:
    """Fraction of regulation still to play, for clock sports.

    Overtime returns 0.0: no regulation time remains. Callers must treat
    overtime separately rather than reading 0.0 as "game over".
    """
    conf = REGULATION[league]
    period_seconds = conf["period_minutes"] * 60.0
    total = conf["periods"] * period_seconds
    if period > conf["periods"]:
        return 0.0
    periods_done = max(0, period - 1)
    if clock_seconds is None:
        # Fall back to whole completed periods when the clock is unusable.
        elapsed = periods_done * period_seconds
        return max(0.0, min(1.0, 1.0 - elapsed / total))
    within_period = clock_seconds if conf["counts_up"] else (period_seconds - clock_seconds)
    within_period = max(0.0, min(period_seconds, within_period))
    elapsed = periods_done * period_seconds + within_period
    return max(0.0, min(1.0, 1.0 - elapsed / total))


def frac_remaining_innings(inning: int, is_top: bool) -> float:
    """Fraction of a regulation baseball game still to play."""
    half_innings_done = (inning - 1) * 2 + (0 if is_top else 1)
    total_half_innings = MLB_REGULATION_INNINGS * 2
    return max(0.0, min(1.0, 1.0 - half_innings_done / total_half_innings))


def _espn_wp_by_play(summary: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for entry in summary.get("winprobability") or []:
        play_id = entry.get("playId")
        pct = entry.get("homeWinPercentage")
        if play_id is not None and pct is not None:
            out[str(play_id)] = float(pct)
    return out


def _iter_plays(summary: dict[str, Any], league: str) -> list[dict[str, Any]]:
    """Return the flat play list, whichever shape ESPN used.

    Measured shapes: NBA/NHL/MLB expose a top-level `plays` list, but NFL
    returns `plays: null` and nests them under `drives.previous[].plays[]`.
    Reading only the top-level key silently yields zero NFL training data.
    """
    plays = summary.get("plays")
    if plays:
        return list(plays)
    drives = summary.get("drives") or {}
    if isinstance(drives, dict):
        collected: list[dict[str, Any]] = []
        for bucket in ("previous", "current"):
            for drive in drives.get(bucket) or []:
                collected.extend(drive.get("plays") or [])
        if collected:
            return collected
    return []


def snapshots_from_summary(
    summary: dict[str, Any],
    league: str,
    game_id: str,
    *,
    final_home: int | None = None,
    final_away: int | None = None,
) -> list[Snapshot]:
    """Turn one game summary into labelled in-game snapshots.

    Returns [] rather than guessing when the outcome is unknown or the game
    ended level, since an unlabelled or tied row would poison training.
    """
    plays = _iter_plays(summary, league)
    if not plays:
        return []

    if final_home is None or final_away is None:
        final_home = _last_int(plays, "homeScore")
        final_away = _last_int(plays, "awayScore")
    if final_home is None or final_away is None or final_home == final_away:
        return []

    home_won = 1 if final_home > final_away else 0
    espn_wp = _espn_wp_by_play(summary)

    out: list[Snapshot] = []
    for play in plays:
        period_obj = play.get("period") or {}
        period = _int(period_obj.get("number"))
        if period is None:
            continue
        home = _int(play.get("homeScore"))
        away = _int(play.get("awayScore"))
        if home is None or away is None:
            continue
        clock_seconds = parse_clock_seconds((play.get("clock") or {}).get("displayValue"))
        if league in REGULATION:
            frac = frac_remaining_clock(league, period, clock_seconds)
        else:
            # Baseball: period.type is "Top"/"Bottom", which halves the inning.
            is_top = str(period_obj.get("type") or "Top").lower().startswith("t")
            frac = frac_remaining_innings(period, is_top)
        out.append(
            Snapshot(
                game_id=game_id,
                league=league,
                period=period,
                clock_seconds=clock_seconds,
                frac_remaining=frac,
                home_score=home,
                away_score=away,
                margin=home - away,
                home_won=home_won,
                espn_home_wp=espn_wp.get(str(play.get("id"))),
                outs=_int(play.get("outs")),
            )
        )
    return out


def _last_int(plays: list[dict[str, Any]], key: str) -> int | None:
    for play in reversed(plays):
        value = _int(play.get(key))
        if value is not None:
            return value
    return None


def harvest_games(
    league: str,
    game_ids: list[str],
    *,
    sleep_seconds: float = 0.15,
    on_error: str = "skip",
) -> Iterator[list[Snapshot]]:
    """Yield snapshots per game, politely rate-limited.

    Errors are skipped and counted by the caller rather than aborting a long
    harvest, but they are never silently turned into empty "valid" games.
    """
    with httpx.Client(headers=_headers(), timeout=30.0, follow_redirects=True) as client:
        for game_id in game_ids:
            try:
                summary = fetch_summary(league, game_id, client=client)
            except Exception:
                if on_error == "raise":
                    raise
                continue
            yield snapshots_from_summary(summary, league, game_id)
            if sleep_seconds:
                time.sleep(sleep_seconds)


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
