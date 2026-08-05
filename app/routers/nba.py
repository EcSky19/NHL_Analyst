"""FastAPI routes for NBA UI data."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import fail, ok, season_state_for, settings
from app.services.nba_service import (
    SOURCE,
    canonical_team,
    coverage,
    db_available,
    latest_schedule_season,
    players_payload,
    resolve_season,
    schedule_payload,
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
        return ok(
            rows,
            source=SOURCE,
            season=meta_season,
            season_state=season_state_for(league="nba"),
            season_coverage=_safe_coverage(),
            **cache_meta,
        )
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE, season_coverage=_safe_coverage())
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE, season_coverage=_safe_coverage())


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
