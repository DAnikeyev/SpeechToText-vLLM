from __future__ import annotations


class AppUI:
    """Optional tray/settings UI extension point."""

    def start(self) -> None:
        return

    def stop(self) -> None:
        return
