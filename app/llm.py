from __future__ import annotations

import os
from typing import Any

from openai import OpenAI


def resolve_api_key(api_key: str | None = None) -> str:
    if api_key is not None and api_key.strip():
        return api_key.strip()

    for env_name in ("SPEECHTOTEXT_VLLM_API_KEY", "OPENAI_API_KEY"):
        value = os.getenv(env_name)
        if value is not None and value.strip():
            return value.strip()

    return "local"


class TranscriptCleaner:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model_name: str,
        restructure_prompt: str,
        answer_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 512,
        timeout_seconds: float = 60.0,
        extra_body: dict[str, Any] | None = None,
        strict_model_name_match: bool = True,
    ) -> None:
        self.client = OpenAI(base_url=base_url, api_key=resolve_api_key(api_key), timeout=timeout_seconds)
        self.model_name = model_name
        self.restructure_prompt = restructure_prompt
        self.answer_prompt = answer_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_body = extra_body
        self.strict_model_name_match = strict_model_name_match

    def is_model_available(self) -> bool:
        response = self.client.models.list()
        for model in response.data:
            if self.strict_model_name_match:
                if model.id == self.model_name:
                    return True
            else:
                m_name = self.model_name.lower()
                s_name = model.id.lower()
                if m_name in s_name or s_name in m_name:
                    return True
        return False

    def clean(self, raw_text: str, language: str | None = None) -> str:
        return self._generate(self.restructure_prompt, raw_text, language)

    def answer(self, raw_text: str, language: str | None = None) -> str:
        return self._generate(self.answer_prompt, raw_text, language)

    def _generate(self, system_prompt: str, user_text: str, language: str | None = None) -> str:
        if not user_text.strip():
            return ""
        if language:
            user_text = f"[Respond in {language}]\n\n{user_text}"
        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        }
        if self.extra_body is not None:
            kwargs["extra_body"] = self.extra_body
        response = self.client.chat.completions.create(**kwargs)
        return (response.choices[0].message.content or "").strip()
