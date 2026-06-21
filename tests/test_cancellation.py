from __future__ import annotations

import queue
import unittest

from app.cancellation import CancellationCoordinator


class CancellationCoordinatorTests(unittest.TestCase):
    def test_current_generation_is_not_cancelled(self) -> None:
        coord = CancellationCoordinator()
        self.assertFalse(coord.is_cancelled(coord.generation()))

    def test_request_cancel_bumps_generation_and_drains_queue(self) -> None:
        coord = CancellationCoordinator()
        job_queue: queue.Queue[object] = queue.Queue()
        job_queue.put_nowait("a")
        job_queue.put_nowait("b")
        stale = coord.generation()

        was_processing, drained = coord.request_cancel(job_queue)

        self.assertEqual(drained, 2)
        self.assertFalse(was_processing)
        self.assertTrue(job_queue.empty())
        self.assertNotEqual(coord.generation(), stale)
        self.assertTrue(coord.is_cancelled(stale))

    def test_request_cancel_reports_in_flight_processing(self) -> None:
        coord = CancellationCoordinator()
        coord.begin(7)
        was_processing, drained = coord.request_cancel(queue.Queue())
        self.assertTrue(was_processing)
        self.assertEqual(drained, 0)

    def test_begin_and_end_track_processing_generation(self) -> None:
        coord = CancellationCoordinator()
        self.assertIsNone(coord.processing_generation)
        coord.begin(3)
        self.assertEqual(coord.processing_generation, 3)
        coord.end()
        self.assertIsNone(coord.processing_generation)


if __name__ == "__main__":
    unittest.main()
