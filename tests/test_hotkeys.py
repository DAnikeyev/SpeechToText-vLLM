from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from app.hotkeys import DoublePressHotkeyTracker


class _FakeBackend:
    def __init__(self) -> None:
        self.started_with = None
        self.stop_calls = 0

    def start(self, handler) -> None:
        self.started_with = handler

    def stop(self) -> None:
        self.stop_calls += 1


def _make_event(name: str, event_type: str) -> MagicMock:
    ev = MagicMock()
    ev.name = name
    ev.event_type = event_type
    return ev


class DoublePressHotkeyTrackerTests(unittest.TestCase):
    def test_default_bindings_do_not_depend_on_platform_services(self) -> None:
        services = SimpleNamespace(
            create_hotkey_backend=lambda: _FakeBackend(),
            key_modes={"right cmd": "restructure", "right shift": "answer"},
            triple_press_raw_keys={"right cmd"},
        )

        with patch("app.hotkeys.get_platform_services", return_value=services):
            tracker = DoublePressHotkeyTracker(
                on_record_start=lambda mode, output, skip_llm: None,
                on_record_stop=lambda hold, mode, output, skip_llm: None,
                min_hold_seconds=2.0,
            )

        self.assertEqual(tracker.key_modes, {"right ctrl": "restructure", "right shift": "answer"})
        self.assertEqual(tracker.triple_press_raw_keys, {"right ctrl"})

    def test_start_and_stop_use_injected_backend(self) -> None:
        backend = _FakeBackend()
        tracker = DoublePressHotkeyTracker(
            on_record_start=lambda mode, output, skip_llm: None,
            on_record_stop=lambda hold, mode, output, skip_llm: None,
            min_hold_seconds=2.0,
            backend_factory=lambda: backend,
        )

        tracker.start()
        self.assertIs(tracker._backend, backend)
        self.assertTrue(callable(backend.started_with))

        tracker.stop()
        self.assertIsNone(tracker._backend)
        self.assertEqual(backend.stop_calls, 1)

    def test_start_is_idempotent_when_backend_is_already_running(self) -> None:
        backends: list[_FakeBackend] = []

        def _factory() -> _FakeBackend:
            backend = _FakeBackend()
            backends.append(backend)
            return backend

        tracker = DoublePressHotkeyTracker(
            on_record_start=lambda mode, output, skip_llm: None,
            on_record_stop=lambda hold, mode, output, skip_llm: None,
            min_hold_seconds=2.0,
            backend_factory=_factory,
        )

        tracker.start()
        tracker.start()

        self.assertEqual(len(backends), 1)

    def test_single_tap_does_not_record(self) -> None:
        starts: list[tuple[str, str, bool]] = []
        stops: list[tuple[float, str, str, bool]] = []
        tracker = DoublePressHotkeyTracker(
            on_record_start=lambda mode, output, skip_llm: starts.append((mode, output, skip_llm)),
            on_record_stop=lambda hold, mode, output, skip_llm: stops.append((hold, mode, output, skip_llm)),
            min_hold_seconds=2.0,
            start_delay_seconds=0.0,
            double_press_window_seconds=0.5,
            first_press_max_seconds=0.3,
        )
        t0 = time.monotonic()
        tracker._process("right ctrl", "down", t0)
        tracker._process("right ctrl", "up", t0 + 0.1)
        self.assertEqual(starts, [])
        self.assertEqual(stops, [])

    def test_double_press_and_hold_starts_recording(self) -> None:
        starts: list[tuple[str, str, bool]] = []
        stops: list[tuple[float, str, str, bool]] = []
        tracker = DoublePressHotkeyTracker(
            on_record_start=lambda mode, output, skip_llm: starts.append((mode, output, skip_llm)),
            on_record_stop=lambda hold, mode, output, skip_llm: stops.append((hold, mode, output, skip_llm)),
            min_hold_seconds=2.0,
            start_delay_seconds=0.0,
            first_press_max_seconds=0.05,
        )
        t0 = time.monotonic()
        tracker._process("right ctrl", "down", t0)
        tracker._process("right ctrl", "up", t0 + 0.02)
        tracker._process("right ctrl", "down", t0 + 0.08)
        time.sleep(0.2)

        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0], ("restructure", "clipboard", False))

        tracker._process("right ctrl", "up", t0 + 2.5)
        self.assertEqual(len(stops), 1)
        self.assertGreaterEqual(stops[0][0], 2.0)
        self.assertEqual(stops[0][1], "restructure")
        self.assertEqual(stops[0][2], "clipboard")
        self.assertFalse(stops[0][3])

    def test_triple_press_right_ctrl_uses_raw_clipboard_mode(self) -> None:
        starts: list[tuple[str, str, bool]] = []
        stops: list[tuple[float, str, str, bool]] = []
        tracker = DoublePressHotkeyTracker(
            on_record_start=lambda mode, output, skip_llm: starts.append((mode, output, skip_llm)),
            on_record_stop=lambda hold, mode, output, skip_llm: stops.append((hold, mode, output, skip_llm)),
            min_hold_seconds=2.0,
            start_delay_seconds=0.0,
            first_press_max_seconds=0.05,
        )
        t0 = time.monotonic()
        tracker._process("right ctrl", "down", t0)
        tracker._process("right ctrl", "up", t0 + 0.02)
        tracker._process("right ctrl", "down", t0 + 0.08)
        tracker._process("right ctrl", "up", t0 + 0.10)
        tracker._process("right ctrl", "down", t0 + 0.16)
        time.sleep(0.2)

        self.assertEqual(starts, [("restructure", "both", True)])

        tracker._process("right ctrl", "up", t0 + 2.5)
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0][1], "restructure")
        self.assertEqual(stops[0][2], "both")
        self.assertTrue(stops[0][3])

    def test_single_hold_starts_insert_recording(self) -> None:
        starts: list[tuple[str, str, bool]] = []
        stops: list[tuple[float, str, str, bool]] = []
        tracker = DoublePressHotkeyTracker(
            on_record_start=lambda mode, output, skip_llm: starts.append((mode, output, skip_llm)),
            on_record_stop=lambda hold, mode, output, skip_llm: stops.append((hold, mode, output, skip_llm)),
            min_hold_seconds=2.0,
            start_delay_seconds=0.0,
            first_press_max_seconds=0.05,
        )
        t0 = time.monotonic()
        tracker._process("right ctrl", "down", t0)
        time.sleep(0.2)

        self.assertEqual(starts, [("restructure", "both", False)])

        tracker._process("right ctrl", "up", t0 + 2.2)
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0][1], "restructure")
        self.assertEqual(stops[0][2], "both")
        self.assertFalse(stops[0][3])

    def test_right_shift_uses_answer_mode(self) -> None:
        starts: list[tuple[str, str, bool]] = []
        tracker = DoublePressHotkeyTracker(
            on_record_start=lambda mode, output, skip_llm: starts.append((mode, output, skip_llm)),
            on_record_stop=lambda hold, mode, output, skip_llm: None,
            min_hold_seconds=2.0,
            start_delay_seconds=0.0,
        )
        t0 = time.monotonic()
        tracker._process("right shift", "down", t0)
        tracker._process("right shift", "up", t0 + 0.1)
        tracker._process("right shift", "down", t0 + 0.15)
        time.sleep(0.2)

        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0], ("answer", "clipboard", False))

    def test_disabled_mode_ignored_via_handle_event(self) -> None:
        starts: list[tuple[str, str, bool]] = []
        tracker = DoublePressHotkeyTracker(
            on_record_start=lambda mode, output, skip_llm: starts.append((mode, output, skip_llm)),
            on_record_stop=lambda hold, mode, output, skip_llm: None,
            min_hold_seconds=2.0,
            start_delay_seconds=0.0,
            first_press_max_seconds=0.05,
        )
        tracker.enable_mode("restructure", False)

        tracker._handle_event(_make_event("right ctrl", "down"))
        tracker._handle_event(_make_event("right ctrl", "up"))
        self.assertEqual(starts, [])

        tracker.enable_mode("restructure", True)
        tracker._handle_event(_make_event("right ctrl", "down"))
        tracker._handle_event(_make_event("right ctrl", "up"))
        tracker._handle_event(_make_event("right ctrl", "down"))
        time.sleep(0.2)
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0], ("restructure", "clipboard", False))


if __name__ == "__main__":
    unittest.main()