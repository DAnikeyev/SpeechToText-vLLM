from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from app.audio import AudioRecorder, rms


class _FakeInputStream:
    def __init__(
        self, *, samplerate, channels, dtype, device, blocksize=None, callback=None
    ) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.device = device
        self.blocksize = blocksize
        self.callback = callback
        self.started = False
        self.stopped = False
        self.closed = False
        self._frames = [
            np.array([[0.1], [0.2]], dtype=np.float32),
            np.array([[0.3], [0.4]], dtype=np.float32),
        ]

    def start(self) -> None:
        self.started = True
        if self.callback is not None:
            for frame in self._frames:
                self.callback(frame, len(frame), None, None)

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class AudioRecorderTests(unittest.TestCase):
    def test_start_and_stop_collect_audio_with_callback(self) -> None:
        created: list[_FakeInputStream] = []

        def _factory(*, samplerate, channels, dtype, device, blocksize, callback):
            stream = _FakeInputStream(
                samplerate=samplerate,
                channels=channels,
                dtype=dtype,
                device=device,
                blocksize=blocksize,
                callback=callback,
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
        self.assertEqual(stream.blocksize, 1024)
        self.assertIsNotNone(stream.callback)
        np.testing.assert_allclose(audio, np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32))

    def test_start_retries_with_default_device_when_configured_device_fails(self) -> None:
        created: list[_FakeInputStream] = []

        def _factory(*, samplerate, channels, dtype, device, blocksize, callback):
            if device == 2:
                raise RuntimeError("device unavailable")
            stream = _FakeInputStream(
                samplerate=samplerate,
                channels=channels,
                dtype=dtype,
                device=device,
                blocksize=blocksize,
                callback=callback,
            )
            created.append(stream)
            return stream

        with patch("app.audio.sd") as sd_module:
            sd_module.InputStream.side_effect = _factory
            recorder = AudioRecorder(device=2)
            recorder.start()
            recorder.stop()

        self.assertEqual(len(created), 1)
        self.assertIsNone(created[0].device)

    def test_stop_returns_empty_array_when_no_audio_was_captured(self) -> None:
        with patch("app.audio.sd") as sd_module:
            sd_module.InputStream.return_value = _FakeInputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                device=None,
                blocksize=1024,
                callback=None,
            )
            recorder = AudioRecorder()
            result = recorder.stop()

        self.assertEqual(result.shape, (0,))
        self.assertEqual(result.dtype, np.float32)

    def test_start_sets_stop_event_when_a_capture_callback_fails(self) -> None:
        created: list[_FakeInputStream] = []

        def _factory(*, samplerate, channels, dtype, device, blocksize, callback):
            stream = _FakeInputStream(
                samplerate=samplerate,
                channels=channels,
                dtype=dtype,
                device=device,
                blocksize=blocksize,
                callback=callback,
            )
            # 1-D array makes ``indata[:, 0]`` raise, exercising the callback error path.
            stream._frames = [np.array([0.1, 0.2], dtype=np.float32)]
            created.append(stream)
            return stream

        with patch("app.audio.sd") as sd_module:
            sd_module.InputStream.side_effect = _factory
            recorder = AudioRecorder()
            recorder.start()

        self.assertTrue(recorder._stop_event.is_set())
        recorder.stop()

    def test_rms_handles_empty_and_non_empty_audio(self) -> None:
        self.assertEqual(rms(np.zeros((0,), dtype=np.float32)), 0.0)
        self.assertGreater(rms(np.array([0.5, -0.5], dtype=np.float32)), 0.0)


if __name__ == "__main__":
    unittest.main()
