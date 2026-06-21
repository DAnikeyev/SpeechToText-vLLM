"""Monotonic cancellation generation for the dictation pipeline.

A single Backspace press bumps the generation; jobs stamped with an older
generation are treated as cancelled whether they are still queued or already
being processed. This lets one keystroke abort both the queued recording and the
in-flight transcription/LLM work.
"""

from __future__ import annotations

import queue
import threading
from typing import Any


class CancellationCoordinator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        # The generation currently being processed, or None when the worker is idle.
        self.processing_generation: int | None = None

    def generation(self) -> int:
        with self._lock:
            return self._generation

    def is_cancelled(self, generation: int) -> bool:
        return generation != self.generation()

    def begin(self, generation: int) -> None:
        with self._lock:
            self.processing_generation = generation

    def end(self) -> None:
        with self._lock:
            self.processing_generation = None

    def request_cancel(self, job_queue: queue.Queue[Any]) -> tuple[bool, int]:
        """Bump the generation and drain ``job_queue``.

        Returns ``(was_processing, drained_count)`` so the caller can log it.
        """
        drained = 0
        with self._lock:
            self._generation += 1
            was_processing = self.processing_generation is not None
        while True:
            try:
                job_queue.get_nowait()
                drained += 1
            except queue.Empty:
                break
        return was_processing, drained
