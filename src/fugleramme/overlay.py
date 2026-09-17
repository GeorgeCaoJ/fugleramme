"""A Source that overlays upload-analysis hits on top of the live detector.

BirdNET-Go's `file` command writes a Raven table rather than the realtime API,
so upload results would never appear in `/preview.png` without a local inject.
This wrapper keeps the detector for everything else and prefers the latest
upload when the admin asked to show it.
"""

from __future__ import annotations

import threading
from datetime import datetime

from .source import Detection, Source, Species


class UploadOverlay:
    """Delegates to `inner`, with optional upload detections taking precedence.

    While an upload session is active, the page is about those birds alone - not
    a merge with the live detector - so a collage of two hits shows two birds.
    """

    def __init__(self, inner: Source):
        self._inner = inner
        self._lock = threading.Lock()
        self._hits: list[Detection] = []
        self._rev = 0  # bumps on every set/clear so render caches cannot stick

    @property
    def inner(self) -> Source:
        return self._inner

    @property
    def upload_rev(self) -> int:
        with self._lock:
            return self._rev

    def set_upload(self, detections: list[Detection]) -> None:
        """Replace the overlay with these hits (already filtered to birds)."""
        with self._lock:
            self._hits = list(detections)
            self._rev += 1
        from . import modes

        modes.invalidate_png_cache()

    def clear(self) -> None:
        with self._lock:
            self._hits = []
            self._rev += 1
        from . import modes

        modes.invalidate_png_cache()

    def _snapshot(self) -> list[Detection]:
        with self._lock:
            return list(self._hits)

    @property
    def base_url(self) -> str:
        return self._inner.base_url

    @property
    def station(self) -> str:
        return getattr(self._inner, "station", self._inner.base_url)

    def latest_upload(self) -> Detection | None:
        """The newest upload hit only (ignores the live detector)."""
        hits = self._snapshot()
        return max(hits, key=lambda d: d.detected_at) if hits else None

    def latest(self) -> Detection | None:
        hit = self.latest_upload()
        return hit if hit is not None else self._inner.latest()

    def recent(self, limit: int = 20) -> list[Detection]:
        hits = self._snapshot()
        if hits:
            return sorted(hits, key=lambda d: d.detected_at, reverse=True)[:limit]
        return self._inner.recent(limit)

    def species_since(self, hours: float = 24) -> list[tuple[str, int]]:
        hits = self._snapshot()
        if hits:
            counts: dict[str, int] = {}
            for d in hits:
                counts[d.scientific_name] = counts.get(d.scientific_name, 0) + 1
            return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return self._inner.species_since(hours)

    def life_list(self) -> list[Species]:
        return self._inner.life_list()

    def stats(self) -> dict:
        return self._inner.stats()

    def request(self, path: str, method: str = "GET", headers=None, params=None):
        return self._inner.request(path, method, headers, params)

    def close(self) -> None:
        self._inner.close()
