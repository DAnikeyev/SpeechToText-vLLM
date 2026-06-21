"""Polls config.json for external changes and applies them at runtime."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from app.config import AppConfig, load_config


class ConfigWatcher:
    """Watches ``config_path`` for mtime changes and applies reloaded config.

    - ``get_current`` returns the live ``AppConfig`` (for change detection).
    - ``apply`` receives a freshly loaded ``AppConfig`` and pushes it to the app
      (rebuilding collaborators and refreshing the tray menu).
    """

    def __init__(
        self,
        config_path: Path,
        get_current: Callable[[], AppConfig],
        apply: Callable[[AppConfig], None],
        logger: logging.Logger,
    ) -> None:
        self._config_path = config_path
        self._get_current = get_current
        self._apply = apply
        self._logger = logger
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._mtime_ns = self._get_mtime_ns()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="config-reload-watcher"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def mark_current(self) -> None:
        """Reset the baseline mtime to the file's current value.

        Call after writing the config ourselves so the watcher does not treat
        our own write as an external change to reload.
        """
        self._mtime_ns = self._get_mtime_ns()

    def reload_if_needed(self) -> bool:
        current_mtime_ns = self._get_mtime_ns()
        if current_mtime_ns is None or current_mtime_ns == self._mtime_ns:
            return False

        try:
            updated_config = load_config(self._config_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._logger.warning("Config reload skipped; file is not ready yet: %s", exc)
            return False

        self._mtime_ns = current_mtime_ns
        if updated_config.to_dict() == self._get_current().to_dict():
            return False

        self._apply(updated_config)
        return True

    def _loop(self) -> None:
        while not self._stop.wait(timeout=1.0):
            self.reload_if_needed()

    def _get_mtime_ns(self) -> int | None:
        try:
            return self._config_path.stat().st_mtime_ns
        except OSError:
            return None
