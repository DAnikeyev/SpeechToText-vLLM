from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.config import AppConfig, save_config
from app.config_watcher import ConfigWatcher


def _make_watcher(config_path: Path, current: AppConfig, applied: MagicMock) -> ConfigWatcher:
    return ConfigWatcher(
        config_path=config_path,
        get_current=lambda: current,
        apply=applied,
        logger=MagicMock(),
    )


class ConfigWatcherTests(unittest.TestCase):
    def test_reload_applies_external_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            original = AppConfig()
            updated = AppConfig(model_name="reloaded-model", language_mode="ru")
            save_config(config_path, original)

            applied = MagicMock()
            watcher = _make_watcher(config_path, current=original, applied=applied)

            save_config(config_path, updated)
            changed = watcher.reload_if_needed()

        self.assertTrue(changed)
        applied.assert_called_once()
        applied_config = applied.call_args.args[0]
        self.assertEqual(applied_config.model_name, "reloaded-model")
        self.assertEqual(applied_config.language_mode, "ru")

    def test_reload_skips_invalid_json_until_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            original = AppConfig()
            save_config(config_path, original)

            logger = MagicMock()
            applied = MagicMock()
            watcher = ConfigWatcher(config_path, lambda: original, applied, logger)

            config_path.write_text('{"model_name": ', encoding="utf-8")
            changed = watcher.reload_if_needed()

        self.assertFalse(changed)
        applied.assert_not_called()
        logger.warning.assert_called_once()

    def test_reload_is_noop_when_file_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            original = AppConfig()
            save_config(config_path, original)

            applied = MagicMock()
            watcher = _make_watcher(config_path, current=original, applied=applied)

            changed = watcher.reload_if_needed()

        self.assertFalse(changed)
        applied.assert_not_called()

    def test_mark_current_prevents_reload_of_own_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            original = AppConfig()
            save_config(config_path, original)

            applied = MagicMock()
            watcher = _make_watcher(config_path, current=original, applied=applied)

            # Simulate us writing the same config back to disk.
            save_config(config_path, original)
            watcher.mark_current()
            changed = watcher.reload_if_needed()

        self.assertFalse(changed)
        applied.assert_not_called()


if __name__ == "__main__":
    unittest.main()
