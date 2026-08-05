from __future__ import annotations

import sqlite3

from app.config import settings
from tests.ui.conftest import STANDINGS_KEYS


def test_nba_standings_exact_shared_key_set(client):
    payload = client.get("/api/nba/standings").json()
    assert payload["ok"] is True
    assert payload["data"]
    assert all(set(row) == STANDINGS_KEYS for row in payload["data"])


def test_nba_2025_26_standings_static_facts(client):
    payload = client.get("/api/nba/standings?season=2025-26").json()
    assert payload["ok"] is True
    rows = payload["data"]
    assert len(rows) == 30
    by_team = {row["abbrev"]: row for row in rows}
    assert (by_team["OKC"]["wins"], by_team["OKC"]["losses"]) == (64, 18)
    assert (by_team["SAS"]["wins"], by_team["SAS"]["losses"]) == (62, 20)
    assert (by_team["DET"]["wins"], by_team["DET"]["losses"]) == (60, 22)
    assert sum(row["wins"] for row in rows) == sum(row["losses"] for row in rows) == 1230


def test_nba_current_standings_seasons_are_balanced():
    with sqlite3.connect(f"file:{settings.nba_db}?mode=ro", uri=True) as con:
        rows = con.execute(
            """
            SELECT season, COUNT(*) AS teams, SUM(wins) AS wins
            FROM nba_current_standings
            WHERE season IN ('2023-24', '2024-25', '2025-26')
            GROUP BY season
            ORDER BY season
            """
        ).fetchall()
    assert rows == [("2023-24", 30, 1230), ("2024-25", 30, 1230), ("2025-26", 30, 1230)]


def test_nba_teams_players_and_schedule_endpoints(client):
    teams = client.get("/api/nba/teams").json()
    players = client.get("/api/nba/players?limit=5").json()
    schedule = client.get("/api/nba/schedule?season=2022-23").json()
    for payload in (teams, players, schedule):
        assert payload["ok"] is True, payload
        assert payload["data"]
    assert len(teams["data"]) == 30
    assert len(players["data"]) <= 5
    assert {row["status"] for row in schedule["data"]} <= {"scheduled", "final"}


def test_nba_unknown_team_and_season_errors_are_enveloped(client):
    team = client.get("/api/nba/teams/XXX").json()
    season = client.get("/api/nba/standings?season=1900-01").json()
    assert team["ok"] is False
    assert team["error"]["code"] == "not_found"
    assert season["ok"] is False
    assert season["error"]["code"] == "bad_request"
