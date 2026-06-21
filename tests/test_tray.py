from __future__ import annotations

import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app.tray as tray_module
from app.tray import TrayApp


class TrayAppRunTests(unittest.TestCase):
    def _make_tray_app(self) -> tuple[TrayApp, SimpleNamespace]:
        tray_app = TrayApp.__new__(TrayApp)
        app = SimpleNamespace(
            logger=MagicMock(),
            worker=MagicMock(),
            llm_monitor=MagicMock(),
            hotkeys=MagicMock(),
            shutdown=MagicMock(),
            _processing=False,
            stop_event=Event(),
        )
        tray_app._app = app
        tray_app._icon = None
        tray_app._paused = False
        tray_app._build_menu = MagicMock(return_value="menu")
        tray_app._config_watcher = MagicMock()
        tray_app._start_qt = MagicMock()
        tray_app._stop_qt = MagicMock()
        tray_app._open_windows = []
        tray_app._named_windows = {}
        return tray_app, app

    def test_run_starts_hotkeys_before_tray_loop(self) -> None:
        tray_app, app = self._make_tray_app()

        with (
            patch("app.tray.tint_icon", return_value="icon"),
            patch("app.tray.pystray.Icon") as icon_cls,
        ):
            icon = icon_cls.return_value
            TrayApp.run(tray_app)

        app.worker.start.assert_called_once_with()
        app.llm_monitor.start.assert_called_once_with()
        app.hotkeys.start.assert_called_once_with()
        tray_app._config_watcher.start.assert_called_once_with()
        app.hotkeys.stop.assert_called_once_with()
        app.shutdown.assert_called_once_with()
        icon.run.assert_called_once_with()
        self.assertIs(tray_app._icon, icon)

    def test_run_stops_hotkeys_when_tray_loop_fails(self) -> None:
        tray_app, app = self._make_tray_app()

        with (
            patch("app.tray.tint_icon", return_value="icon"),
            patch("app.tray.pystray.Icon") as icon_cls,
        ):
            icon_cls.return_value.run.side_effect = RuntimeError("tray failed")

            with self.assertRaisesRegex(RuntimeError, "tray failed"):
                TrayApp.run(tray_app)

        app.hotkeys.start.assert_called_once_with()
        app.llm_monitor.start.assert_called_once_with()
        tray_app._config_watcher.start.assert_called_once_with()
        app.hotkeys.stop.assert_called_once_with()
        app.shutdown.assert_called_once_with()

    def test_run_keeps_tray_alive_when_hotkeys_fail_to_start(self) -> None:
        tray_app, app = self._make_tray_app()
        app.hotkeys.start.side_effect = RuntimeError("hotkey init failed")

        with (
            patch("app.tray.tint_icon", return_value="icon") as tint_icon,
            patch("app.tray.pystray.Icon") as icon_cls,
        ):
            icon = icon_cls.return_value
            TrayApp.run(tray_app)

        self.assertTrue(tray_app._paused)
        app.logger.exception.assert_called_once()
        tint_icon.assert_called_once_with(paused=True)
        app.hotkeys.stop.assert_not_called()
        icon.run.assert_called_once_with()
        app.shutdown.assert_called_once_with()


class TrayAboutTests(unittest.TestCase):
    def test_show_about_opens_help_window_with_text(self) -> None:
        tray_app = TrayApp.__new__(TrayApp)

        with (
            patch.object(tray_app, "_show_text_window") as show_text_window,
            patch("app.tray.build_about_text", return_value="about text"),
        ):
            TrayApp._show_about(tray_app, None, None)

        show_text_window.assert_called_once_with(
            title="About SpeechToText-vLLM", text_content="about text"
        )

    def test_register_window_tracks_and_forgets_destroyed_windows(self) -> None:
        tray_app = TrayApp.__new__(TrayApp)
        tray_app._open_windows = []
        window = MagicMock()
        destroyed = MagicMock()
        window.destroyed = destroyed

        TrayApp._register_window(tray_app, window)

        self.assertEqual(tray_app._open_windows, [window])
        destroyed.connect.assert_called_once()
        forget_callback = destroyed.connect.call_args.args[0]
        forget_callback()
        self.assertEqual(tray_app._open_windows, [])

    def test_show_text_window_qt_registers_and_presents_window(self) -> None:
        tray_app = TrayApp.__new__(TrayApp)
        tray_app._open_windows = []
        tray_app._named_windows = {}

        with (
            patch("app.tray.TextWindow") as text_window_cls,
            patch.object(tray_app, "_register_window") as register_window,
            patch.object(tray_app, "_present_window") as present_window,
        ):
            window = text_window_cls.return_value

            TrayApp._show_text_window_qt(
                tray_app,
                title="Recent Logs",
                text_content="first line",
                geometry="900x480",
                content_provider=None,
                refresh_interval_ms=250,
            )

        text_window_cls.assert_called_once_with(
            None,
            title="Recent Logs",
            text_content="first line",
            geometry="900x480",
            content_provider=None,
            refresh_interval_ms=250,
        )
        register_window.assert_called_once_with(window, key="Recent Logs")
        present_window.assert_called_once_with(window)

    def test_build_about_text_uses_platform_specific_labels(self) -> None:
        services = SimpleNamespace(key_modes={"right ctrl": "restructure", "right shift": "answer"})

        with patch("app.tray.get_platform_services", return_value=services):
            about = tray_module.build_about_text()

        self.assertIn("Windows dictation assistant", about)
        self.assertIn("Right Ctrl", about)
        self.assertIn("Right Shift", about)
        self.assertIn("Ctrl+V", about)
        self.assertIn("OpenRouter", about)
        self.assertIn("openai/gpt-oss-120b:free", about)
        self.assertIn("SPEECHTOTEXT_VLLM_API_KEY", about)

    def test_show_recent_logs_uses_log_text_window(self) -> None:
        tray_app = TrayApp.__new__(TrayApp)
        tray_app._app = SimpleNamespace(
            memory_handler=SimpleNamespace(get_entries=lambda: ["a", "b"])
        )

        with patch.object(tray_app, "_show_text_window") as show_text_window:
            TrayApp._show_recent_logs(tray_app, None, None)

        show_text_window.assert_called_once_with(
            title="Recent Logs",
            text_content="a\nb",
            geometry="900x480",
            content_provider=tray_app._get_recent_logs_text,
        )

    def test_get_recent_logs_text_handles_missing_and_empty_logs(self) -> None:
        tray_app = TrayApp.__new__(TrayApp)
        tray_app._app = SimpleNamespace()
        self.assertEqual(
            TrayApp._get_recent_logs_text(tray_app), "Recent log storage is not available."
        )

        tray_app._app = SimpleNamespace(memory_handler=SimpleNamespace(get_entries=list))
        self.assertEqual(TrayApp._get_recent_logs_text(tray_app), "No log entries yet.")


if __name__ == "__main__":
    unittest.main()
