from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.config import AppConfig, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_load_config_creates_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            cfg = load_config(config_path)
            self.assertIsInstance(cfg, AppConfig)
            self.assertTrue(config_path.exists())
            self.assertEqual(cfg.whisper_model, "medium")

    def test_load_config_ignores_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps({"min_hold_seconds": 3, "unknown": 1}), encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.min_hold_seconds, 3)
            self.assertFalse(hasattr(cfg, "unknown"))

    def test_save_config_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            cfg = AppConfig(model_name="local-model")
            save_config(config_path, cfg)
            loaded = load_config(config_path)
            self.assertEqual(loaded.model_name, "local-model")


if __name__ == "__main__":
    unittest.main()
