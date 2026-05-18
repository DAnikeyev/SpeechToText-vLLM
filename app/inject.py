from __future__ import annotations

import ctypes
from ctypes import wintypes


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


def _send_input_char(char: str) -> None:
    code_point = ord(char)
    press = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, code_point, KEYEVENTF_UNICODE, 0, None))
    release = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(0, code_point, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None),
    )
    inputs = (INPUT * 2)(press, release)
    sent = ctypes.windll.user32.SendInput(2, inputs, ctypes.sizeof(INPUT))
    if sent != 2:
        raise RuntimeError(f"Failed to inject character via SendInput: {char!r}") from ctypes.WinError()


def inject_text(text: str) -> None:
    if not text:
        return
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("Direct text injection requires Windows")
    for char in text:
        _send_input_char(char)
