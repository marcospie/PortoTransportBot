"""Bounded in-memory TTL cache.

The cache used to grow without limit: per-stop and per-query keys were added
for the whole lifetime of the process and ``cleanup()`` was never called from
anywhere, so a long-running bot leaked memory slowly but steadily.

It is now bounded in two independent ways:

* **Lazy expiry sweep** — expired entries are dropped opportunistically on
  writes (at most once every :data:`CLEANUP_INTERVAL` seconds) so a cache whose
  keys are never read again does not keep them forever.
* **Hard size cap** — once :attr:`max_size` live entries are stored, inserting
  a new key evicts the least-recently-used one.

The public API (``get``/``set``/``clear``/``cleanup``) is unchanged, and
``TTLCache(default_ttl=...)`` keeps working for the services that construct it.
"""

import time
from collections import OrderedDict
from typing import Any

#: Default upper bound on the number of live entries in a single cache.
DEFAULT_MAX_SIZE = 512

#: Minimum number of seconds between two opportunistic expiry sweeps.
CLEANUP_INTERVAL = 60


class TTLCache:
    """In-memory cache with time-to-live expiration and a bounded size.

    Args:
        default_ttl: Seconds an entry stays valid when ``set`` gets no explicit
            ``ttl``.
        max_size: Maximum number of live entries. Inserting beyond this evicts
            the least-recently-used entry. Values below 1 are clamped to 1.
    """

    def __init__(self, default_ttl: int = 60,
                 max_size: int = DEFAULT_MAX_SIZE):
        self._store: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._default_ttl = default_ttl
        self._max_size = max(1, int(max_size))
        self._last_cleanup = time.monotonic()
        self.evictions = 0

    # -- introspection ----------------------------------------------------

    @property
    def max_size(self) -> int:
        """Maximum number of entries kept before LRU eviction kicks in."""
        return self._max_size

    def __len__(self) -> int:
        """Number of stored entries (including not-yet-swept expired ones)."""
        return len(self._store)

    def __contains__(self, key: str) -> bool:
        """True when ``key`` is present *and* not expired."""
        entry = self._store.get(key)
        return entry is not None and time.monotonic() <= entry[0]

    # -- core API ---------------------------------------------------------

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expiry, value = entry
        if time.monotonic() > expiry:
            del self._store[key]
            return None
        # Mark as recently used so the size cap evicts cold keys first.
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl if ttl is not None else self._default_ttl
        if key in self._store:
            del self._store[key]
        else:
            self._maybe_cleanup()
            self._enforce_max_size()
        self._store[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        self._store.clear()
        self._last_cleanup = time.monotonic()

    def cleanup(self) -> None:
        """Drop every expired entry.

        Called automatically (at most once per :data:`CLEANUP_INTERVAL`) from
        :meth:`set`; still available for callers that want to force a sweep.
        """
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        self._last_cleanup = now

    # -- internals --------------------------------------------------------

    def _maybe_cleanup(self) -> None:
        """Sweep expired entries, but not more often than once per interval."""
        now = time.monotonic()
        if now - self._last_cleanup < CLEANUP_INTERVAL:
            return
        self.cleanup()

    def _enforce_max_size(self) -> None:
        """Make room for one new entry, evicting LRU keys if necessary."""
        if len(self._store) < self._max_size:
            return
        # An expired entry is always the better thing to drop than a live one.
        self.cleanup()
        while len(self._store) >= self._max_size:
            self._store.popitem(last=False)
            self.evictions += 1
