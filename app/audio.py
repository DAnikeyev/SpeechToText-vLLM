from __future__ import annotations

import wave
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - optional at import time
    sd = None


@dataclass
class AudioRecorder:
    sample_rate: int = 16_000
    channels: int = 1
    dtype: str = "float32"
    device: int | str | None = None

    _stream = None
    _chunks: list[np.ndarray] = field(default_factory=list)

    def list_input_devices(self) -> list[str]:
        if sd is None:
            return []
        devices = sd.query_devices()
        return [d["name"] for d in devices if d.get("max_input_channels", 0) > 0]

    def start(self) -> None:
        if sd is None:
            raise RuntimeError("sounddevice library is required for audio recording")
        self._chunks.clear()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._chunks:
            return np.zeros((0,), dtype=np.float32)
        return np.concatenate(self._chunks, axis=0).astype(np.float32, copy=False)

    def _callback(self, indata, _frames, _time_info, _status) -> None:
        self._chunks.append(indata[:, 0].copy())

    @staticmethod
    def to_pcm16(audio: np.ndarray) -> np.ndarray:
        clipped = np.clip(audio, -1.0, 1.0)
        return (clipped * 32767).astype(np.int16)

    def save_wav(self, audio: np.ndarray, path: str | Path) -> None:
        pcm16 = self.to_pcm16(audio)
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm16.tobytes())


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio))))


def chunk_audio(audio: np.ndarray, frame_size: int) -> Iterable[np.ndarray]:
    for start in range(0, len(audio), frame_size):
        chunk = audio[start : start + frame_size]
        if len(chunk) == frame_size:
            yield chunk
