"""FastAPI entrypoint for the Sports Analytics UI.

Routers are imported defensively: a broken or missing router degrades that one
section instead of preventing the whole app from booting.
"""

from __future__ import annotations

import importlib
import logging
import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.cache import cached_fetch, clear_cache
from app.config import fail, ok, season_state_for, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Sports Analytics UI",
    description="Live NHL and NFL standings, stats, and honestly-labelled model predictions.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

ROUTER_MODULES = [
    ("app.routers.nhl", "/api/nhl", ["nhl"]),
    ("app.routers.nfl", "/api/nfl", ["nfl"]),
    ("app.routers.nba", "/api/nba", ["nba"]),
    ("app.routers.mlb", "/api/mlb", ["mlb"]),
    ("app.routers.predictions", "/api/predictions", ["predictions"]),
]

LOADED_ROUTERS: dict[str, str] = {}

for module_path, prefix, tags in ROUTER_MODULES:
    try:
        module = importlib.import_module(module_path)
        app.include_router(module.router, prefix=prefix, tags=tags)
        LOADED_ROUTERS[module_path] = "loaded"
    except Exception as exc:  # noqa: BLE001 - keep the app bootable
        LOADED_ROUTERS[module_path] = f"unavailable: {type(exc).__name__}: {exc}"
        logger.warning("Router %s unavailable: %s", module_path, exc)


@app.get("/api/health")
def health() -> dict:
    """Liveness plus a view of which routers and local databases are present."""
    return ok(
        {
            "status": "up",
            "routers": LOADED_ROUTERS,
            "databases": {
                "nhl": settings.nhl_db.exists(),
                "nfl": settings.nfl_db.exists(),
                "nba": settings.nba_db.exists(),
                "mlb": settings.mlb_db.exists(),
            },
            "season_state": {
                "nhl": season_state_for(league="nhl"),
                "nfl": season_state_for(league="nfl"),
                "nba": season_state_for(league="nba"),
                "mlb": season_state_for(league="mlb"),
            },
        },
        source="app",
    )


@app.get("/api/meta/seasons")
def meta_seasons() -> dict:
    """Seasons that actually have data, per league.

    Sourced from the local databases so the UI's season pickers can never offer a
    season we cannot serve. Synthetic NHL rows are excluded via `is_synthetic`.
    """

    def load() -> dict:
        payload: dict[str, list] = {"nhl": [], "nfl": []}

        if settings.nhl_db.exists():
            with sqlite3.connect(f"file:{settings.nhl_db}?mode=ro", uri=True) as conn:
                rows = conn.execute(
                    "SELECT season, COUNT(*) FROM historical_games_last5 "
                    "WHERE is_synthetic = 0 AND is_final = 1 "
                    "GROUP BY season ORDER BY season DESC"
                ).fetchall()
            payload["nhl"] = [
                {"season": str(season), "label": _nhl_label(season), "games": count}
                for season, count in rows
            ]

        if settings.nfl_db.exists():
            with sqlite3.connect(f"file:{settings.nfl_db}?mode=ro", uri=True) as conn:
                rows = conn.execute(
                    "SELECT season, "
                    "SUM(CASE WHEN home_score IS NOT NULL THEN 1 ELSE 0 END), COUNT(*) "
                    "FROM games GROUP BY season ORDER BY season DESC"
                ).fetchall()
            payload["nfl"] = [
                {
                    "season": str(season),
                    "label": str(season),
                    "games": played,
                    "scheduled": total,
                    "complete": played == total and total > 0,
                }
                for season, played, total in rows
            ]

        return payload

    try:
        data, cache_meta = cached_fetch("meta:seasons", settings.ttl_stats, load)
    except Exception as exc:  # noqa: BLE001 - surface as an envelope, never a 500
        logger.warning("meta/seasons failed: %s", exc)
        return fail("internal", f"Could not read season metadata: {exc}", source="app")

    if not data["nhl"] and not data["nfl"]:
        return fail("no_data", "No local season data is available.", source="app")

    return ok(
        data,
        source="local-db",
        season_state={"nhl": season_state_for(league="nhl"), "nfl": season_state_for(league="nfl")},
        **cache_meta,
    )


def _nhl_label(season: object) -> str:
    """Render 20242025 as 2024-25."""
    text = str(season)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[6:]}"
    return text


@app.post("/api/cache/clear")
def cache_clear() -> dict:
    return ok({"removed": clear_cache()}, source="app")


@app.get("/", response_model=None)
def index() -> FileResponse | JSONResponse:
    candidate = STATIC_DIR / "index.html"
    if candidate.exists():
        return FileResponse(candidate)
    return JSONResponse(
        {"ok": False, "error": {"code": "no_data", "message": "UI not built yet."}}
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
