from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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

    def test_is_model_available_requires_successful_completion_probe(self) -> None:
        cleaner = TranscriptCleaner(
            base_url="https://example.test/v1",
            api_key="provider-key",
            model_name="provider/model",
            restructure_prompt="clean",
            answer_prompt="answer",
        )
        cleaner.client = SimpleNamespace(
            models=SimpleNamespace(list=MagicMock(return_value=SimpleNamespace(data=[SimpleNamespace(id="provider/model")]))) ,
            chat=SimpleNamespace(completions=SimpleNamespace(create=MagicMock(side_effect=RuntimeError("401 unauthorized")))),
        )

        with self.assertRaisesRegex(RuntimeError, "401 unauthorized"):
            cleaner.is_model_available()

    def test_is_model_available_uses_probe_completion_after_model_match(self) -> None:
        cleaner = TranscriptCleaner(
            base_url="https://example.test/v1",
            api_key="provider-key",
            model_name="provider/model",
            restructure_prompt="clean",
            answer_prompt="answer",
            extra_body={"foo": "bar"},
        )
        create = MagicMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))]))
        cleaner.client = SimpleNamespace(
            models=SimpleNamespace(list=MagicMock(return_value=SimpleNamespace(data=[SimpleNamespace(id="provider/model")]))) ,
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

        self.assertTrue(cleaner.is_model_available())
        create.assert_called_once_with(
            model="provider/model",
            temperature=0.0,
            max_tokens=1,
            messages=[
                {"role": "system", "content": "Reply with OK."},
                {"role": "user", "content": "ping"},
            ],
            extra_body={"foo": "bar"},
        )

    def test_is_model_available_returns_false_when_model_is_missing(self) -> None:
        cleaner = TranscriptCleaner(
            base_url="https://example.test/v1",
            api_key="provider-key",
            model_name="provider/model",
            restructure_prompt="clean",
            answer_prompt="answer",
        )
        create = MagicMock()
        cleaner.client = SimpleNamespace(
            models=SimpleNamespace(list=MagicMock(return_value=SimpleNamespace(data=[SimpleNamespace(id="other/model")]))) ,
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

        self.assertFalse(cleaner.is_model_available())
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()


