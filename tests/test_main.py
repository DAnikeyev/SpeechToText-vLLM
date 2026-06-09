from __future__ import annotations

import copy
import queue
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from app.config import AppConfig
from app.main import DictationApp, DictationJob, default_config_path


class DictationAppInitTests(unittest.TestCase):
    def test_init_injects_platform_hotkeys_and_llm_api_key(self) -> None:
        config = SimpleNamespace(
            microphone_device=None,
            whisper_model="small",
            language_mode="auto",
            whisper_device="auto",
            whisper_compute_type="float16",
            vllm_url="https://example.test/v1",
            llm_api_key="provider-key",
            model_name="provider/model",
            restructure_prompt="clean prompt",
            answer_prompt="answer prompt",
            temperature=0.2,
            max_tokens=256,
            llm_timeout_seconds=30.0,
            llm_extra_body=None,
            llm_strict_model_name_match=False,
            min_hold_seconds=2.0,
            record_start_delay_seconds=0.1,
            double_press_window_seconds=0.5,
            first_press_max_seconds=0.25,
        )
        platform_services = SimpleNamespace(
            create_hotkey_backend=MagicMock(name="create_hotkey_backend"),
            key_modes={"right cmd": "restructure", "right shift": "answer"},
            triple_press_raw_keys={"right cmd"},
        )
        recorder = SimpleNamespace(sample_rate=16000)

        with patch("app.main.setup_logging", return_value=MagicMock()), patch(
            "app.main.get_platform_services", return_value=platform_services
        ), patch("app.main.AudioRecorder", return_value=recorder), patch(
            "app.main.VoiceActivityTrimmer"
        ), patch("app.main.WhisperTranscriber"), patch("app.main.TranscriptCleaner") as cleaner_cls, patch(
            "app.main.DoublePressHotkeyTracker"
        ) as tracker_cls, patch("app.main.threading.Thread"):
            DictationApp(config=config, base_dir=Path("C:/Repos/GitHub/SpeechToText-vLLM"))

        cleaner_cls.assert_called_once_with(
            base_url="https://example.test/v1",
            api_key="provider-key",
            model_name="provider/model",
            restructure_prompt="clean prompt",
            answer_prompt="answer prompt",
            temperature=0.2,
            max_tokens=256,
            timeout_seconds=30.0,
            extra_body=None,
            strict_model_name_match=False,
        )
        tracker_cls.assert_called_once()
        tracker_kwargs = tracker_cls.call_args.kwargs
        self.assertIs(tracker_kwargs["backend_factory"], platform_services.create_hotkey_backend)
        self.assertEqual(tracker_kwargs["key_modes"], {"right cmd": "restructure", "right shift": "answer"})
        self.assertEqual(tracker_kwargs["triple_press_raw_keys"], {"right cmd"})


class DictationAppOutputTests(unittest.TestCase):
    def _make_app(self) -> DictationApp:
        app = DictationApp.__new__(DictationApp)
        app.logger = MagicMock()
        app.config = AppConfig(
            vllm_url="http://127.0.0.1:8000/v1",
            model_name="base-model",
            llm_availability_check_interval_seconds=60.0,
            vad_enabled=False,
            microphone_device=None,
            language_mode="auto",
            whisper_model="small",
            whisper_device="auto",
            whisper_compute_type="float16",
            llm_api_key=None,
        )
        app.cleaner = MagicMock()
        app.transcriber = MagicMock()
        app.transcriber.last_language = None
        app.recorder = SimpleNamespace(sample_rate=16000)
        app.vad = MagicMock()
        app._llm_status_lock = threading.Lock()
        app._llm_recheck_event = threading.Event()
        app._llm_available = True
        app.job_queue = queue.Queue()
        app._cancel_lock = threading.Lock()
        app._config_lock = threading.RLock()
        app._cancel_generation = 0
        app._processing_generation = None
        app.hotkeys = SimpleNamespace(
            min_hold_seconds=2.0,
            start_delay_seconds=0.2,
            double_press_window_seconds=0.5,
            first_press_max_seconds=0.3,
        )
        return app

    def test_deliver_result_inserts_into_active_field(self) -> None:
        app = self._make_app()

        with patch("app.main.inject_text") as inject_text, patch("app.main.copy_to_clipboard") as copy_to_clipboard:
            app._deliver_result("hello", output_target="insert")

        inject_text.assert_called_once_with("hello")
        copy_to_clipboard.assert_not_called()

    def test_deliver_result_copies_to_clipboard_for_clipboard_output(self) -> None:
        app = self._make_app()

        with patch("app.main.inject_text") as inject_text, patch("app.main.copy_to_clipboard") as copy_to_clipboard:
            app._deliver_result("hello", output_target="clipboard")

        inject_text.assert_not_called()
        copy_to_clipboard.assert_called_once_with("hello")

    def test_deliver_result_does_not_copy_twice_after_successful_insert_for_both_output(self) -> None:
        app = self._make_app()

        with patch("app.main.inject_text") as inject_text, patch("app.main.copy_to_clipboard") as copy_to_clipboard:
            app._deliver_result("hello", output_target="both")

        inject_text.assert_called_once_with("hello")
        copy_to_clipboard.assert_not_called()

    def test_deliver_result_logs_warning_when_clipboard_copy_fails(self) -> None:
        app = self._make_app()
        clipboard_error = RuntimeError("clipboard busy")

        with patch("app.main.inject_text") as inject_text, patch(
            "app.main.copy_to_clipboard", side_effect=clipboard_error
        ):
            app._deliver_result("hello", output_target="clipboard")

        inject_text.assert_not_called()
        app.logger.warning.assert_called_once_with("Clipboard copy failed: %s", clipboard_error)

    def test_deliver_result_logs_warning_when_insert_fallback_clipboard_fails(self) -> None:
        app = self._make_app()
        insert_error = RuntimeError("insert failed")
        clipboard_error = RuntimeError("clipboard busy")

        with patch("app.main.inject_text", side_effect=insert_error) as inject_text, patch(
            "app.main.copy_to_clipboard", side_effect=clipboard_error
        ):
            app._deliver_result("hello", output_target="insert")

        inject_text.assert_called_once_with("hello")
        app.logger.warning.assert_any_call("Text insertion failed: %s", insert_error)
        app.logger.warning.assert_any_call("Clipboard copy after insert failure also failed: %s", clipboard_error)

    def test_deliver_result_falls_back_to_clipboard_when_insert_fails(self) -> None:
        app = self._make_app()

        with patch("app.main.inject_text", side_effect=RuntimeError("insert failed")) as inject_text, patch(
            "app.main.copy_to_clipboard"
        ) as copy_to_clipboard:
            app._deliver_result("hello", output_target="insert")

        inject_text.assert_called_once_with("hello")
        copy_to_clipboard.assert_called_once_with("hello")

    def test_cancel_requested_drains_queue_and_marks_current_generation_cancelled(self) -> None:
        app = self._make_app()
        app.job_queue.put_nowait("job-1")
        app.job_queue.put_nowait("job-2")
        app._processing_generation = 0

        app._on_cancel_requested()

        self.assertEqual(app._get_cancel_generation(), 1)
        self.assertTrue(app.job_queue.empty())

    def test_process_job_drops_output_after_cancel_requested_during_transcription(self) -> None:
        app = self._make_app()
        app.transcriber.transcribe.side_effect = lambda audio, sample_rate: (app._on_cancel_requested(), "whisper text")[1]
        app._transform_transcript = MagicMock(return_value="clean text")
        app._deliver_result = MagicMock()
        job = DictationJob(
            audio=np.zeros(1600, dtype=np.float32),
            hold_seconds=2.0,
            mode="restructure",
            output_target="insert",
            skip_llm=False,
            cancel_generation=app._get_cancel_generation(),
        )

        app._process_job(job)

        app._transform_transcript.assert_not_called()
        app._deliver_result.assert_not_called()
        self.assertIsNone(app._processing_generation)

    def test_transform_transcript_uses_whisper_text_when_llm_raises(self) -> None:
        app = self._make_app()
        app.cleaner.clean.side_effect = RuntimeError("vLLM offline")

        result = app._transform_transcript("whisper text", mode="restructure")

        self.assertEqual(result, "whisper text")
        app.cleaner.clean.assert_called_once_with("whisper text", language=None)
        self.assertFalse(app._get_llm_available())

    def test_transform_transcript_uses_whisper_text_when_llm_returns_empty(self) -> None:
        app = self._make_app()
        app.cleaner.answer.return_value = "   "

        result = app._transform_transcript("whisper text", mode="answer")

        self.assertEqual(result, "whisper text")
        app.cleaner.answer.assert_called_once_with("whisper text", language=None)

    def test_transform_transcript_skips_llm_when_requested(self) -> None:
        app = self._make_app()

        result = app._transform_transcript("whisper text", mode="restructure", skip_llm=True)

        self.assertEqual(result, "whisper text")
        app.cleaner.clean.assert_not_called()
        app.cleaner.answer.assert_not_called()

    def test_transform_transcript_skips_llm_when_last_check_failed(self) -> None:
        app = self._make_app()
        app._llm_available = False

        result = app._transform_transcript("whisper text", mode="restructure")

        self.assertEqual(result, "whisper text")
        app.cleaner.clean.assert_not_called()
        app.cleaner.answer.assert_not_called()

    def test_check_llm_availability_marks_model_available(self) -> None:
        app = self._make_app()
        app.cleaner.is_model_available.return_value = True

        result = app._check_llm_availability()

        self.assertTrue(result)
        self.assertTrue(app._get_llm_available())
        app.cleaner.is_model_available.assert_called_once_with()

    def test_check_llm_availability_logs_single_retry_warning_on_failure(self) -> None:
        app = self._make_app()
        app.cleaner.is_model_available.side_effect = RuntimeError("Connection error")

        result = app._check_llm_availability()

        self.assertFalse(result)
        self.assertFalse(app._get_llm_available())
        app.logger.warning.assert_called_once_with(
            "LLM server unavailable (%s); retrying in %.1fs",
            app.cleaner.is_model_available.side_effect,
            60.0,
        )
        app.logger.info.assert_not_called()

    def test_update_llm_endpoint_resets_availability_and_wakes_monitor(self) -> None:
        app = self._make_app()
        app.cleaner.client = SimpleNamespace(base_url="http://127.0.0.1:8000/v1")
        app._llm_available = True

        app.update_llm_endpoint("http://127.0.0.1:8512/v1")

        self.assertEqual(app.config.vllm_url, "http://127.0.0.1:8512/v1")
        self.assertEqual(app.cleaner.client.base_url, "http://127.0.0.1:8512/v1")
        self.assertIsNone(app._get_llm_available())
        self.assertTrue(app._llm_recheck_event.is_set())

    def test_apply_runtime_config_updates_collaborators_without_relaunch(self) -> None:
        app = self._make_app()
        new_config = copy.deepcopy(app.config)
        new_config.microphone_device = 3
        new_config.language_mode = "ru"
        new_config.whisper_model = "medium"
        new_config.whisper_device = "cpu"
        new_config.whisper_compute_type = "int8"
        new_config.vllm_url = "https://example.test/v1"
        new_config.llm_api_key = "reloaded-key"
        new_config.model_name = "reloaded-model"
        new_config.temperature = 0.4
        new_config.max_tokens = 1024
        new_config.llm_timeout_seconds = 12.0
        new_config.llm_extra_body = {"foo": "bar"}
        new_config.llm_strict_model_name_match = False
        new_config.min_hold_seconds = 1.2
        new_config.record_start_delay_seconds = 0.05
        new_config.double_press_window_seconds = 0.7
        new_config.first_press_max_seconds = 0.15

        with patch("app.main.WhisperTranscriber", return_value=MagicMock()) as transcriber_cls, patch(
            "app.main.TranscriptCleaner", return_value=MagicMock()
        ) as cleaner_cls:
            app.apply_runtime_config(new_config)

        self.assertIs(app.config, new_config)
        self.assertEqual(app.recorder.device, 3)
        transcriber_cls.assert_called_once_with("medium", "ru", "cpu", "int8")
        cleaner_cls.assert_called_once_with(
            base_url="https://example.test/v1",
            api_key="reloaded-key",
            model_name="reloaded-model",
            restructure_prompt=new_config.restructure_prompt,
            answer_prompt=new_config.answer_prompt,
            temperature=0.4,
            max_tokens=1024,
            timeout_seconds=12.0,
            extra_body={"foo": "bar"},
            strict_model_name_match=False,
        )
        self.assertEqual(app.hotkeys.min_hold_seconds, 1.2)
        self.assertEqual(app.hotkeys.start_delay_seconds, 0.05)
        self.assertEqual(app.hotkeys.double_press_window_seconds, 0.7)
        self.assertEqual(app.hotkeys.first_press_max_seconds, 0.15)
        self.assertIsNone(app._get_llm_available())
        self.assertTrue(app._llm_recheck_event.is_set())


class MainConfigPathTests(unittest.TestCase):
    def test_default_config_path_on_windows_uses_appdata(self) -> None:
        with patch("app.main.sys.platform", "win32"), patch("app.main.os.getenv", return_value=r"C:\Users\tester\AppData\Roaming"):
            path = default_config_path()

        self.assertEqual(path, Path(r"C:\Users\tester\AppData\Roaming\SpeechToText-vLLM\config.json"))


if __name__ == "__main__":
    unittest.main()
