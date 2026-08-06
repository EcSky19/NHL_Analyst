from __future__ import annotations


def test_live_schedule_tab_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert 'data-view="liveSchedule"' in response.text
    assert "Live &amp; Schedule" in response.text


def test_live_schedule_static_assets_expose_contract_ui(client):
    app_js = client.get("/static/app.js")
    styles = client.get("/static/styles.css")

    assert app_js.status_code == 200
    assert styles.status_code == 200
    assert "/api/${league}/live" in app_js.text
    assert "/api/${league}/schedule/week" in app_js.text
    assert "meta.empty_reason" in app_js.text
    assert "poll_interval_seconds" in app_js.text
    assert "live.clock == null" in app_js.text
    assert "escapeHtml(live.last_play)" in app_js.text
    assert "function formatPeriodLabel" in app_js.text
    assert "Top" in app_js.text
    assert "Raw period label" in app_js.text
    assert "visibilitychange" in app_js.text
    assert "MLB no model exists yet" not in app_js.text
    assert "MLB model accuracy is 55.72%" in app_js.text
    assert "56.13% pure-Elo baseline" in app_js.text
    assert "live-game-card" in styles.text
    assert "schedule-day" in styles.text


def test_live_cards_guard_optional_situation_fields(client):
    """Static guard using ESPN MLB live rows captured on 2026-08-05 as fixture shape."""

    real_espn_mlb_live_rows = [
        {
            "game_id": "401816412",
            "league": "mlb",
            "home": "SEA",
            "away": "DET",
            "home_score": 4,
            "away_score": 2,
            "status": "live",
            "detailed_status": "Top 9th",
            "live": {"period": 9, "period_label": "9", "clock": "0:00", "last_play": "Torkelson struck out swinging."},
        },
        {
            "game_id": "401816413",
            "league": "mlb",
            "home": "ARI",
            "away": "SD",
            "home_score": 8,
            "away_score": 0,
            "status": "live",
            "detailed_status": "Top 8th",
            "live": {"period": 8, "period_label": "8", "clock": "0:00", "last_play": "Pitch 3 : Ball 1"},
        },
    ]
    assert len(real_espn_mlb_live_rows) == 2

    app_js = client.get("/static/app.js").text
    styles = client.get("/static/styles.css").text

    assert "normalizeObject(gameRow.live)" in app_js
    assert "normalizeObject(gameRow.situation)" in app_js
    assert "normalizeObject(live.situation)" in app_js
    assert "situation.down_distance != null" in app_js
    assert "situation.possession != null" in app_js
    assert "isRedZone(situation)" in app_js
    assert "hasPossession(gameRow, 'away', situation.possession)" in app_js
    assert "possession-chip" in app_js
    assert "red-zone" in styles
