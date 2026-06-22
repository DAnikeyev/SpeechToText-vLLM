from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes

from app.platform.base import GlobalHotkeyHandler, HotkeyEvent, PlatformServices

try:
    import keyboard
except Exception:  # pragma: no cover - optional at import time
    keyboard = None

try:
    import win32clipboard
except Exception:  # pragma: no cover - optional at import time
    win32clipboard = None

logger = logging.getLogger(__name__)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56
CLIPBOARD_OPEN_RETRY_SECONDS = 0.35
CLIPBOARD_OPEN_RETRY_INTERVAL_SECONDS = 0.02


class KeyboardHotkeyBackend:
    def __init__(self, keyboard_module=None) -> None:
        self._keyboard = keyboard_module if keyboard_module is not None else keyboard
        self._hook = None
        self._handler: GlobalHotkeyHandler | None = None

    def start(self, handler: GlobalHotkeyHandler) -> None:
        if self._hook is not None:
            return
        if self._keyboard is None:
            raise RuntimeError("keyboard library is required to capture global hotkeys on Windows")
        self._handler = handler
        self._hook = self._keyboard.hook(self._handle_keyboard_event)

    def stop(self) -> None:
        if self._hook is not None and self._keyboard is not None:
            self._keyboard.unhook(self._hook)
        self._hook = None
        self._handler = None

    def _handle_keyboard_event(self, event) -> None:
        handler = self._handler
        if handler is None:
            return
        handler(
            HotkeyEvent(
                name=((getattr(event, "name", "") or "").lower()),
                event_type=str(getattr(event, "event_type", "")).lower(),
            )
        )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


def copy_to_clipboard(text: str) -> None:
    if not text:
        return
    if win32clipboard is None:
        raise RuntimeError("pywin32 is required for clipboard access on Windows")

    deadline = time.monotonic() + CLIPBOARD_OPEN_RETRY_SECONDS
    while True:
        try:
            win32clipboard.OpenClipboard()
            break
        except Exception as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Timed out waiting for the Windows clipboard. Another app may be holding it open."
                ) from exc
            time.sleep(CLIPBOARD_OPEN_RETRY_INTERVAL_SECONDS)

    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()


def _send_vk(vk: int, *, key_up: bool = False) -> None:
    flags = KEYEVENTF_KEYUP if key_up else 0
    event = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(vk, 0, flags, 0, None),
    )
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
    if sent != 1:
        error = ctypes.WinError()
        raise RuntimeError(f"Failed to send virtual key {vk:#x}; win_error={error}")


def _send_ctrl_v() -> None:
    _send_vk(VK_CONTROL)
    _send_vk(VK_V)
    _send_vk(VK_V, key_up=True)
    _send_vk(VK_CONTROL, key_up=True)


def inject_text(text: str) -> None:
    if not text:
        return

    copy_to_clipboard(text)
    time.sleep(0.03)

    if keyboard is not None:
        try:
            keyboard.press_and_release("ctrl+v")
            return
        except Exception as exc:
            logger.debug("Ctrl+V paste failed, falling back to SendInput: %s", exc)

    if sys.platform != "win32" or not hasattr(ctypes, "windll"):
        raise RuntimeError("Clipboard paste injection requires Windows")

    _send_ctrl_v()


def detect_input_language() -> str | None:
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        hkl = user32.GetKeyboardLayout(tid)
        lang_id = hkl & 0xFFFF
        locale_siso639_langname = 0x59
        buf = ctypes.create_unicode_buffer(10)
        res = kernel32.GetLocaleInfoW(lang_id, locale_siso639_langname, buf, len(buf))
        if res:
            return buf.value.lower()
    except Exception:
        logger.debug("Could not detect foreground keyboard language", exc_info=True)
    return None


def create_hotkey_backend() -> KeyboardHotkeyBackend:
    return KeyboardHotkeyBackend()


SERVICES = PlatformServices(
    name="windows",
    copy_to_clipboard=copy_to_clipboard,
    inject_text=inject_text,
    detect_input_language=detect_input_language,
    create_hotkey_backend=create_hotkey_backend,
    key_modes={"right ctrl": "restructure", "right shift": "answer"},
    triple_press_keys={"right ctrl"},
)
