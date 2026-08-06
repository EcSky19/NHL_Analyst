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
