from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.clipboard import copy_to_clipboard
from app.inject import inject_text
from app.platform import get_platform_services
from app.platform.base import HotkeyEvent
from app.stt import detect_keyboard_language
import app.platform.macos as macos_platform
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
        self.assertEqual(get_platform_services("darwin").name, "macos")
        self.assertTrue(callable(get_platform_services("win32").create_hotkey_backend))
        self.assertTrue(callable(get_platform_services("darwin").create_hotkey_backend))

    def test_get_platform_services_rejects_unknown_platform(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Unsupported platform"):
            get_platform_services("linux")


class MacOSPlatformTests(unittest.TestCase):
    class _FakeListener:
        def __init__(self, *, on_press, on_release) -> None:
            self.on_press = on_press
            self.on_release = on_release
            self.started = False
            self.stopped = False

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

    class _FakePynputKeyboard:
        class Key:
            ctrl_r = object()
            cmd_r = object()
            shift_r = object()
            backspace = object()

        def __init__(self) -> None:
            self.listeners: list[MacOSPlatformTests._FakeListener] = []

        def Listener(self, *, on_press, on_release):
            listener = MacOSPlatformTests._FakeListener(on_press=on_press, on_release=on_release)
            self.listeners.append(listener)
            return listener

    def test_copy_to_clipboard_uses_pbcopy(self) -> None:
        with patch("app.platform.macos.subprocess.run") as run:
            macos_platform.copy_to_clipboard("hello")

        run.assert_called_once_with(["pbcopy"], input="hello", text=True, check=True)

    def test_inject_text_pastes_with_osascript(self) -> None:
        with patch("app.platform.macos.copy_to_clipboard") as copy_mock, patch(
            "app.platform.macos.subprocess.run"
        ) as run, patch("app.platform.macos.time.sleep"):
            macos_platform.inject_text("hello")

        copy_mock.assert_called_once_with("hello")
        run.assert_called_once_with(
            [
                "osascript",
                "-e",
                'tell application "System Events" to keystroke "v" using command down',
            ],
            check=True,
        )

    def test_macos_hotkey_backend_maps_supported_keys(self) -> None:
        fake_keyboard = self._FakePynputKeyboard()
        backend = macos_platform.PynputHotkeyBackend(keyboard_module=fake_keyboard)
        received: list[HotkeyEvent] = []

        backend.start(received.append)
        listener = fake_keyboard.listeners[0]
        listener.on_press(fake_keyboard.Key.ctrl_r)
        listener.on_release(fake_keyboard.Key.shift_r)
        listener.on_press(fake_keyboard.Key.backspace)
        backend.stop()

        self.assertTrue(listener.started)
        self.assertTrue(listener.stopped)
        self.assertEqual(
            received,
            [
                HotkeyEvent(name="right ctrl", event_type="down"),
                HotkeyEvent(name="right shift", event_type="up"),
                HotkeyEvent(name="backspace", event_type="down"),
            ],
        )


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




