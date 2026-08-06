from __future__ import annotations

from typing import Any

SHARED_GAME_KEYS = {
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
LIVE_KEYS = {"period", "period_label", "clock", "last_play"}


def _game(game_id: str, status: str, home_score: int | None, away_score: int | None) -> dict[str, Any]:
    return {
        "game_id": game_id,
        "game_date": "2026-08-05",
        "start_time_utc": f"2026-08-05T{game_id[-2:]}:00:00Z",
        "home": "LAD",
        "away": "TOR",
        "home_name": "Los Angeles Dodgers",
        "away_name": "Toronto Blue Jays",
        "home_score": home_score,
        "away_score": away_score,
        "status": status,
        "detailed_status": "In Progress" if status == "in-progress" else status.title(),
        "venue": "Test Park",
        "live": {"period": 7, "period_label": "T7", "clock": None, "last_play": None, "balls": 1, "strikes": 2, "outs": 1, "runners_on_base": {"first": True, "second": False, "third": False}},
    }


def test_mlb_week_schedule_contract_shape_and_statuses(client, mocked_mlb, monkeypatch):
    import app.routers.mlb as mlb

    meta = {"cached": True, "stale": False, "age_seconds": 0.0, "fetched_at": "2026-08-05T00:00:00Z"}
    games = [_game("823596", "final", 3, 2), _game("823597", "scheduled", 0, 0), _game("823598", "in-progress", 5, 4)]
    monkeypatch.setattr(mlb, "_fetch_schedule_range", lambda start, end, season, ttl=None: (games, meta, season))

    payload = client.get("/api/mlb/schedule/week?start=2026-08-05&days=1").json()

    assert payload["ok"] is True
    assert payload["meta"]["league"] == "mlb"
    assert payload["meta"]["start_date"] == "2026-08-05"
    assert payload["meta"]["end_date"] == "2026-08-05"
    assert payload["meta"]["days"] == 1
    assert payload["meta"]["count"] == 3
    assert {row["status"] for row in payload["data"]} <= ALLOWED_STATUSES
    assert all(SHARED_GAME_KEYS <= set(row) for row in payload["data"])
    scheduled = next(row for row in payload["data"] if row["status"] == "scheduled")
    assert scheduled["home_score"] is None
    assert scheduled["away_score"] is None
    assert "live" not in scheduled


def test_mlb_week_schedule_dedupes_rescheduled_gamepks_but_keeps_doubleheaders(client, mocked_mlb, monkeypatch):
    import app.routers.mlb as mlb

    meta = {"cached": True, "stale": False, "age_seconds": 0.0, "fetched_at": "2026-07-29T00:00:00Z"}
    postponed = {**_game("823598", "postponed", None, None), "game_date": "2026-07-28", "detailed_status": "Postponed"}
    makeup = {**_game("823598", "final", 1, 0), "game_date": "2026-07-29", "detailed_status": "Final"}
    doubleheader_game = {**_game("823596", "final", 3, 2), "game_date": "2026-07-29", "detailed_status": "Final"}
    monkeypatch.setattr(mlb, "_fetch_schedule_range", lambda start, end, season, ttl=None: ([postponed, makeup, doubleheader_game], meta, season))

    payload = client.get("/api/mlb/schedule/week?start=2026-07-27&days=7").json()

    assert payload["ok"] is True
    ids = [row["game_id"] for row in payload["data"]]
    assert len(ids) == len(set(ids))
    assert ids.count("823598") == 1
    assert {"823596", "823598"} <= set(ids)
    kept = next(row for row in payload["data"] if row["game_id"] == "823598")
    assert kept["game_date"] == "2026-07-29"
    assert kept["status"] == "final"


def test_mlb_live_contract_shape_and_empty_safe(client, mocked_mlb, monkeypatch):
    import app.routers.mlb as mlb

    meta = {"cached": True, "stale": False, "age_seconds": 0.0, "fetched_at": "2026-08-05T00:00:00Z"}
    monkeypatch.setattr(mlb, "_fetch_live_window", lambda: ([_game("823598", "in-progress", 5, 4)], meta, "2026"))

    payload = client.get("/api/mlb/live").json()

    assert payload["ok"] is True
    assert payload["meta"]["poll_interval_seconds"] == 30
    assert payload["meta"]["count"] == 1
    row = payload["data"][0]
    assert SHARED_GAME_KEYS <= set(row)
    assert row["status"] == "live"
    assert LIVE_KEYS <= set(row["live"])
    assert row["live"]["period_label"] == "T7"
    assert row["live"]["clock"] is None

    monkeypatch.setattr(mlb, "_fetch_live_window", lambda: ([], meta, "2026"))
    empty = client.get("/api/mlb/live").json()
    assert empty["ok"] is True
    assert empty["data"] == []
    assert empty["meta"]["empty_reason"]


def test_mlb_week_schedule_bad_params_are_enveloped(client, mocked_mlb):
    for query in ("days=0", "days=15", "days=abc", "start=notadate"):
        payload = client.get(f"/api/mlb/schedule/week?{query}").json()
        assert payload["ok"] is False
        assert payload["error"]["code"] == "bad_request"


def test_mlb_status_uses_abstract_state_for_live():
    import app.routers.mlb as mlb

    assert mlb._contract_status({"status": {"abstractGameState": "Live", "detailedState": "Player challenge"}}) == "live"
    assert mlb._contract_status({"status": {"abstractGameState": "Preview", "detailedState": "Warmup"}}) == "scheduled"
    assert mlb._contract_status({"status": {"abstractGameState": "Preview", "detailedState": "In Progress"}}) == "scheduled"
