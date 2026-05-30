from __future__ import annotations

from collections import deque
import logging
import threading

from app.platform import current_platform_name


class InMemoryLogHandler(logging.Handler):
    def __init__(self, max_entries: int = 1000) -> None:
        super().__init__()
        self._entries: deque[str] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()
        with self._lock:
            self._entries.append(message)

    def get_entries(self) -> list[str]:
        with self._lock:
            return list(self._entries)


class PlatformContextFilter(logging.Filter):
    def __init__(self, platform_name: str) -> None:
        super().__init__()
        self._platform_name = platform_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.platform_name = self._platform_name
        return True


def setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("dictation")
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    platform_filter = PlatformContextFilter(current_platform_name())
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(platform_name)s | %(message)s")

    handler = logging.StreamHandler()
    handler.addFilter(platform_filter)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    memory_handler = InMemoryLogHandler(max_entries=1000)
    memory_handler.addFilter(platform_filter)
    memory_handler.setFormatter(formatter)
    logger.addHandler(memory_handler)
    logger.memory_handler = memory_handler  # type: ignore[attr-defined]

    logger.propagate = False
    return logger
