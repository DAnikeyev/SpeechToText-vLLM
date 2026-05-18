from __future__ import annotations

from openai import OpenAI

SYSTEM_PROMPT = """You are a transcription cleanup engine.

Transform raw dictated speech into clean readable text.

Rules:
- preserve meaning exactly
- remove filler words
- improve punctuation
- improve grammar
- preserve technical terminology
- preserve original language
- do not summarize
- do not add information
- output only final cleaned text."""


class TranscriptCleaner:
    def __init__(self, base_url: str, model_name: str, temperature: float = 0.1, max_tokens: int = 512) -> None:
        self.client = OpenAI(base_url=base_url, api_key="local")
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens

    def clean(self, raw_text: str) -> str:
        if not raw_text.strip():
            return ""
        response = self.client.chat.completions.create(
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": raw_text},
            ],
        )
        return (response.choices[0].message.content or "").strip()
