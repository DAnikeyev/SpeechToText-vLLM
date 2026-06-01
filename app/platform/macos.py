from __future__ import annotations

import logging
import subprocess
import time

from app.platform.base import GlobalHotkeyHandler, HotkeyEvent, PlatformServices

try:
    from pynput import keyboard as pynput_keyboard
except Exception:  # pragma: no cover - optional at import time
    pynput_keyboard = None

logger = logging.getLogger(__name__)


class PynputHotkeyBackend:
    def __init__(self, keyboard_module=None) -> None:
        self._keyboard = keyboard_module if keyboard_module is not None else pynput_keyboard
        self._listener = None
        self._handler: GlobalHotkeyHandler | None = None

    def start(self, handler: GlobalHotkeyHandler) -> None:
        if self._listener is not None:
            return
        if self._keyboard is None:
            raise RuntimeError(
                "pynput is required to capture global hotkeys on macOS. Install requirements/macos.txt and grant Accessibility access."
            )
        self._handler = handler
        self._listener = self._keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
        self._listener = None
        self._handler = None

    def _on_press(self, key) -> None:
        self._emit(key, "down")

    def _on_release(self, key) -> None:
        self._emit(key, "up")

    def _emit(self, key, event_type: str) -> None:
        name = self._normalize_key(key)
        handler = self._handler
        if name is None or handler is None:
            return
        handler(HotkeyEvent(name=name, event_type=event_type))

    def _normalize_key(self, key) -> str | None:
        keyboard_module = self._keyboard
        if keyboard_module is None:
            return None
        key_enum = getattr(keyboard_module, "Key", None)
        if key_enum is None:
            return None
        mapping = {}

        def _map(attr: str, normalized_name: str) -> None:
            raw_key = getattr(key_enum, attr, None)
            if raw_key is not None:
                mapping[raw_key] = normalized_name

        # Some macOS layouts/reporting paths emit generic modifiers (cmd/shift/ctrl)
        # instead of side-specific variants, so we normalize both to the configured keys.
        _map("ctrl_r", "right ctrl")
        _map("ctrl", "right ctrl")
        _map("cmd_r", "right cmd")
        _map("cmd", "right cmd")
        _map("shift_r", "right shift")
        _map("shift", "right shift")
        _map("backspace", "backspace")
        _map("delete", "backspace")

        return mapping.get(key)


def copy_to_clipboard(text: str) -> None:
    if not text:
        return
    subprocess.run(
        ["pbcopy"],
        input=text,
        text=True,
        check=True,
    )


def inject_text(text: str) -> None:
    if not text:
        return
    copy_to_clipboard(text)
    time.sleep(0.03)
    subprocess.run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to keystroke "v" using command down',
        ],
        check=True,
    )


def detect_input_language() -> str | None:
    return None


def create_hotkey_backend() -> PynputHotkeyBackend:
    return PynputHotkeyBackend()


SERVICES = PlatformServices(
    name="macos",
    copy_to_clipboard=copy_to_clipboard,
    inject_text=inject_text,
    detect_input_language=detect_input_language,
    create_hotkey_backend=create_hotkey_backend,
    key_modes={"right cmd": "restructure", "right shift": "answer"},
    triple_press_raw_keys={"right cmd"},
)




