from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.clipboard import copy_to_clipboard
from app.inject import inject_text
from app.platform import get_platform_services
from app.platform.base import HotkeyEvent
from app.stt import detect_keyboard_language
import app.platform.windows as windows_platform


class PlatformDispatchTests(unittest.TestCase):
    def test_clipboard_wrapper_uses_platform_service(self) -> None:
        services = SimpleNamespace(copy_to_clipboard=MagicMock())

        with patch("app.clipboard.get_platform_services", return_value=services):
            copy_to_clipboard("hello")

        services.copy_to_clipboard.assert_called_once_with("hello")

    def test_inject_wrapper_uses_platform_service(self) -> None:
        services = SimpleNamespace(inject_text=MagicMock())

        with patch("app.inject.get_platform_services", return_value=services):
            inject_text("hello")

        services.inject_text.assert_called_once_with("hello")

    def test_language_detection_uses_platform_service(self) -> None:
        services = SimpleNamespace(detect_input_language=MagicMock(return_value="en"))

        with patch("app.stt.get_platform_services", return_value=services):
            language = detect_keyboard_language()

        self.assertEqual(language, "en")
        services.detect_input_language.assert_called_once_with()

    def test_get_platform_services_resolves_known_platforms(self) -> None:
        self.assertEqual(get_platform_services("win32").name, "windows")
        self.assertTrue(callable(get_platform_services("win32").create_hotkey_backend))

    def test_get_platform_services_rejects_unknown_platform(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Unsupported platform"):
            get_platform_services("linux")


class WindowsPlatformTests(unittest.TestCase):
    def test_windows_hotkey_backend_uses_keyboard_hook_and_unhook(self) -> None:
        events: list[HotkeyEvent] = []
        keyboard_module = SimpleNamespace(
            hook=MagicMock(return_value="hook-id"),
            unhook=MagicMock(),
        )
        backend = windows_platform.KeyboardHotkeyBackend(keyboard_module=keyboard_module)

        backend.start(events.append)
        hook_handler = keyboard_module.hook.call_args.args[0]
        hook_handler(SimpleNamespace(name="RIGHT CTRL", event_type="down"))
        backend.stop()

        keyboard_module.hook.assert_called_once()
        keyboard_module.unhook.assert_called_once_with("hook-id")
        self.assertEqual(events, [HotkeyEvent(name="right ctrl", event_type="down")])

    def test_windows_clipboard_retries_until_open_succeeds(self) -> None:
        clipboard_module = SimpleNamespace(
            CF_UNICODETEXT=13,
            OpenClipboard=MagicMock(side_effect=[RuntimeError("busy"), None]),
            EmptyClipboard=MagicMock(),
            SetClipboardData=MagicMock(),
            CloseClipboard=MagicMock(),
        )

        with patch.object(windows_platform, "win32clipboard", clipboard_module), patch(
            "app.platform.windows.time.sleep"
        ) as sleep:
            windows_platform.copy_to_clipboard("hello")

        self.assertEqual(clipboard_module.OpenClipboard.call_count, 2)
        clipboard_module.EmptyClipboard.assert_called_once_with()
        clipboard_module.SetClipboardData.assert_called_once_with(13, "hello")
        clipboard_module.CloseClipboard.assert_called_once_with()
        sleep.assert_called_once()

    def test_windows_clipboard_raises_clear_error_after_retry_timeout(self) -> None:
        clipboard_module = SimpleNamespace(
            CF_UNICODETEXT=13,
            OpenClipboard=MagicMock(side_effect=RuntimeError("busy")),
            EmptyClipboard=MagicMock(),
            SetClipboardData=MagicMock(),
            CloseClipboard=MagicMock(),
        )

        monotonic_values = iter([0.0, 0.4])
        with patch.object(windows_platform, "win32clipboard", clipboard_module), patch(
            "app.platform.windows.time.monotonic", side_effect=lambda: next(monotonic_values)
        ), patch("app.platform.windows.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "Timed out waiting for the Windows clipboard"):
                windows_platform.copy_to_clipboard("hello")

        clipboard_module.EmptyClipboard.assert_not_called()
        clipboard_module.SetClipboardData.assert_not_called()


if __name__ == "__main__":
    unittest.main()





