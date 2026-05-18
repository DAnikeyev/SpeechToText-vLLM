from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from app.audio import AudioRecorder

try:
    from faster_whisper import WhisperModel
except Exception:  # pragma: no cover - optional at import time
    WhisperModel = None


class WhisperTranscriber:
    def __init__(self, model_name: str = "medium", language_mode: str = "auto") -> None:
        self.model_name = model_name
        self.language_mode = language_mode
        self.model = None

    def load(self) -> None:
        if self.model is not None:
            return
        if WhisperModel is None:
            raise RuntimeError("faster-whisper is required for transcription")
        self.model = WhisperModel(self.model_name, device="cpu", compute_type="int8")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16_000) -> str:
        if audio.size == 0:
            return ""
        self.load()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            AudioRecorder(sample_rate=sample_rate).save_wav(audio, path)
            kwargs = {}
            if self.language_mode.lower() != "auto":
                kwargs["language"] = self.language_mode
            segments, _ = self.model.transcribe(str(path), **kwargs)
            return "".join(segment.text for segment in segments).strip()
        finally:
            path.unlink(missing_ok=True)
