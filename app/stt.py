from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
from app.platform import get_platform_services

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover - optional at import time
    WhisperModel = None


def _ensure_cuda_libs() -> None:
    """Add NVIDIA pip-packaged CUDA libraries to PATH on Windows.

    faster-whisper / CTranslate2 needs cublas64_12.dll etc. at runtime.
    When installed via pip (nvidia-cublas-cu12), the DLLs live inside
    site-packages but are not automatically on PATH.
    """
    if sys.platform != "win32":
        return
    try:
        import nvidia.cublas
        import nvidia.cuda_nvrtc
        import nvidia.cuda_runtime
    except Exception:
        return
    bins = [
        os.path.join(list(nvidia.cublas.__path__)[0], "bin"),
        os.path.join(list(nvidia.cuda_runtime.__path__)[0], "bin"),
        os.path.join(list(nvidia.cuda_nvrtc.__path__)[0], "bin"),
    ]
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep)
    extra = [b for b in bins if b not in parts]
    if extra:
        os.environ["PATH"] = os.pathsep.join(extra + parts)


def _try_cuda() -> bool:
    """Probe whether CTranslate2 can actually use CUDA on this machine."""
    if WhisperModel is None:
        return False
    _ensure_cuda_libs()
    try:
        import ctranslate2
        # get_supported_compute_types raises if CUDA is not functional.
        _ = ctranslate2.get_supported_compute_types("cuda")
        return True
    except Exception:
        return False

AUDIO_MIN = -1.0
AUDIO_MAX = 1.0
PCM16_MAX = 32767


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
        self.model = None
        self.last_language: str | None = None
        self.logger = logging.getLogger(__name__)

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
                effective_compute_type = "int8"

        if effective_device == "cuda" and not _try_cuda():
            self.logger.warning(
                "CUDA not available (cublas DLLs missing or incompatible). "
                "Falling back to CPU with int8."
            )
            effective_device = "cpu"
            effective_compute_type = "int8"

        self.logger.info(
            "Loading Whisper model=%s device=%s compute_type=%s",
            self.model_name,
            effective_device,
            effective_compute_type,
        )
        self.model = WhisperModel(
            self.model_name,
            device=effective_device,
            compute_type=effective_compute_type,
        )

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16_000) -> str:
        if audio.size == 0:
            return ""
        self.load()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            self._save_wav(audio, path, sample_rate=sample_rate)
            kwargs = {}
            language = self.language_mode.lower()
            if language == "auto-detected":
                detected = detect_keyboard_language()
                language = detected if detected else None
            elif language == "auto":
                language = None
            self.last_language = language
            if self.last_language is not None:
                kwargs["language"] = self.last_language
            start = time.monotonic()
            segments, _ = self.model.transcribe(str(path), **kwargs)
            elapsed = time.monotonic() - start
            text = "".join(segment.text for segment in segments).strip()
            self.logger.info("Text recognition took %.3f seconds", elapsed)
            return text
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def _save_wav(audio: np.ndarray, path: Path, sample_rate: int) -> None:
        clipped = np.clip(audio, AUDIO_MIN, AUDIO_MAX)
        pcm16 = (clipped * PCM16_MAX).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm16.tobytes())
