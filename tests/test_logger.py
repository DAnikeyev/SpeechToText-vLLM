from __future__ import annotations

import logging
import unittest

from app.logger import InMemoryLogHandler, PlatformContextFilter


class InMemoryLogHandlerTests(unittest.TestCase):
    def test_keeps_only_latest_entries(self) -> None:
        handler = InMemoryLogHandler(max_entries=3)
        handler.setFormatter(logging.Formatter("%(message)s"))

        logger = logging.getLogger("test.in_memory_log_handler")
        logger.handlers = []
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = False

        logger.info("one")
        logger.info("two")
        logger.info("three")
        logger.info("four")

        self.assertEqual(handler.get_entries(), ["two", "three", "four"])

    def test_platform_context_filter_injects_platform_name(self) -> None:
        record = logging.LogRecord(
            name="dictation",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )

        result = PlatformContextFilter("macos").filter(record)

        self.assertTrue(result)
        self.assertEqual(record.platform_name, "macos")


if __name__ == "__main__":
    unittest.main()
