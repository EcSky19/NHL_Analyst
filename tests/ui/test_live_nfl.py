from __future__ import annotations

from typing import Any


CONTRACT_KEYS = {
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


def _games() -> list[dict[str, Any]]:
    base = {
        "game_type": "REG",
        "weekday": "Sunday",
        "location": "Home",
        "roof": "outdoors",
        "surface": "grass",
        "spread_line": "",
        "total_line": "",
        "home_moneyline": "",
        "away_moneyline": "",
        "home_qb_name": "",
        "away_qb_name": "",
    }
    return [
        {
            **base,
            "game_id": "2026_01_DAL_KC",
            "season": 2026,
            "week": 1,
            "gameday": "2026-09-09",
            "gametime": "19:20",
            "away_team": "DAL",
            "home_team": "KC",
            "away_score": None,
            "home_score": None,
            "stadium": "GEHA Field at Arrowhead Stadium",
        },
        {
            **base,
            "game_id": "2026_01_ARI_ATL",
            "season": 2026,
            "week": 1,
            "gameday": "2026-09-10",
            "gametime": "20:15",
            "away_team": "ARI",
            "home_team": "ATL",
            "away_score": None,
            "home_score": None,
            "stadium": "Mercedes-Benz Stadium",
        },
        {
            **base,
            "game_id": "2025_01_ARI_ATL",
            "season": 2025,
            "week": 1,
            "gameday": "2025-09-07",
            "gametime": "13:00",
            "away_team": "ARI",
            "home_team": "ATL",
            "away_score": 10,
            "home_score": 20,
            "stadium": "Mercedes-Benz Stadium",
        },
    ]


def _mock_fetch(monkeypatch) -> None:
    import app.routers.nfl as nfl

    meta = {"cached": True, "stale": False, "age_seconds": 0.0}
    monkeypatch.setattr(nfl, "fetch_games", lambda ttl: (_games(), meta))


def test_nfl_schedule_week_window_contract_keys_and_honest_scores(client, monkeypatch) -> None:
    _mock_fetch(monkeypatch)
    payload = client.get("/api/nfl/schedule/week?start=2026-09-09&days=7").json()
    assert payload["ok"] is True
    assert payload["meta"]["count"] == 2
    assert payload["meta"]["empty_reason"] is None
    row = payload["data"][0]
    assert CONTRACT_KEYS <= set(row)
    assert row["home"] == row["home_team"]
    assert row["away"] == row["away_team"]
    assert row["league"] == "nfl"
    assert row["status"] == "scheduled"
    assert row["detailed_status"] is None
    assert row["home_score"] is None
    assert row["away_score"] is None
    assert row["start_time_utc"].endswith("Z")


def test_nfl_schedule_week_param_uses_current_season(client, monkeypatch) -> None:
    _mock_fetch(monkeypatch)
    payload = client.get("/api/nfl/schedule/week?week=1").json()
    assert payload["ok"] is True
    assert payload["meta"]["season"] == 2026
    assert payload["meta"]["week"] == 1
    assert payload["meta"]["count"] == 2


def test_nfl_schedule_week_completed_range_keeps_final_scores(client, monkeypatch) -> None:
    _mock_fetch(monkeypatch)
    payload = client.get("/api/nfl/schedule/week?start=2025-09-07&days=1").json()
    assert payload["ok"] is True
    assert payload["meta"]["count"] == 1
    row = payload["data"][0]
    assert row["status"] == "final"
    assert row["detailed_status"] is None
    assert row["home_score"] == 20
    assert row["away_score"] == 10


def test_nfl_schedule_empty_window_names_source_coverage_not_world_state(client, monkeypatch) -> None:
    _mock_fetch(monkeypatch)
    payload = client.get("/api/nfl/schedule/week?start=2026-08-06&days=7").json()
    assert payload["ok"] is True
    assert payload["data"] == []
    assert payload["meta"]["count"] == 0
    assert (
        payload["meta"]["empty_reason"]
        == "No NFL regular-season or postseason games fall in this window. "
        "The nflverse source used here does not include preseason games, and the 2026 regular season opens 2026-09-09."
    )


def test_nfl_schedule_week_bad_params_return_contract_failures(client, monkeypatch) -> None:
    _mock_fetch(monkeypatch)
    for path in (
        "/api/nfl/schedule/week?days=0",
        "/api/nfl/schedule/week?days=15",
        "/api/nfl/schedule/week?start=notadate",
        "/api/nfl/schedule/week?week=1&start=2026-09-09",
    ):
        payload = client.get(path).json()
        assert payload["ok"] is False
        assert payload["error"]["code"] == "bad_request"


def test_nfl_live_is_empty_when_upstream_has_no_live_state(client, monkeypatch) -> None:
    _mock_fetch(monkeypatch)
    payload = client.get("/api/nfl/live").json()
    assert payload["ok"] is True
    assert payload["data"] == []
    assert payload["meta"]["count"] == 0
    assert payload["meta"]["league"] == "nfl"
    assert "does not expose true real-time NFL clock, quarter, or last-play state" in payload["meta"]["empty_reason"]
    assert "does not include preseason games" in payload["meta"]["empty_reason"]
