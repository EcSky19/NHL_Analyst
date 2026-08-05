from __future__ import annotations

import pytest

from tests.ui.conftest import STANDINGS_KEYS

MLB_STANDINGS_KEYS = STANDINGS_KEYS | {"games_behind"}
ALLOWED_MLB_STATUSES = {"scheduled", "in-progress", "final"}


def test_mlb_standings_shared_keys_plus_games_behind(client, mocked_mlb):
    payload = client.get("/api/mlb/standings?season=2026").json()
    assert payload["ok"] is True
    assert payload["data"]
    assert all(STANDINGS_KEYS <= set(row) for row in payload["data"])
    assert all(set(row) == MLB_STANDINGS_KEYS for row in payload["data"])


def test_mlb_standings_live_safe_invariants(client, mocked_mlb):
    payload = client.get("/api/mlb/standings?season=2026").json()
    assert payload["ok"] is True
    rows = payload["data"]
    assert len(rows) == 30
    assert sum(row["wins"] for row in rows) == sum(row["losses"] for row in rows)
    assert all(0 <= row["games_played"] <= 162 for row in rows)
    assert all(row["games_played"] == row["wins"] + row["losses"] for row in rows)


def test_mlb_teams_players_and_schedule_endpoints(client, mocked_mlb):
    teams = client.get("/api/mlb/teams?season=2026").json()
    players = client.get("/api/mlb/players?season=2026&group=hitting&limit=5").json()
    schedule = client.get("/api/mlb/schedule?date=2026-07-29").json()
    for payload in (teams, players, schedule):
        assert payload["ok"] is True, payload
        assert payload["data"]
    assert len(teams["data"]) == 30
    assert len(players["data"]) <= 5
    game_ids = [row["game_id"] for row in schedule["data"]]
    assert len(game_ids) == len(set(game_ids))
    assert {row["status"] for row in schedule["data"]} <= ALLOWED_MLB_STATUSES
    assert {"823596", "823598"} <= set(game_ids)


def test_mlb_unknown_team_and_season_errors_are_enveloped(client, mocked_mlb):
    team = client.get("/api/mlb/teams/XXX?season=2026").json()
    season = client.get("/api/mlb/standings?season=9999").json()
    assert team["ok"] is False
    assert team["error"]["code"] == "not_found"
    assert season["ok"] is False
    assert season["error"]["code"] == "bad_request"


@pytest.mark.network
def test_live_mlb_standings_shape_when_available(client):
    response = client.get("/api/mlb/standings")
    assert response.status_code == 200
    payload = response.json()
    if not payload.get("ok"):
        pytest.skip(f"MLB StatsAPI/cache unavailable: {payload.get('error')}")
    rows = payload["data"]
    assert len(rows) == 30
    assert all(STANDINGS_KEYS <= set(row) for row in rows)
    assert all("games_behind" in row for row in rows)
    assert sum(row["wins"] for row in rows) == sum(row["losses"] for row in rows)
    assert all(0 <= row["games_played"] <= 162 for row in rows)
