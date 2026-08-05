from __future__ import annotations

import uuid

import pytest

from app import cache


def test_cached_fetch_hits_ttl_refreshes_after_expiry_and_serves_stale_on_error():
    key = f"pytest-cache-{uuid.uuid4()}"
    path = cache._path_for(key)
    path.unlink(missing_ok=True)
    calls = {"count": 0}

    def loader() -> dict[str, int]:
        calls["count"] += 1
        return {"value": calls["count"]}

    try:
        first, first_meta = cache.cached_fetch(key, 300, loader)
        second, second_meta = cache.cached_fetch(key, 300, loader)
        assert first == {"value": 1}
        assert second == first
        assert calls["count"] == 1
        assert first_meta["cached"] is False
        assert second_meta["cached"] is True
        assert second_meta["stale"] is False

        refreshed, refreshed_meta = cache.cached_fetch(key, -1, loader)
        assert refreshed == {"value": 2}
        assert refreshed_meta["cached"] is False
        assert calls["count"] == 2

        def failing_loader() -> dict[str, int]:
            raise RuntimeError("simulated outage")

        stale, stale_meta = cache.cached_fetch(key, -1, failing_loader)
        assert stale == refreshed
        assert stale_meta["cached"] is True
        assert stale_meta["stale"] is True
        assert "simulated outage" in stale_meta["stale_reason"]
    finally:
        path.unlink(missing_ok=True)


def test_cached_fetch_raises_without_stale_copy():
    key = f"pytest-cache-miss-{uuid.uuid4()}"
    path = cache._path_for(key)
    path.unlink(missing_ok=True)

    def failing_loader() -> None:
        raise RuntimeError("cold outage")

    with pytest.raises(RuntimeError, match="cold outage"):
        cache.cached_fetch(key, 300, failing_loader)
