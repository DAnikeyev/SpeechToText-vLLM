from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from app.config import AppConfig, save_config
from app.tray import TrayApp
import app.tray as tray_module


class TrayAppRunTests(unittest.TestCase):
    def _make_tray_app(self) -> tuple[TrayApp, SimpleNamespace]:
        tray_app = TrayApp.__new__(TrayApp)
        app = SimpleNamespace(
            logger=MagicMock(),
            worker=MagicMock(),
            llm_monitor=MagicMock(),
            hotkeys=MagicMock(),
            shutdown=MagicMock(),
        )
        tray_app._app = app
        tray_app._icon = None
        tray_app._paused = False
        tray_app._build_menu = MagicMock(return_value="menu")
        tray_app._start_config_reload_watcher = MagicMock()
        tray_app._config_reload_stop = MagicMock()
        return tray_app, app

    def test_run_starts_hotkeys_before_tray_loop(self) -> None:
        tray_app, app = self._make_tray_app()

        with patch("app.tray._tint_icon", return_value="icon"), patch("app.tray.pystray.Icon") as icon_cls:
            icon = icon_cls.return_value
            TrayApp.run(tray_app)

        app.worker.start.assert_called_once_with()
        app.llm_monitor.start.assert_called_once_with()
        app.hotkeys.start.assert_called_once_with()
        tray_app._start_config_reload_watcher.assert_called_once_with()
        app.hotkeys.stop.assert_called_once_with()
        app.shutdown.assert_called_once_with()
        icon.run.assert_called_once_with()
        self.assertIs(tray_app._icon, icon)

    def test_run_stops_hotkeys_when_tray_loop_fails(self) -> None:
        tray_app, app = self._make_tray_app()

        with patch("app.tray._tint_icon", return_value="icon"), patch("app.tray.pystray.Icon") as icon_cls:
            icon_cls.return_value.run.side_effect = RuntimeError("tray failed")

            with self.assertRaisesRegex(RuntimeError, "tray failed"):
                TrayApp.run(tray_app)

        app.hotkeys.start.assert_called_once_with()
        app.llm_monitor.start.assert_called_once_with()
        tray_app._start_config_reload_watcher.assert_called_once_with()
        app.hotkeys.stop.assert_called_once_with()
        app.shutdown.assert_called_once_with()


class TrayIconTests(unittest.TestCase):
    def test_fit_icon_to_canvas_reduces_padding(self) -> None:
        source = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        for x in range(4, 12):
            for y in range(4, 12):
                source.putpixel((x, y), (255, 255, 255, 255))

        fitted = tray_module._fit_icon_to_canvas(source)
        source_bbox = source.getchannel("A").getbbox()
        fitted_bbox = fitted.getchannel("A").getbbox()

        self.assertEqual(fitted.size, source.size)
        self.assertEqual(source_bbox, (4, 4, 12, 12))
        self.assertIsNotNone(fitted_bbox)
        self.assertLessEqual(fitted_bbox[0], 1)
        self.assertLessEqual(fitted_bbox[1], 1)
        self.assertGreaterEqual(fitted_bbox[2], 15)
        self.assertGreaterEqual(fitted_bbox[3], 15)

    def test_tint_icon_preserves_alpha_and_applies_color(self) -> None:
        original_base_icon = tray_module._BASE_ICON
        try:
            base_icon = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
            base_icon.putpixel((0, 0), (255, 255, 255, 255))
            base_icon.putpixel((1, 0), (255, 255, 255, 0))
            tray_module._BASE_ICON = base_icon

            active_icon = tray_module._tint_icon(paused=False)
            paused_icon = tray_module._tint_icon(paused=True)

            self.assertEqual(active_icon.getpixel((0, 0))[3], 255)
            self.assertEqual(active_icon.getpixel((1, 0))[3], 0)
            self.assertGreater(active_icon.getpixel((0, 0))[1], active_icon.getpixel((0, 0))[0])
            self.assertGreater(paused_icon.getpixel((0, 0))[0], paused_icon.getpixel((0, 0))[1])
        finally:
            tray_module._BASE_ICON = original_base_icon


class TrayAboutTests(unittest.TestCase):
    def test_show_about_opens_help_window_with_text(self) -> None:
        tray_app = TrayApp.__new__(TrayApp)

        with patch.object(tray_app, "_show_text_window") as show_text_window, patch(
            "app.tray.build_about_text", return_value="about text"
        ):
            TrayApp._show_about(tray_app, None, None)

        show_text_window.assert_called_once_with(title="About SpeechToText-vLLM", text_content="about text")

    def test_run_text_window_configures_close_and_refresh(self) -> None:
        tray_app = TrayApp.__new__(TrayApp)
        root = MagicMock()
        root.winfo_exists.return_value = True
        text_widget = MagicMock()
        text_widget.yview.return_value = (0.0, 1.0)
        frame = MagicMock()
        button = MagicMock()

        with patch("app.tray.tk.Tk", return_value=root), patch(
            "app.tray.scrolledtext.ScrolledText", return_value=text_widget
        ), patch("app.tray.tk.Frame", return_value=frame), patch("app.tray.tk.Button", return_value=button) as button_cls:
            TrayApp._run_text_window(
                tray_app,
                title="Recent Logs",
                text_content="first line",
                geometry="900x480",
                content_provider=lambda: "updated line",
                refresh_interval_ms=250,
            )

        root.title.assert_called_once_with("Recent Logs")
        root.resizable.assert_called_once_with(True, True)
        root.geometry.assert_called_once_with("900x480")
        root.minsize.assert_called_once_with(420, 240)
        root.mainloop.assert_called_once_with()
        root.protocol.assert_called_once()
        self.assertEqual(root.protocol.call_args.args[0], "WM_DELETE_WINDOW")
        close_handler = root.protocol.call_args.args[1]
        self.assertTrue(callable(close_handler))
        button.pack.assert_called_once_with(side=tray_module.tk.RIGHT)
        self.assertEqual(button_cls.call_args.kwargs["command"], close_handler)
        text_widget.insert.assert_called_once_with("1.0", "updated line")
        root.after.assert_any_call(250, unittest.mock.ANY)

    def test_build_about_text_uses_platform_specific_labels(self) -> None:
        services = SimpleNamespace(key_modes={"right cmd": "restructure", "right shift": "answer"})

        with patch("app.tray.get_platform_services", return_value=services), patch(
            "app.tray.current_platform_name", return_value="macos"
        ):
            about = tray_module.build_about_text()

        self.assertIn("macOS dictation assistant", about)
        self.assertIn("Right Command", about)
        self.assertIn("Right Shift", about)
        self.assertIn("Command+V", about)
        self.assertIn("OpenRouter", about)
        self.assertIn("openai/gpt-oss-120b:free", about)
        self.assertIn("SPEECHTOTEXT_VLLM_API_KEY", about)

    def test_show_recent_logs_uses_log_text_window(self) -> None:
        tray_app = TrayApp.__new__(TrayApp)
        tray_app._app = SimpleNamespace(logger=SimpleNamespace(memory_handler=SimpleNamespace(get_entries=lambda: ["a", "b"])))

        with patch.object(tray_app, "_show_text_window") as show_text_window:
            TrayApp._show_recent_logs(tray_app, None, None)

        show_text_window.assert_called_once_with(
            title="Recent Logs",
            text_content="a\nb",
            geometry="900x480",
            content_provider=tray_app._get_recent_logs_text,
        )

    def test_reload_config_if_needed_applies_external_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            original = AppConfig()
            updated = AppConfig(model_name="reloaded-model", language_mode="ru")
            save_config(config_path, original)

            tray_app = TrayApp.__new__(TrayApp)
            tray_app._config_path = config_path
            tray_app._config = original
            tray_app._config_mtime_ns = tray_app._get_config_mtime_ns()
            tray_app._app = SimpleNamespace(apply_runtime_config=MagicMock(), logger=MagicMock())
            tray_app._refresh_menu = MagicMock()

            save_config(config_path, updated)

            changed = TrayApp._reload_config_if_needed(tray_app)

        self.assertTrue(changed)
        self.assertEqual(tray_app._config.model_name, "reloaded-model")
        self.assertEqual(tray_app._config.language_mode, "ru")
        tray_app._app.apply_runtime_config.assert_called_once()
        tray_app._refresh_menu.assert_called_once_with()

    def test_reload_config_if_needed_skips_invalid_json_until_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            original = AppConfig()
            save_config(config_path, original)

            tray_app = TrayApp.__new__(TrayApp)
            tray_app._config_path = config_path
            tray_app._config = original
            tray_app._config_mtime_ns = tray_app._get_config_mtime_ns()
            tray_app._app = SimpleNamespace(apply_runtime_config=MagicMock(), logger=MagicMock())
            tray_app._refresh_menu = MagicMock()

            config_path.write_text('{"model_name": ', encoding="utf-8")

            changed = TrayApp._reload_config_if_needed(tray_app)

        self.assertFalse(changed)
        tray_app._app.apply_runtime_config.assert_not_called()
        tray_app._app.logger.warning.assert_called_once()

    def test_get_recent_logs_text_handles_missing_and_empty_logs(self) -> None:
        tray_app = TrayApp.__new__(TrayApp)
        tray_app._app = SimpleNamespace(logger=SimpleNamespace())
        self.assertEqual(TrayApp._get_recent_logs_text(tray_app), "Recent log storage is not available.")

        tray_app._app = SimpleNamespace(logger=SimpleNamespace(memory_handler=SimpleNamespace(get_entries=lambda: [])))
        self.assertEqual(TrayApp._get_recent_logs_text(tray_app), "No log entries yet.")


if __name__ == "__main__":
    unittest.main()
