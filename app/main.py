from __future__ import annotations

import argparse
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.audio import AudioRecorder, rms
from app.clipboard import copy_to_clipboard
from app.config import AppConfig, load_config
from app.hotkeys import DoublePressHotkeyTracker
from app.inject import inject_text
from app.llm import TranscriptCleaner
from app.logger import setup_logging
from app.platform import get_platform_services
from app.stt import WhisperTranscriber
from app.vad import VoiceActivityTrimmer


@dataclass
class DictationJob:
    audio: np.ndarray
    hold_seconds: float
    mode: str
    output_target: str
    skip_llm: bool = False
    cancel_generation: int = 0


class DictationApp:
    def __init__(self, config: AppConfig, base_dir: Path) -> None:
        self.config = config
        self.base_dir = base_dir
        self.logger = setup_logging()
        self.stop_event = threading.Event()
        self._llm_recheck_event = threading.Event()
        self._llm_status_lock = threading.Lock()
        self._llm_available: bool | None = None
        self.job_queue: queue.Queue[DictationJob] = queue.Queue(maxsize=1)
        self._cancel_lock = threading.Lock()
        self._cancel_generation = 0
        self._processing_generation: int | None = None
        self._config_lock = threading.RLock()
        platform_services = get_platform_services()

        self.recorder = AudioRecorder(device=config.microphone_device)
        self.vad = VoiceActivityTrimmer(sample_rate=self.recorder.sample_rate)
        self.transcriber = WhisperTranscriber(
            config.whisper_model,
            config.language_mode,
            config.whisper_device,
            config.whisper_compute_type,
        )
        self.cleaner = TranscriptCleaner(
            base_url=config.vllm_url,
            api_key=config.llm_api_key,
            model_name=config.model_name,
            restructure_prompt=config.restructure_prompt,
            answer_prompt=config.answer_prompt,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout_seconds=config.llm_timeout_seconds,
            extra_body=config.llm_extra_body,
            strict_model_name_match=config.llm_strict_model_name_match,
        )
        self.hotkeys = DoublePressHotkeyTracker(
            on_record_start=self._on_record_start,
            on_record_stop=self._on_record_stop,
            on_cancel=self._on_cancel_requested,
            min_hold_seconds=config.min_hold_seconds,
            start_delay_seconds=config.record_start_delay_seconds,
            double_press_window_seconds=config.double_press_window_seconds,
            first_press_max_seconds=config.first_press_max_seconds,
            backend_factory=platform_services.create_hotkey_backend,
            key_modes=dict(platform_services.key_modes),
            triple_press_raw_keys=set(platform_services.triple_press_raw_keys),
        )
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.llm_monitor = threading.Thread(target=self._llm_monitor_loop, daemon=True)

    def run(self) -> None:
        self.logger.info("Starting dictation assistant")
        self.worker.start()
        self.llm_monitor.start()
        self.hotkeys.start()

        while not self.stop_event.is_set():
            time.sleep(0.1)

        self.hotkeys.stop()

    def shutdown(self) -> None:
        self.logger.info("Shutting down dictation assistant")
        self.stop_event.set()
        self._llm_recheck_event.set()

    def update_llm_endpoint(self, base_url: str) -> None:
        self.config.vllm_url = base_url
        self.cleaner.client.base_url = base_url
        with self._llm_status_lock:
            self._llm_available = None
        self._llm_recheck_event.set()

    def update_llm_settings(
        self,
        extra_body: dict[str, Any] | None,
        strict_model_name_match: bool,
    ) -> None:
        self.config.llm_extra_body = extra_body
        self.config.llm_strict_model_name_match = strict_model_name_match
        self.cleaner.extra_body = extra_body
        self.cleaner.strict_model_name_match = strict_model_name_match
        with self._llm_status_lock:
            self._llm_available = None
        self._llm_recheck_event.set()

    def apply_runtime_config(self, config: AppConfig) -> None:
        with self._config_lock:
            previous = self.config
            self.config = config

            self.recorder.device = config.microphone_device

            transcriber_needs_rebuild = any(
                (
                    previous.whisper_model != config.whisper_model,
                    previous.whisper_device != config.whisper_device,
                    previous.whisper_compute_type != config.whisper_compute_type,
                )
            )
            if transcriber_needs_rebuild:
                self.transcriber = WhisperTranscriber(
                    config.whisper_model,
                    config.language_mode,
                    config.whisper_device,
                    config.whisper_compute_type,
                )
            else:
                self.transcriber.language_mode = config.language_mode

            cleaner_needs_rebuild = any(
                (
                    previous.vllm_url != config.vllm_url,
                    previous.llm_api_key != config.llm_api_key,
                    previous.model_name != config.model_name,
                    previous.restructure_prompt != config.restructure_prompt,
                    previous.answer_prompt != config.answer_prompt,
                    previous.temperature != config.temperature,
                    previous.max_tokens != config.max_tokens,
                    previous.llm_timeout_seconds != config.llm_timeout_seconds,
                    previous.llm_extra_body != config.llm_extra_body,
                    previous.llm_strict_model_name_match != config.llm_strict_model_name_match,
                )
            )
            if cleaner_needs_rebuild:
                self.cleaner = TranscriptCleaner(
                    base_url=config.vllm_url,
                    api_key=config.llm_api_key,
                    model_name=config.model_name,
                    restructure_prompt=config.restructure_prompt,
                    answer_prompt=config.answer_prompt,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                    timeout_seconds=config.llm_timeout_seconds,
                    extra_body=config.llm_extra_body,
                    strict_model_name_match=config.llm_strict_model_name_match,
                )
                with self._llm_status_lock:
                    self._llm_available = None
                self._llm_recheck_event.set()

            self.hotkeys.min_hold_seconds = config.min_hold_seconds
            self.hotkeys.start_delay_seconds = config.record_start_delay_seconds
            self.hotkeys.double_press_window_seconds = config.double_press_window_seconds
            self.hotkeys.first_press_max_seconds = config.first_press_max_seconds

            self.logger.info("Reloaded config from disk")

    def _on_record_start(self, mode: str, output_target: str, skip_llm: bool) -> None:
        self.logger.info(
            "Recording started (mode: %s, output: %s, skip_llm: %s)",
            mode,
            output_target,
            skip_llm,
        )
        try:
            self.recorder.start()
        except Exception as exc:
            self.logger.exception("Failed to start recording: %s", exc)

    def _on_record_stop(self, hold_seconds: float, mode: str, output_target: str, skip_llm: bool) -> None:
        self.logger.info(
            "Recording stopped, hold %.2fs (mode: %s, output: %s, skip_llm: %s)",
            hold_seconds,
            mode,
            output_target,
            skip_llm,
        )
        audio = self.recorder.stop()

        if hold_seconds < self.config.min_hold_seconds:
            self.logger.info("Ignored: hold shorter than %.2fs", self.config.min_hold_seconds)
            return

        if audio.size == 0 or rms(audio) < self.config.silence_rms_threshold:
            self.logger.info("Ignored: empty/silent audio")
            return

        if self.config.debug_save_wav:
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
            debug_path = self.base_dir / self.config.debug_wav_dir / f"capture-{stamp}.wav"
            self.recorder.save_wav(audio, debug_path)

        job = DictationJob(
            audio=audio,
            hold_seconds=hold_seconds,
            mode=mode,
            output_target=output_target,
            skip_llm=skip_llm,
            cancel_generation=self._get_cancel_generation(),
        )
        try:
            self.job_queue.put_nowait(job)
        except queue.Full:
            try:
                self.job_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.job_queue.put_nowait(job)
                self.logger.warning(
                    "Replaced queued recording: pipeline busy (transcription/LLM still running)"
                )
            except queue.Full:
                self.logger.warning("Dropped recording: pipeline busy")

    def _get_cancel_generation(self) -> int:
        with self._cancel_lock:
            return self._cancel_generation

    def _is_cancelled(self, job: DictationJob) -> bool:
        return job.cancel_generation != self._get_cancel_generation()

    def _set_processing_generation(self, generation: int | None) -> None:
        with self._cancel_lock:
            self._processing_generation = generation

    def _on_cancel_requested(self) -> None:
        drained = 0
        with self._cancel_lock:
            self._cancel_generation += 1
            processing = self._processing_generation is not None

        while True:
            try:
                self.job_queue.get_nowait()
                drained += 1
            except queue.Empty:
                break

        if processing or drained:
            self.logger.info(
                "Cancellation requested via Backspace (processing=%s, dropped_queued_jobs=%d)",
                processing,
                drained,
            )

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                job = self.job_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                self._process_job(job)
            except Exception as exc:
                self.logger.exception("Pipeline error: %s", exc)

    def _llm_monitor_loop(self) -> None:
        while not self.stop_event.is_set():
            if self._get_llm_available() is True:
                self._llm_recheck_event.wait(timeout=0.5)
                self._llm_recheck_event.clear()
                continue

            self._check_llm_availability()
            if self.stop_event.is_set():
                return
            if self._get_llm_available() is True:
                continue
            if self.stop_event.wait(timeout=self.config.llm_availability_check_interval_seconds):
                return

    def _get_llm_available(self) -> bool | None:
        with self._llm_status_lock:
            return self._llm_available

    def _set_llm_available(self, available: bool) -> bool | None:
        with self._llm_status_lock:
            previous = self._llm_available
            self._llm_available = available

        if not available and previous is not False:
            self._llm_recheck_event.set()
        return previous

    def _check_llm_availability(self) -> bool:
        try:
            available = self.cleaner.is_model_available()
        except Exception as exc:
            self._set_llm_available(False)
            self.logger.warning(
                "LLM server unavailable (%s); retrying in %.1fs",
                exc,
                self.config.llm_availability_check_interval_seconds,
            )
            return False

        previous = self._set_llm_available(available)
        if available:
            if previous is not True:
                self.logger.info("LLM model is available again")
            return True

        self.logger.warning(
            "Configured LLM model '%s' is unavailable; retrying in %.1fs",
            self.config.model_name,
            self.config.llm_availability_check_interval_seconds,
        )
        return False

    def _process_job(self, job: DictationJob) -> None:
        if self._is_cancelled(job):
            self.logger.info("Skipped job: cancelled before processing started")
            return

        self._set_processing_generation(job.cancel_generation)
        self.logger.info(
            "Processing recording (mode: %s, output: %s, skip_llm: %s)",
            job.mode,
            job.output_target,
            job.skip_llm,
        )

        try:
            audio = job.audio
            pcm16 = AudioRecorder.to_pcm16(audio)
            if self.config.vad_enabled:
                trimmed = self.vad.trim(pcm16)
                if trimmed.size == 0:
                    self.logger.info("Ignored: VAD detected silence")
                    return
                audio = (trimmed.astype(np.float32) / 32767.0).clip(-1.0, 1.0)

            if self._is_cancelled(job):
                self.logger.info("Cancelled before transcription completed")
                return

            self.logger.info("Transcribing audio (%.1fs)...", job.hold_seconds)
            transcript = self.transcriber.transcribe(audio, sample_rate=self.recorder.sample_rate)
            if self._is_cancelled(job):
                self.logger.info("Cancelled after transcription; dropping result")
                return
            if not transcript:
                self.logger.info("Ignored: empty transcription")
                return

            self.logger.info("Raw transcript: %s", transcript)
            result = self._transform_transcript(transcript, mode=job.mode, skip_llm=job.skip_llm)
            if self._is_cancelled(job):
                self.logger.info("Cancelled after transformation; not delivering output")
                return

            if result:
                self._deliver_result(result, output_target=job.output_target)
        finally:
            self._set_processing_generation(None)

    def _transform_transcript(self, transcript: str, mode: str, skip_llm: bool = False) -> str:
        if skip_llm:
            self.logger.info("Skipping LLM and using raw transcript for fast clipboard output")
            return transcript

        if self._get_llm_available() is not True:
            self.logger.info("Skipping LLM because the last availability check reported it unavailable")
            return transcript

        language = getattr(getattr(self, "transcriber", None), "last_language", None)
        self.logger.info("Sending transcript to LLM (%s)...", self.config.vllm_url)
        try:
            if mode == "answer":
                candidate = self.cleaner.answer(transcript, language=language)
            else:
                candidate = self.cleaner.clean(transcript, language=language)
        except Exception as exc:
            self.logger.warning("LLM request failed, using raw transcript until recovery check succeeds: %s", exc)
            self._set_llm_available(False)
            return transcript

        if not candidate or not candidate.strip():
            self.logger.warning("LLM returned an empty response, using raw transcript")
            return transcript

        candidate = candidate.strip()
        self._set_llm_available(True)
        self.logger.info("LLM response received (%d characters)", len(candidate))
        return candidate

    def _deliver_result(self, result: str, output_target: str) -> None:
        inserted = False
        if output_target in ("insert", "both"):
            try:
                inject_text(result)
                inserted = True
                self.logger.info("Inserted %d characters into the active field", len(result))
            except Exception as exc:
                self.logger.warning("Text insertion failed: %s", exc)
                if output_target == "insert":
                    try:
                        copy_to_clipboard(result)
                        self.logger.info("Copied %d characters to clipboard after insert failure", len(result))
                    except Exception as clipboard_exc:
                        self.logger.warning("Clipboard copy after insert failure also failed: %s", clipboard_exc)

        if output_target in ("clipboard", "both"):
            if inserted and output_target == "both":
                self.logger.debug("Skipped duplicate clipboard write because insertion already populated the clipboard")
                return
            try:
                copy_to_clipboard(result)
                self.logger.info("Copied %d characters to clipboard", len(result))
            except Exception as exc:
                self.logger.warning("Clipboard copy failed: %s", exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local push-to-talk dictation assistant (system tray app)")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to JSON config file",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()

    logger = setup_logging()
    logger.info("Launching tray UI; look for the microphone icon in the system tray or menu bar area.")

    from app.tray import TrayApp
    tray = TrayApp(config_path=config_path)
    tray.run()


if __name__ == "__main__":
    main()