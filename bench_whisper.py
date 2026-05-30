"""Benchmark faster-whisper models on CPU vs GPU for 10-second audio clips."""

from __future__ import annotations

import os
import time
import wave
import tempfile
from pathlib import Path

import numpy as np

try:
    import nvidia.cublas
    import nvidia.cuda_runtime
    import nvidia.cuda_nvrtc

    _cublas_bin = os.path.join(list(nvidia.cublas.__path__)[0], "bin")
    _cudart_bin = os.path.join(list(nvidia.cuda_runtime.__path__)[0], "bin")
    _nvrtc_bin = os.path.join(list(nvidia.cuda_nvrtc.__path__)[0], "bin")
    os.environ["PATH"] = _cublas_bin + ";" + _cudart_bin + ";" + _nvrtc_bin + ";" + os.environ["PATH"]
except Exception:
    pass

from faster_whisper import WhisperModel

SAMPLE_RATE = 16_000
DURATION_SECONDS = 10
MODELS = ["small", "medium"]
DEVICES = [
    ("cpu", "int8"),
    ("cuda", "float16"),
]
NUM_RUNS = 3


def generate_speech_like_audio(duration: float, sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng(42)
    t = np.linspace(0, duration, int(duration * sample_rate), dtype=np.float32)
    signal = np.zeros_like(t)
    for _ in range(12):
        freq = rng.uniform(80, 400)
        amp = rng.uniform(0.02, 0.12)
        phase = rng.uniform(0, 2 * np.pi)
        signal += amp * np.sin(2 * np.pi * freq * t + phase)
    noise = rng.normal(0, 0.02, size=t.shape).astype(np.float32)
    signal = (signal + noise).astype(np.float32)
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak * 0.9
    return signal


def save_temp_wav(audio: np.ndarray, sample_rate: int) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    path = Path(tmp.name)
    tmp.close()
    pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return path


def benchmark(
    model_name: str, device: str, compute_type: str, wav_path: Path
) -> list[float]:
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    times: list[float] = []
    for i in range(NUM_RUNS):
        start = time.perf_counter()
        segments, info = model.transcribe(str(wav_path), language="en")
        _ = list(segments)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print("  run %d/%d: %.3fs" % (i + 1, NUM_RUNS, elapsed))
    del model
    return times


def main() -> None:
    print(
        "Generating %ds speech-like audio at %dHz..."
        % (DURATION_SECONDS, SAMPLE_RATE)
    )
    audio = generate_speech_like_audio(DURATION_SECONDS, SAMPLE_RATE)
    wav_path = save_temp_wav(audio, SAMPLE_RATE)
    print("WAV saved to %s" % wav_path)
    print()

    results: dict[str, list[float]] = {}

    for model_name in MODELS:
        for device, compute_type in DEVICES:
            label = "%s | %s (%s)" % (model_name, device, compute_type)
            print("Benchmarking: %s" % label)
            try:
                times = benchmark(model_name, device, compute_type, wav_path)
                results[label] = times
                avg = sum(times) / len(times)
                print("  avg: %.3fs" % avg)
            except Exception as exc:
                print("  SKIPPED: %s" % exc)
                results[label] = []
            print()

    wav_path.unlink(missing_ok=True)

    print("=" * 65)
    header = "%-30s %8s %8s %8s" % ("Config", "Avg", "Min", "Max")
    print(header)
    print("-" * 65)
    for label, times in results.items():
        if times:
            avg = sum(times) / len(times)
            line = "%-30s %8.3f %8.3f %8.3f" % (label, avg, min(times), max(times))
            print(line)
        else:
            print("%-30s   SKIPPED" % label)
    print("=" * 65)


if __name__ == "__main__":
    main()
