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
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def list_input_devices(self) -> list[str]:
        if sd is None:
            return []
        devices = sd.query_devices()
        return [d["name"] for d in devices if d.get("max_input_channels", 0) > 0]

    def start(self) -> None:
        if sd is None:
            raise RuntimeError("sounddevice library is required for audio recording")
        with self._lock:
            if self._stream is not None:
                self.stop()
            self._chunks.clear()
            self._stop_event = threading.Event()
            self._reader_thread = None
            self._read_exception = None

            def _on_audio(indata, _frames, _time_info, status) -> None:
                if self._stop_event.is_set():
                    return
                if status:
                    logger.warning("Audio input reported callback status: %s", status)
                if indata is None or len(indata) == 0:
                    return
                try:
                    chunk = np.asarray(indata[:, 0], dtype=np.float32)
                    self._chunks.append(chunk.copy())
                except Exception as exc:
                    self._read_exception = exc
                    self._stop_event.set()

            stream_kwargs = dict(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                blocksize=self.read_block_frames,
                callback=_on_audio,
            )
            try:
                self._stream = sd.InputStream(device=self.device, **stream_kwargs)
            except Exception as exc:
                if self.device is None:
                    raise
                logger.warning(
                    "Failed to open configured microphone device %r (%s); retrying with system default device",
                    self.device,
                    exc,
                )
                self._stream = sd.InputStream(device=None, **stream_kwargs)
            self._stream.start()

    def stop(self) -> np.ndarray:
        with self._lock:
            stream = self._stream
            self._stream = None
            self._reader_thread = None
            self._stop_event.set()

        if stream is not None:
            try:
                stream.stop()
            except Exception:
                logger.debug("Audio stream stop raised during shutdown", exc_info=True)
            try:
                stream.close()
            except Exception:
                logger.debug("Audio stream close raised during shutdown", exc_info=True)

        with self._lock:
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
