from __future__ import annotations

import tempfile
import wave
from pathlib import Path

import numpy as np

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
            self._save_wav(audio, path, sample_rate=sample_rate)
            kwargs = {}
            if self.language_mode.lower() != "auto":
                kwargs["language"] = self.language_mode
            segments, _ = self.model.transcribe(str(path), **kwargs)
            return "".join(segment.text for segment in segments).strip()
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def _save_wav(audio: np.ndarray, path: Path, sample_rate: int) -> None:
        clipped = np.clip(audio, -1.0, 1.0)
        pcm16 = (clipped * 32767).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm16.tobytes())
