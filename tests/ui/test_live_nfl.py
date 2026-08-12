from __future__ import annotations

from typing import Any
import app.services.live_wp_state as _wp_state


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

STATUS_VALUES = {"scheduled", "live", "final", "postponed"}


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


def _espn_rows() -> list[dict[str, Any]]:
    return [
        {
            "game_id": "401772510",
            "league": "nfl",
            "game_date": "2026-08-06",
            "start_time_utc": "2026-08-07T00:00:00Z",
            "home": "ARI",
            "away": "CAR",
            "home_name": "Arizona Cardinals",
            "away_name": "Carolina Panthers",
            "home_score": None,
            "away_score": None,
            "status": "scheduled",
            "detailed_status": "8:00 PM EDT",
            "venue": "Tom Benson Hall of Fame Stadium",
            "neutral_site": True,
        }
    ]


def _mock_espn(monkeypatch, rows: list[dict[str, Any]] | None = None) -> None:
    import app.routers.nfl as nfl

    meta = {"cached": False, "stale": False, "age_seconds": 0.0}
    monkeypatch.setattr(nfl, "espn_schedule_window", lambda start, days, ttl: (rows if rows is not None else _espn_rows(), meta))
    monkeypatch.setattr(nfl, "espn_live_games", lambda ttl=30: ([], rows if rows is not None else _espn_rows(), meta))


def _assert_contract_rows(rows: list[dict[str, Any]]) -> None:
    ids = [row["game_id"] for row in rows]
    assert len(ids) == len(set(ids))
    for row in rows:
        assert CONTRACT_KEYS <= set(row)
        assert row["status"] in STATUS_VALUES
        if row["status"] in {"scheduled", "postponed"}:
            assert row["home_score"] is None
            assert row["away_score"] is None


def test_nfl_schedule_week_window_contract_keys_and_honest_scores(client, monkeypatch) -> None:
    _mock_espn(monkeypatch)
    payload = client.get("/api/nfl/schedule/week?start=2026-08-06&days=7").json()
    assert payload["ok"] is True
    assert payload["meta"]["source"].startswith("espn-web-api:")
    assert payload["meta"]["count"] == 1
    assert payload["meta"]["empty_reason"] is None
    _assert_contract_rows(payload["data"])
    assert all("2026-08-06" <= row["game_date"] <= "2026-08-12" for row in payload["data"])


def test_nfl_schedule_week_param_uses_current_season(client, monkeypatch) -> None:
    _mock_fetch(monkeypatch)
    payload = client.get("/api/nfl/schedule/week?week=1").json()
    assert payload["ok"] is True
    assert payload["meta"]["season"] == 2026
    assert payload["meta"]["week"] == 1
    assert payload["meta"]["count"] == 2


def test_nfl_schedule_week_completed_range_keeps_final_scores(client, monkeypatch) -> None:
    rows = [
        {
            **_espn_rows()[0],
            "game_id": "401777777",
            "game_date": "2025-09-07",
            "start_time_utc": "2025-09-07T17:00:00Z",
            "home_score": 20,
            "away_score": 10,
            "status": "final",
            "detailed_status": "Final",
            "neutral_site": False,
        }
    ]
    _mock_espn(monkeypatch, rows)
    payload = client.get("/api/nfl/schedule/week?start=2025-09-07&days=1").json()
    assert payload["ok"] is True
    assert payload["meta"]["count"] == 1
    row = payload["data"][0]
    assert row["status"] == "final"
    assert row["detailed_status"] == "Final"
    assert row["home_score"] == 20
    assert row["away_score"] == 10


def test_nfl_schedule_empty_window_names_espn_not_nflverse_coverage(client, monkeypatch) -> None:
    _mock_espn(monkeypatch, [])
    payload = client.get("/api/nfl/schedule/week?start=2026-08-06&days=7").json()
    assert payload["ok"] is True
    assert payload["data"] == []
    assert payload["meta"]["count"] == 0
    assert payload["meta"]["empty_reason"] == "ESPN reports no NFL games from 2026-08-06 through 2026-08-12."


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


def test_nfl_live_is_empty_when_espn_has_no_in_progress_games(client, monkeypatch) -> None:
    _mock_espn(monkeypatch)
    payload = client.get("/api/nfl/live").json()
    assert payload["ok"] is True
    assert payload["data"] == []
    assert payload["meta"]["count"] == 0
    assert payload["meta"]["league"] == "nfl"
    assert payload["meta"]["source"].startswith("espn-web-api:")
    assert payload["meta"]["empty_reason"] == "No NFL games are currently in progress on ESPN's current Eastern-date slate."


def test_nfl_live_win_probability_threads_situation(monkeypatch) -> None:
    import app.routers.nfl as nfl

    seen = {}

    def fake_predict(state):
        seen["state"] = state
        return 0.7, {"available": True}

    monkeypatch.setattr(_wp_state, "predict_home_win_prob", fake_predict)
    row = {
        "status": "live",
        "home": "KC",
        "away": "BAL",
        "home_score": 17,
        "away_score": 14,
        "live": {
            "period": 4,
            "clock": "2:00",
            "situation": {
                "possession": "12",
                "home_team_id": "12",
                "away_team_id": "33",
                "down": 1,
                "distance": 10,
                "yardLine": 80,
            },
        },
    }

    wp = nfl._live_win_probability(row, "nfl")

    assert wp["available"] is True
    assert seen["state"].offense_is_home is True
    assert seen["state"].down == 1
    assert seen["state"].distance == 10
    assert seen["state"].yards_to_endzone == 20


def test_nfl_yard_line_conversion_for_away_possession(monkeypatch) -> None:
    import app.routers.nfl as nfl

    seen = {}
    monkeypatch.setattr(_wp_state, "predict_home_win_prob", lambda state: seen.setdefault("state", state) and (0.3, {"available": True}))
    row = {
        "status": "live",
        "home": "KC",
        "away": "BAL",
        "home_score": 17,
        "away_score": 21,
        "live": {
            "period": 4,
            "clock": "1:30",
            "situation": {
                "possession": "33",
                "home_team_id": "12",
                "away_team_id": "33",
                "down": 2,
                "distance": 6,
                "yardLine": 20,
            },
        },
    }

    nfl._live_win_probability(row, "nfl")

    assert seen["state"].offense_is_home is False
    assert seen["state"].yards_to_endzone == 20


def test_nfl_live_win_probability_omitted_situation_is_neutral(monkeypatch) -> None:
    import app.routers.nfl as nfl

    seen = {}
    monkeypatch.setattr(_wp_state, "predict_home_win_prob", lambda state: seen.setdefault("state", state) and (0.55, {"available": True}))
    row = {
        "status": "live",
        "home": "KC",
        "away": "BAL",
        "home_score": 10,
        "away_score": 10,
        "live": {"period": 2, "clock": "10:00"},
    }

    wp = nfl._live_win_probability(row, "nfl")

    assert wp["available"] is True
    assert seen["state"].offense_is_home is None
    assert seen["state"].down is None
    assert seen["state"].distance is None
    assert seen["state"].yards_to_endzone is None
