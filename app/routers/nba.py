"""FastAPI routes for NBA UI data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter

from app.config import fail, ok, season_state_for, settings
from app.services.nba_service import (
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
            empty_reason = (
                "NBA is in its offseason; no games are scheduled in this window."
                if league_state == "offseason"
                else "No NBA games are scheduled in this window."
            )
        return ok(
            rows,
            source=SOURCE,
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
    """Return currently in-progress NBA games only, if a verified source exists."""
    league_state = season_state_for(league="nba")
    try:
        rows, cache_meta = live_payload()
        empty_reason = None
        if not rows:
            empty_reason = (
                "No free verified NBA source available to this app exposes true real-time in-game state; returning no live games rather than fabricating data."
            )
        return ok(
            rows,
            source=SOURCE,
            **cache_meta,
            count=len(rows),
            season_state=league_state,
            league="nba",
            polled_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            poll_interval_seconds=30,
            empty_reason=empty_reason,
        )
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE, season_state=league_state, league="nba")


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
