"""Configuration and shared response helpers for the Sports Analytics UI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Settings:
    """Runtime settings, overridable by environment variable."""

    host: str = os.environ.get("UI_HOST", "127.0.0.1")
    port: int = int(os.environ.get("UI_PORT", "8000"))
    cache_dir: Path = REPO_ROOT / "data" / "ui_cache"
    nhl_db: Path = REPO_ROOT / "data" / "processed" / "nhl_research.db"
    nfl_db: Path = REPO_ROOT / "data" / "nfl" / "nfl_research.db"
    nba_db: Path = REPO_ROOT / "data" / "nba" / "nba_research.db"
    nba_recent_games_db: Path = REPO_ROOT / "data" / "nba" / "nba_recent_games.db"
    mlb_db: Path = REPO_ROOT / "data" / "mlb" / "mlb_research.db"

    nhl_api_base: str = "https://api-web.nhle.com/v1"
    nhl_stats_api_base: str = "https://api.nhle.com/stats/rest/en"
    nflverse_games_url: str = (
        "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
    )
    mlb_api_base: str = "https://statsapi.mlb.com/api/v1"

    request_timeout: float = float(os.environ.get("UI_TIMEOUT", "20"))

    ttl_standings: int = 300
    ttl_stats: int = 900
    ttl_schedule: int = 120
    ttl_predictions: int = 600

    # Measured accuracy. These are audited figures - see docs/ui_api_contract.md.
    # They must never be inflated in the UI.
    nhl_model_accuracy: float = 0.5682
    nhl_baseline_accuracy: float = 0.535
    nfl_market_free_accuracy: float = 0.6611
    nfl_full_accuracy: float = 0.6740
    nfl_vegas_accuracy: float = 0.6851
    nfl_baseline_accuracy: float = 0.5617

    # A confidence tier computed on fewer than this many games is not trustworthy.
    min_tier_games: int = 150

    extra: dict[str, Any] = field(default_factory=dict)


settings = Settings()
settings.cache_dir.mkdir(parents=True, exist_ok=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ok(data: Any, *, source: str, **meta: Any) -> dict[str, Any]:
    """Build a successful envelope. See docs/ui_api_contract.md."""
    payload_meta: dict[str, Any] = {
        "source": source,
        "fetched_at": utc_now_iso(),
        "cached": False,
        "stale": False,
    }
    payload_meta.update(meta)
    return {"ok": True, "data": data, "error": None, "meta": payload_meta}


def fail(code: str, message: str, *, source: str, **meta: Any) -> dict[str, Any]:
    """Build a failure envelope. Always HTTP 200 so the client parses one shape."""
    payload_meta: dict[str, Any] = {
        "source": source,
        "fetched_at": None,
        "cached": False,
        "stale": True,
    }
    payload_meta.update(meta)
    return {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message},
        "meta": payload_meta,
    }


def season_state_for(today: datetime | None = None, league: str = "nhl") -> str:
    """Classify where we are in the calendar.

    August sits between seasons for both leagues, so a naive "current standings"
    lookup would show an empty or misleading table. Callers use this to label data.
    """
    today = today or datetime.now(timezone.utc)
    month, day = today.month, today.day
    if league == "nhl":
        if month in (7, 8) or (month == 9 and day < 15):
            return "offseason"
        if month == 9:
            return "preseason"
        if month in (5, 6):
            return "playoffs"
        return "regular"
    if league == "nba":
        if month in (7, 8) or (month == 9 and day < 20):
            return "offseason"
        if month == 9 or (month == 10 and day < 15):
            return "preseason"
        if month in (5, 6):
            return "playoffs"
        return "regular"
    if league == "mlb":
        # MLB runs late March through October, so summer is mid-season.
        if month in (11, 12, 1, 2):
            return "offseason"
        if month == 3 and day < 20:
            return "preseason"
        if month == 10:
            return "playoffs"
        return "regular"
    if month in (3, 4, 5, 6, 7) or (month == 8 and day < 5):
        return "offseason"
    if month == 8:
        return "preseason"
    if month in (1, 2):
        return "playoffs"
    return "regular"
