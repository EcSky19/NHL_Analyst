from __future__ import annotations

import pytest

from tests.ui.conftest import ERROR_CODES


def assert_envelope(payload: dict) -> None:
    assert set(payload) == {"ok", "data", "error", "meta"}
    assert isinstance(payload["ok"], bool)
    assert isinstance(payload["meta"], dict)
    if payload["ok"]:
        assert payload["error"] is None
    else:
        assert payload["data"] is None
        assert payload["error"]["code"] in ERROR_CODES
        assert payload["error"]["message"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/health",
        "/api/nhl/standings",
        "/api/nhl/teams",
        "/api/nhl/teams/ANA",
        "/api/nhl/players",
        "/api/nhl/schedule?date=2026-01-01",
        "/api/nfl/standings?season=2025",
        "/api/nfl/teams",
        "/api/nfl/teams/KC",
        "/api/nfl/players",
        "/api/nfl/schedule?season=2025&week=1",
        "/api/nba/standings",
        "/api/nba/teams",
        "/api/nba/teams/OKC",
        "/api/nba/players",
        "/api/nba/schedule?season=2022-23",
        "/api/mlb/standings?season=2026",
        "/api/mlb/teams?season=2026",
        "/api/mlb/teams/LAD?season=2026",
        "/api/mlb/players?season=2026",
        "/api/mlb/schedule?date=2026-07-29",
        "/api/predictions/nhl",
        "/api/predictions/nfl",
        "/api/predictions/matchup?league=nhl&home=COL&away=SJS",
    ],
)
def test_success_endpoints_return_contract_envelope(path, client, mocked_nhl, mocked_nfl, mocked_mlb):
    response = client.get(path)
    assert response.status_code == 200
    payload = response.json()
    assert_envelope(payload)
    assert payload["ok"] is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/nhl/standings?season=2026",
        "/api/nhl/schedule?date=not-a-date",
        "/api/nfl/schedule?season=2025&week=99",
        "/api/nba/standings?season=1900-01",
        "/api/nba/teams/XXX",
        "/api/mlb/standings?season=9999",
        "/api/mlb/teams/XXX?season=2026",
        "/api/predictions/matchup?league=mlb&home=COL&away=SJS",
        "/api/predictions/matchup?league=nhl&home=COL&away=COL",
    ],
)
def test_error_endpoints_still_return_http_200_envelope(path, client, mocked_nhl, mocked_nfl, mocked_mlb):
    response = client.get(path)
    assert response.status_code == 200
    payload = response.json()
    assert_envelope(payload)
    assert payload["ok"] is False


def test_meta_seasons_contract_endpoint_exists(client):
    response = client.get("/api/meta/seasons")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_health_reports_all_four_leagues(client):
    payload = client.get("/api/health").json()
    assert payload["ok"] is True
    assert set(payload["data"]["databases"]) == {"nhl", "nfl", "nba", "mlb"}
    assert set(payload["data"]["season_state"]) == {"nhl", "nfl", "nba", "mlb"}
