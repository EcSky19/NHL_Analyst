from __future__ import annotations

import math


def _rows(client, league: str, home: str, away: str) -> list[dict]:
    payload = client.get(f"/api/predictions/matchup?league={league}&home={home}&away={away}").json()
    assert payload["ok"] is True, payload
    assert payload["data"]
    return payload["data"]


def _assert_probability_invariants(row: dict, upper_bound: float) -> None:
    assert 0.0 <= row["home_win_prob"] <= upper_bound
    assert 0.0 <= row["away_win_prob"] <= upper_bound
    assert math.isclose(row["home_win_prob"] + row["away_win_prob"], 1.0, abs_tol=1e-6)


def test_nhl_prediction_invariants_bounds_and_direction(client):
    home_strong = _rows(client, "nhl", "COL", "SJS")[0]
    away_strong = _rows(client, "nhl", "SJS", "COL")[0]
    _assert_probability_invariants(home_strong, 0.80)
    _assert_probability_invariants(away_strong, 0.80)
    assert home_strong["home_win_prob"] > home_strong["away_win_prob"]
    assert away_strong["away_win_prob"] > away_strong["home_win_prob"]
    assert away_strong["home_win_prob"] < home_strong["home_win_prob"]


def test_nfl_prediction_invariants_bounds_and_direction(client):
    home_strong = _rows(client, "nfl", "KC", "CAR")
    away_strong = _rows(client, "nfl", "CAR", "KC")
    assert len(home_strong) == len(away_strong) == 2
    for first, second in zip(home_strong, away_strong, strict=True):
        _assert_probability_invariants(first, 0.85)
        _assert_probability_invariants(second, 0.85)
        assert first["home_win_prob"] > first["away_win_prob"]
        assert second["away_win_prob"] > second["home_win_prob"]
        assert second["home_win_prob"] < first["home_win_prob"]


def test_prediction_honesty_fields_and_audited_accuracy_caps(client):
    rows = _rows(client, "nhl", "COL", "SJS") + _rows(client, "nfl", "KC", "CAR")
    for row in rows:
        assert row["model_accuracy"] is not None
        assert row["baseline_accuracy"] is not None
        assert row["disclaimer"]
        if row["league"] == "nhl":
            assert row["model_accuracy"] <= 0.5682
        else:
            assert row["model_accuracy"] <= 0.6740


def test_prediction_edge_cases_are_bad_request(client):
    same_team = client.get("/api/predictions/matchup?league=nfl&home=KC&away=KC").json()
    invalid_league = client.get("/api/predictions/matchup?league=mlb&home=KC&away=CAR").json()
    invalid_date = client.get("/api/predictions/nhl?date=not-a-date").json()
    invalid_week = client.get("/api/predictions/nfl?week=99").json()
    for payload in (same_team, invalid_league, invalid_date, invalid_week):
        assert payload["ok"] is False
        assert payload["error"]["code"] == "bad_request"
