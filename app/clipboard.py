from __future__ import annotations

from app.platform import get_platform_services


def copy_to_clipboard(text: str) -> None:
    get_platform_services().copy_to_clipboard(text)
