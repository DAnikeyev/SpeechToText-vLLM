from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


ClipboardCopy = Callable[[str], None]
TextInject = Callable[[str], None]
LanguageDetect = Callable[[], str | None]


@dataclass(frozen=True, slots=True)
class HotkeyEvent:
    name: str
    event_type: str


GlobalHotkeyHandler = Callable[[HotkeyEvent], None]


class GlobalHotkeyBackend(Protocol):
    def start(self, handler: GlobalHotkeyHandler) -> None:
        ...

    def stop(self) -> None:
        ...


HotkeyBackendFactory = Callable[[], GlobalHotkeyBackend]


@dataclass(frozen=True, slots=True)
class PlatformServices:
    name: str
    copy_to_clipboard: ClipboardCopy
    inject_text: TextInject
    detect_input_language: LanguageDetect
    create_hotkey_backend: HotkeyBackendFactory
    key_modes: dict[str, str]
    triple_press_raw_keys: set[str]



