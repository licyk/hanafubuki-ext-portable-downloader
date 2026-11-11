"""Coalescing frequent changes into at most a few calls a second, never dropping the last."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class Throttle:
    """Calls ``flush`` on a timer thread after a ``poke``, at most once per ``interval``.

    A poke while a flush is pending joins it; a poke during or after a flush schedules
    another, so the last change is always flushed.
    """

    def __init__(self, interval: float, flush: Callable[[], None]) -> None:
        """Builds the throttle.

        Args:
            interval: The shortest time between two flushes, in seconds.
            flush: What to call; runs on a timer thread, never two at once.
        """
        self._interval = interval
        self._flush = flush
        self._lock = threading.Lock()
        self._flushing = threading.Lock()
        self._timer: threading.Timer | None = None
        self._last = 0.0
        self._closed = False

    def poke(self) -> None:
        """Asks for a flush."""
        with self._lock:
            if self._closed or self._timer is not None:
                return
            delay = max(0.0, self._last + self._interval - time.monotonic())
            self._timer = threading.Timer(delay, self._run)
            self._timer.daemon = True
            self._timer.start()

    def close(self) -> None:
        """Cancels a pending flush; later pokes do nothing."""
        with self._lock:
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _run(self) -> None:
        with self._flushing:
            with self._lock:
                self._timer = None
                self._last = time.monotonic()
            self._flush()
