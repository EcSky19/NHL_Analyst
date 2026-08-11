"""Tests for the shared in-game snapshot harvester and win-probability core.

These lock in traps that were found by inspecting real ESPN payloads. Each one
would have silently produced a plausible-but-wrong model rather than an obvious
failure, which is the dangerous kind of bug for this repo.
"""

from __future__ import annotations

import math

import pytest

from app.services import espn_pbp as P
from app.services import live_winprob as W


def _play(period, clock, home, away, ptype=None, outs=None, play_id="1"):
    play = {
        "id": play_id,
        "period": {"number": period},
        "clock": {"displayValue": clock},
        "homeScore": home,
        "awayScore": away,
    }
    if ptype:
        play["period"]["type"] = ptype
    if outs is not None:
        play["outs"] = outs
    return play


class TestClockDirection:
    """NHL counts UP; NBA/NFL count DOWN. Mixing them up is silent and fatal."""

    def test_nba_clock_counts_down(self):
        # Full 12:00 on the clock in Q1 means nothing has elapsed.
        assert P.frac_remaining_clock("nba", 1, 720.0) == pytest.approx(1.0)
        assert P.frac_remaining_clock("nba", 4, 0.0) == pytest.approx(0.0)

    def test_nhl_clock_counts_up(self):
        # 0:00 elapsed in period 1 means the whole game remains.
        assert P.frac_remaining_clock("nhl", 1, 0.0) == pytest.approx(1.0)
        assert P.frac_remaining_clock("nhl", 3, 1200.0) == pytest.approx(0.0)

    def test_nhl_would_be_wrong_under_countdown_assumption(self):
        # Regression guard: the count-down formula scores puck drop as a third
        # of the game already gone.
        assert P.frac_remaining_clock("nhl", 1, 0.0) != pytest.approx(2 / 3)

    def test_overtime_has_no_regulation_left(self):
        assert P.frac_remaining_clock("nba", 5, 300.0) == 0.0
        assert P.frac_remaining_clock("nhl", 4, 10.0) == 0.0

    def test_nba_overtime_fraction_uses_current_ot_clock(self):
        assert P.ot_frac_remaining_clock("nba", 5, 300.0) == pytest.approx(1.0)
        assert P.ot_frac_remaining_clock("nba", 5, 0.0) == pytest.approx(0.0)
        assert P.ot_frac_remaining_clock("nba", 4, 60.0) is None
        assert P.ot_frac_remaining_clock("nba", 5, None) is None

    def test_missing_clock_falls_back_to_whole_periods(self):
        assert P.frac_remaining_clock("nba", 3, None) == pytest.approx(0.5)


class TestClockParsing:
    @pytest.mark.parametrize(
        "raw,expected", [("9:51", 591.0), ("0:00", 0.0), ("12:00", 720.0), (45, 45.0), ("30", 30.0)]
    )
    def test_parses_known_formats(self, raw, expected):
        assert P.parse_clock_seconds(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "junk"])
    def test_bad_clock_returns_none_rather_than_guessing(self, raw):
        assert P.parse_clock_seconds(raw) is None


class TestInnings:
    def test_game_start_is_full_game_remaining(self):
        assert P.frac_remaining_innings(1, True) == pytest.approx(1.0)

    def test_bottom_of_ninth_is_nearly_over(self):
        assert P.frac_remaining_innings(9, False) == pytest.approx(1 / 18)

    def test_top_and_bottom_differ(self):
        # The home team's last at-bat makes these genuinely different states.
        assert P.frac_remaining_innings(9, True) != P.frac_remaining_innings(9, False)

    def test_extra_innings_clamped_at_zero(self):
        assert P.frac_remaining_innings(11, False) == 0.0


class TestPlayExtraction:
    def test_nfl_plays_are_read_from_drives(self):
        # ESPN sends plays: null for NFL and nests them under drives.
        summary = {
            "plays": None,
            "drives": {"previous": [{"plays": [_play(1, "15:00", 0, 0)]}, {"plays": [_play(2, "7:00", 7, 3)]}]},
        }
        assert len(P._iter_plays(summary, "nfl")) == 2

    def test_top_level_plays_preferred_when_present(self):
        summary = {"plays": [_play(1, "12:00", 0, 0)], "drives": {"previous": []}}
        assert len(P._iter_plays(summary, "nba")) == 1

    def test_no_plays_yields_no_snapshots(self):
        assert P.snapshots_from_summary({"plays": []}, "nba", "g1") == []


class TestSnapshotLabelling:
    def test_home_win_label_and_margin(self):
        summary = {"plays": [_play(1, "12:00", 0, 0), _play(4, "0:00", 110, 100)]}
        snaps = P.snapshots_from_summary(summary, "nba", "g1")
        assert all(s.home_won == 1 for s in snaps)
        assert snaps[-1].margin == 10

    def test_away_win_label(self):
        summary = {"plays": [_play(1, "12:00", 0, 0), _play(4, "0:00", 99, 110)]}
        assert all(s.home_won == 0 for s in P.snapshots_from_summary(summary, "nba", "g1"))

    def test_tied_final_is_discarded_not_guessed(self):
        # An unresolved game has no honest label, so it must not be emitted.
        summary = {"plays": [_play(1, "12:00", 0, 0), _play(4, "0:00", 100, 100)]}
        assert P.snapshots_from_summary(summary, "nba", "g1") == []

    def test_mlb_uses_half_innings_and_keeps_outs(self):
        summary = {"plays": [_play(5, None, 3, 2, ptype="Top", outs=2), _play(9, None, 5, 2, ptype="Bottom", outs=3)]}
        snaps = P.snapshots_from_summary(summary, "mlb", "g1")
        assert snaps[0].outs == 2
        assert snaps[0].frac_remaining > snaps[1].frac_remaining

    def test_frac_remaining_is_non_increasing_through_a_game(self):
        summary = {"plays": [_play(1, "12:00", 0, 0), _play(2, "6:00", 20, 18), _play(4, "0:00", 99, 90)]}
        fracs = [s.frac_remaining for s in P.snapshots_from_summary(summary, "nba", "g1")]
        assert all(fracs[i] >= fracs[i + 1] for i in range(len(fracs) - 1))

    def test_espn_win_probability_is_attached_for_benchmarking(self):
        summary = {
            "plays": [_play(1, "12:00", 0, 0, play_id="p1"), _play(4, "0:00", 110, 100, play_id="p2")],
            "winprobability": [{"playId": "p1", "homeWinPercentage": 0.55}],
        }
        snaps = P.snapshots_from_summary(summary, "nba", "g1")
        assert snaps[0].espn_home_wp == 0.55
        assert snaps[1].espn_home_wp is None


class TestFeatures:
    def test_frozen_feature_names_are_stable(self):
        # Training and serving both key off this list; reordering breaks artifacts.
        assert W.FEATURE_NAMES == [
            "margin",
            "margin_scaled",
            "frac_remaining",
            "pregame_logit",
            "pregame_logit_decay",
            "is_overtime",
        ]

    def test_feature_vector_matches_names(self):
        state = W.GameState(league="nba", margin=5, frac_remaining=0.25)
        assert len(W.feature_vector(state)) == len(W.FEATURE_NAMES)

    def test_margin_scaled_grows_as_time_runs_out(self):
        early = W.build_features(W.GameState(league="nba", margin=6, frac_remaining=1.0))
        late = W.build_features(W.GameState(league="nba", margin=6, frac_remaining=0.05))
        assert late["margin_scaled"] > early["margin_scaled"]

    def test_absent_pregame_prior_is_neutral_not_invented(self):
        feats = W.build_features(W.GameState(league="nba", margin=0, frac_remaining=1.0))
        assert feats["pregame_logit"] == 0.0

    def test_pregame_prior_decays_with_time(self):
        state = W.GameState(league="nba", margin=0, frac_remaining=0.1, pregame_home_prob=0.7)
        feats = W.build_features(state)
        assert abs(feats["pregame_logit_decay"]) < abs(feats["pregame_logit"])

    def test_logit_roundtrip(self):
        for p in (0.01, 0.5, 0.99):
            assert W.inv_logit(W.logit(p)) == pytest.approx(p, abs=1e-9)


class TestBaselines:
    def test_leader_baseline_follows_the_lead(self):
        assert W.baseline_leader(W.GameState("nba", 5, 0.5)) > 0.5
        assert W.baseline_leader(W.GameState("nba", -5, 0.5)) < 0.5
        assert W.baseline_leader(W.GameState("nba", 0, 0.5)) == 0.5

    def test_normal_baseline_is_time_aware(self):
        early = W.baseline_normal(W.GameState("nba", 6, 1.0), mu=2.5, sigma=12.0)
        late = W.baseline_normal(W.GameState("nba", 6, 0.05), mu=2.5, sigma=12.0)
        assert late > early

    def test_normal_baseline_resolves_at_game_end(self):
        assert W.baseline_normal(W.GameState("nba", 3, 0.0), 2.5, 12.0) == 1.0
        assert W.baseline_normal(W.GameState("nba", -3, 0.0), 2.5, 12.0) == 0.0

    def test_normal_baseline_stays_a_probability(self):
        for margin in (-40, -5, 0, 5, 40):
            for frac in (0.0, 0.01, 0.5, 1.0):
                p = W.baseline_normal(W.GameState("nba", margin, frac), 2.5, 12.0)
                assert 0.0 <= p <= 1.0


class TestMetrics:
    def test_brier_rewards_confident_correctness(self):
        assert W.brier_score([1.0, 0.0], [1, 0]) == 0.0
        assert W.brier_score([0.0, 1.0], [1, 0]) == 1.0

    def test_log_loss_is_finite_at_extremes(self):
        assert math.isfinite(W.log_loss([0.0, 1.0], [1, 0]))

    def test_calibration_table_reports_gap(self):
        probs = [0.9] * 100
        outcomes = [1] * 50 + [0] * 50
        gap = W.max_calibration_gap(probs, outcomes, min_n=10)
        assert gap == pytest.approx(0.4, abs=1e-6)

    def test_perfect_calibration_has_no_gap(self):
        probs = [0.5] * 100
        outcomes = [1] * 50 + [0] * 50
        assert W.max_calibration_gap(probs, outcomes, min_n=10) == pytest.approx(0.0, abs=1e-9)


class TestHonestRefusal:
    def test_unknown_league_returns_none_with_reason(self):
        prob, meta = W.predict_home_win_prob(W.GameState(league="cricket", margin=1, frac_remaining=0.5))
        assert prob is None
        assert meta["available"] is False
        assert meta["reason"]
