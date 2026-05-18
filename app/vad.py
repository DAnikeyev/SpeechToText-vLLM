from __future__ import annotations

import numpy as np

from app.audio import chunk_audio

try:
    import webrtcvad
except Exception:  # pragma: no cover - optional at import time
    webrtcvad = None


class VoiceActivityTrimmer:
    def __init__(self, sample_rate: int = 16_000, mode: int = 2, frame_ms: int = 30) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_size = int(sample_rate * frame_ms / 1000)
        self.vad = webrtcvad.Vad(mode) if webrtcvad is not None else None

    def trim(self, pcm16: np.ndarray) -> np.ndarray:
        if pcm16.size == 0:
            return pcm16
        if self.vad is None:
            return pcm16

        voiced_flags: list[bool] = []
        frames: list[np.ndarray] = []
        for frame in chunk_audio(pcm16, self.frame_size):
            speech = self.vad.is_speech(frame.tobytes(), self.sample_rate)
            voiced_flags.append(speech)
            frames.append(frame)

        if not voiced_flags:
            return np.zeros((0,), dtype=np.int16)

        voiced_count = sum(voiced_flags)
        if voiced_count == 0 or voiced_count / len(voiced_flags) < 0.1:
            return np.zeros((0,), dtype=np.int16)

        voiced_indices = [i for i, flag in enumerate(voiced_flags) if flag]
        if not voiced_indices:
            return np.zeros((0,), dtype=np.int16)
        first = voiced_indices[0]
        last = voiced_indices[-1]
        return np.concatenate(frames[first : last + 1])
