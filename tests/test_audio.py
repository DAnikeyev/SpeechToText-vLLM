from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from app.audio import AudioRecorder, rms


class _FakeInputStream:
    def __init__(self, *, samplerate, channels, dtype, device) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.device = device
        self.started = False
        self.stopped = False
        self.closed = False
        self.read_calls = 0
        self._frames = [
            np.array([[0.1], [0.2]], dtype=np.float32),
            np.array([[0.3], [0.4]], dtype=np.float32),
        ]

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def read(self, _frames: int):
        self.read_calls += 1
        if self._frames:
            return self._frames.pop(0), False
        raise RuntimeError("stream stopped")


class AudioRecorderTests(unittest.TestCase):
    def test_start_and_stop_collect_audio_without_callback(self) -> None:
        created: list[_FakeInputStream] = []

        def _factory(*, samplerate, channels, dtype, device):
            stream = _FakeInputStream(
                samplerate=samplerate,
                channels=channels,
                dtype=dtype,
                device=device,
            )
            created.append(stream)
            return stream

        with patch("app.audio.sd") as sd_module:
            sd_module.InputStream.side_effect = _factory
            recorder = AudioRecorder(device=2)
            recorder.start()
            audio = recorder.stop()

        self.assertEqual(len(created), 1)
        stream = created[0]
        self.assertTrue(stream.started)
        self.assertTrue(stream.stopped)
        self.assertTrue(stream.closed)
        np.testing.assert_allclose(audio, np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32))

    def test_stop_returns_empty_array_when_no_audio_was_captured(self) -> None:
        with patch("app.audio.sd") as sd_module:
            sd_module.InputStream.return_value = _FakeInputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                device=None,
            )
            recorder = AudioRecorder()
            result = recorder.stop()

        self.assertEqual(result.shape, (0,))
        self.assertEqual(result.dtype, np.float32)

    def test_read_loop_sets_stop_event_when_read_fails(self) -> None:
        stream = _FakeInputStream(samplerate=16000, channels=1, dtype="float32", device=None)
        recorder = AudioRecorder()
        recorder._stream = stream
        stream._frames.clear()

        recorder._read_loop()

        self.assertTrue(recorder._stop_event.is_set())
        self.assertIsInstance(recorder._read_exception, RuntimeError)

    def test_rms_handles_empty_and_non_empty_audio(self) -> None:
        self.assertEqual(rms(np.zeros((0,), dtype=np.float32)), 0.0)
        self.assertGreater(rms(np.array([0.5, -0.5], dtype=np.float32)), 0.0)


if __name__ == "__main__":
    unittest.main()

