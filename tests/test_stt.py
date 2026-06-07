from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call, patch

from app.stt import WhisperTranscriber


class WhisperTranscriberLoadTests(unittest.TestCase):
    def test_load_uses_safe_cpu_profile_on_macos_when_cuda_is_unavailable(self) -> None:
        fake_model = object()

        with patch("app.stt.sys.platform", "darwin"), patch("app.stt._try_cuda", return_value=False), patch(
            "app.stt.WhisperModel", return_value=fake_model
        ) as whisper_model:
            transcriber = WhisperTranscriber(model_name="small", device="auto", compute_type="float16")

            transcriber.load()

        self.assertIs(transcriber.model, fake_model)
        whisper_model.assert_called_once_with(
            "small",
            device="cpu",
            compute_type="float32",
            cpu_threads=1,
            num_workers=1,
        )

    def test_load_retries_alternative_compute_types_on_macos_cpu(self) -> None:
        fake_model = object()
        whisper_model = MagicMock(side_effect=[RuntimeError("int8 failed"), fake_model])

        with patch("app.stt.sys.platform", "darwin"), patch("app.stt.WhisperModel", whisper_model):
            transcriber = WhisperTranscriber(model_name="small", device="cpu", compute_type="int8")

            transcriber.load()

        self.assertIs(transcriber.model, fake_model)
        self.assertEqual(
            whisper_model.call_args_list,
            [
                call("small", device="cpu", compute_type="int8", cpu_threads=1, num_workers=1),
                call("small", device="cpu", compute_type="float32", cpu_threads=1, num_workers=1),
            ],
        )

    def test_load_falls_back_from_explicit_cuda_to_safe_cpu_profile(self) -> None:
        fake_model = object()

        with patch("app.stt.sys.platform", "darwin"), patch("app.stt._try_cuda", return_value=False), patch(
            "app.stt.WhisperModel", return_value=fake_model
        ) as whisper_model:
            transcriber = WhisperTranscriber(model_name="small", device="cuda", compute_type="float16")

            transcriber.load()

        self.assertIs(transcriber.model, fake_model)
        whisper_model.assert_called_once_with(
            "small",
            device="cpu",
            compute_type="float32",
            cpu_threads=1,
            num_workers=1,
        )


if __name__ == "__main__":
    unittest.main()

