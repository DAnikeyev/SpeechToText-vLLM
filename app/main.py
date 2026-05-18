from __future__ import annotations

import argparse
import queue
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.audio import AudioRecorder, rms
from app.config import AppConfig, load_config
from app.hotkeys import CtrlHoldTracker
from app.inject import inject_text
from app.llm import TranscriptCleaner
from app.logger import setup_logging
from app.stt import WhisperTranscriber
from app.vad import VoiceActivityTrimmer


@dataclass
class DictationJob:
    audio: np.ndarray
    hold_seconds: float


class DictationApp:
    def __init__(self, config: AppConfig, base_dir: Path) -> None:
        self.config = config
        self.base_dir = base_dir
        self.logger = setup_logging()
        self.stop_event = threading.Event()
        self.job_queue: queue.Queue[DictationJob] = queue.Queue(maxsize=1)

        self.recorder = AudioRecorder(device=config.microphone_device)
        self.vad = VoiceActivityTrimmer(sample_rate=self.recorder.sample_rate)
        self.transcriber = WhisperTranscriber(config.whisper_model, config.language_mode)
        self.cleaner = TranscriptCleaner(
            base_url=config.vllm_url,
            model_name=config.model_name,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        self.hotkeys = CtrlHoldTracker(
            on_record_start=self._on_record_start,
            on_record_stop=self._on_record_stop,
            min_hold_seconds=config.min_hold_seconds,
            start_delay_seconds=config.record_start_delay_seconds,
        )
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)

    def run(self) -> None:
        self.logger.info("Starting dictation assistant")
        self.worker.start()
        self.hotkeys.start()

        while not self.stop_event.is_set():
            time.sleep(0.1)

        self.hotkeys.stop()

    def shutdown(self) -> None:
        self.logger.info("Shutting down dictation assistant")
        self.stop_event.set()

    def _on_record_start(self) -> None:
        self.logger.info("CTRL pressed, recording started")
        try:
            self.recorder.start()
        except Exception as exc:
            self.logger.exception("Failed to start recording: %s", exc)

    def _on_record_stop(self, hold_seconds: float) -> None:
        self.logger.info("CTRL released, hold duration %.2fs", hold_seconds)
        audio = self.recorder.stop()

        if hold_seconds < self.config.min_hold_seconds:
            self.logger.info("Ignored: hold shorter than %.2fs", self.config.min_hold_seconds)
            return

        if audio.size == 0 or rms(audio) < 0.005:
            self.logger.info("Ignored: empty/silent audio")
            return

        if self.config.debug_save_wav:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            debug_path = self.base_dir / self.config.debug_wav_dir / f"capture-{stamp}.wav"
            self.recorder.save_wav(audio, debug_path)

        job = DictationJob(audio=audio, hold_seconds=hold_seconds)
        try:
            self.job_queue.put_nowait(job)
        except queue.Full:
            self.logger.warning("Dropped recording: previous job is still processing")

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

    def _process_job(self, job: DictationJob) -> None:
        self.logger.info("Processing recording")

        audio = job.audio
        pcm16 = AudioRecorder.to_pcm16(audio)
        if self.config.vad_enabled:
            trimmed = self.vad.trim(pcm16)
            if trimmed.size == 0:
                self.logger.info("Ignored: VAD detected silence")
                return
            audio = (trimmed.astype(np.float32) / 32767.0).clip(-1.0, 1.0)

        transcript = self.transcriber.transcribe(audio, sample_rate=self.recorder.sample_rate)
        if not transcript:
            self.logger.info("Ignored: empty transcription")
            return

        self.logger.info("Raw transcript: %s", transcript)
        cleaned = transcript
        try:
            cleaned = self.cleaner.clean(transcript)
        except Exception as exc:
            self.logger.warning("LLM cleanup unavailable, using raw transcript: %s", exc)

        if cleaned:
            inject_text(cleaned)
            self.logger.info("Injected %d characters", len(cleaned))


def _install_signal_handlers(app: DictationApp) -> None:
    def _handler(signum, frame) -> None:  # noqa: ARG001
        app.shutdown()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local push-to-talk dictation assistant")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to JSON config file",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    app = DictationApp(config=config, base_dir=config_path.parent)
    _install_signal_handlers(app)
    app.run()


if __name__ == "__main__":
    main()
