from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any
import app.services.live_wp_state as _wp_state


def _live_game(game_id: str = "823598") -> dict[str, Any]:
    return {
        "game_id": game_id,
        "game_date": "2026-08-05",
        "start_time_utc": "2026-08-05T23:00:00Z",
        "home": "LAD",
        "away": "TOR",
        "home_name": "Los Angeles Dodgers",
        "away_name": "Toronto Blue Jays",
        "home_score": 5,
        "away_score": 4,
        "status": "in-progress",
        "detailed_status": "Top 7th",
        "venue": "Test Park",
        "live": {"period": 7, "period_label": "T7", "clock": None, "last_play": "Single to left."},
    }


def test_mlb_live_win_probability_available(client, mocked_mlb, monkeypatch):
    import app.routers.mlb as mlb

    meta = {"cached": True, "stale": False, "age_seconds": 0.0, "fetched_at": "2026-08-05T00:00:00Z"}
    monkeypatch.setattr(mlb, "_fetch_live_window", lambda: ([_live_game()], meta, "2026"))
    monkeypatch.setattr(_wp_state, "predict_home_win_prob", lambda state: (0.62, {"available": True}))

    payload = client.get("/api/mlb/live").json()

    wp = payload["data"][0]["win_probability"]
    assert wp == {"available": True, "home": 0.62, "away": 0.38, "model": "mlb_live_wp", "reason": None}
    assert 0 < wp["home"] < 1
    assert 0 < wp["away"] < 1
    assert wp["home"] + wp["away"] == 1


def test_mlb_live_win_probability_unavailable_surfaces_model_reason(client, mocked_mlb, monkeypatch):
    import app.routers.mlb as mlb

    meta = {"cached": True, "stale": False, "age_seconds": 0.0, "fetched_at": "2026-08-05T00:00:00Z"}
    reason = "No validated live win-probability model exists for MLB."
    monkeypatch.setattr(mlb, "_fetch_live_window", lambda: ([_live_game()], meta, "2026"))
    monkeypatch.setattr(_wp_state, "predict_home_win_prob", lambda state: (None, {"available": False, "reason": reason}))

    payload = client.get("/api/mlb/live").json()

    wp = payload["data"][0]["win_probability"]
    assert wp["available"] is False
    assert wp["home"] is None
    assert wp["away"] is None
    assert wp["model"] == "mlb_live_wp"
    assert wp["reason"] == reason


def test_live_win_probability_static_ui_guards(client):
    app_js = client.get("/static/app.js").text
    styles = client.get("/static/styles.css").text

    assert "function liveWinProbabilityMarkup" in app_js
    assert "Live win probability unavailable" in app_js
    assert "No validated live win-probability model is available" in app_js
    assert "not a betting line" in app_js
    assert "asNumber(wp.home)" in app_js
    assert "asNumber(wp.away)" in app_js
    assert "sumsToOne" in app_js
    assert "live-winprob" in styles
    assert "live-wp-track" in styles


def _render_live_winprob_fixtures() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    script = r"""
const fs = require('fs');
const vm = require('vm');
const appPath = process.argv[1];
const context = {
  console,
  location: { search: '' },
  localStorage: { getItem: () => '', setItem: () => {} },
  document: { addEventListener: () => {}, querySelector: () => null, querySelectorAll: () => [] },
  window: { __SPORTS_ANALYTICS_TEST_HOOKS__: true },
  URLSearchParams,
  Date,
  Number,
  String,
  Array,
  Math,
  Map,
  Promise,
  encodeURIComponent,
  setTimeout,
  clearTimeout
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(appPath, 'utf8'), context, { filename: appPath });
const hooks = context.window.__sportsAnalyticsTestHooks__;
function game(league, wp) {
  const row = {
    game_id: `${league}-fixture`,
    league,
    away: 'AWY',
    home: 'HME',
    away_name: `${league.toUpperCase()} Away`,
    home_name: `${league.toUpperCase()} Home`,
    away_score: 2,
    home_score: 3,
    status: 'live',
    detailed_status: 'Top 7th',
    venue: 'Fixture Park',
    live: { period: 7, period_label: 'T7', clock: '01:23', last_play: 'Fixture play.' }
  };
  if (wp !== undefined) row.win_probability = wp;
  return row;
}
const output = {};
for (const league of ['nhl', 'nfl', 'nba', 'mlb']) {
  hooks.setLeagueForTest(league);
  output[`${league}Card`] = hooks.liveGameCard(game(league, { available: true, home: 0.9761, away: 0.0239, model: `${league}_live_wp`, reason: null }));
}
output.homeFavored = hooks.liveWinProbabilityMarkup({ win_probability: { available: true, home: 0.9761, away: 0.0239, model: 'mlb_live_wp', reason: null } }, 'Away Team', 'Home Team');
output.awayFavored = hooks.liveWinProbabilityMarkup({ win_probability: { available: true, home: 0.371, away: 0.629, model: 'nfl_live_wp', reason: null } }, 'Away Team', 'Home Team');
output.nearEven = hooks.liveWinProbabilityMarkup({ win_probability: { available: true, home: 0.501, away: 0.499, model: 'nba_live_wp', reason: null } }, 'Away Team', 'Home Team');
output.unavailable = hooks.liveWinProbabilityMarkup({ win_probability: { available: false, home: null, away: null, model: 'nhl_live_wp', reason: 'Score state is outside model coverage.' } }, 'Away Team', 'Home Team');
output.missing = hooks.liveWinProbabilityMarkup({}, 'Away Team', 'Home Team');
output.badSum = hooks.liveWinProbabilityMarkup({ win_probability: { available: true, home: 0.7, away: 0.7, model: 'mlb_live_wp', reason: null } }, 'Away Team', 'Home Team');
output.nearCertain = hooks.liveWinProbabilityMarkup({ win_probability: { available: true, home: 0.9996, away: 0.0004, model: 'nba_live_wp', reason: null } }, 'Away Team', 'Home Team');
output.exactCertain = hooks.liveWinProbabilityMarkup({ win_probability: { available: true, home: 1, away: 0, model: 'nhl_live_wp', reason: null } }, 'Away Team', 'Home Team');
process.stdout.write(JSON.stringify(output));
"""
    result = subprocess.run(
        ["node", "-e", script, str(root / "app" / "static" / "app.js")],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stderr == ""
    return json.loads(result.stdout)


def test_live_win_probability_rendering_for_all_leagues_and_states():
    rendered = _render_live_winprob_fixtures()

    for league in ("nhl", "nfl", "nba", "mlb"):
        html = rendered[f"{league}Card"]
        assert f"{league.upper()} Away (AWY) at {league.upper()} Home (HME)" in html
        assert f"{league}_live_wp" in html
        assert "Live win probability" in html
        assert "Model estimate - not a betting line." in html
        assert "undefined" not in html
        assert "NaN" not in html

    assert "Away Team 2.4%" in rendered["homeFavored"]
    assert "Home Team 97.6%" in rendered["homeFavored"]
    assert "Away Team 62.9%" in rendered["awayFavored"]
    assert "Home Team 37.1%" in rendered["awayFavored"]
    assert "Away Team 49.9%" in rendered["nearEven"]
    assert "Home Team 50.1%" in rendered["nearEven"]

    assert "Score state is outside model coverage." in rendered["unavailable"]
    assert "Live win probability unavailable" in rendered["unavailable"]
    assert "live-wp-track" not in rendered["unavailable"]
    assert "0%" not in rendered["unavailable"]
    assert "50%" not in rendered["unavailable"]

    assert "Live win probability unavailable" in rendered["missing"]
    assert "No validated live win-probability model is available for this league." in rendered["missing"]
    assert "undefined" not in rendered["missing"]
    assert "NaN" not in rendered["missing"]

    assert "Live win probability unavailable" in rendered["badSum"]
    assert "70.0%" not in rendered["badSum"]


def test_live_win_probability_never_displays_absolute_certainty():
    """0.9996 must not be rounded up into a bare "100%".

    The live models legitimately return values above 0.999, and naive one-decimal
    rounding prints those as "100.0%". This repo does not claim certainty it has
    not earned, so extremes render as ">99.9%" / "<0.1%" instead.
    """
    rendered = _render_live_winprob_fixtures()

    near = rendered["nearCertain"]
    assert ">99.9%" in near
    assert "100.0%" not in near
    assert "100%" not in near
    assert "<0.1%" in near
    assert "0.0%" not in near

    # An exact 1.0/0.0 is not a probability we will render at all.
    assert "Live win probability unavailable" in rendered["exactCertain"]
