"""FastAPI routes for NFL UI data."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request

from app.config import fail, ok, season_state_for, settings, utc_now_iso
from app.services.nfl_service import (
    SOURCE,
    available_seasons,
    canonical_team,
    fetch_games,
    latest_completed_season,
    live_games,
    players_payload,
    schedule_for,
    schedule_week as schedule_week_rows,
    schedule_window,
    standings_for_season_cached,
    teams_payload,
)

router = APIRouter()


@router.get("/standings")
def standings(season: int | None = None) -> dict[str, Any]:
    """Return computed regular-season NFL standings."""
    try:
        games, meta = fetch_games(settings.ttl_standings)
        selected = season or latest_completed_season(games)
        if selected is None:
            return fail("no_data", "No NFL games are available", source=SOURCE, **meta)
        error = _validate_season(selected, games, meta)
        if error:
            return error
        rows = standings_for_season_cached(selected)
        if not rows:
            return fail("no_data", f"No completed regular-season games for {selected}", source=SOURCE, season=selected, season_state=season_state_for(league="nfl"), **meta)
        return ok(rows, source=SOURCE, season=selected, season_state=season_state_for(league="nfl"), **meta)
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE)


@router.get("/teams")
def teams() -> dict[str, Any]:
    """Return NFL teams with summary standings and advanced stats."""
    try:
        games, games_meta = fetch_games(settings.ttl_stats)
        season = latest_completed_season(games)
        if season is None:
            return fail("no_data", "No completed NFL season is available", source=SOURCE, **games_meta)
        rows, stats_meta = teams_payload(season)
        return ok(rows, source=SOURCE, season=season, season_state=season_state_for(league="nfl"), **_merge_cache_meta(games_meta, stats_meta))
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE)


@router.get("/teams/{abbrev}")
def team_detail(abbrev: str) -> dict[str, Any]:
    """Return one NFL team detail by abbreviation."""
    team = canonical_team(abbrev)
    if team is None:
        return fail("not_found", f"Unknown NFL team abbreviation: {abbrev}", source=SOURCE)
    response = teams()
    if not response.get("ok"):
        return response
    for item in response["data"]:
        if item["abbrev"] == team:
            meta = dict(response["meta"])
            source = meta.pop("source", SOURCE)
            return ok(item, source=source, **meta)
    return fail("not_found", f"Unknown NFL team abbreviation: {abbrev}", source=SOURCE)


@router.get("/players")
def players(team: str | None = None, stat: str = "passing_yards", limit: int = 25) -> dict[str, Any]:
    """Return NFL QB leaders from the local research database."""
    if limit < 1 or limit > 100:
        return fail("bad_request", "limit must be between 1 and 100", source=SOURCE)
    try:
        games, games_meta = fetch_games(settings.ttl_stats)
        season = latest_completed_season(games)
        if season is None:
            return fail("no_data", "No completed NFL season is available", source=SOURCE, **games_meta)
        rows, stats_meta = players_payload(team, stat, limit, season)
        return ok(rows, source=SOURCE, season=season, season_state=season_state_for(league="nfl"), **_merge_cache_meta(games_meta, stats_meta))
    except KeyError:
        return fail("not_found", f"Unknown NFL team abbreviation: {team}", source=SOURCE)
    except ValueError as exc:
        return fail("bad_request", str(exc), source=SOURCE)
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE)


@router.get("/live")
def live() -> dict[str, Any]:
    """Return currently in-progress NFL games when nflverse can report them."""
    try:
        games, meta = fetch_games(settings.ttl_schedule)
        rows = live_games(games)
        return ok(
            rows,
            source=SOURCE,
            count=len(rows),
            season_state=season_state_for(league="nfl"),
            league="nfl",
            polled_at=utc_now_iso(),
            poll_interval_seconds=30,
            empty_reason=(
                None
                if rows
                else _nfl_live_empty_reason(games)
            ),
            **meta,
        )
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE, league="nfl")


@router.get("/schedule/week")
def schedule_week(request: Request, start: str | None = None, days: int = 7, week: int | None = None) -> dict[str, Any]:
    """Return a flat NFL schedule window or one NFL week."""
    if week is not None and ("start" in request.query_params or "days" in request.query_params):
        return fail("bad_request", "week cannot be combined with start or days", source=SOURCE, league="nfl")
    if days < 1 or days > 14:
        return fail("bad_request", "days must be between 1 and 14", source=SOURCE, league="nfl")
    if week is not None and (week < 1 or week > 22):
        return fail("bad_request", "week must be between 1 and 22", source=SOURCE, league="nfl")
    start_date = _parse_query_date(start) if start is not None else datetime.now(timezone.utc).date()
    if start_date is None:
        return fail("bad_request", "start must be a YYYY-MM-DD date", source=SOURCE, league="nfl")

    try:
        games, meta = fetch_games(settings.ttl_schedule)
        if week is not None:
            seasons = available_seasons(games)
            season = max(seasons) if seasons else None
            rows = schedule_week_rows(games, season, week) if season is not None else []
            return ok(
                rows,
                source=SOURCE,
                season=season,
                week=week,
                count=len(rows),
                season_state=season_state_for(league="nfl"),
                league="nfl",
                empty_reason=None if rows else _nfl_covered_empty_reason(games),
                **meta,
            )

        end_date = start_date + timedelta(days=days - 1)
        rows = schedule_window(games, start_date, days)
        return ok(
            rows,
            source=SOURCE,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            days=days,
            count=len(rows),
            season_state=season_state_for(league="nfl"),
            league="nfl",
            empty_reason=None if rows else _nfl_covered_empty_reason(games),
            **meta,
        )
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE, league="nfl")


@router.get("/schedule")
def schedule(season: int | None = None, week: int | None = None) -> dict[str, Any]:
    """Return NFL schedule games by season and optional week."""
    if week is not None and (week < 1 or week > 22):
        return fail("bad_request", "week must be between 1 and 22", source=SOURCE)
    try:
        games, meta = fetch_games(settings.ttl_schedule)
        seasons = available_seasons(games)
        selected = season or (max(seasons) if seasons else None)
        if selected is None:
            return fail("no_data", "No NFL schedule is available", source=SOURCE, **meta)
        error = _validate_season(selected, games, meta)
        if error:
            return error
        rows = schedule_for(games, selected, week)
        if week is not None and not rows:
            return fail("no_data", f"No NFL games found for season {selected}, week {week}", source=SOURCE, season=selected, season_state=season_state_for(league="nfl"), **meta)
        return ok(rows, source=SOURCE, season=selected, week=week, season_state=season_state_for(league="nfl"), **meta)
    except Exception as exc:  # noqa: BLE001
        return fail("upstream_unavailable", str(exc), source=SOURCE)


def _validate_season(season: int, games: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any] | None:
    seasons = available_seasons(games)
    if season not in seasons:
        return fail(
            "bad_request",
            f"season must be between {min(seasons)} and {max(seasons)}",
            source=SOURCE,
            season=season,
            season_state=season_state_for(league="nfl"),
            **meta,
        )
    return None


def _merge_cache_meta(*items: dict[str, Any]) -> dict[str, Any]:
    """Combine cache metadata from multiple data sources."""
    merged: dict[str, Any] = {"cached": False, "stale": False}
    ages: list[float] = []
    stale_reasons: list[str] = []
    for item in items:
        merged["cached"] = bool(merged["cached"] or item.get("cached"))
        merged["stale"] = bool(merged["stale"] or item.get("stale"))
        if item.get("age_seconds") is not None:
            ages.append(float(item["age_seconds"]))
        if item.get("stale_reason"):
            stale_reasons.append(str(item["stale_reason"]))
    if ages:
        merged["age_seconds"] = round(max(ages), 1)
    if stale_reasons:
        merged["stale_reason"] = "; ".join(stale_reasons)
    return merged


def _parse_query_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _nfl_covered_empty_reason(games: list[dict[str, Any]]) -> str:
    seasons = available_seasons(games)
    latest = max(seasons) if seasons else None
    opener = _season_opener(games, latest) if latest is not None else None
    suffix = f", and the {latest} regular season opens {opener}" if latest is not None and opener else ""
    return (
        "No NFL regular-season or postseason games fall in this window. "
        f"The nflverse source used here does not include preseason games{suffix}."
    )


def _nfl_live_empty_reason(games: list[dict[str, Any]]) -> str:
    return (
        "nflverse games.csv does not expose true real-time NFL clock, quarter, or last-play state. "
        f"{_nfl_covered_empty_reason(games)}"
    )


def _season_opener(games: list[dict[str, Any]], season: int | None) -> str | None:
    if season is None:
        return None
    dates = [
        str(row["gameday"])
        for row in games
        if row.get("season") == season and row.get("gameday") and str(row.get("game_type") or "").upper() == "REG"
    ]
    return min(dates) if dates else None
