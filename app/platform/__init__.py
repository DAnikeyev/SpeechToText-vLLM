from __future__ import annotations

import sys
from functools import lru_cache

from app.platform.base import PlatformServices


@lru_cache(maxsize=3)
def get_platform_services(platform: str | None = None) -> PlatformServices:
    target = platform or sys.platform
    if target == "win32":
        from app.platform import windows

        return windows.SERVICES
    if target == "darwin":
        from app.platform import macos

        return macos.SERVICES
    raise RuntimeError(f"Unsupported platform '{target}'. Windows and macOS are currently supported.")


def current_platform_name() -> str:
    return get_platform_services().name

