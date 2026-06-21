from __future__ import annotations

import unittest

import numpy as np

from app.vad import VoiceActivityTrimmer


class _FakeVad:
    """Replays a fixed voiced/unvoiced pattern, mimicking webrtcvad.Vad.is_speech."""

    def __init__(self, voiced_pattern: list[bool]) -> None:
        self._pattern = voiced_pattern
        self._idx = 0

    def is_speech(self, _frame: bytes, _sample_rate: int) -> bool:
        voiced = self._pattern[self._idx % len(self._pattern)]
        self._idx += 1
        return voiced


def _silent_frames(count: int, sample_rate: int = 16000, frame_ms: int = 30) -> np.ndarray:
    frame_size = int(sample_rate * frame_ms / 1000)
    return np.ones(count * frame_size, dtype=np.int16)


class VoiceActivityTrimmerTests(unittest.TestCase):
    def test_trim_returns_empty_for_empty_input(self) -> None:
        trimmer = VoiceActivityTrimmer()
        result = trimmer.trim(np.zeros((0,), dtype=np.int16))
        self.assertEqual(result.size, 0)

    def test_trim_returns_input_unchanged_when_vad_unavailable(self) -> None:
        trimmer = VoiceActivityTrimmer()
        trimmer.vad = None
        audio = _silent_frames(4)
        np.testing.assert_array_equal(trimmer.trim(audio), audio)

    def test_trim_keeps_span_from_first_to_last_voiced_frame(self) -> None:
        trimmer = VoiceActivityTrimmer()
        # Pattern: silent, voiced, silent, voiced, silent
        trimmer.vad = _FakeVad([False, True, False, True, False])
        audio = _silent_frames(5)
        result = trimmer.trim(audio)
        # First voiced at index 1, last at index 3 -> frames[1:4] = 3 frames.
        frame_size = int(16000 * 30 / 1000)
        self.assertEqual(result.size, frame_size * 3)

    def test_trim_drops_audio_when_voiced_ratio_below_threshold(self) -> None:
        trimmer = VoiceActivityTrimmer()
        # 1 voiced of 20 frames = 5%, below the 10% gate.
        trimmer.vad = _FakeVad([True, *([False] * 19)])
        audio = _silent_frames(20)
        result = trimmer.trim(audio)
        self.assertEqual(result.size, 0)


if __name__ == "__main__":
    unittest.main()
