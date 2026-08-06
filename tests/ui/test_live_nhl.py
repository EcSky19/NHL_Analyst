from __future__ import annotations

from datetime import date
from typing import Any

import pytest


SHARED_KEYS = {
    "game_id",
    "league",
    "game_date",
    "start_time_utc",
    "home",
    "away",
    "home_name",
    "away_name",
    "home_score",
    "away_score",
    "status",
    "detailed_status",
    "venue",
}
ALLOWED_STATUSES = {"scheduled", "live", "final", "postponed"}


def _game(status: str = "scheduled") -> dict[str, Any]:
    return {
        "game_id": "2026020001",
        "league": "nhl",
        "game_date": "2026-09-29",
        "start_time_utc": "2026-09-29T21:00:00Z",
        "home": "CAR",
        "away": "FLA",
        "home_name": "Carolina Hurricanes",
        "away_name": "Florida Panthers",
        "home_score": None if status == "scheduled" else 4,
        "away_score": None if status == "scheduled" else 2,
        "status": status,
        "detailed_status": "FUT" if status == "scheduled" else "OFF",
        "venue": "Lenovo Center",
    }


def test_nhl_schedule_week_empty_window_has_truthful_meta(client, monkeypatch: pytest.MonkeyPatch):
    import app.routers.nhl as nhl

    meta = {"cached": True, "stale": False, "age_seconds": 0.0}
    monkeypatch.setattr(nhl, "_fetch_schedule_week", lambda start, days: ([], meta, None))
    monkeypatch.setattr(nhl, "_next_scheduled_game_date", lambda start: ("2026-09-19", meta))

    payload = client.get("/api/nhl/schedule/week?start=2026-08-05&days=7").json()

    assert payload["ok"] is True
    assert payload["data"] == []
    assert payload["meta"]["league"] == "nhl"
    assert payload["meta"]["start_date"] == "2026-08-05"
    assert payload["meta"]["end_date"] == "2026-08-11"
    assert payload["meta"]["days"] == 7
    assert payload["meta"]["count"] == 0
    assert isinstance(payload["meta"]["empty_reason"], str)
    assert payload["meta"]["next_scheduled_game_date"] == "2026-09-19"


def test_nhl_schedule_week_returns_flat_rows(client, monkeypatch: pytest.MonkeyPatch):
    import app.routers.nhl as nhl

    meta = {"cached": True, "stale": False, "age_seconds": 0.0}
    rows = [_game("scheduled"), {**_game("final"), "game_id": "2025020283", "game_date": "2025-11-15"}]
    monkeypatch.setattr(nhl, "_fetch_schedule_week", lambda start, days: (rows, meta, "20262027"))

    payload = client.get("/api/nhl/schedule/week?start=2026-09-29&days=7").json()

    assert payload["ok"] is True
    assert len(payload["data"]) == 2
    assert payload["meta"]["count"] == 2
    assert payload["meta"]["empty_reason"] is None
    assert all(SHARED_KEYS <= set(row) for row in payload["data"])
    assert {row["status"] for row in payload["data"]} <= ALLOWED_STATUSES
    assert payload["data"][0]["home_score"] is None


def test_nhl_schedule_week_bad_params_return_enveloped_bad_request(client):
    for query in ("days=0", "days=15", "start=notadate"):
        response = client.get(f"/api/nhl/schedule/week?{query}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert payload["error"]["code"] == "bad_request"


def test_nhl_live_empty_in_offseason_is_ok(client, monkeypatch: pytest.MonkeyPatch):
    import app.routers.nhl as nhl

    meta = {"cached": True, "stale": False, "age_seconds": 0.0}
    monkeypatch.setattr(nhl, "_fetch_live_games", lambda today: ([], meta))
    monkeypatch.setattr(nhl, "_next_scheduled_game_date", lambda start: ("2026-09-19", meta))

    payload = client.get("/api/nhl/live").json()

    assert payload["ok"] is True
    assert payload["data"] == []
    assert payload["meta"]["league"] == "nhl"
    assert payload["meta"]["count"] == 0
    assert payload["meta"]["poll_interval_seconds"] == 30
    assert isinstance(payload["meta"]["empty_reason"], str)
    assert payload["meta"]["next_scheduled_game_date"] == "2026-09-19"


def test_nhl_live_rows_include_live_object(client, monkeypatch: pytest.MonkeyPatch):
    import app.routers.nhl as nhl

    meta = {"cached": True, "stale": False, "age_seconds": 0.0}
    row = {
        **_game("live"),
        "game_id": "2025020001",
        "game_date": "2025-11-15",
        "home_score": 2,
        "away_score": 1,
        "detailed_status": "CRIT",
        "live": {"period": 3, "period_label": "P3", "clock": "04:12", "last_play": None},
    }
    monkeypatch.setattr(nhl, "_fetch_live_games", lambda today: ([row], meta))

    payload = client.get("/api/nhl/live").json()

    assert payload["ok"] is True
    assert payload["meta"]["count"] == 1
    assert SHARED_KEYS <= set(payload["data"][0])
    assert payload["data"][0]["status"] == "live"
    assert payload["data"][0]["live"] == {"period": 3, "period_label": "P3", "clock": "04:12", "last_play": None}


def test_nhl_normalizes_upstream_status_and_scores():
    import app.routers.nhl as nhl

    future = {
        "id": 1,
        "gameState": "FUT",
        "gameScheduleState": "OK",
        "homeTeam": {"abbrev": "CAR", "score": 0},
        "awayTeam": {"abbrev": "FLA", "score": 0},
    }
    critical = {**future, "gameState": "CRIT", "homeTeam": {"score": 2}, "awayTeam": {"score": 1}}
    postponed = {**future, "gameScheduleState": "PPD"}

    assert nhl._normalize_game(future, date(2026, 9, 29).isoformat())["status"] == "scheduled"
    assert nhl._normalize_game(future, "2026-09-29")["home_score"] is None
    assert nhl._normalize_game(critical, "2025-11-15")["status"] == "live"
    assert nhl._normalize_game(postponed, "2026-09-29")["status"] == "postponed"


def test_next_scheduled_game_date_points_to_a_day_with_games(monkeypatch: pytest.MonkeyPatch):
    import app.routers.nhl as nhl

    meta = {"cached": True, "stale": False, "age_seconds": 0.0}
    pages = {
        "2026-09-14": {
            "nextStartDate": "2026-09-17",
            "gameWeek": [
                {"date": "2026-09-14", "numberOfGames": 0, "games": []},
                {"date": "2026-09-15", "numberOfGames": 0, "games": []},
                {"date": "2026-09-16", "numberOfGames": 0, "games": []},
                {"date": "2026-09-17", "numberOfGames": 0, "games": []},
                {"date": "2026-09-18", "numberOfGames": 0, "games": []},
                {"date": "2026-09-19", "numberOfGames": 7, "games": [{"id": 1}]},
                {"date": "2026-09-20", "numberOfGames": 7, "games": [{"id": 2}]},
            ],
        }
    }
    monkeypatch.setattr(nhl, "_fetch_schedule_raw", lambda requested: (pages[requested], meta))

    next_date, _ = nhl._next_scheduled_game_date(date(2026, 9, 14))
    advertised_day = next(
        day
        for page in pages.values()
        for day in page["gameWeek"]
        if day["date"] == next_date
    )

    assert advertised_day["numberOfGames"] >= 1
