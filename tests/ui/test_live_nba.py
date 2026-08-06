from __future__ import annotations


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
    "venue",
    "status",
    "detailed_status",
}

ALLOWED_STATUSES = {"scheduled", "live", "final", "postponed"}


def test_nba_week_default_is_honest_empty_in_offseason(client):
    payload = client.get("/api/nba/schedule/week").json()
    assert payload["ok"] is True, payload
    assert payload["meta"]["league"] == "nba"
    assert payload["meta"]["days"] == 7
    assert payload["meta"]["count"] == len(payload["data"])
    if payload["meta"]["season_state"] == "offseason":
        assert payload["data"] == []
        assert payload["meta"]["empty_reason"]


def test_nba_week_past_range_emits_contract_rows(client):
    payload = client.get("/api/nba/schedule/week?start=2025-01-15&days=7").json()
    assert payload["ok"] is True, payload
    assert payload["meta"]["source"].startswith("espn-web-api:")
    assert payload["meta"]["start_date"] == "2025-01-15"
    assert payload["meta"]["end_date"] == "2025-01-21"
    assert payload["meta"]["count"] == len(payload["data"])
    assert payload["data"]
    assert all(CONTRACT_KEYS <= set(row) for row in payload["data"])
    assert {row["status"] for row in payload["data"]} <= ALLOWED_STATUSES
    assert all(row["league"] == "nba" for row in payload["data"])
    assert len({row["game_id"] for row in payload["data"]}) == len(payload["data"])
    assert all("2025-01-15" <= row["game_date"] <= "2025-01-21" for row in payload["data"])
    assert all(
        row["home_score"] is None and row["away_score"] is None
        for row in payload["data"]
        if row["status"] in {"scheduled", "postponed"}
    )


def test_nba_week_bad_params_are_enveloped(client):
    for query in ("days=0", "days=15", "start=notadate"):
        payload = client.get(f"/api/nba/schedule/week?{query}").json()
        assert payload["ok"] is False
        assert payload["error"]["code"] == "bad_request"


def test_nba_live_uses_espn_without_asserting_games_exist(client):
    payload = client.get("/api/nba/live").json()
    assert payload["ok"] is True, payload
    assert payload["meta"]["source"].startswith("espn-web-api:")
    assert payload["meta"]["count"] == len(payload["data"])
    assert payload["meta"]["league"] == "nba"
    assert payload["meta"]["poll_interval_seconds"] == 30
    assert {row["status"] for row in payload["data"]} <= {"live"}
    assert all(CONTRACT_KEYS <= set(row) and "live" in row for row in payload["data"])
    if not payload["data"]:
        assert payload["meta"]["empty_reason"]
        assert "no free verified NBA source" not in payload["meta"]["empty_reason"].lower()


def test_nba_schedule_default_does_not_fall_back_to_stale_2022_23_season(client):
    payload = client.get("/api/nba/schedule").json()
    assert payload["ok"] is True, payload
    assert payload["meta"]["source"].startswith("espn-web-api:")
    assert payload["meta"]["count"] == len(payload["data"])
    assert all(row.get("season") != "2022-23" for row in payload["data"])


def test_nba_completed_games_are_never_labelled_scheduled(client):
    payload = client.get("/api/nba/schedule?season=2022-23").json()
    assert payload["ok"] is True, payload
    completed = [row for row in payload["data"] if row.get("played")]
    assert completed
    assert all(row["status"] != "scheduled" for row in completed)
    assert {row["status"] for row in payload["data"]} <= ALLOWED_STATUSES
