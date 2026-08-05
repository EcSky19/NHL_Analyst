from __future__ import annotations

from tests.ui.conftest import STANDINGS_KEYS


def test_nfl_standings_exact_shared_key_set(client, mocked_nfl):
    payload = client.get("/api/nfl/standings?season=2025").json()
    assert payload["ok"] is True
    assert payload["data"]
    assert all(set(row) == STANDINGS_KEYS for row in payload["data"])


def test_nfl_2025_standings_sanity(client, mocked_nfl):
    payload = client.get("/api/nfl/standings?season=2025").json()
    assert payload["ok"] is True
    rows = payload["data"]
    assert len(rows) == 32
    assert all(row["games_played"] == 17 for row in rows)
    assert all(row["games_played"] == row["wins"] + row["losses"] + row["ties"] for row in rows)
    assert sum(row["wins"] for row in rows) == sum(row["losses"] for row in rows)
    assert sum(row["ties"] for row in rows) % 2 == 0


def test_nfl_unknown_team_returns_not_found(client, mocked_nfl):
    payload = client.get("/api/nfl/teams/XXX").json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_found"


def test_nfl_bad_season_and_week_are_bad_request(client, mocked_nfl):
    standings = client.get("/api/nfl/standings?season=1800").json()
    schedule = client.get("/api/nfl/schedule?season=2025&week=99").json()
    assert standings["ok"] is False
    assert standings["error"]["code"] == "bad_request"
    assert schedule["ok"] is False
    assert schedule["error"]["code"] == "bad_request"
