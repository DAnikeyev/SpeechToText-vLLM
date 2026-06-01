from __future__ import annotations

import json
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import scrolledtext, simpledialog

import sys

import sounddevice as sd
from PIL import Image, ImageEnhance, ImageOps

import pystray

from app.platform import current_platform_name, get_platform_services

_ICON_PATH = Path(__file__).parent / "mic.ico"
_BASE_ICON: Image.Image | None = None


def _format_hotkey_name(name: str) -> str:
    mapping = {
        "right ctrl": "Right Ctrl",
        "right shift": "Right Shift",
        "right cmd": "Right Command",
        "right alt": "Right Option",
    }
    return mapping.get(name, name.title())


def _hotkey_labels() -> dict[str, str]:
    services = get_platform_services()
    return {mode: _format_hotkey_name(key) for key, mode in services.key_modes.items()}


def build_about_text() -> str:
    platform_name = current_platform_name()
    labels = _hotkey_labels()
    restructure_key = labels.get("restructure", "Primary key")
    answer_key = labels.get("answer", "Secondary key")
    paste_shortcut = "Ctrl+V" if platform_name == "windows" else "Command+V"
    location = "system tray" if platform_name == "windows" else "menu bar"
    platform_label = "Windows" if platform_name == "windows" else "macOS"
    return f"""SpeechToText-vLLM

{platform_label} dictation assistant with shared speech and OpenAI-compatible LLM pipeline.

Hotkeys
- {restructure_key}: single hold -> transcribe, clean with LLM, insert and copy to clipboard
- {restructure_key}: double-press then hold -> transcribe, clean with LLM, copy to clipboard
- {restructure_key}: triple-press then hold -> transcribe only, skip vLLM, insert and copy raw text
- {answer_key}: single hold -> transcribe, answer with vLLM, insert and copy to clipboard
- {answer_key}: double-press then hold -> transcribe, answer with vLLM, copy to clipboard

LLM defaults
- Hosted default: OpenRouter at https://openrouter.ai/api/v1
- Default hosted model: openai/gpt-oss-120b:free
- API key: set llm_api_key in config.json or use SPEECHTOTEXT_VLLM_API_KEY
- Compatibility presets: Hosted OpenAI-compatible, Ollama, and vLLM / Qwen

Tips
- The icon is green when active and red when paused.
- Open the {location} icon to change microphone, language, LLM server URL, or compatibility preset.
- Press Backspace while processing to cancel the current analysis/output.
- Text insertion pastes from the clipboard ({paste_shortcut}) for better editor compatibility.
"""


def _fit_icon_to_canvas(img: Image.Image, margin: int = 0) -> Image.Image:
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return rgba

    left, top, right, bottom = bbox
    if (left, top, right, bottom) == (0, 0, rgba.width, rgba.height):
        return rgba

    cropped = rgba.crop(bbox)
    target_width = max(1, rgba.width - margin * 2)
    target_height = max(1, rgba.height - margin * 2)
    scale = min(target_width / cropped.width, target_height / cropped.height)
    resized = cropped.resize(
        (max(1, int(round(cropped.width * scale))), max(1, int(round(cropped.height * scale)))),
        Image.Resampling.LANCZOS,
    )

    fitted = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    offset_x = (rgba.width - resized.width) // 2
    offset_y = (rgba.height - resized.height) // 2
    fitted.paste(resized, (offset_x, offset_y), resized)
    return fitted


def _resolve_icon_path() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "app" / "mic.ico"
    return Path(__file__).parent / "mic.ico"


def _load_base_icon() -> Image.Image:
    global _BASE_ICON
    if _BASE_ICON is None:
        _BASE_ICON = _fit_icon_to_canvas(Image.open(_resolve_icon_path()))
    return _BASE_ICON


def _tint_icon(paused: bool = False) -> Image.Image:
    img = _load_base_icon().copy()
    alpha = img.getchannel("A")
    luminance = ImageOps.grayscale(img)

    if paused:
        dark_color = (90, 20, 20)
        light_color = (220, 50, 50)
    else:
        dark_color = (20, 60, 30)
        light_color = (50, 200, 80)

    tinted = ImageOps.colorize(luminance, black=dark_color, white=light_color).convert("RGBA")
    tinted.putalpha(alpha)

    enhancer = ImageEnhance.Color(tinted)
    tinted = enhancer.enhance(1.4 if paused else 1.2)

    return tinted


def _list_input_devices() -> list[tuple[int, str]]:
    devices = sd.query_devices()
    result: list[tuple[int, str]] = []
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) > 0:
            result.append((i, d["name"]))
    return result


class TrayApp:
    def __init__(self, *, config_path: Path) -> None:
        from app.config import load_config
        from app.main import DictationApp

        self._config_path = config_path
        self._config = load_config(config_path)
        self._app = DictationApp(config=self._config, base_dir=config_path.parent)
        self._paused = False
        self._ctrl_enabled = True
        self._shift_enabled = True
        self._icon: pystray.Icon | None = None
        self._config_reload_stop = threading.Event()
        self._config_reload_thread: threading.Thread | None = None
        self._config_mtime_ns = self._get_config_mtime_ns()

    def run(self) -> None:
        self._app.logger.info("Starting dictation assistant (tray mode)")
        self._app.worker.start()
        self._app.llm_monitor.start()
        hotkeys_started = False
        try:
            self._app.hotkeys.start()
            hotkeys_started = True
        except Exception as exc:
            self._paused = True
            self._app.logger.exception(
                "Failed to start global hotkeys; running in paused mode so the app stays open: %s",
                exc,
            )
        self._start_config_reload_watcher()
        icon = pystray.Icon(
            "dictation",
            icon=_tint_icon(paused=self._paused),
            title="Dictation Assistant",
            menu=self._build_menu(),
        )
        self._icon = icon
        try:
            icon.run()
        finally:
            self._config_reload_stop.set()
            if hotkeys_started:
                self._app.hotkeys.stop()
            self._app.shutdown()

    def _get_config_mtime_ns(self) -> int | None:
        try:
            return self._config_path.stat().st_mtime_ns
        except OSError:
            return None

    def _start_config_reload_watcher(self) -> None:
        if self._config_reload_thread is not None and self._config_reload_thread.is_alive():
            return
        self._config_reload_stop.clear()
        self._config_reload_thread = threading.Thread(
            target=self._watch_config_reload_loop,
            daemon=True,
            name="config-reload-watcher",
        )
        self._config_reload_thread.start()

    def _watch_config_reload_loop(self) -> None:
        while not self._config_reload_stop.wait(timeout=1.0):
            self._reload_config_if_needed()

    def _reload_config_if_needed(self) -> bool:
        current_mtime_ns = self._get_config_mtime_ns()
        if current_mtime_ns is None or current_mtime_ns == self._config_mtime_ns:
            return False

        try:
            from app.config import load_config

            updated_config = load_config(self._config_path)
        except (OSError, json.JSONDecodeError) as exc:
            self._app.logger.warning("Config reload skipped; file is not ready yet: %s", exc)
            return False

        self._config_mtime_ns = current_mtime_ns
        if updated_config.to_dict() == self._config.to_dict():
            return False

        self._apply_config(updated_config)
        return True

    def _apply_config(self, config) -> None:
        self._config = config
        self._app.apply_runtime_config(config)
        self._refresh_menu()

    def _build_menu(self) -> pystray.Menu:
        current_device = self._config.microphone_device
        labels = _hotkey_labels()

        def make_mic_items() -> list[pystray.MenuItem]:
            devices = _list_input_devices()
            items: list[pystray.MenuItem] = []
            items.append(pystray.MenuItem(
                "Default",
                lambda _icon, _item: self._set_mic(None),
                checked=lambda _item: current_device is None,
            ))
            for idx, name in devices:
                def _make_select(dev_idx: int):
                    def _handler(_icon, _item):
                        self._set_mic(dev_idx)
                    return _handler

                def _make_checked(dev_idx: int, cur_dev):
                    def _check(_item):
                        return cur_dev == dev_idx
                    return _check

                items.append(pystray.MenuItem(
                    f"{idx}: {name[:40]}",
                    _make_select(idx),
                    checked=_make_checked(idx, current_device),
                ))
            return items

        def make_lang_items() -> list[pystray.MenuItem]:
            items: list[pystray.MenuItem] = []
            builtin = [("Auto", "auto"), ("Auto-detected", "auto-detected")]
            all_langs = builtin + [
                (entry.get("label", entry["code"]), entry["code"])
                for entry in self._config.languages
            ]
            for label, code in all_langs:

                def _make_lang_select(lang_code: str):
                    def _handler(_icon, _item):
                        self._set_language(lang_code)
                    return _handler

                def _make_lang_checked(lang_code: str):
                    def _check(_item):
                        return self._config.language_mode == lang_code
                    return _check

                items.append(pystray.MenuItem(
                    label,
                    _make_lang_select(code),
                    checked=_make_lang_checked(code),
                ))
            return items

        return pystray.Menu(
            pystray.MenuItem(
                f"{labels.get('restructure', 'Primary key')} (restructure)",
                self._toggle_ctrl,
                checked=lambda _i: self._ctrl_enabled,
            ),
            pystray.MenuItem(
                f"{labels.get('answer', 'Secondary key')} (answer)",
                self._toggle_shift,
                checked=lambda _i: self._shift_enabled,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Microphone",
                pystray.Menu(*make_mic_items()),
            ),
            pystray.MenuItem(
                "Language",
                pystray.Menu(*make_lang_items()),
            ),
            pystray.MenuItem(
                "LLM Server URL...",
                self._configure_vllm_url,
            ),
            pystray.MenuItem(
                "LLM Compatibility...",
                self._configure_llm_compatibility,
            ),
            pystray.MenuItem(
                "About",
                self._show_about,
            ),
            pystray.MenuItem(
                "Recent Logs",
                self._show_recent_logs,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Pause" if not self._paused else "Resume",
                self._toggle_pause,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._exit),
        )

    def _refresh_menu(self) -> None:
        if self._icon:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()

    def _update_icon_image(self) -> None:
        if self._icon:
            self._icon.icon = _tint_icon(paused=self._paused)

    def _toggle_ctrl(self, _icon, _item) -> None:
        self._ctrl_enabled = not self._ctrl_enabled
        self._app.hotkeys.enable_mode("restructure", self._ctrl_enabled)
        self._refresh_menu()

    def _toggle_shift(self, _icon, _item) -> None:
        self._shift_enabled = not self._shift_enabled
        self._app.hotkeys.enable_mode("answer", self._shift_enabled)
        self._refresh_menu()

    def _set_language(self, code: str) -> None:
        self._config.language_mode = code
        self._app.transcriber.language_mode = code
        self._save_config()
        self._refresh_menu()

    def _set_mic(self, device: int | None) -> None:
        self._config.microphone_device = device
        self._app.recorder.device = device
        self._save_config()
        self._refresh_menu()

    def _configure_vllm_url(self, _icon, _item) -> None:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            result = simpledialog.askstring(
                "LLM Server URL",
                "Enter LLM server URL:",
                initialvalue=self._config.vllm_url,
                parent=root,
            )
        finally:
            root.quit()
            root.destroy()
        if result is not None and result.strip():
            normalized = result.strip() + ("/v1" if not result.strip().endswith("/v1") else "")
            self._app.update_llm_endpoint(normalized)
            self._save_config()

    def _configure_llm_compatibility(self, _icon, _item) -> None:
        import json
        from tkinter import messagebox

        _PRESETS = {
            "Hosted OpenAI-compatible (OpenRouter default)": {"extra_body": None, "strict": True},
            "Ollama": {"extra_body": None, "strict": False},
            "vLLM / Qwen": {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}, "strict": True},
        }

        def _guess_preset():
            current_extra = self._config.llm_extra_body
            current_strict = self._config.llm_strict_model_name_match
            for label, cfg in _PRESETS.items():
                if current_strict == cfg["strict"] and current_extra == cfg["extra_body"]:
                    return label
            return "Custom"

        root = tk.Tk()
        root.title("LLM Compatibility")
        root.attributes("-topmost", True)
        root.resizable(False, False)

        tk.Label(root, text="Server preset:", anchor="w").pack(fill="x", padx=12, pady=(12, 0))
        preset_var = tk.StringVar(value=_guess_preset())
        preset_options = list(_PRESETS.keys()) + ["Custom"]
        preset_menu = tk.OptionMenu(root, preset_var, *preset_options)
        preset_menu.pack(fill="x", padx=12, pady=(0, 8))

        strict_var = tk.BooleanVar(value=self._config.llm_strict_model_name_match)
        strict_check = tk.Checkbutton(root, text="Exact model name match", variable=strict_var, anchor="w")
        strict_check.pack(fill="x", padx=12, pady=(0, 8))

        tk.Label(root, text="Extra request body JSON:", anchor="w").pack(fill="x", padx=12, pady=(0, 0))
        text_widget = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=50, height=8, padx=8, pady=8)
        text_widget.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        def _on_preset_change(*_):
            label = preset_var.get()
            if label in _PRESETS:
                cfg = _PRESETS[label]
                strict_var.set(cfg["strict"])
                text_widget.configure(state=tk.NORMAL)
                text_widget.delete("1.0", tk.END)
                text_widget.insert("1.0", json.dumps(cfg["extra_body"], indent=2) if cfg["extra_body"] else "")
                text_widget.configure(state=tk.DISABLED)
            else:
                text_widget.configure(state=tk.NORMAL)

        preset_var.trace_add("write", _on_preset_change)

        if preset_var.get() == "Custom":
            text_widget.insert("1.0", json.dumps(self._config.llm_extra_body, indent=2) if self._config.llm_extra_body else "")
        else:
            _on_preset_change()

        def _save():
            label = preset_var.get()
            strict = strict_var.get()
            if label in _PRESETS:
                extra_body = _PRESETS[label]["extra_body"]
            else:
                raw = text_widget.get("1.0", tk.END).strip()
                if not raw:
                    extra_body = None
                else:
                    try:
                        extra_body = json.loads(raw)
                        if not isinstance(extra_body, dict):
                            messagebox.showerror("Invalid JSON", "Extra body must be a JSON object.", parent=root)
                            return
                    except json.JSONDecodeError as exc:
                        messagebox.showerror("Invalid JSON", f"Failed to parse extra body:\n{exc}", parent=root)
                        return

            self._config.llm_strict_model_name_match = strict
            self._config.llm_extra_body = extra_body
            self._app.update_llm_settings(extra_body=extra_body, strict_model_name_match=strict)
            self._save_config()
            root.destroy()

        def _cancel():
            root.destroy()

        btn_frame = tk.Frame(root)
        btn_frame.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(btn_frame, text="Cancel", command=_cancel, width=10).pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(btn_frame, text="Save", command=_save, width=10).pack(side=tk.RIGHT)

        root.mainloop()

    def _show_text_window(
        self,
        *,
        title: str,
        text_content: str,
        geometry: str = "560x360",
        content_provider: Callable[[], str] | None = None,
        refresh_interval_ms: int = 1000,
    ) -> None:
        threading.Thread(
            target=self._run_text_window,
            kwargs={
                "title": title,
                "text_content": text_content,
                "geometry": geometry,
                "content_provider": content_provider,
                "refresh_interval_ms": refresh_interval_ms,
            },
            daemon=True,
            name=f"{title}-window",
        ).start()

    def _run_text_window(
        self,
        *,
        title: str,
        text_content: str,
        geometry: str = "560x360",
        content_provider: Callable[[], str] | None = None,
        refresh_interval_ms: int = 1000,
    ) -> None:
        root = tk.Tk()
        root.title(title)
        root.resizable(True, True)
        root.geometry(geometry)
        root.minsize(420, 240)
        root.attributes("-topmost", True)

        def _clear_topmost() -> None:
            try:
                if root.winfo_exists():
                    root.attributes("-topmost", False)
            except tk.TclError:
                pass

        root.after(250, _clear_topmost)

        def _close_window() -> None:
            try:
                root.quit()
            except tk.TclError:
                pass
            try:
                if root.winfo_exists():
                    root.destroy()
            except tk.TclError:
                pass

        root.protocol("WM_DELETE_WINDOW", _close_window)

        text = scrolledtext.ScrolledText(root, wrap=tk.WORD, padx=12, pady=12)
        text.pack(fill=tk.BOTH, expand=True)

        current_content = ""

        def _refresh_text() -> None:
            nonlocal current_content
            try:
                if not root.winfo_exists():
                    return
            except tk.TclError:
                return

            next_content = content_provider() if content_provider is not None else text_content
            if next_content != current_content:
                yview = text.yview()
                should_follow_end = yview[1] >= 0.999 if current_content else True
                text.configure(state=tk.NORMAL)
                text.delete("1.0", tk.END)
                text.insert("1.0", next_content)
                text.configure(state=tk.DISABLED)
                if should_follow_end:
                    text.see(tk.END)
                else:
                    text.yview_moveto(yview[0])
                current_content = next_content

            if content_provider is not None:
                try:
                    if root.winfo_exists():
                        root.after(refresh_interval_ms, _refresh_text)
                except tk.TclError:
                    return

        _refresh_text()

        button_frame = tk.Frame(root)
        button_frame.pack(fill=tk.X, padx=12, pady=(0, 12))
        tk.Button(button_frame, text="Close", command=_close_window, width=10).pack(side=tk.RIGHT)

        root.mainloop()

    def _show_about(self, _icon, _item) -> None:
        self._show_text_window(title="About SpeechToText-vLLM", text_content=build_about_text())

    def _show_recent_logs(self, _icon, _item) -> None:
        log_text = self._get_recent_logs_text()
        self._show_text_window(
            title="Recent Logs",
            text_content=log_text,
            geometry="900x480",
            content_provider=self._get_recent_logs_text,
        )

    def _toggle_pause(self, _icon, _item) -> None:
        self._paused = not self._paused
        if self._paused:
            self._app.hotkeys.stop()
            self._app.logger.info("Paused")
        else:
            try:
                self._app.hotkeys.start()
                self._app.logger.info("Resumed")
            except Exception as exc:
                self._paused = True
                self._app.logger.exception("Failed to resume hotkeys: %s", exc)
        self._update_icon_image()
        self._refresh_menu()

    def _exit(self, _icon, _item) -> None:
        self._app.logger.info("Exiting from tray")
        self._app.shutdown()
        if self._icon:
            self._icon.stop()

    def _save_config(self) -> None:
        from app.config import save_config
        save_config(self._config_path, self._config)
        self._config_mtime_ns = self._get_config_mtime_ns()

    def _get_recent_logs_text(self) -> str:
        memory_handler = getattr(self._app.logger, "memory_handler", None)
        if memory_handler is None:
            return "Recent log storage is not available."

        entries = memory_handler.get_entries()
        if not entries:
            return "No log entries yet."
        return "\n".join(entries)