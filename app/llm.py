from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from openai import OpenAI


def fetch_model_names(
    base_url: str,
    api_key: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[str]:
    """Return a list of model IDs available on the OpenAI-compatible server.

    Raises on connection/HTTP errors so callers can display the failure reason.
    """
    client = OpenAI(base_url=base_url, api_key=resolve_api_key(api_key), timeout=timeout_seconds)
    response = client.models.list()
    return [m.id for m in response.data]


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
        self._base_url = base_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self.model_name = model_name
        self.restructure_prompt = restructure_prompt
        self.answer_prompt = answer_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_body = extra_body
        self.strict_model_name_match = strict_model_name_match
        self.logger = logging.getLogger(__name__)
        self.client = self._build_client()
        self._active_stream: Any = None
        self._stream_lock = threading.Lock()

    def _build_client(self) -> OpenAI:
        return OpenAI(
            base_url=self._base_url,
            api_key=resolve_api_key(self._api_key),
            timeout=self._timeout_seconds,
        )

    def reconfigure(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_name: str,
        restructure_prompt: str,
        answer_prompt: str,
        temperature: float,
        max_tokens: int,
        timeout_seconds: float,
        extra_body: dict[str, Any] | None,
        strict_model_name_match: bool,
    ) -> None:
        """Apply new settings in place, rebuilding the HTTP client only when a
        connection-affecting field changes.

        Mutating in place (rather than swapping the whole object) avoids handing
        a half-rebuilt cleaner to the worker/monitor threads mid-request.
        """
        connection_changed = (
            base_url != self._base_url
            or api_key != self._api_key
            or timeout_seconds != self._timeout_seconds
        )
        self._base_url = base_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self.model_name = model_name
        self.restructure_prompt = restructure_prompt
        self.answer_prompt = answer_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_body = extra_body
        self.strict_model_name_match = strict_model_name_match
        if connection_changed:
            self.client = self._build_client()

    def is_model_available(self) -> bool:
        response = self.client.models.list()
        model_found = False
        for model in response.data:
            if self.strict_model_name_match:
                if model.id == self.model_name:
                    model_found = True
                    break
            else:
                m_name = self.model_name.lower()
                s_name = model.id.lower()
                if m_name in s_name or s_name in m_name:
                    model_found = True
                    break
        if not model_found:
            return False

        probe = self.client.chat.completions.create(
            **self._build_completion_kwargs(
                system_prompt="Reply with OK.",
                user_text="ping",
                temperature=0.0,
                max_tokens=1,
            )
        )
        return bool(getattr(probe, "choices", None))

    def clean(
        self,
        raw_text: str,
        language: str | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> str:
        return self._generate(self.restructure_prompt, raw_text, language, is_cancelled)

    def answer(
        self,
        raw_text: str,
        language: str | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> str:
        return self._generate(self.answer_prompt, raw_text, language, is_cancelled)

    def abort(self) -> None:
        """Close the in-flight streaming request, if any.

        Safe to call from another thread (e.g. the hotkey thread on cancel).
        Closing the underlying response interrupts the blocked read in the
        worker thread so the pipeline can wind down promptly instead of waiting
        out the full request timeout.
        """
        with self._stream_lock:
            stream = self._active_stream
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.close()

    def _build_completion_kwargs(
        self,
        *,
        system_prompt: str,
        user_text: str,
        language: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if language:
            user_text = f"[Respond in {language}]\n\n{user_text}"

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        }
        if self.extra_body is not None:
            kwargs["extra_body"] = self.extra_body
        return kwargs

    def _generate(
        self,
        system_prompt: str,
        user_text: str,
        language: str | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> str:
        if not user_text.strip():
            return ""
        kwargs = self._build_completion_kwargs(
            system_prompt=system_prompt, user_text=user_text, language=language
        )
        # Stream so the worker thread can (a) see incremental progress on slow
        # local servers and (b) be interrupted mid-request by abort() instead of
        # blocking until the full response is generated or the timeout fires.
        kwargs["stream"] = True
        start = time.monotonic()
        stream = self.client.chat.completions.create(**kwargs)
        with self._stream_lock:
            self._active_stream = stream
        parts: list[str] = []
        try:
            for chunk in stream:
                if is_cancelled is not None and is_cancelled():
                    self.logger.info("LLM stream cancelled by user")
                    return ""
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = getattr(choices[0].delta, "content", None)
                if delta:
                    parts.append(delta)
        except Exception:
            # abort() closes the socket, which surfaces here as a connection
            # error. Treat a cancellation as a clean stop rather than a failure
            # (don't let it mark the LLM unavailable).
            if is_cancelled is not None and is_cancelled():
                self.logger.info("LLM stream cancelled by user")
                return ""
            raise
        finally:
            with self._stream_lock:
                self._active_stream = None
            with contextlib.suppress(Exception):
                stream.close()
        content = "".join(parts).strip()
        elapsed = time.monotonic() - start
        self.logger.info(
            "LLM request took %.3f seconds (response length: %d characters)",
            elapsed,
            len(content),
        )
        return content
