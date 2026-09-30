"""Één begrensde achtergrondworker voor netwerk- en feedtaken.

Tkinter en de alarmtick blijven op de hoofdthread. Langzame HTTP-requests,
feedopslag en agenda-import draaien hier serieel zodat ze nooit een tweede
onbegrensde thread per seconde kunnen starten.
"""

from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
from collections.abc import Callable
from typing import Any


@dataclass(frozen=True)
class JobResult:
    key: str
    ok: bool
    value: Any = None
    error: str = ""


class BackgroundWorker:
    def __init__(self, name: str = "wakesync-background") -> None:
        self._jobs: queue.Queue[tuple[str, Callable[[], Any]] | None] = queue.Queue(maxsize=8)
        self._results: queue.SimpleQueue[JobResult] = queue.SimpleQueue()
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, key: str, fn: Callable[[], Any]) -> bool:
        """Plan hoogstens één taak met dezelfde sleutel."""
        with self._lock:
            if self._closed or key in self._pending:
                return False
            self._pending.add(key)
        try:
            self._jobs.put_nowait((key, fn))
        except queue.Full:
            with self._lock:
                self._pending.discard(key)
            return False
        return True

    def has_pending(self, key: str) -> bool:
        with self._lock:
            return key in self._pending

    def poll(self) -> list[JobResult]:
        results: list[JobResult] = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                break
        return results

    def close(self) -> None:
        with self._lock:
            self._closed = True
        try:
            self._jobs.put_nowait(None)
        except queue.Full:
            pass

    def _run(self) -> None:
        while True:
            item = self._jobs.get()
            if item is None:
                return
            key, fn = item
            try:
                value = fn()
            except Exception as exc:
                self._results.put(
                    JobResult(key=key, ok=False, error=f"{type(exc).__name__}: {exc}")
                )
            else:
                self._results.put(JobResult(key=key, ok=True, value=value))
            finally:
                with self._lock:
                    self._pending.discard(key)
