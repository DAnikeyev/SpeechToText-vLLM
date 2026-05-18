from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

try:
    import keyboard
except Exception:  # pragma: no cover - optional at import time
    keyboard = None

CTRL_NAMES = {"ctrl", "left ctrl", "right ctrl"}


@dataclass
class CtrlHoldTracker:
    on_record_start: Callable[[], None]
    on_record_stop: Callable[[float], None]
    min_hold_seconds: float
    start_delay_seconds: float = 0.2

    _pressed: set[str] = field(default_factory=set)
    _start_time: float | None = None
    _start_timer: threading.Timer | None = None
    _recording_started: bool = False
    _hook = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self) -> None:
        if keyboard is None:
            raise RuntimeError("keyboard library is required to capture global hotkeys")
        self._hook = keyboard.hook(self._handle_keyboard_event)

    def stop(self) -> None:
        with self._lock:
            self._cancel_timer_locked()
            if self._hook is not None and keyboard is not None:
                keyboard.unhook(self._hook)
                self._hook = None
            self._pressed.clear()
            self._start_time = None
            self._recording_started = False

    def _handle_keyboard_event(self, event) -> None:
        name = (event.name or "").lower()
        event_type = event.event_type
        if name not in CTRL_NAMES:
            return

        now = time.monotonic()
        self.handle_ctrl_event(name=name, event_type=event_type, timestamp=now)

    def handle_ctrl_event(self, name: str, event_type: str, timestamp: float) -> None:
        with self._lock:
            if event_type == "down":
                self._pressed.add(name)
                if self._start_time is None:
                    self._start_time = timestamp
                    self._recording_started = False
                    self._schedule_start_locked()
                return

            if event_type != "up":
                return

            self._pressed.discard(name)
            if self._pressed:
                return

            self._cancel_timer_locked()
            if self._start_time is None:
                return

            hold_seconds = max(0.0, timestamp - self._start_time)
            self._start_time = None
            should_stop = self._recording_started
            self._recording_started = False

        if should_stop:
            self.on_record_stop(hold_seconds)

    def _schedule_start_locked(self) -> None:
        self._cancel_timer_locked()
        self._start_timer = threading.Timer(self.start_delay_seconds, self._maybe_start_recording)
        self._start_timer.daemon = True
        self._start_timer.start()

    def _cancel_timer_locked(self) -> None:
        if self._start_timer is not None:
            self._start_timer.cancel()
            self._start_timer = None

    def _maybe_start_recording(self) -> None:
        should_start = False
        with self._lock:
            if self._start_time is not None and self._pressed and not self._recording_started:
                self._recording_started = True
                should_start = True
        if should_start:
            self.on_record_start()
