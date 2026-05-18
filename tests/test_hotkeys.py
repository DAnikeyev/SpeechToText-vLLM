from __future__ import annotations

import time
import unittest

from app.hotkeys import CtrlHoldTracker


class HotkeyTrackerTests(unittest.TestCase):
    def test_short_hold_is_not_forwarded_when_recording_never_started(self) -> None:
        starts = []
        stops = []
        tracker = CtrlHoldTracker(
            on_record_start=lambda: starts.append(True),
            on_record_stop=lambda hold: stops.append(hold),
            min_hold_seconds=2.0,
            start_delay_seconds=0.2,
        )
        t0 = 100.0
        tracker.handle_ctrl_event("left ctrl", "down", t0)
        tracker.handle_ctrl_event("left ctrl", "up", t0 + 0.1)
        self.assertEqual(starts, [])
        self.assertEqual(stops, [])

    def test_hold_after_delay_stops_with_duration(self) -> None:
        starts = []
        stops = []
        tracker = CtrlHoldTracker(
            on_record_start=lambda: starts.append(True),
            on_record_stop=lambda hold: stops.append(hold),
            min_hold_seconds=2.0,
            start_delay_seconds=0.01,
        )
        t0 = time.monotonic()
        tracker.handle_ctrl_event("left ctrl", "down", t0)
        time.sleep(0.03)
        tracker.handle_ctrl_event("left ctrl", "up", t0 + 2.2)

        self.assertEqual(len(starts), 1)
        self.assertEqual(len(stops), 1)
        self.assertGreaterEqual(stops[0], 2.2)


if __name__ == "__main__":
    unittest.main()
