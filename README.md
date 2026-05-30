# SpeechToText-vLLM

Cross-platform dictation assistant with a shared Python core and platform-specific desktop integrations for Windows and macOS. The app records audio, transcribes it locally with Faster-Whisper, optionally cleans or answers with a local vLLM/OpenAI-compatible endpoint, and then inserts the result into the active app and/or copies it to the clipboard.

## Checklist

- Shared speech pipeline for Windows and macOS
- Platform-specific global hotkeys, clipboard, paste, and packaging
- Separate build outputs in `dist/windows` and `dist/macos`
- Tray/menu-bar UI with recent logs and runtime configuration

## Default hotkeys

### Windows defaults

| Key | Action |
|---|---|
| **Right Ctrl** (single hold) | Record → restructure/clean transcript → insert into active field and copy to clipboard |
| **Right Ctrl** (double-press then hold) | Record → restructure/clean transcript → copy to clipboard |
| **Right Ctrl** (triple-press then hold) | Record → transcribe only → insert and copy raw transcript |
| **Right Shift** (single hold) | Record → answer/follow instructions → insert into active field and copy to clipboard |
| **Right Shift** (double-press then hold) | Record → answer/follow instructions → copy to clipboard |

### macOS defaults

| Key | Action |
|---|---|
| **Right Command** (single hold) | Record → restructure/clean transcript → insert into active field and copy to clipboard |
| **Right Command** (double-press then hold) | Record → restructure/clean transcript → copy to clipboard |
| **Right Command** (triple-press then hold) | Record → transcribe only → insert and copy raw transcript |
| **Right Shift** (single hold) | Record → answer/follow instructions → insert into active field and copy to clipboard |
| **Right Shift** (double-press then hold) | Record → answer/follow instructions → copy to clipboard |

Gesture rules:

- **Single hold**: press and hold once; recording starts after the tap threshold passes and stops when you release.
- **Double-press then hold**: tap once briefly, release, then press and hold on the second press.
- **Triple-press then hold**: tap twice briefly, then hold on the third press to skip vLLM and emit raw Whisper output.
- **Backspace** cancels the current processing/output operation on both platforms.

## Tray / menu bar UI

The app runs without a main window. Look for the microphone icon:

- in the **Windows system tray / notification area**, or
- in the **macOS menu bar**.

The icon is green when active and red when paused.

Tray/menu items:

- **Primary hotkey (restructure)** — enable/disable the cleanup hotkey
- **Secondary hotkey (answer)** — enable/disable the answer hotkey
- **Microphone** — choose an input device
- **Language** — Auto, Auto-detected, English, Russian
- **vLLM URL...** — edit the OpenAI-compatible server URL at runtime
- **About** — show the built-in hotkey/help summary
- **Recent Logs** — display the in-memory recent log buffer
- **Pause / Resume** — stop or restart hotkey listening
- **Exit** — quit the app

## Language detection

- On **Windows**, `language_mode = "auto-detected"` reads the foreground keyboard layout and passes that language hint to Whisper.
- On **macOS**, keyboard-layout detection is not implemented yet; `auto-detected` currently falls back to Whisper auto-detection unless you explicitly choose a language from the tray/menu.
- On either platform, `language_mode = "auto"` lets Whisper infer the language from audio.

## Logging

Logs are available in three places:

- console/stdout while running from source
- **Recent Logs** in the tray/menu
- packaged app console logs if you launch the executable from a terminal

Each log line includes the active platform label (`windows` or `macos`) so mixed build/test logs stay readable.

## Install from source

### Windows

```powershell
py -3.11 -m pip install -r requirements/windows.txt
py -3.11 -m app.main --config config.json
```

### macOS

```bash
python3 -m pip install -r requirements/macos.txt
python3 -m app.main --config config.json
```

## Build distributables

### Windows executable

Run on Windows:

```powershell
.\scripts\build_windows.ps1
```

Expected output:

- `dist/windows/DictationAssistant.exe`

### macOS app bundle

Run on macOS:

```bash
chmod +x ./scripts/build_macos.sh
./scripts/build_macos.sh
```

Expected output:

- `dist/macos/DictationAssistant.app`

## Dist folder layout

```text
dist/
  windows/
    DictationAssistant.exe
  macos/
    DictationAssistant.app
```

This repository already contains `dist/macos/README.md` as the target placeholder for the macOS build output. The macOS app bundle itself must be produced on a Mac.

## Platform dependency manifests

- `requirements/base.txt` — shared runtime dependencies
- `requirements/windows.txt` — Windows overlay (`keyboard`, `pywin32`)
- `requirements/macos.txt` — macOS overlay (`pynput`, `pyobjc`)
- `requirements.txt` — compatibility wrapper pointing to the Windows manifest

## Packaging files

- `packaging/windows/dictation-windows.spec` — Windows PyInstaller spec
- `packaging/macos/dictation-macos.spec` — macOS PyInstaller spec
- `dictation.spec` — backward-compatible Windows root spec
- `scripts/build_windows.ps1` — Windows build script
- `scripts/build_macos.sh` — macOS build script

## Permissions / platform notes

### Windows

- Global hotkeys may need elevated privileges in some environments.
- Clipboard paste injection uses `Ctrl+V` and falls back to Win32 `SendInput`.

### macOS

You will typically need to grant:

- **Microphone** access
- **Accessibility** access for paste injection and UI scripting
- possibly **Input Monitoring** depending on the environment/hotkey behavior

macOS packaging should be built on macOS. If you distribute outside your own machine, you may eventually want code signing and notarization.

## Config

`config.json` is created automatically with defaults if missing.

| Key | Default | Description |
|---|---|---|
| `vllm_url` | `http://127.0.0.1:8000/v1` | vLLM OpenAI-compatible endpoint |
| `model_name` | `Qwen3.5-9B-AWQ-4bit-local` | Model name for the LLM endpoint |
| `microphone_device` | `null` | Device index or `null` for default |
| `whisper_model` | `small` | Faster-Whisper model size |
| `whisper_device` | `auto` | Whisper runtime device selection |
| `whisper_compute_type` | `float16` | Preferred Whisper compute type |
| `language_mode` | `auto` | Language hint or auto mode |
| `min_hold_seconds` | `2.0` | Minimum accepted recording duration |
| `record_start_delay_seconds` | `0.2` | Delay before recording starts |
| `double_press_window_seconds` | `0.5` | Time window for second/third press |
| `first_press_max_seconds` | `0.3` | Max duration for a tap |
| `temperature` | `0.1` | LLM sampling temperature |
| `max_tokens` | `512` | Max LLM response tokens |
| `llm_timeout_seconds` | `60.0` | Timeout for the LLM request |
| `llm_availability_check_interval_seconds` | `60.0` | Background model availability polling interval |
| `vad_enabled` | `true` | Enable WebRTC VAD trimming |
| `silence_rms_threshold` | `0.005` | RMS threshold for silent audio |
| `debug_save_wav` | `false` | Save WAVs for debugging |
| `debug_wav_dir` | `debug_recordings` | Directory for debug WAV files |

## Project layout

- `app/main.py` — app orchestration and processing pipeline
- `app/tray.py` — tray/menu-bar UI and runtime configuration
- `app/hotkeys.py` — shared hotkey gesture state machine
- `app/platform/` — platform adapters for clipboard, paste, hotkeys, and language detection
- `app/audio.py` — microphone capture
- `app/vad.py` — WebRTC VAD trimming
- `app/stt.py` — Faster-Whisper transcription
- `app/llm.py` — vLLM/OpenAI-compatible client
- `app/logger.py` — console + in-memory logging
- `packaging/` — platform-specific PyInstaller specs
- `scripts/` — build scripts for each OS
- `dist/` — generated artifacts
