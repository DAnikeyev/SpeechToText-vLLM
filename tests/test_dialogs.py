from __future__ import annotations

import unittest

from app.dialogs import normalize_llm_url


class NormalizeLlmUrlTests(unittest.TestCase):
    def test_empty_or_whitespace_returns_empty_string(self) -> None:
        self.assertEqual(normalize_llm_url(""), "")
        self.assertEqual(normalize_llm_url("   "), "")

    def test_appends_v1_when_missing(self) -> None:
        self.assertEqual(normalize_llm_url("http://localhost:8000"), "http://localhost:8000/v1")
        self.assertEqual(
            normalize_llm_url("https://openrouter.ai/api"), "https://openrouter.ai/api/v1"
        )

    def test_does_not_double_append_v1(self) -> None:
        self.assertEqual(normalize_llm_url("http://localhost:8000/v1"), "http://localhost:8000/v1")

    def test_strips_trailing_slash_before_appending_v1(self) -> None:
        self.assertEqual(
            normalize_llm_url("https://openrouter.ai/api/"), "https://openrouter.ai/api/v1"
        )

    def test_strips_surrounding_whitespace(self) -> None:
        self.assertEqual(normalize_llm_url("  http://localhost:8000  "), "http://localhost:8000/v1")

    def test_preserves_query_and_fragment(self) -> None:
        self.assertEqual(
            normalize_llm_url("http://localhost:8000?key=1#frag"),
            "http://localhost:8000/v1?key=1#frag",
        )

    # --- Scheme-less URL handling ---

    def test_schemeless_url_gets_http_prefix(self) -> None:
        self.assertEqual(normalize_llm_url("localhost:8000"), "http://localhost:8000/v1")
        self.assertEqual(normalize_llm_url("127.0.0.1:8512"), "http://127.0.0.1:8512/v1")

    def test_schemeless_url_with_path(self) -> None:
        self.assertEqual(normalize_llm_url("localhost:8000/api"), "http://localhost:8000/api/v1")

    def test_https_explicitly_preserved(self) -> None:
        self.assertEqual(
            normalize_llm_url("https://localhost:8512/v1"), "https://localhost:8512/v1"
        )
        self.assertEqual(normalize_llm_url("https://localhost:8512"), "https://localhost:8512/v1")


if __name__ == "__main__":
    unittest.main()
