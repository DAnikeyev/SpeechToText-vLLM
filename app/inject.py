from __future__ import annotations

from app.platform import get_platform_services


def inject_text(text: str) -> None:
    get_platform_services().inject_text(text)
