from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from app.platform import get_platform_services
from app.platform.base import GlobalHotkeyBackend, HotkeyBackendFactory, HotkeyEvent


class _Phase(Enum):
    IDLE = auto()
    HELD = auto()
    WAITING_NEXT = auto()
    RECORDING = auto()


DEFAULT_KEY_MODES: dict[str, str] = {
    "right ctrl": "restructure",
    "right shift": "answer",
}

DEFAULT_TRIPLE_PRESS_KEYS = {"right ctrl"}


@dataclass
class _KeyState:
    phase: _Phase = _Phase.IDLE
    press_time: float = 0.0
    tap_count: int = 0
    timer: threading.Timer | None = None


@dataclass
class DoublePressHotkeyTracker:
    on_record_start: Callable[[str, str, bool], None]
    on_record_stop: Callable[[float, str, str, bool], None]
    min_hold_seconds: float
    double_press_window_seconds: float = 0.5
    first_press_max_seconds: float = 0.3
    start_delay_seconds: float = 0.2
    on_cancel: Callable[[], None] | None = None
    backend_factory: HotkeyBackendFactory | None = None
    key_modes: dict[str, str] | None = None
    triple_press_keys: set[str] | None = None

    _keys: dict[str, _KeyState] = field(default_factory=dict)
    _disabled_modes: set[str] = field(default_factory=set)
    _recording_key: str | None = None
    _recording_mode: str = ""
    _recording_output_target: str = ""
    _recording_skip_llm: bool = False
    _record_start_time: float = 0.0
    _recording_started: bool = False
    _backend: GlobalHotkeyBackend | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.backend_factory is None:
            self.backend_factory = get_platform_services().create_hotkey_backend
        if self.key_modes is None:
            self.key_modes = dict(DEFAULT_KEY_MODES)
        if self.triple_press_keys is None:
            self.triple_press_keys = set(DEFAULT_TRIPLE_PRESS_KEYS)

        for key in self.key_modes or DEFAULT_KEY_MODES:
            if key not in self._keys:
                self._keys[key] = _KeyState()

    def start(self) -> None:
        if self._backend is not None:
            return
        backend_factory = self.backend_factory or get_platform_services().create_hotkey_backend
        backend = backend_factory()
        backend.start(self._handle_event)
        self._backend = backend

    def stop(self) -> None:
        backend = self._backend
        self._backend = None
        with self._lock:
            for ks in self._keys.values():
                self._cancel_key_timer_locked(ks)
                ks.phase = _Phase.IDLE
                ks.press_time = 0.0
                ks.tap_count = 0
            self._reset_recording_state_locked()
        if backend is not None:
            backend.stop()

    def _reset_recording_state_locked(self) -> None:
        self._recording_key = None
        self._recording_mode = ""
        self._recording_output_target = ""
        self._recording_skip_llm = False
        self._record_start_time = 0.0
        self._recording_started = False

    def _cancel_key_timer_locked(self, ks: _KeyState) -> None:
        if ks.timer is not None:
            ks.timer.cancel()
            ks.timer = None

    def _handle_event(self, event: Any) -> None:
        normalized = self._normalize_event(event)
        if normalized is None:
            return
        name, event_type = normalized
        if name == "backspace" and event_type == "down":
            if self.on_cancel is not None:
                self.on_cancel()
            return
        if name not in (self.key_modes or DEFAULT_KEY_MODES):
            return
        mode = (self.key_modes or DEFAULT_KEY_MODES).get(name, "")
        if mode in self._disabled_modes:
            return
        self._process(name, event_type, time.monotonic())

    @staticmethod
    def _normalize_event(event: Any) -> tuple[str, str] | None:
        if isinstance(event, HotkeyEvent):
            name = event.name.lower()
            event_type = event.event_type.lower()
        else:
            name = (getattr(event, "name", "") or "").lower()
            event_type = str(getattr(event, "event_type", "")).lower()
        if not name or event_type not in {"down", "up"}:
            return None
        return (name, event_type)

    def _process(self, key: str, event_type: str, timestamp: float) -> None:
        start_info: tuple[str, str, bool] | None = None
        stop_info: tuple[float, str, str, bool] | None = None

        with self._lock:
            ks = self._keys.get(key)
            if ks is None:
                return

            if event_type == "down":
                start_info = self._on_key_down_locked(key, ks, timestamp)
            elif event_type == "up":
                stop_info = self._on_key_up_locked(key, ks, timestamp)

        if start_info is not None:
            self.on_record_start(start_info[0], start_info[1], start_info[2])
        if stop_info is not None:
            self.on_record_stop(stop_info[0], stop_info[1], stop_info[2], stop_info[3])

    def _on_key_down_locked(
        self, key: str, ks: _KeyState, timestamp: float
    ) -> tuple[str, str, bool] | None:
        if ks.phase == _Phase.IDLE:
            ks.phase = _Phase.HELD
            ks.press_time = timestamp
            ks.tap_count = 0
            self._schedule_hold_timer_locked(key, ks)
            return None

        if ks.phase == _Phase.WAITING_NEXT:
            self._cancel_key_timer_locked(ks)
            ks.phase = _Phase.HELD
            ks.press_time = timestamp
            self._schedule_hold_timer_locked(key, ks)

        return None

    def _on_key_up_locked(
        self, key: str, ks: _KeyState, timestamp: float
    ) -> tuple[float, str, str, bool] | None:
        if ks.phase == _Phase.HELD:
            self._cancel_key_timer_locked(ks)
            hold_time = timestamp - ks.press_time
            if hold_time < self.first_press_max_seconds:
                self._register_tap_locked(key, ks)
            else:
                ks.phase = _Phase.IDLE
                ks.press_time = 0.0
                ks.tap_count = 0
            return None

        if ks.phase == _Phase.RECORDING and key == self._recording_key:
            was_recording = self._recording_started
            rec_mode = self._recording_mode
            output_target = self._recording_output_target
            skip_llm = self._recording_skip_llm
            record_start_time = self._record_start_time
            ks.phase = _Phase.IDLE
            ks.press_time = 0.0
            ks.tap_count = 0
            self._reset_recording_state_locked()
            if was_recording:
                hold_seconds = max(0.0, timestamp - record_start_time)
                return (hold_seconds, rec_mode, output_target, skip_llm)
            return None

        return None

    def _register_tap_locked(self, key: str, ks: _KeyState) -> None:
        ks.press_time = 0.0
        ks.tap_count += 1
        triple_press_keys = self.triple_press_keys or DEFAULT_TRIPLE_PRESS_KEYS
        max_taps = 3 if key in triple_press_keys else 2
        if ks.tap_count >= max_taps:
            ks.phase = _Phase.IDLE
            ks.tap_count = 0
            return

        ks.phase = _Phase.WAITING_NEXT
        timer = threading.Timer(
            self.double_press_window_seconds,
            self._on_tap_timeout,
            args=[key],
        )
        timer.daemon = True
        ks.timer = timer
        timer.start()

    def _schedule_hold_timer_locked(self, key: str, ks: _KeyState) -> None:
        self._cancel_key_timer_locked(ks)
        hold_delay = self._hold_delay_for_tap_count(key, ks.tap_count)
        timer = threading.Timer(hold_delay, self._on_hold_ready, args=[key])
        timer.daemon = True
        ks.timer = timer
        timer.start()

    def _hold_delay_for_tap_count(self, key: str, tap_count: int) -> float:
        triple_press_keys = self.triple_press_keys or DEFAULT_TRIPLE_PRESS_KEYS
        if tap_count == 1 and key not in triple_press_keys:
            return max(0.0, self.start_delay_seconds)
        return max(self.start_delay_seconds, self.first_press_max_seconds)

    def _resolve_hold_action(self, key: str, tap_count: int) -> tuple[str, str, bool] | None:
        key_modes = self.key_modes or DEFAULT_KEY_MODES
        triple_press_keys = self.triple_press_keys or DEFAULT_TRIPLE_PRESS_KEYS
        if tap_count == 0:
            return (key_modes[key], "both", key in triple_press_keys)
        if tap_count == 1:
            return (key_modes[key], "clipboard", False)
        if tap_count == 2 and key in triple_press_keys:
            return (key_modes[key], "both", False)
        return None

    def _start_recording_locked(self) -> tuple[str, str, bool] | None:
        if self._recording_key is None or self._recording_started:
            return None
        self._recording_started = True
        self._record_start_time = time.monotonic()
        return (self._recording_mode, self._recording_output_target, self._recording_skip_llm)

    def _on_hold_ready(self, key: str) -> None:
        start_info: tuple[str, str, bool] | None = None
        with self._lock:
            ks = self._keys.get(key)
            if ks is None:
                return
            ks.timer = None
            if ks.phase != _Phase.HELD:
                return
            action = self._resolve_hold_action(key, ks.tap_count)
            if action is None:
                ks.phase = _Phase.IDLE
                ks.press_time = 0.0
                ks.tap_count = 0
                return
            ks.phase = _Phase.RECORDING
            self._recording_key = key
            self._recording_mode = action[0]
            self._recording_output_target = action[1]
            self._recording_skip_llm = action[2]
            self._record_start_time = 0.0
            self._recording_started = False
            start_info = self._start_recording_locked()
        if start_info is not None:
            self.on_record_start(start_info[0], start_info[1], start_info[2])

    def _on_tap_timeout(self, key: str) -> None:
        with self._lock:
            ks = self._keys.get(key)
            if ks is not None and ks.phase == _Phase.WAITING_NEXT:
                ks.timer = None
                ks.phase = _Phase.IDLE
                ks.tap_count = 0
                ks.press_time = 0.0

    def enable_mode(self, mode: str, enabled: bool) -> None:
        with self._lock:
            if enabled:
                self._disabled_modes.discard(mode)
            else:
                self._disabled_modes.add(mode)
                ks = None
                for k, m in (self.key_modes or DEFAULT_KEY_MODES).items():
                    if m == mode:
                        ks = self._keys.get(k)
                        break
                if ks is not None and ks.phase in (_Phase.HELD, _Phase.WAITING_NEXT):
                    self._cancel_key_timer_locked(ks)
                    ks.phase = _Phase.IDLE
                    ks.tap_count = 0
                    ks.press_time = 0.0
