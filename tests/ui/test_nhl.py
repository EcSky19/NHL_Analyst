from __future__ import annotations

import pytest

from tests.ui.conftest import STANDINGS_KEYS


def test_nhl_standings_exact_shared_key_set(client, mocked_nhl):
    payload = client.get("/api/nhl/standings").json()
    assert payload["ok"] is True
    assert payload["data"]
    assert all(set(row) == STANDINGS_KEYS for row in payload["data"])


def test_nhl_standings_has_exactly_32_teams(client, mocked_nhl):
    payload = client.get("/api/nhl/standings").json()
    assert payload["ok"] is True
    assert len(payload["data"]) == 32


def test_nhl_unknown_team_returns_not_found(client, mocked_nhl):
    payload = client.get("/api/nhl/teams/XXX").json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_found"


def test_nhl_bad_season_and_date_are_bad_request(client):
    standings = client.get("/api/nhl/standings?season=2026").json()
    schedule = client.get("/api/nhl/schedule?date=2026-99-99").json()
    assert standings["ok"] is False
    assert standings["error"]["code"] == "bad_request"
    assert schedule["ok"] is False
    assert schedule["error"]["code"] == "bad_request"


@pytest.mark.network
def test_live_nhl_standings_shape_when_available(client):
    response = client.get("/api/nhl/standings")
    assert response.status_code == 200
    payload = response.json()
    if not payload.get("ok"):
        pytest.skip(f"NHL upstream/cache unavailable: {payload.get('error')}")
    assert len(payload["data"]) == 32
    assert all(set(row) == STANDINGS_KEYS for row in payload["data"])
