from __future__ import annotations

import logging
import threading
import wave
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - optional at import time
    sd = None


logger = logging.getLogger(__name__)


@dataclass
class AudioRecorder:
    sample_rate: int = 16_000
    channels: int = 1
    dtype: str = "float32"
    device: int | str | None = None
    read_block_frames: int = 1024

    _stream = None
    _chunks: list[np.ndarray] = field(default_factory=list)
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _reader_thread: threading.Thread | None = None
    _read_exception: Exception | None = None

    def list_input_devices(self) -> list[str]:
        if sd is None:
            return []
        devices = sd.query_devices()
        return [d["name"] for d in devices if d.get("max_input_channels", 0) > 0]

    def start(self) -> None:
        if sd is None:
            raise RuntimeError("sounddevice library is required for audio recording")
        if self._stream is not None:
            self.stop()
        self._chunks.clear()
        self._stop_event = threading.Event()
        self._reader_thread = None
        self._read_exception = None
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            device=self.device,
        )
        self._stream.start()
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True, name="audio-recorder")
        self._reader_thread.start()

    def stop(self) -> np.ndarray:
        stream = self._stream
        reader_thread = self._reader_thread
        self._stop_event.set()

        if stream is not None:
            try:
                stream.stop()
            except Exception:
                logger.debug("Audio stream stop raised during shutdown", exc_info=True)

        if reader_thread is not None and reader_thread.is_alive():
            reader_thread.join(timeout=1.0)

        if stream is not None:
            try:
                stream.close()
            except Exception:
                logger.debug("Audio stream close raised during shutdown", exc_info=True)

        self._stream = None
        self._reader_thread = None

        if not self._chunks:
            return np.zeros((0,), dtype=np.float32)
        return np.concatenate(self._chunks, axis=0).astype(np.float32, copy=False)

    def _read_loop(self) -> None:
        stream = self._stream
        if stream is None:
            return

        while not self._stop_event.is_set():
            try:
                audio_data, overflowed = stream.read(self.read_block_frames)
            except Exception as exc:
                if self._stop_event.is_set():
                    return
                self._read_exception = exc
                logger.warning("Audio capture read failed: %s", exc)
                self._stop_event.set()
                return

            if overflowed:
                logger.warning("Audio input overflow detected; some captured audio may be missing")

            if audio_data is None or len(audio_data) == 0:
                continue

            chunk = np.asarray(audio_data[:, 0], dtype=np.float32)
            self._chunks.append(chunk.copy())

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
