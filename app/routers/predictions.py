"""FastAPI router for honest prediction endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.routing import _IncludedRouter

from app.cache import cached_fetch
from app.config import fail, ok, season_state_for, settings
from app.services.prediction_service import (
    PredictionError,
    nba_matchup,
    nfl_holdout_predictions,
    nfl_matchup,
    nhl_matchup,
    validate_iso_date,
)

router = APIRouter()

if not hasattr(_IncludedRouter, "path"):
    _IncludedRouter.path = property(lambda self: self.include_context.prefix)  # type: ignore[attr-defined]


def _offseason_note(league: str) -> str:
    return f"No {league.upper()} upcoming fixtures are served from local data during the August 2026 offseason; no games were invented."


@router.get("/nhl")
def nhl_predictions(date: str | None = None) -> dict:
    """Return NHL predictions only when real fixtures are available."""
    try:
        validate_iso_date(date)
    except ValueError:
        return fail("bad_request", "date must be YYYY-MM-DD", source="predictions-nhl")
    return ok(
        [],
        source="predictions-nhl",
        season_state=season_state_for(datetime.now(timezone.utc), "nhl"),
        note=_offseason_note("nhl"),
        date=date,
    )


@router.get("/nfl")
def nfl_predictions(season: int | None = None, week: int | None = None) -> dict:
    """Return NFL predictions; historical holdout rows require season and week."""
    if week is not None and not 1 <= week <= 22:
        return fail("bad_request", "week must be between 1 and 22", source="predictions-nfl")
    if season is not None and not 1999 <= season <= 2100:
        return fail("bad_request", "season must be a four-digit NFL season", source="predictions-nfl")
    try:
        rows, cache_meta = cached_fetch(
            f"predictions:v3:nfl:{season}:{week}",
            settings.ttl_predictions,
            lambda: nfl_holdout_predictions(season, week),
        )
    except Exception as exc:  # noqa: BLE001
        return fail("internal", f"could not load NFL predictions: {exc}", source="predictions-nfl")
    note = (
        "Loaded frozen 2024-2025 holdout rows with market-free primary and full secondary models."
        if rows
        else _offseason_note("nfl")
    )
    return ok(
        rows,
        source="predictions-nfl",
        **cache_meta,
        season_state=season_state_for(datetime.now(timezone.utc), "nfl"),
        note=note,
        season=season,
        week=week,
        market_note="The full/market-aware NFL model largely echoes Vegas and did not beat the 68.51% Vegas bar.",
    )


@router.get("/matchup")
def matchup(league: str, home: str, away: str) -> dict:
    """Score an ad-hoc hypothetical matchup without inventing a fixture."""
    league_norm = league.lower().strip()
    home_norm = home.upper().strip()
    away_norm = away.upper().strip()
    if league_norm not in {"nhl", "nfl", "nba"}:
        return fail("bad_request", "league must be nhl, nfl, or nba", source="predictions-matchup")
    try:
        rows, cache_meta = cached_fetch(
            f"predictions:v5:matchup:{league_norm}:{home_norm}:{away_norm}",
            settings.ttl_predictions,
            lambda: (
                nhl_matchup(home_norm, away_norm)
                if league_norm == "nhl"
                else nba_matchup(home_norm, away_norm)
                if league_norm == "nba"
                else nfl_matchup(home_norm, away_norm)
            ),
        )
    except PredictionError as exc:
        return fail(exc.code, exc.message, source="predictions-matchup", league=league_norm)
    except Exception as exc:  # noqa: BLE001
        return fail("internal", f"could not score matchup: {exc}", source="predictions-matchup", league=league_norm)
    return ok(
        rows,
        source="predictions-matchup",
        **cache_meta,
        season_state=season_state_for(datetime.now(timezone.utc), league_norm),
        note="Ad-hoc hypothetical matchup only; game_id is labelled hypothetical and is not a scheduled fixture.",
        market_note=(
            "No live betting line exists for a hypothetical matchup, so the secondary "
            "'market-aware' model falls back to a historical market proxy and lands very close "
            "to the market-free model (typically within ~0.01). Treat the two as one estimate "
            "here, not as independent confirmation. Neither NFL model beat the 68.51% Vegas bar."
            if league_norm == "nfl"
            else None
        ),
    )
