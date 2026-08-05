"""Disk-backed TTL cache with stale-on-error fallback.

The UI must keep rendering when an upstream API blips, so a failed refresh falls
back to the last good payload instead of surfacing an error page.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from app.config import settings

logger = logging.getLogger(__name__)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        if key not in _locks:
            _locks[key] = threading.Lock()
        return _locks[key]


def _path_for(key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:60]
    return settings.cache_dir / f"{safe}.{digest}.json"


def read_cache(key: str) -> tuple[Any, float] | None:
    """Return (value, stored_at) if a cache entry exists, else None."""
    path = _path_for(key)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            blob = json.load(handle)
        return blob["value"], float(blob["stored_at"])
    except (OSError, ValueError, KeyError):
        logger.warning("Discarding unreadable cache entry: %s", path.name)
        return None


def write_cache(key: str, value: Any) -> None:
    path = _path_for(key)
    tmp = path.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump({"stored_at": time.time(), "key": key, "value": value}, handle)
        tmp.replace(path)
    except (OSError, TypeError) as exc:
        logger.warning("Could not write cache for %s: %s", key, exc)
        tmp.unlink(missing_ok=True)


def cached_fetch(
    key: str,
    ttl_seconds: int,
    loader: Callable[[], Any],
    *,
    force_refresh: bool = False,
) -> tuple[Any, dict[str, Any]]:
    """Fetch through the cache.

    Returns (value, meta) where meta carries cached/stale flags for the envelope.
    Raises only when there is no fresh data AND no cached fallback.
    """
    with _lock_for(key):
        entry = read_cache(key)
        now = time.time()

        if entry is not None and not force_refresh:
            value, stored_at = entry
            age = now - stored_at
            if age < ttl_seconds:
                return value, {"cached": True, "stale": False, "age_seconds": round(age, 1)}

        try:
            value = loader()
        except Exception as exc:  # noqa: BLE001 - fall back to any cached copy
            if entry is not None:
                stale_value, stored_at = entry
                logger.warning("Refresh failed for %s, serving stale copy: %s", key, exc)
                return stale_value, {
                    "cached": True,
                    "stale": True,
                    "age_seconds": round(now - stored_at, 1),
                    "stale_reason": f"{type(exc).__name__}: {exc}",
                }
            raise

        write_cache(key, value)
        return value, {"cached": False, "stale": False, "age_seconds": 0.0}


def clear_cache() -> int:
    """Remove all cache entries. Returns the number of files deleted."""
    removed = 0
    for path in settings.cache_dir.glob("*.json"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed
