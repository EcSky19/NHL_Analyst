from __future__ import annotations

from typing import Any


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
    monkeypatch.setattr(mlb, "predict_home_win_prob", lambda state: (0.62, {"available": True}))

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
    monkeypatch.setattr(mlb, "predict_home_win_prob", lambda state: (None, {"available": False, "reason": reason}))

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
    assert "Not betting advice" in app_js
    assert "asNumber(wp.home)" in app_js
    assert "asNumber(wp.away)" in app_js
    assert "live-winprob" in styles
    assert "live-wp-track" in styles
