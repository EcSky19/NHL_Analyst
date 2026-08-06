"""Tests for the shared ESPN scoreboard client.

These lock in the specific traps found while validating the client against live
ESPN data and against this repo's own databases. Network-dependent assertions
are kept to invariants that hold year-round, so the suite does not break in an
offseason or on a quiet slate.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services import espn_client as E

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

VALID_STATUS = {"scheduled", "live", "final", "postponed"}


def _event(state, type_name="STATUS_SCHEDULED", home_score="0", away_score="0", comp_type="STD"):
    return {
        "id": "1",
        "date": "2026-08-07T00:00Z",
        "competitions": [
            {
                "type": {"abbreviation": comp_type},
                "status": {"type": {"state": state, "name": type_name, "shortDetail": "detail"}},
                "competitors": [
                    {"homeAway": "home", "score": home_score, "team": {"abbreviation": "NY", "displayName": "Knicks"}},
                    {"homeAway": "away", "score": away_score, "team": {"abbreviation": "GS", "displayName": "Warriors"}},
                ],
            }
        ],
    }


class TestScoresAreNeverFabricated:
    """ESPN sends "0" for games that never happened; that must never surface."""

    def test_scheduled_game_scores_are_null_not_zero(self):
        row = E.normalize_event(_event("pre"), "nba")
        assert row["home_score"] is None
        assert row["away_score"] is None

    def test_postponed_game_scores_are_null_not_zero(self):
        row = E.normalize_event(_event("pre", "STATUS_POSTPONED"), "nba")
        assert row["status"] == "postponed"
        assert row["home_score"] is None
        assert row["away_score"] is None

    def test_real_scores_survive_for_played_games(self):
        row = E.normalize_event(_event("post", "STATUS_FINAL", "118", "102"), "nba")
        assert (row["home_score"], row["away_score"]) == (118, 102)


class TestTeamAbbreviations:
    """Unmapped abbrevs silently break joins to our models and standings."""

    @pytest.mark.parametrize(
        "league,espn,ours",
        [
            ("nba", "GS", "GSW"),
            ("nba", "NY", "NYK"),
            ("nba", "SA", "SAS"),
            ("nba", "UTAH", "UTA"),
            ("nba", "NO", "NOP"),
            ("nba", "WSH", "WAS"),
            ("nfl", "LAR", "LA"),
            ("nfl", "WSH", "WAS"),
        ],
    )
    def test_espn_abbrev_maps_to_repo_abbrev(self, league, espn, ours):
        assert E.map_abbrev(league, espn) == ours

    def test_unknown_abbrev_passes_through(self):
        assert E.map_abbrev("nba", "PHI") == "PHI"


class TestExhibitionGamesExcluded:
    def test_allstar_game_is_dropped(self):
        assert E.normalize_event(_event("post", comp_type="ALLSTAR"), "nba") is None

    def test_standard_game_is_kept(self):
        assert E.normalize_event(_event("post", comp_type="STD"), "nba") is not None


class TestEasternDating:
    """Leagues label games by local slate date, matching our stored history."""

    def test_late_tipoff_keeps_previous_local_date(self):
        # 2026-08-07T00:00Z is 8/6 8:00 PM EDT and belongs to the 8/6 slate.
        assert E.eastern_date("2026-08-07T00:00:00Z") == "2026-08-06"

    def test_event_dating_uses_eastern_not_utc(self):
        row = E.normalize_event(_event("pre"), "nfl")
        assert row["game_date"] == "2026-08-06"
        assert row["start_time_utc"] == "2026-08-07T00:00:00Z"


class TestStatusMapping:
    @pytest.mark.parametrize(
        "state,expected", [("pre", "scheduled"), ("in", "live"), ("post", "final")]
    )
    def test_states_map_to_contract_enum(self, state, expected):
        status, _ = E.normalize_status({"type": {"state": state, "name": "X"}})
        assert status == expected

    def test_postponed_detected_despite_pre_state(self):
        status, _ = E.normalize_status({"type": {"state": "pre", "name": "STATUS_POSTPONED"}})
        assert status == "postponed"


class TestMalformedInput:
    def test_event_without_competitions_returns_none(self):
        assert E.normalize_event({"id": "1"}, "nba") is None

    def test_event_missing_a_side_returns_none(self):
        ev = _event("pre")
        ev["competitions"][0]["competitors"] = [ev["competitions"][0]["competitors"][0]]
        assert E.normalize_event(ev, "nba") is None

    def test_normalize_events_drops_bad_rows_without_raising(self):
        assert E.normalize_events([{"id": "1"}, _event("pre")], "nba") == E.normalize_events(
            [_event("pre")], "nba"
        )


class TestDedupe:
    def test_more_progressed_row_wins(self):
        a = {"game_id": "7", "status": "scheduled"}
        b = {"game_id": "7", "status": "final"}
        assert E.dedupe_by_game_id([a, b]) == [b]
        assert E.dedupe_by_game_id([b, a]) == [b]


class TestDateParams:
    def test_single_day(self):
        assert E.date_range_param(date(2026, 8, 5), date(2026, 8, 5)) == "20260805"

    def test_range(self):
        assert E.date_range_param(date(2026, 8, 5), date(2026, 8, 15)) == "20260805-20260815"


@pytest.mark.network
class TestAgainstLiveEspn:
    """Year-round invariants against the real feed; no assertion that games exist."""

    def test_window_rows_obey_the_contract(self):
        rows, _ = E.fetch_window("nba", date(2025, 1, 10), 11, ttl=0)
        assert rows, "a known-busy historical NBA window should not be empty"
        for row in rows:
            assert CONTRACT_KEYS <= set(row)
            assert row["status"] in VALID_STATUS
            assert "2025-01-10" <= row["game_date"] <= "2025-01-20"
            if row["status"] not in ("live", "final"):
                assert row["home_score"] is None and row["away_score"] is None

    def test_no_duplicate_game_ids(self):
        rows, _ = E.fetch_window("nba", date(2025, 1, 10), 11, ttl=0)
        ids = [r["game_id"] for r in rows]
        assert len(ids) == len(set(ids))

    def test_boundary_game_is_found_by_its_slate_date(self):
        # Regression: a UTC reading files this game under 08-07 and loses it.
        rows, _ = E.fetch_window("nfl", date(2026, 8, 6), 1, ttl=0)
        assert any(r["home"] == "ARI" and r["away"] == "CAR" for r in rows)
