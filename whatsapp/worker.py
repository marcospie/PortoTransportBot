"""Off-request-path execution for the WhatsApp webhook.

Meta retries a webhook delivery whenever it is not acknowledged quickly, and a
retry produces a *second* reply to a real user.  The old code called
``asyncio.run()`` once per inbound message **inside** the synchronous Flask
view, which meant every network round-trip to STCP/Metro/Graph happened before
the 200 was returned - the exact recipe for retries and duplicate replies.

:class:`BackgroundWorker` fixes that: the view validates, de-duplicates,
enqueues and returns 200 immediately, while a single daemon thread owning one
persistent asyncio event loop does the real work.  One loop (rather than
``asyncio.run`` per message) also keeps aiohttp connection pools and caches
alive between messages.

Works unchanged under gunicorn: the thread is created lazily on first use, so
each forked worker process gets its own loop and nothing is inherited across a
``fork()``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

__all__ = ["BackgroundWorker", "InlineWorker"]


class BackgroundWorker:
    """Runs coroutines on a single persistent event loop in a daemon thread."""

    def __init__(self, name: str = "whatsapp-worker") -> None:
        self._name = name
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # Strong references to in-flight tasks (asyncio only keeps weak ones).
        self._pending: set[asyncio.Task] = set()

    # -- lifecycle ---------------------------------------------------------
    def _ensure_running(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._thread is not None and self._thread.is_alive():
                return self._loop
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run_loop, args=(loop,), name=self._name, daemon=True,
            )
            self._loop = loop
            self._thread = thread
            thread.start()
            logger.info("Background worker %s started", self._name)
            return loop

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop the worker loop (used by tests and clean shutdowns)."""
        with self._lock:
            loop, thread = self._loop, self._thread
            self._loop, self._thread = None, None
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=timeout)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- submission --------------------------------------------------------
    def submit(self, fn: Callable[..., Awaitable[Any]], *args, **kwargs) -> None:
        """Schedule ``fn(*args, **kwargs)`` on the worker loop, fire and forget.

        *fn* is a coroutine **function**, not a coroutine: nothing is created
        until the worker is confirmed running, so a rejected submission can
        never leave a "coroutine was never awaited" warning behind.
        """
        try:
            loop = self._ensure_running()
        except Exception:  # pragma: no cover - thread creation failure
            logger.exception("Could not start background worker; dropping message")
            return

        def _schedule() -> None:
            task = loop.create_task(self._guard(fn, *args, **kwargs))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

        try:
            loop.call_soon_threadsafe(_schedule)
        except RuntimeError:  # pragma: no cover - loop closed under us
            logger.exception("Worker loop unavailable; dropping message")

    @staticmethod
    async def _guard(fn: Callable[..., Awaitable[Any]], *args, **kwargs) -> None:
        """Never let a handler exception kill the worker loop."""
        try:
            await fn(*args, **kwargs)
        except Exception:
            logger.exception("Unhandled error while processing WhatsApp message")


class InlineWorker:
    """Runs the coroutine immediately, in the calling thread.

    Used by the test suite (deterministic: the reply has been sent by the time
    the webhook call returns) and handy for step-through debugging.  Never use
    it in production - it reintroduces the blocking-webhook bug.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def submit(self, fn: Callable[..., Awaitable[Any]], *args, **kwargs) -> None:
        self.calls.append((fn, args, kwargs))
        try:
            asyncio.run(fn(*args, **kwargs))
        except Exception:
            logger.exception("Unhandled error while processing WhatsApp message")

    def shutdown(self, timeout: float = 5.0) -> None:  # pragma: no cover - no-op
        return None
