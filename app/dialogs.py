from __future__ import annotations

import json
import logging
import ssl
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from app.llm import fetch_model_names
from PySide6 import QtCore, QtGui, QtWidgets

_logger = logging.getLogger(__name__)

_PRESETS: dict[str, dict] = {
    "Hosted OpenAI-compatible (OpenRouter default)": {"extra_body": None, "strict": True},
    "Ollama": {"extra_body": None, "strict": False},
    "vLLM / Qwen": {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        "strict": True,
    },
}


def normalize_llm_url(raw_url: str) -> str:
    normalized = raw_url.strip()
    if not normalized:
        return ""

    # Auto-add http:// when the user omits a scheme (e.g. "localhost:8000").
    if "://" not in normalized:
        normalized = f"http://{normalized}"

    parts = urlsplit(normalized)
    path = parts.path.rstrip("/")
    if not path.endswith("/v1"):
        path = f"{path}/v1" if path else "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


class _CheckLLMSignal(QtCore.QObject):
    """Signal bundle emitted by :class:`_CheckLLMWorker`."""
    finished = QtCore.Signal(bool, str, list)  # success, message, model_names


class _CheckLLMWorker(QtCore.QRunnable):
    """Off-main-thread probe that tries to list models on the LLM endpoint."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.setAutoDelete(True)
        self.signals = _CheckLLMSignal()

    def run(self) -> None:  # noqa: D401
        try:
            all_names = fetch_model_names(self.base_url, timeout_seconds=10.0)
            short = all_names[:5]
            suffix = f" ({len(all_names)} total)" if len(all_names) > 5 else ""
            msg = "OK — models: " + ", ".join(short) + suffix
            self.signals.finished.emit(True, msg, all_names)
        except ssl.SSLError as exc:
            self.signals.finished.emit(False, f"SSL error: {exc}", [])
        except Exception as exc:
            err_text = str(exc)
            if len(err_text) > 200:
                err_text = err_text[:200] + "…"
            self.signals.finished.emit(False, f"Connection failed: {err_text}", [])


class _FramelessPanelMixin:
    def _apply_window_style(self) -> None:
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self.setStyleSheet(
            """
            QDialog {
                background-color: #16181d;
                color: #f4f7fb;
            }
            QLabel {
                color: #eef2f8;
            }
            QLabel[role="hint"] {
                color: #a7b0c0;
            }
            QLineEdit, QPlainTextEdit, QComboBox {
                background-color: #20242c;
                border: 1px solid #3a4354;
                border-radius: 8px;
                color: #f4f7fb;
                padding: 8px 10px;
                selection-background-color: #2d8cff;
            }
            QPlainTextEdit {
                padding: 10px;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QCheckBox {
                spacing: 8px;
            }
            QPushButton {
                background-color: #2b3140;
                border: 1px solid #465068;
                border-radius: 8px;
                color: #f4f7fb;
                min-height: 18px;
                padding: 8px 14px;
            }
            QPushButton:hover {
                background-color: #333c4f;
            }
            QPushButton:pressed {
                background-color: #222834;
            }
            QPushButton[accent="true"] {
                background-color: #2d8cff;
                border-color: #2d8cff;
                color: white;
            }
            QPushButton[accent="true"]:hover {
                background-color: #1f7aeb;
            }
            QDialogButtonBox {
                button-layout: 0;
            }
            """
        )

    def _build_header(
        self,
        layout: QtWidgets.QVBoxLayout,
        *,
        title: str,
        subtitle: str | None = None,
    ) -> None:
        title_label = QtWidgets.QLabel(title)
        title_font = title_label.font()
        title_font.setPointSize(title_font.pointSize() + 4)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QtWidgets.QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            subtitle_label.setProperty("role", "hint")
            layout.addWidget(subtitle_label)

    def _present_window(self) -> None:
        self.show()
        if self.windowState() & QtCore.Qt.WindowState.WindowMinimized:
            self.setWindowState(self.windowState() & ~QtCore.Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()


class LLMUrlDialog(_FramelessPanelMixin, QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None, current_url: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("LLM Server URL")
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.resize(600, 310)
        self.setMinimumWidth(500)
        self._apply_window_style()

        self._thread_pool = QtCore.QThreadPool.globalInstance()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        self._build_header(
            layout,
            title="LLM Server URL",
            subtitle="Point the app to your OpenAI-compatible server. `/v1` will be appended automatically when missing.",
        )

        label = QtWidgets.QLabel("Server address")
        layout.addWidget(label)

        url_row = QtWidgets.QHBoxLayout()
        url_row.setSpacing(8)
        self._url_edit = QtWidgets.QLineEdit(current_url)
        self._url_edit.setPlaceholderText("http://127.0.0.1:8000/v1")
        self._url_edit.returnPressed.connect(self._save)
        url_row.addWidget(self._url_edit)

        self._check_btn = QtWidgets.QPushButton("Check")
        self._check_btn.setFixedWidth(80)
        self._check_btn.clicked.connect(self._start_check)
        url_row.addWidget(self._check_btn)
        layout.addLayout(url_row)

        # Status indicator row — icon + message label.
        status_row = QtWidgets.QHBoxLayout()
        status_row.setSpacing(6)
        self._status_icon = QtWidgets.QLabel("●")
        self._status_icon.setFixedWidth(20)
        status_row.addWidget(self._status_icon)
        self._status_label = QtWidgets.QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setProperty("role", "hint")
        self._status_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        status_row.addWidget(self._status_label, stretch=1)
        layout.addLayout(status_row)

        hint = QtWidgets.QLabel("Examples: `http://localhost:8000`, `https://openrouter.ai/api`.")
        hint.setProperty("role", "hint")
        layout.addWidget(hint)

        button_box = QtWidgets.QDialogButtonBox()
        self._save_button = button_box.addButton(
            "Save", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._save_button.setProperty("accent", "true")
        self._cancel_button = button_box.addButton(
            "Cancel", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole
        )
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._normalized_url = normalize_llm_url(current_url) or current_url
        self._last_model_names: list[str] = []
        QtCore.QTimer.singleShot(0, self._focus_url_edit)

    def _focus_url_edit(self) -> None:
        self._present_window()
        self._url_edit.setFocus(QtCore.Qt.FocusReason.ActiveWindowFocusReason)
        self._url_edit.selectAll()

    def _start_check(self) -> None:
        raw_url = self._url_edit.text().strip()
        if not raw_url:
            self._set_status(None, "Enter a URL first.")
            return
        normalized = normalize_llm_url(raw_url)
        if not normalized:
            self._set_status(False, "Could not parse the URL.")
            return

        self._check_btn.setEnabled(False)
        self._check_btn.setText("…")
        self._set_status(None, "Checking…")
        self._set_status_icon_color("#f4c542")  # yellow — pending

        worker = _CheckLLMWorker(normalized)
        worker.signals.finished.connect(self._on_check_finished)
        self._thread_pool.start(worker)

    def _on_check_finished(self, success: bool, message: str, model_names: list[str]) -> None:
        self._check_btn.setEnabled(True)
        self._check_btn.setText("Check")
        self._last_model_names = model_names
        if success:
            self._set_status(True, message)
        else:
            self._set_status(False, message)

    def _set_status(self, success: bool | None, text: str) -> None:
        self._status_label.setText(text)
        if success is True:
            self._set_status_icon_color("#4caf50")  # green
        elif success is False:
            self._set_status_icon_color("#e53935")  # red
        else:
            self._set_status_icon_color("#f4c542")  # yellow — pending

    def _set_status_icon_color(self, color: str) -> None:
        self._status_icon.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: bold;")

    def _save(self) -> None:
        raw_url = self._url_edit.text().strip()
        if not raw_url:
            QtWidgets.QMessageBox.critical(self, "Missing URL", "Please enter an LLM server URL.")
            return

        self._normalized_url = normalize_llm_url(raw_url)
        self.accept()

    @property
    def normalized_url(self) -> str:
        return self._normalized_url


class LLMCompatibilityDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        current_extra_body: dict | None,
        current_strict: bool,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("LLM Compatibility")
        self.resize(560, 420)
        self.setMinimumWidth(500)
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        _FramelessPanelMixin._apply_window_style(self)

        self._result_extra_body: dict | None = current_extra_body
        self._result_strict: bool = current_strict

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        _FramelessPanelMixin._build_header(
            self,
            layout,
            title="LLM Compatibility",
            subtitle="Choose the request format that best matches your server so completion requests stay compatible and predictable.",
        )

        preset_label = QtWidgets.QLabel("Server preset:")
        layout.addWidget(preset_label)

        self._preset_combo = QtWidgets.QComboBox()
        self._preset_combo.addItems([*_PRESETS, "Custom"])
        self._preset_combo.currentTextChanged.connect(self._on_preset_changed)
        layout.addWidget(self._preset_combo)

        self._strict_check = QtWidgets.QCheckBox("Exact model name match")
        self._strict_check.setChecked(current_strict)
        layout.addWidget(self._strict_check)

        extra_label = QtWidgets.QLabel("Extra request body JSON:")
        layout.addWidget(extra_label)

        self._json_edit = QtWidgets.QPlainTextEdit()
        self._json_edit.setPlaceholderText("Enter JSON object (optional)")
        self._json_edit.setTabChangesFocus(True)
        font = QtGui.QFont("Consolas", 10)
        font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        self._json_edit.setFont(font)
        layout.addWidget(self._json_edit, stretch=1)

        button_box = QtWidgets.QDialogButtonBox()
        save_button = button_box.addButton("Save", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        save_button.setProperty("accent", "true")
        button_box.addButton("Cancel", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._set_preset_by_values(current_extra_body, current_strict)
        QtCore.QTimer.singleShot(0, self._focus_primary_input)

    def _focus_primary_input(self) -> None:
        _FramelessPanelMixin._present_window(self)
        self._preset_combo.setFocus(QtCore.Qt.FocusReason.ActiveWindowFocusReason)

    def _set_preset_by_values(self, extra_body: dict | None, strict: bool) -> None:
        for label, cfg in _PRESETS.items():
            if strict == cfg["strict"] and extra_body == cfg["extra_body"]:
                idx = self._preset_combo.findText(label)
                if idx >= 0:
                    self._preset_combo.setCurrentIndex(idx)
                return
        idx = self._preset_combo.findText("Custom")
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)

    def _on_preset_changed(self, label: str) -> None:
        if label in _PRESETS:
            cfg = _PRESETS[label]
            self._strict_check.setChecked(cfg["strict"])
            self._json_edit.setPlainText(
                json.dumps(cfg["extra_body"], indent=2) if cfg["extra_body"] else ""
            )
            self._json_edit.setReadOnly(True)
        else:
            self._json_edit.setReadOnly(False)

    def _save(self) -> None:
        label = self._preset_combo.currentText()
        strict = self._strict_check.isChecked()

        if label in _PRESETS:
            self._result_extra_body = _PRESETS[label]["extra_body"]
        else:
            raw = self._json_edit.toPlainText().strip()
            if not raw:
                self._result_extra_body = None
            else:
                try:
                    parsed = json.loads(raw)
                    if not isinstance(parsed, dict):
                        QtWidgets.QMessageBox.critical(
                            self, "Invalid JSON", "Extra body must be a JSON object."
                        )
                        return
                    self._result_extra_body = parsed
                except json.JSONDecodeError as exc:
                    QtWidgets.QMessageBox.critical(
                        self, "Invalid JSON", f"Failed to parse extra body:\n{exc}"
                    )
                    return

        self._result_strict = strict
        self.accept()

    @property
    def result_extra_body(self) -> dict | None:
        return self._result_extra_body

    @property
    def result_strict(self) -> bool:
        return self._result_strict


class ModelPickerDialog(_FramelessPanelMixin, QtWidgets.QDialog):
    """Modal dialog that lets the user pick a model from a remote server."""

    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        model_names: list[str],
        current_model: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Model")
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.resize(520, 440)
        self.setMinimumWidth(460)
        self._apply_window_style()

        self._result_model: str = current_model

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        self._build_header(
            layout,
            title="Select Model",
            subtitle=f"{len(model_names)} model(s) found on the server. Choose one to use.",
        )

        self._model_list = QtWidgets.QListWidget()
        self._model_list.setAlternatingRowColors(True)
        for name in model_names:
            item = QtWidgets.QListWidgetItem(name)
            if name == current_model:
                item.setSelected(True)
            self._model_list.addItem(item)
        # If nothing matched the current model, select the first entry.
        if not self._model_list.selectedItems() and model_names:
            self._model_list.setCurrentRow(0)
        layout.addWidget(self._model_list, stretch=1)

        button_box = QtWidgets.QDialogButtonBox()
        save_btn = button_box.addButton("Save", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        save_btn.setProperty("accent", "true")
        button_box.addButton("Cancel", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        QtCore.QTimer.singleShot(0, self._focus_list)

    def _focus_list(self) -> None:
        self._present_window()
        self._model_list.setFocus(QtCore.Qt.FocusReason.ActiveWindowFocusReason)

    def _save(self) -> None:
        items = self._model_list.selectedItems()
        if not items:
            QtWidgets.QMessageBox.critical(self, "No model selected", "Please select a model.")
            return
        self._result_model = items[0].text()
        self.accept()

    @property
    def result_model(self) -> str:
        return self._result_model


class TextWindow(_FramelessPanelMixin, QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        title: str,
        text_content: str,
        geometry: str = "560x360",
        content_provider: Callable[[], str] | None = None,
        refresh_interval_ms: int = 1000,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._content_provider = content_provider
        self._text_content = text_content
        self._last_content = ""
        self._apply_window_style()

        parts = geometry.split("x")
        width = int(parts[0]) if len(parts) > 0 else 560
        height = int(parts[1]) if len(parts) > 1 else 360
        self.resize(width, height)
        self.setMinimumSize(420, 240)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self._build_header(layout, title=title)

        self._text_edit = QtWidgets.QPlainTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setTabChangesFocus(True)
        font = QtGui.QFont("Consolas", 10)
        font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        self._text_edit.setFont(font)
        layout.addWidget(self._text_edit, stretch=1)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addStretch()

        self._close_btn = QtWidgets.QPushButton("Close")
        self._close_btn.setProperty("accent", "true")
        self._close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

        self._refresh_text(force_reset=True)

        if content_provider is not None:
            self._refresh_timer = QtCore.QTimer(self)
            self._refresh_timer.timeout.connect(self._refresh_text)
            self._refresh_timer.start(refresh_interval_ms)

        QtCore.QTimer.singleShot(0, self._focus_close_button)

    def _focus_close_button(self) -> None:
        self._present_window()
        self._close_btn.setFocus(QtCore.Qt.FocusReason.ActiveWindowFocusReason)

    def _refresh_text(self, force_reset: bool = False) -> None:
        current_y = self._text_edit.verticalScrollBar().value() if self._content_provider else 0
        at_end = (
            self._text_edit.verticalScrollBar().value()
            >= self._text_edit.verticalScrollBar().maximum() - 5
        )

        next_content = (
            self._content_provider() if self._content_provider is not None else self._text_content
        )
        if force_reset or next_content != self._last_content:
            if (
                not force_reset
                and self._last_content
                and next_content.startswith(self._last_content)
                and self._content_provider is not None
            ):
                appended = next_content[len(self._last_content) :]
                if appended:
                    cursor = self._text_edit.textCursor()
                    cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
                    cursor.insertText(appended)
            else:
                self._text_edit.setPlainText(next_content)

            self._last_content = next_content
            if at_end or not self._content_provider:
                self._text_edit.moveCursor(QtGui.QTextCursor.MoveOperation.End)
            else:
                sb = self._text_edit.verticalScrollBar()
                sb.setValue(min(current_y, sb.maximum()))
