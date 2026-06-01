from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.llm import TranscriptCleaner, resolve_api_key


class ResolveApiKeyTests(unittest.TestCase):
    def test_explicit_api_key_wins(self) -> None:
        with patch.dict(os.environ, {"SPEECHTOTEXT_VLLM_API_KEY": "env-key", "OPENAI_API_KEY": "openai-key"}, clear=False):
            self.assertEqual(resolve_api_key(" explicit-key "), "explicit-key")

    def test_custom_env_var_takes_precedence(self) -> None:
        with patch.dict(os.environ, {"SPEECHTOTEXT_VLLM_API_KEY": "custom-key", "OPENAI_API_KEY": "openai-key"}, clear=False):
            self.assertEqual(resolve_api_key(None), "custom-key")

    def test_local_default_is_used_when_no_key_exists(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_api_key(None), "local")


class TranscriptCleanerTests(unittest.TestCase):
    def test_cleaner_builds_openai_client_with_resolved_api_key(self) -> None:
        with patch("app.llm.OpenAI") as openai_cls, patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}, clear=True):
            TranscriptCleaner(
                base_url="https://example.test/v1",
                api_key=None,
                model_name="provider/model",
                restructure_prompt="clean",
                answer_prompt="answer",
            )

        openai_cls.assert_called_once_with(base_url="https://example.test/v1", api_key="env-key", timeout=60.0)


if __name__ == "__main__":
    unittest.main()

