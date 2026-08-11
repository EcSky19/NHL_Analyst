"""FastAPI routes for NBA UI data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter

from app.config import fail, ok, season_state_for, settings
from app.services.espn_pbp import (
    REGULATION,
    frac_remaining_clock,
    frac_remaining_innings,
    ot_frac_remaining_clock,
    parse_clock_seconds,
)
from app.services.live_winprob import GameState, predict_home_win_prob
from app.services.nba_service import (
    ESPN_SOURCE,
    SOURCE,
    canonical_team,
    coverage,
    db_available,
    latest_schedule_season,
    live_payload,
    players_payload,
    resolve_season,
    schedule_payload,
    schedule_window_payload,
    standings_payload,
    teams_payload,
    validate_date,
)

router = APIRouter()


@router.get("/standings")
def standings(season: str | None = None) -> dict[str, Any]:
    """Return NBA standings from current or historical local data."""
    try:
        selected = resolve_season(season)
        rows, cache_meta = standings_payload(selected)
        if not rows:
            return _failure("no_data", f"No NBA standings for {selected.label}", selected, cache_meta)
        return _success(rows, selected, cache_meta)
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE, season_coverage=_safe_coverage())
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE, season_coverage=_safe_coverage())


@router.get("/teams")
def teams() -> dict[str, Any]:
    """Return NBA teams with standings and summary stats."""
    try:
        selected = resolve_season(None)
        rows, cache_meta = teams_payload(selected)
        if not rows:
            return _failure("no_data", "No NBA teams are available", selected, cache_meta)
        return _success(rows, selected, cache_meta)
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE, season_coverage=_safe_coverage())


@router.get("/teams/{abbrev}")
def team_detail(abbrev: str) -> dict[str, Any]:
    """Return one NBA team detail by abbreviation or historical alias."""
    team = canonical_team(abbrev)
    if team is None:
        return fail("not_found", f"Unknown NBA team abbreviation: {abbrev}", source=SOURCE, season_coverage=_safe_coverage())
    response = teams()
    if not response.get("ok"):
        return response
    for item in response["data"]:
        if item["abbrev"] == team:
            meta = dict(response["meta"])
            source = meta.pop("source", SOURCE)
            return ok(item, source=source, **meta)
    return fail("not_found", f"Unknown NBA team abbreviation: {abbrev}", source=SOURCE, season_coverage=_safe_coverage())


@router.get("/players")
def players(team: str | None = None, stat: str = "points_per_game", limit: int = 25) -> dict[str, Any]:
    """Return current NBA player leaders."""
    if limit < 1 or limit > 100:
        return fail("bad_request", "limit must be between 1 and 100", source=SOURCE, season_coverage=_safe_coverage())
    try:
        rows, cache_meta = players_payload(team, stat, limit)
        selected = resolve_season(None)
        if not rows:
            return _failure("no_data", "No NBA player leaders match the request", selected, cache_meta)
        return _success(rows, selected, cache_meta)
    except KeyError:
        return fail("not_found", f"Unknown NBA team abbreviation: {team}", source=SOURCE, season_coverage=_safe_coverage())
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE, season_coverage=_safe_coverage())
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE, season_coverage=_safe_coverage())


@router.get("/schedule")
def schedule(date: str | None = None, season: str | None = None) -> dict[str, Any]:
    """Return NBA games by optional date and season."""
    try:
        game_date = validate_date(date) if date else None
    except ValueError:
        return fail("bad_request", "date must be YYYY-MM-DD", source=SOURCE, season_coverage=_safe_coverage())
    try:
        if season is None:
            requested_date = game_date or datetime.now(timezone.utc).date().isoformat()
            rows, cache_meta = schedule_window_payload(requested_date, requested_date)
            return ok(
                rows,
                source=ESPN_SOURCE,
                **cache_meta,
                season_state=season_state_for(league="nba"),
                count=len(rows),
                date=requested_date,
                league="nba",
                empty_reason=_espn_empty_reason(rows, cache_meta, "schedule", requested_date, requested_date),
            )
        selected = resolve_season(season) if season else (latest_schedule_season() if not date else None)
        rows, cache_meta = schedule_payload(game_date, selected)
        if not rows:
            label = selected.label if selected else "all available seasons"
            return fail(
                "no_data",
                f"No NBA games found for {label}{f' on {game_date}' if game_date else ''}",
                source=SOURCE,
                season=selected.label if selected else None,
                season_state=season_state_for(league="nba"),
                season_coverage=_safe_coverage(),
                **cache_meta,
            )
        meta_season = selected.label if selected else rows[0].get("season")
        historical_meta = _historical_schedule_meta(rows)
        return ok(
            rows,
            source=SOURCE,
            season=meta_season,
            season_state=season_state_for(league="nba"),
            season_coverage=_safe_coverage(),
            **historical_meta,
            **cache_meta,
        )
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE, season_coverage=_safe_coverage())
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE, season_coverage=_safe_coverage())


@router.get("/schedule/week")
def schedule_week(start: str | None = None, days: str | None = None) -> dict[str, Any]:
    """Return a flat NBA schedule window in the frozen shared game-row shape."""
    league_state = season_state_for(league="nba")
    try:
        start_date, day_count, end_date = _validate_week_params(start, days)
        rows, cache_meta = schedule_window_payload(start_date, end_date)
        rows.sort(key=lambda row: (row.get("start_time_utc") or "", row.get("game_id") or ""))
        empty_reason = None
        if not rows:
            empty_reason = _espn_empty_reason(rows, cache_meta, "schedule", start_date, end_date)
        return ok(
            rows,
            source=ESPN_SOURCE,
            **cache_meta,
            start_date=start_date,
            end_date=end_date,
            days=day_count,
            count=len(rows),
            season_state=league_state,
            league="nba",
            empty_reason=empty_reason,
        )
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE, season_state=league_state, league="nba")
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE, season_state=league_state, league="nba")


@router.get("/live")
def live() -> dict[str, Any]:
    """Return currently in-progress NBA games only from ESPN."""
    league_state = season_state_for(league="nba")
    try:
        rows, cache_meta = live_payload()
        rows = [_with_live_win_probability(row, "nba") for row in rows]
        return ok(
            rows,
            source=ESPN_SOURCE,
            **cache_meta,
            count=len(rows),
            season_state=league_state,
            league="nba",
            polled_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            poll_interval_seconds=30,
            empty_reason=_espn_empty_reason(rows, cache_meta, "live"),
        )
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=ESPN_SOURCE, season_state=league_state, league="nba")


def _success(data: Any, selected: Any, cache_meta: dict[str, Any]) -> dict[str, Any]:
    return ok(
        data,
        source=SOURCE,
        season=selected.label,
        season_state=season_state_for(league="nba"),
        season_coverage=_safe_coverage(),
        **cache_meta,
    )


def _failure(code: str, message: str, selected: Any, cache_meta: dict[str, Any]) -> dict[str, Any]:
    return fail(
        code,
        message,
        source=SOURCE,
        season=selected.label,
        season_state=season_state_for(league="nba"),
        season_coverage=_safe_coverage(),
        **cache_meta,
    )


def _safe_coverage() -> dict[str, Any]:
    if not db_available():
        return {"available": False, "database": str(settings.nba_db)}
    try:
        return coverage()
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": str(exc)}


def _validate_week_params(start: str | None, days: str | None) -> tuple[str, int, str]:
    start_date = validate_date(start) if start else datetime.now(timezone.utc).date().isoformat()
    try:
        day_count = int(days) if days is not None else 7
    except ValueError as exc:
        raise ValueError("days must be an integer between 1 and 14") from exc
    if day_count < 1 or day_count > 14:
        raise ValueError("days must be between 1 and 14")
    end_date = (datetime.fromisoformat(start_date).date() + timedelta(days=day_count - 1)).isoformat()
    return start_date, day_count, end_date


def _historical_schedule_meta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"historical": False, "empty_reason": None}
    today = datetime.now(timezone.utc).date().isoformat()
    latest_game_date = max(str(row.get("game_date") or "") for row in rows)
    historical = latest_game_date < today
    return {
        "historical": historical,
        "latest_game_date": latest_game_date,
        "empty_reason": (
            "Latest available NBA schedule data is historical; no upcoming NBA schedule is available locally."
            if historical
            else None
        ),
    }


def _espn_empty_reason(
    rows: list[dict[str, Any]],
    cache_meta: dict[str, Any],
    kind: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str | None:
    if rows:
        return None
    if cache_meta.get("stale"):
        reason = cache_meta.get("stale_reason") or "ESPN refresh failed"
        return f"ESPN NBA data is currently unreachable; serving cached empty {kind} result. {reason}"
    league_state = season_state_for(league="nba")
    if kind == "live":
        if league_state == "offseason":
            return "ESPN returned no live NBA games today; the NBA is in its offseason."
        return "ESPN returned no currently in-progress NBA games."
    window = start_date if start_date == end_date else f"{start_date} through {end_date}"
    if league_state == "offseason":
        return f"ESPN returned no NBA games for {window}; the NBA is in its offseason."
    return f"ESPN returned no NBA games for {window}."


def _live_win_probability(row: dict[str, Any], league: str) -> dict[str, Any]:
    """Return the honest live win-probability payload for one live row."""
    unavailable = {
        "available": False,
        "home": None,
        "away": None,
        "model": f"{league}_live_wp",
        "reason": "Live win probability unavailable because live game state is incomplete.",
    }
    if row.get("status") != "live":
        return unavailable
    live = row.get("live") if isinstance(row.get("live"), dict) else {}
    home_score = _wp_int(row.get("home_score"))
    away_score = _wp_int(row.get("away_score"))
    period = _wp_int(live.get("period"))
    if home_score is None or away_score is None or period is None:
        return unavailable

    if league == "mlb":
        label = str(live.get("period_label") or row.get("detailed_status") or "")
        is_top = label.upper().startswith("T") or label.lower().startswith("top")
        is_overtime = period > 9
        frac_remaining = 0.0 if is_overtime else frac_remaining_innings(period, is_top)
    else:
        is_overtime = period > int(REGULATION[league]["periods"])
        clock_seconds = parse_clock_seconds(live.get("clock"))
        frac_remaining = frac_remaining_clock(league, period, clock_seconds)
        ot_frac_remaining = ot_frac_remaining_clock(league, period, clock_seconds)

    prob, meta = predict_home_win_prob(
        GameState(
            league=league,
            margin=home_score - away_score,
            frac_remaining=frac_remaining,
            period=period,
            is_overtime=is_overtime,
            ot_frac_remaining=ot_frac_remaining if league == "nba" else None,
        )
    )
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


def _with_live_win_probability(row: dict[str, Any], league: str) -> dict[str, Any]:
    if row.get("status") != "live":
        return row
    return {**row, "win_probability": _live_win_probability(row, league)}


def _wp_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
