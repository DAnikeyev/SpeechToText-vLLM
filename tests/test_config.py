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
            self.assertEqual(cfg.vllm_url, "https://openrouter.ai/api/v1")
            self.assertIsNone(cfg.llm_api_key)
            self.assertEqual(cfg.model_name, "openai/gpt-oss-120b:free")
            self.assertTrue(cfg.llm_strict_model_name_match)
            self.assertIsNone(cfg.llm_extra_body)
            self.assertEqual(cfg.whisper_model, "small")
            self.assertEqual(cfg.llm_availability_check_interval_seconds, 60.0)

    def test_load_config_ignores_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps({"min_hold_seconds": 3, "unknown": 1}), encoding="utf-8"
            )
            cfg = load_config(config_path)
            self.assertEqual(cfg.min_hold_seconds, 3)
            self.assertFalse(hasattr(cfg, "unknown"))

    def test_save_config_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            cfg = AppConfig(
                model_name="local-model",
                llm_api_key="secret-token",
                llm_availability_check_interval_seconds=90.0,
            )
            save_config(config_path, cfg)
            loaded = load_config(config_path)
            self.assertEqual(loaded.model_name, "local-model")
            self.assertEqual(loaded.llm_api_key, "secret-token")
            self.assertEqual(loaded.llm_availability_check_interval_seconds, 90.0)

    def test_from_dict_uses_defaults_for_missing_fields(self) -> None:
        cfg = AppConfig.from_dict({})
        self.assertEqual(cfg.whisper_model, "small")
        self.assertEqual(cfg.max_tokens, 512)
        self.assertTrue(cfg.llm_strict_model_name_match)
        self.assertIsNone(cfg.llm_extra_body)

    def test_to_dict_contains_all_documented_fields(self) -> None:
        data = AppConfig().to_dict()
        for field in (
            "vllm_url",
            "model_name",
            "whisper_model",
            "language_mode",
            "min_hold_seconds",
            "llm_extra_body",
            "llm_strict_model_name_match",
            "restructure_prompt",
            "answer_prompt",
            "languages",
        ):
            self.assertIn(field, data)

    def test_validate_accepts_default_config(self) -> None:
        AppConfig().validate()  # must not raise

    def test_validate_rejects_out_of_range_values(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(max_tokens=0).validate()
        with self.assertRaises(ValueError):
            AppConfig(temperature=-1).validate()
        with self.assertRaises(ValueError):
            AppConfig(min_hold_seconds=-1).validate()
        with self.assertRaises(ValueError):
            AppConfig(llm_timeout_seconds=0).validate()

    def test_from_dict_validates_loaded_values(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig.from_dict({"max_tokens": 0})


if __name__ == "__main__":
    unittest.main()
