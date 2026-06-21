from __future__ import annotations

import logging
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

from app.audio import float_to_pcm16
from app.cuda_bootstrap import ensure_cuda_libs_on_path
from app.platform import get_platform_services

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover - optional at import time
    WhisperModel = None


def _try_cuda() -> bool:
    """Probe whether CTranslate2 can actually use CUDA on this machine."""
    if WhisperModel is None:
        return False
    ensure_cuda_libs_on_path()
    try:
        import ctranslate2

        # get_supported_compute_types raises if CUDA is not functional.
        _ = ctranslate2.get_supported_compute_types("cuda")
        return True
    except Exception:
        return False


def detect_keyboard_language() -> str | None:
    """Detect the active input language using the current platform backend."""
    try:
        return get_platform_services().detect_input_language()
    except Exception:
        return None


class WhisperTranscriber:
    def __init__(
        self,
        model_name: str = "small",
        language_mode: str = "auto",
        device: str = "auto",
        compute_type: str = "float16",
    ) -> None:
        self.model_name = model_name
        self.language_mode = language_mode
        self.device = device
        self.compute_type = compute_type
        self.model: WhisperModel | None = None
        self.last_language: str | None = None
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _default_cpu_compute_type() -> str:
        return "int8"

    def load(self) -> None:
        if self.model is not None:
            return
        if WhisperModel is None:
            raise RuntimeError("faster-whisper is required for transcription")

        effective_device = self.device
        effective_compute_type = self.compute_type

        if effective_device == "auto":
            if _try_cuda():
                effective_device = "cuda"
                effective_compute_type = self.compute_type
            else:
                effective_device = "cpu"
                effective_compute_type = self._default_cpu_compute_type()

        if effective_device == "cuda" and not _try_cuda():
            self.logger.warning(
                "CUDA not available (cublas DLLs missing or incompatible). "
                "Falling back to CPU with a safe compute profile."
            )
            effective_device = "cpu"
            effective_compute_type = self._default_cpu_compute_type()

        # Prefer the configured compute type; fall back to int8 if it fails
        # (e.g. GPU float16 unavailable). CPU already resolves to int8 above.
        compute_candidates: list[str] = [effective_compute_type]
        if effective_compute_type != "int8":
            compute_candidates.append("int8")

        last_error: Exception | None = None
        for candidate in compute_candidates:
            self.logger.info(
                "Loading Whisper model=%s device=%s compute_type=%s",
                self.model_name,
                effective_device,
                candidate,
            )
            try:
                self.model = WhisperModel(
                    self.model_name,
                    device=effective_device,
                    compute_type=candidate,
                )
                return
            except Exception as exc:
                last_error = exc
                self.logger.warning(
                    "Failed to load Whisper with compute_type=%s (%s)",
                    candidate,
                    exc,
                )

        raise RuntimeError(
            "Unable to load faster-whisper model with any safe profile"
        ) from last_error

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16_000) -> str:
        if audio.size == 0:
            return ""
        self.load()
        model = self.model
        assert model is not None
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            self._save_wav(audio, path, sample_rate=sample_rate)
            kwargs = {}
            language: str | None = self.language_mode.lower()
            if language == "auto-detected":
                detected = detect_keyboard_language()
                language = detected if detected else None
            elif language == "auto":
                language = None
            self.last_language = language
            if self.last_language is not None:
                kwargs["language"] = self.last_language
            start = time.monotonic()
            segments, _ = model.transcribe(str(path), **kwargs)
            elapsed = time.monotonic() - start
            text = "".join(segment.text for segment in segments).strip()
            self.logger.info("Text recognition took %.3f seconds", elapsed)
            return text
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def _save_wav(audio: np.ndarray, path: Path, sample_rate: int) -> None:
        pcm16 = float_to_pcm16(audio)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm16.tobytes())
