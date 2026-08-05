from __future__ import annotations


def test_static_assets_are_served(client):
    index = client.get("/")
    app_js = client.get("/static/app.js")
    styles = client.get("/static/styles.css")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    assert app_js.status_code == 200
    assert styles.status_code == 200
