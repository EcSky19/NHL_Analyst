from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app

STANDINGS_KEYS = {
    "team_id",
    "abbrev",
    "name",
    "conference",
    "division",
    "rank",
    "games_played",
    "wins",
    "losses",
    "otl",
    "ties",
    "points",
    "points_pct",
    "win_pct",
    "goals_for",
    "goals_against",
    "differential",
    "streak",
    "last10",
    "home_record",
    "away_record",
    "logo_url",
    "clinched",
}

ERROR_CODES = {"upstream_unavailable", "not_found", "bad_request", "no_data", "internal"}

NHL_TEAMS = [
    "ANA",
    "BOS",
    "BUF",
    "CAR",
    "CBJ",
    "CGY",
    "CHI",
    "COL",
    "DAL",
    "DET",
    "EDM",
    "FLA",
    "LAK",
    "MIN",
    "MTL",
    "NJD",
    "NSH",
    "NYI",
    "NYR",
    "OTT",
    "PHI",
    "PIT",
    "SEA",
    "SJS",
    "STL",
    "TBL",
    "TOR",
    "UTA",
    "VAN",
    "VGK",
    "WPG",
    "WSH",
]

NFL_TEAMS = [
    "ARI",
    "ATL",
    "BAL",
    "BUF",
    "CAR",
    "CHI",
    "CIN",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GB",
    "HOU",
    "IND",
    "JAX",
    "KC",
    "LA",
    "LAC",
    "LV",
    "MIA",
    "MIN",
    "NE",
    "NO",
    "NYG",
    "NYJ",
    "PHI",
    "PIT",
    "SEA",
    "SF",
    "TB",
    "TEN",
    "WAS",
]

NBA_TEAMS = [
    "ATL",
    "BOS",
    "BKN",
    "CHA",
    "CHI",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GSW",
    "HOU",
    "IND",
    "LAC",
    "LAL",
    "MEM",
    "MIA",
    "MIL",
    "MIN",
    "NOP",
    "NYK",
    "OKC",
    "ORL",
    "PHI",
    "PHX",
    "POR",
    "SAC",
    "SAS",
    "TOR",
    "UTA",
    "WAS",
]

MLB_TEAMS = [
    "ARI",
    "ATL",
    "BAL",
    "BOS",
    "CHC",
    "CIN",
    "CLE",
    "COL",
    "CWS",
    "DET",
    "HOU",
    "KC",
    "LAA",
    "LAD",
    "MIA",
    "MIL",
    "MIN",
    "NYM",
    "NYY",
    "OAK",
    "PHI",
    "PIT",
    "SD",
    "SEA",
    "SF",
    "STL",
    "TB",
    "TEX",
    "TOR",
    "WSH",
]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def make_standing(abbrev: str, index: int, league: str) -> dict[str, Any]:
    if league == "nhl":
        wins = 52 - (index % 20)
        losses = 20 + (index % 10)
        otl = max(0, 82 - wins - losses)
        ties = None
        games = 82
        points = 2 * wins + otl
    else:
        wins = 10 if index <= 16 else 7
        losses = 7 if index <= 16 else 10
        ties = 0
        otl = None
        games = 17
        points = None
    return {
        "team_id": abbrev,
        "abbrev": abbrev,
        "name": f"{abbrev} Test Team",
        "conference": "Eastern" if index <= 16 else "Western",
        "division": "Test",
        "rank": index,
        "games_played": games,
        "wins": wins,
        "losses": losses,
        "otl": otl,
        "ties": ties,
        "points": points,
        "points_pct": round((points / 164) if league == "nhl" else (wins + 0.5 * ties) / games, 3),
        "win_pct": round(wins / games, 3),
        "goals_for": 250 + index,
        "goals_against": 200 + index,
        "differential": 50,
        "streak": "W1",
        "last10": "6-4-0",
        "home_record": "5-3-0",
        "away_record": "5-4-0",
        "logo_url": None,
        "clinched": None,
    }


def make_mlb_standing(abbrev: str, index: int) -> dict[str, Any]:
    wins = 60 if index <= 15 else 50
    losses = 50 if index <= 15 else 60
    games = wins + losses
    return {
        **make_standing(abbrev, index, "nfl"),
        "team_id": str(100 + index),
        "games_played": games,
        "wins": wins,
        "losses": losses,
        "ties": None,
        "points": wins,
        "points_pct": round(wins / games, 3),
        "win_pct": round(wins / games, 3),
        "goals_for": 500 + index,
        "goals_against": 450 + index,
        "conference": "American" if index <= 15 else "National",
        "division": ["East", "Central", "West"][(index - 1) % 3],
        "home_record": "30-25",
        "away_record": "30-25",
        "games_behind": None if index in {1, 16} else "1.0",
    }


@pytest.fixture
def nhl_rows() -> list[dict[str, Any]]:
    return [make_standing(team, index, "nhl") for index, team in enumerate(NHL_TEAMS, start=1)]


@pytest.fixture
def nfl_rows() -> list[dict[str, Any]]:
    return [make_standing(team, index, "nfl") for index, team in enumerate(NFL_TEAMS, start=1)]


@pytest.fixture
def mlb_rows() -> list[dict[str, Any]]:
    return [make_mlb_standing(team, index) for index, team in enumerate(MLB_TEAMS, start=1)]


@pytest.fixture
def mocked_nhl(monkeypatch: pytest.MonkeyPatch, nhl_rows: list[dict[str, Any]]) -> None:
    import app.routers.nhl as nhl

    meta = {"cached": True, "stale": False, "age_seconds": 0.0}
    monkeypatch.setattr(
        nhl,
        "_fetch_standings",
        lambda season=None: (nhl_rows, meta, season or "20252026"),
    )
    monkeypatch.setattr(nhl, "_fetch_schedule", lambda date=None: ([], meta, "20252026"))
    monkeypatch.setattr(nhl, "_fetch_players", lambda teams, season: ([], meta))
    monkeypatch.setattr(nhl, "_db_team_abbrevs", lambda: [row["abbrev"] for row in nhl_rows])


@pytest.fixture
def mocked_nfl(monkeypatch: pytest.MonkeyPatch, nfl_rows: list[dict[str, Any]]) -> None:
    import app.routers.nfl as nfl

    meta = {"cached": True, "stale": False, "age_seconds": 0.0}
    games = [{"season": 2025, "week": 1, "game_type": "REG", "away_score": 10, "home_score": 20}]
    schedule = [
        {
            "game_id": "2025_01_ARI_ATL",
            "season": 2025,
            "week": 1,
            "game_type": "REG",
            "away_team": "ARI",
            "home_team": "ATL",
            "played": True,
            "status": "final",
        }
    ]
    teams = [{"team_id": row["abbrev"], "abbrev": row["abbrev"], "name": row["name"], "standings": row} for row in nfl_rows]
    players = [{"player_id": "qb-1", "name": "Test QB", "team": "KC", "position": "QB", "stat": "passing_yards", "value": 4500}]
    monkeypatch.setattr(nfl, "fetch_games", lambda ttl: (games, meta))
    monkeypatch.setattr(nfl, "standings_for_season_cached", lambda season: nfl_rows if season == 2025 else [])
    monkeypatch.setattr(nfl, "teams_payload", lambda season: (teams, meta))
    monkeypatch.setattr(nfl, "players_payload", lambda team, stat, limit, season: (players, meta))
    monkeypatch.setattr(nfl, "schedule_for", lambda games_arg, season, week=None: schedule if season == 2025 else [])


@pytest.fixture
def mocked_mlb(monkeypatch: pytest.MonkeyPatch, mlb_rows: list[dict[str, Any]]) -> None:
    import app.routers.mlb as mlb

    meta = {"cached": True, "stale": False, "age_seconds": 0.0, "fetched_at": "2026-08-05T00:00:00Z"}
    teams_by_id = {
        int(row["team_id"]): {
            "id": int(row["team_id"]),
            "abbreviation": row["abbrev"],
            "name": row["name"],
            "venue": {"name": f"{row['abbrev']} Ballpark"},
            "locationName": "Test City",
            "clubName": row["name"].split()[-1],
            "firstYearOfPlay": "1901",
            "active": True,
        }
        for row in mlb_rows
    }
    schedule = [
        {
            "game_id": "823596",
            "game_date": "2026-07-29",
            "season": "2026",
            "home": "NYM",
            "away": "ATL",
            "status": "final",
            "home_score": 3,
            "away_score": 2,
            "doubleheader": "Y",
            "game_number": 1,
        },
        {
            "game_id": "823598",
            "game_date": "2026-07-29",
            "season": "2026",
            "home": "NYM",
            "away": "ATL",
            "status": "scheduled",
            "home_score": None,
            "away_score": None,
            "doubleheader": "Y",
            "game_number": 2,
        },
        {
            "game_id": "823999",
            "game_date": "2026-07-29",
            "season": "2026",
            "home": "LAD",
            "away": "TOR",
            "status": "in-progress",
            "home_score": 5,
            "away_score": 4,
            "doubleheader": "N",
            "game_number": 1,
        },
    ]
    players = [
        {"player_id": "1", "name": "Test Hitter", "team": "Los Angeles Dodgers", "team_id": "119", "position": "DH", "group": "hitting", "rank": 1, "games_played": 100, "stat": "ops", "value": "1.000", "stats": {"ops": "1.000"}},
        {"player_id": "2", "name": "Test Pitcher", "team": "Seattle Mariners", "team_id": "136", "position": "P", "group": "pitching", "rank": 1, "games_played": 25, "stat": "era", "value": "2.50", "stats": {"era": "2.50"}},
    ]

    monkeypatch.setattr(mlb, "_fetch_standings", lambda season: (mlb_rows, meta, season))
    monkeypatch.setattr(mlb, "_team_meta", lambda season: (teams_by_id, meta))
    monkeypatch.setattr(mlb, "_fetch_schedule", lambda date, season: (schedule, meta, season))
    monkeypatch.setattr(
        mlb,
        "_fetch_players",
        lambda season, team, stat, group, limit: (
            [] if team == "XXX" else [row for row in players if row["group"] == group][:limit],
            meta,
            season,
        ),
    )
