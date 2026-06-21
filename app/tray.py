from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pystray
import sounddevice as sd
from PySide6 import QtCore, QtWidgets

from app.config import AppConfig, save_config
from app.config_watcher import ConfigWatcher
from app.dialogs import LLMCompatibilityDialog, LLMUrlDialog, ModelPickerDialog, TextWindow
from app.icons import tint_icon
from app.llm import fetch_model_names
from app.platform import get_platform_services

if TYPE_CHECKING:
    from app.main import DictationApp


def _format_hotkey_name(name: str) -> str:
    mapping = {
        "right ctrl": "Right Ctrl",
        "right shift": "Right Shift",
        "right cmd": "Right Command",
        "right alt": "Right Option",
    }
    return mapping.get(name, name.title())


def _hotkey_labels() -> dict[str, str]:
    services = get_platform_services()
    return {mode: _format_hotkey_name(key) for key, mode in services.key_modes.items()}


def build_about_text() -> str:
    labels = _hotkey_labels()
    restructure_key = labels.get("restructure", "Primary key")
    answer_key = labels.get("answer", "Secondary key")
    return f"""SpeechToText-vLLM

Windows dictation assistant with shared speech and OpenAI-compatible LLM pipeline.

Hotkeys
- {restructure_key}: single hold -> transcribe, clean with LLM, insert and copy to clipboard
- {restructure_key}: double-press then hold -> transcribe, clean with LLM, copy to clipboard
- {restructure_key}: triple-press then hold -> transcribe only, skip vLLM, insert and copy raw text
- {answer_key}: single hold -> transcribe, answer with vLLM, insert and copy to clipboard
- {answer_key}: double-press then hold -> transcribe, answer with vLLM, copy to clipboard

LLM defaults
- Hosted default: OpenRouter at https://openrouter.ai/api/v1
- Default hosted model: openai/gpt-oss-120b:free
- API key: set llm_api_key in config.json or use SPEECHTOTEXT_VLLM_API_KEY
- Compatibility presets: Hosted OpenAI-compatible, Ollama, and vLLM / Qwen

Tips
- The icon is green when active, yellow while processing (transcribing/LLM), and red when paused.
- Open the system tray icon to change microphone, language, LLM server URL, or compatibility preset.
- Press Backspace while processing to cancel the current analysis/output.
- Text insertion pastes from the clipboard (Ctrl+V) for better editor compatibility.
"""


def _list_input_devices() -> list[tuple[int, str]]:
    devices = sd.query_devices()
    result: list[tuple[int, str]] = []
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) > 0:
            result.append((i, d["name"]))
    return result


_logger = logging.getLogger(__name__)


class _DialogInvoker(QtCore.QObject):
    show_url_dialog = QtCore.Signal()
    show_compat_dialog = QtCore.Signal()
    show_text_window = QtCore.Signal(str, str, str, object, int)


class TrayApp:
    def __init__(self, *, app: DictationApp, config_path: Path) -> None:
        self._app = app
        self._config_path = config_path
        self._paused = False
        self._ctrl_enabled = True
        self._shift_enabled = True
        self._icon: pystray.Icon | None = None
        self._config_watcher = ConfigWatcher(
            config_path=config_path,
            get_current=lambda: self._app.config,
            apply=self._apply_config,
            logger=self._app.logger,
        )
        self._qt_app: QtWidgets.QApplication | None = None
        self._qt_thread: threading.Thread | None = None
        self._qt_invoker: _DialogInvoker | None = None
        self._open_windows: list[QtWidgets.QWidget] = []
        self._named_windows: dict[str, QtWidgets.QWidget] = {}

    def run(self) -> None:
        self._app.logger.info("Starting dictation assistant (tray mode)")
        self._app.worker.start()
        self._app.llm_monitor.start()
        hotkeys_started = False
        try:
            self._app.hotkeys.start()
            hotkeys_started = True
        except Exception as exc:
            self._paused = True
            self._app.logger.exception(
                "Failed to start global hotkeys; running in paused mode so the app stays open: %s",
                exc,
            )
        self._config_watcher.start()
        self._icon_refresh_thread = threading.Thread(
            target=self._icon_refresh_loop, daemon=True, name="icon-refresh"
        )
        self._icon_refresh_thread.start()

        self._start_qt()

        icon = pystray.Icon(
            "dictation",
            icon=tint_icon(paused=self._paused),
            title="Dictation Assistant",
            menu=self._build_menu(),
        )
        self._icon = icon
        try:
            icon.run()
        finally:
            self._stop_qt()
            self._config_watcher.stop()
            if hotkeys_started:
                self._app.hotkeys.stop()
            self._app.shutdown()

    def _start_qt(self) -> None:
        self._qt_ready = threading.Event()
        self._qt_thread = threading.Thread(target=self._qt_main, daemon=True, name="qt-event-loop")
        self._qt_thread.start()
        self._qt_ready.wait()

    def _qt_main(self) -> None:
        self._qt_app = QtWidgets.QApplication(sys.argv)
        self._qt_app.setQuitOnLastWindowClosed(False)

        self._qt_invoker = _DialogInvoker()
        self._qt_invoker.show_url_dialog.connect(self._show_url_dialog_qt)
        self._qt_invoker.show_compat_dialog.connect(self._show_compat_dialog_qt)
        self._qt_invoker.show_text_window.connect(self._show_text_window_qt)

        self._qt_ready.set()
        self._qt_app.exec()

    def _stop_qt(self) -> None:
        if self._qt_app:
            self._qt_app.quit()
        if self._qt_thread and self._qt_thread.is_alive():
            self._qt_thread.join(timeout=2)

    def _apply_config(self, config: AppConfig) -> None:
        self._app.apply_runtime_config(config)
        self._refresh_menu()

    def _build_menu(self) -> pystray.Menu:
        current_device = self._app.config.microphone_device
        labels = _hotkey_labels()

        def make_mic_items() -> list[pystray.MenuItem]:
            devices = _list_input_devices()
            items: list[pystray.MenuItem] = []
            items.append(
                pystray.MenuItem(
                    "Default",
                    lambda _icon, _item: self._set_mic(None),
                    checked=lambda _item: current_device is None,
                )
            )
            for idx, name in devices:

                def _make_select(dev_idx: int):
                    def _handler(_icon, _item):
                        self._set_mic(dev_idx)

                    return _handler

                def _make_checked(dev_idx: int, cur_dev):
                    def _check(_item):
                        return cur_dev == dev_idx

                    return _check

                items.append(
                    pystray.MenuItem(
                        f"{idx}: {name[:40]}",
                        _make_select(idx),
                        checked=_make_checked(idx, current_device),
                    )
                )
            return items

        def make_lang_items() -> list[pystray.MenuItem]:
            items: list[pystray.MenuItem] = []
            builtin = [("Auto", "auto"), ("Auto-detected", "auto-detected")]
            all_langs = builtin + [
                (entry.get("label", entry["code"]), entry["code"])
                for entry in self._app.config.languages
            ]
            for label, code in all_langs:

                def _make_lang_select(lang_code: str):
                    def _handler(_icon, _item):
                        self._set_language(lang_code)

                    return _handler

                def _make_lang_checked(lang_code: str):
                    def _check(_item):
                        return self._app.config.language_mode == lang_code

                    return _check

                items.append(
                    pystray.MenuItem(
                        label,
                        _make_lang_select(code),
                        checked=_make_lang_checked(code),
                    )
                )
            return items

        return pystray.Menu(
            pystray.MenuItem(
                f"{labels.get('restructure', 'Primary key')} (restructure)",
                self._toggle_ctrl,
                checked=lambda _i: self._ctrl_enabled,
            ),
            pystray.MenuItem(
                f"{labels.get('answer', 'Secondary key')} (answer)",
                self._toggle_shift,
                checked=lambda _i: self._shift_enabled,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Microphone",
                pystray.Menu(*make_mic_items()),
            ),
            pystray.MenuItem(
                "Language",
                pystray.Menu(*make_lang_items()),
            ),
            pystray.MenuItem(
                "LLM Server URL...",
                self._configure_vllm_url,
            ),
            pystray.MenuItem(
                "LLM Compatibility...",
                self._configure_llm_compatibility,
            ),
            pystray.MenuItem(
                "About",
                self._show_about,
            ),
            pystray.MenuItem(
                "Recent Logs",
                self._show_recent_logs,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Pause" if not self._paused else "Resume",
                self._toggle_pause,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._exit),
        )

    def _refresh_menu(self) -> None:
        if self._icon:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()

    def _update_icon_image(self) -> None:
        if self._icon:
            self._icon.icon = tint_icon(paused=self._paused, processing=self._app._processing)

    def _icon_refresh_loop(self) -> None:
        """Periodically update the tray icon to reflect the current processing state."""
        prev_processing = self._app._processing
        while not self._app.stop_event.is_set():
            self._app.stop_event.wait(timeout=0.25)
            if self._app._processing != prev_processing:
                prev_processing = self._app._processing
                self._update_icon_image()

    def _toggle_ctrl(self, _icon, _item) -> None:
        self._ctrl_enabled = not self._ctrl_enabled
        self._app.hotkeys.enable_mode("restructure", self._ctrl_enabled)
        self._refresh_menu()

    def _toggle_shift(self, _icon, _item) -> None:
        self._shift_enabled = not self._shift_enabled
        self._app.hotkeys.enable_mode("answer", self._shift_enabled)
        self._refresh_menu()

    def _set_language(self, code: str) -> None:
        self._app.set_language(code)
        self._save_config()
        self._refresh_menu()

    def _set_mic(self, device: int | None) -> None:
        self._app.set_microphone(device)
        self._save_config()
        self._refresh_menu()

    def _configure_vllm_url(self, _icon, _item) -> None:
        if self._qt_invoker:
            self._qt_invoker.show_url_dialog.emit()

    def _show_url_dialog_qt(self) -> None:
        existing = self._named_windows.get("llm-url")
        if isinstance(existing, QtWidgets.QDialog):
            self._present_window(existing)
            return

        dialog = LLMUrlDialog(None, self._app.config.vllm_url)
        self._register_window(dialog, key="llm-url")
        if self._show_modal_dialog(dialog) != QtWidgets.QDialog.DialogCode.Accepted:
            return

        new_url = dialog.normalized_url
        self._app.update_llm_endpoint(new_url)

        # Try to fetch models from the new endpoint so the user can pick one.
        model_names: list[str] = []
        try:
            model_names = fetch_model_names(new_url)
        except Exception as exc:
            _logger.warning("Could not fetch model list from %s: %s", new_url, exc)

        if model_names:
            picker = ModelPickerDialog(
                None,
                model_names=model_names,
                current_model=self._app.config.model_name,
            )
            self._register_window(picker, key="llm-url")
            if self._show_modal_dialog(picker) == QtWidgets.QDialog.DialogCode.Accepted:
                self._app.config.model_name = picker.result_model
                self._app._reconfigure_cleaner()

        self._save_config()

    def _configure_llm_compatibility(self, _icon, _item) -> None:
        if self._qt_invoker:
            self._qt_invoker.show_compat_dialog.emit()

    def _show_compat_dialog_qt(self) -> None:
        existing = self._named_windows.get("llm-compat")
        if isinstance(existing, QtWidgets.QDialog):
            self._present_window(existing)
            return

        dialog = LLMCompatibilityDialog(
            None,
            current_extra_body=self._app.config.llm_extra_body,
            current_strict=self._app.config.llm_strict_model_name_match,
        )
        self._register_window(dialog, key="llm-compat")
        if self._show_modal_dialog(dialog) == QtWidgets.QDialog.DialogCode.Accepted:
            self._app.update_llm_settings(
                extra_body=dialog.result_extra_body,
                strict_model_name_match=dialog.result_strict,
            )
            self._save_config()

    def _show_text_window(
        self,
        *,
        title: str,
        text_content: str,
        geometry: str = "560x360",
        content_provider: Callable[[], str] | None = None,
        refresh_interval_ms: int = 1000,
    ) -> None:
        if self._qt_invoker:
            self._qt_invoker.show_text_window.emit(
                title, text_content, geometry, content_provider, refresh_interval_ms
            )

    def _show_text_window_qt(
        self,
        title: str,
        text_content: str,
        geometry: str,
        content_provider: Callable[[], str] | None,
        refresh_interval_ms: int,
    ) -> None:
        existing = self._named_windows.get(title)
        if isinstance(existing, QtWidgets.QWidget):
            self._present_window(existing)
            return

        window = TextWindow(
            None,
            title=title,
            text_content=text_content,
            geometry=geometry,
            content_provider=content_provider,
            refresh_interval_ms=refresh_interval_ms,
        )
        self._register_window(window, key=title)
        self._present_window(window)

    def _register_window(self, window: QtWidgets.QWidget, key: str | None = None) -> None:
        self._open_windows.append(window)
        window.destroyed.connect(lambda *_: self._forget_window(window))
        if key is not None:
            self._named_windows[key] = window
            window.destroyed.connect(lambda *_: self._forget_named_window(key, window))

    def _forget_window(self, window: QtWidgets.QWidget) -> None:
        self._open_windows = [
            open_window for open_window in self._open_windows if open_window is not window
        ]

    def _forget_named_window(self, key: str, window: QtWidgets.QWidget) -> None:
        if self._named_windows.get(key) is window:
            self._named_windows.pop(key, None)

    def _present_window(self, window: QtWidgets.QWidget) -> None:
        window.show()
        if window.isMinimized():
            window.showNormal()
        window.raise_()
        window.activateWindow()

    def _show_modal_dialog(self, dialog: QtWidgets.QDialog) -> int:
        return dialog.exec()

    def _show_about(self, _icon, _item) -> None:
        self._show_text_window(title="About SpeechToText-vLLM", text_content=build_about_text())

    def _show_recent_logs(self, _icon, _item) -> None:
        log_text = self._get_recent_logs_text()
        self._show_text_window(
            title="Recent Logs",
            text_content=log_text,
            geometry="900x480",
            content_provider=self._get_recent_logs_text,
        )

    def _toggle_pause(self, _icon, _item) -> None:
        self._paused = not self._paused
        if self._paused:
            self._app.hotkeys.stop()
            self._app.logger.info("Paused")
        else:
            try:
                self._app.hotkeys.start()
                self._app.logger.info("Resumed")
            except Exception as exc:
                self._paused = True
                self._app.logger.exception("Failed to resume hotkeys: %s", exc)
        self._update_icon_image()
        self._refresh_menu()

    def _exit(self, _icon, _item) -> None:
        self._app.logger.info("Exiting from tray")
        self._app.shutdown()
        if self._icon:
            self._icon.stop()

    def _save_config(self) -> None:
        save_config(self._config_path, self._app.config)
        self._config_watcher.mark_current()

    def _get_recent_logs_text(self) -> str:
        memory_handler = getattr(self._app, "memory_handler", None)
        if memory_handler is None:
            return "Recent log storage is not available."

        entries = memory_handler.get_entries()
        if not entries:
            return "No log entries yet."
        return "\n".join(entries)
