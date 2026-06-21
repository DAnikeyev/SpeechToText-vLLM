# SpeechToText-vLLM

Windows dictation assistant. The app records audio, transcribes it locally with Faster-Whisper, optionally cleans or answers with a local vLLM/OpenAI-compatible endpoint, and then inserts the result into the active app and/or copies it to the clipboard.

## Default hotkeys

| Key | Action |
|---|---|
| **Right Ctrl** (single hold) | Record → restructure/clean transcript → insert into active field and copy to clipboard |
| **Right Ctrl** (double-press then hold) | Record → restructure/clean transcript → copy to clipboard |
| **Right Ctrl** (triple-press then hold) | Record → transcribe only → insert and copy raw transcript |
| **Right Shift** (single hold) | Record → answer/follow instructions → insert into active field and copy to clipboard |
| **Right Shift** (double-press then hold) | Record → answer/follow instructions → copy to clipboard |

Gesture rules:

- **Single hold**: press and hold once; recording starts after the tap threshold passes and stops when you release.
- **Double-press then hold**: tap once briefly, release, then press and hold on the second press.
- **Triple-press then hold**: tap twice briefly, then hold on the third press to skip vLLM and emit raw Whisper output.
- **Backspace** cancels the current processing/output operation.

## Tray UI

The app runs without a main window. Look for the microphone icon in the **Windows system tray / notification area**.

The icon is green when active and red when paused.

Tray menu items:

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

`language_mode = "auto-detected"` reads the foreground keyboard layout and passes that language hint to Whisper.

## Logging

Logs are available in three places:

- console/stdout while running from source
- **Recent Logs** in the tray
- packaged app console logs if you launch the executable from a terminal

## Install from source

```powershell
py -3.11 -m pip install -r requirements/windows.txt
py -3.11 -m app.main --config config.json
```

## Hosted provider quick start (OpenRouter default)

Default `config.json` values already target OpenRouter. The only thing you usually need to provide is an API key.

### Copyable `config.json` snippet

```json
{
  "vllm_url": "https://openrouter.ai/api/v1",
  "llm_api_key": null,
  "model_name": "openai/gpt-oss-120b:free",
  "llm_strict_model_name_match": true,
  "llm_extra_body": null
}
```

### PowerShell

```powershell
$env:SPEECHTOTEXT_VLLM_API_KEY = "your-openrouter-key"
py -3.11 -m app.main --config config.json
```

Notes:

- `llm_api_key` in `config.json` overrides environment variables if you prefer storing the key there.
- `SPEECHTOTEXT_VLLM_API_KEY` is the preferred environment variable.
- `OPENAI_API_KEY` also works as a fallback.
- Keep `llm_extra_body` set to `null` for hosted OpenAI-compatible providers such as OpenRouter, OpenAI, Groq, Together, and DeepInfra.

## Build executable

Run on Windows:

```powershell
.\scripts\build_windows.ps1
```

Expected output:

- `dist/windows/DictationAssistant.exe`

## Build and release with GitHub Actions

`dist/` is intended to stay local-only and is already gitignored. Do not commit executables.

### Build in Actions

Use the `Build and Release` workflow:

1. Open **GitHub -> Actions -> Build and Release**.
2. Click **Run workflow**.
3. Wait for the `build` job to finish.
4. Download `DictationAssistant-windows` artifact from the run summary.

### Automatic release on tag

Push a tag matching `v*` and the workflow will:

1. Run tests
2. Build `DictationAssistant.exe`
3. Create a GitHub Release with the executable attached

Example:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

### Local rebuild after cleaning generated output

```powershell
Remove-Item -Recurse -Force .\dist -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\build\windows -ErrorAction SilentlyContinue
.\scripts\build_windows.ps1
```

## Platform dependency manifests

- `requirements/base.txt` — shared runtime dependencies
- `requirements/windows.txt` — Windows overlay (`keyboard`, `pywin32`)
- `requirements.txt` — compatibility wrapper pointing to the Windows manifest

## Permissions

- Global hotkeys may need elevated privileges in some environments.
- Clipboard paste injection uses `Ctrl+V` and falls back to Win32 `SendInput`.

## Config

`config.json` is created automatically with defaults if missing.

For hosted OpenAI-compatible providers, you can either set `llm_api_key` in `config.json` or provide one of these environment variables before starting the app:

- `SPEECHTOTEXT_VLLM_API_KEY` (preferred)
- `OPENAI_API_KEY`

If neither is set, the app falls back to the local placeholder key `local`, which is suitable for local vLLM / Ollama-style gateways that do not enforce auth.

| Key | Default | Description |
|---|---|---|
| `vllm_url` | `https://openrouter.ai/api/v1` | OpenAI-compatible LLM endpoint |
| `llm_api_key` | `null` | Optional bearer token for hosted OpenAI-compatible providers; can also come from environment |
| `model_name` | `openai/gpt-oss-120b:free` | Model name for the LLM endpoint |
| `restructure_prompt` | _see `config.example.json`_ | System prompt for the restructure/cleanup mode |
| `answer_prompt` | _see `config.example.json`_ | System prompt for the answer mode |
| `languages` | `[{label: English, code: en}, {label: Russian, code: ru}]` | Tray language-menu entries (`label`/`code` pairs) |
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
| `llm_strict_model_name_match` | `true` | Require an exact match between `model_name` and the provider's `/v1/models` response |
| `llm_extra_body` | `null` | Optional extra JSON fields sent with chat completions; leave `null` for hosted OpenAI-compatible providers |
| `vad_enabled` | `true` | Enable WebRTC VAD trimming |
| `silence_rms_threshold` | `0.005` | RMS threshold for silent audio |
| `debug_save_wav` | `false` | Save WAVs for debugging |
| `debug_wav_dir` | `debug_recordings` | Directory for debug WAV files |

## Project layout

- `app/main.py` — app orchestration and processing pipeline
- `app/tray.py` — tray UI and runtime configuration
- `app/hotkeys.py` — shared hotkey gesture state machine
- `app/platform/` — platform adapters for clipboard, paste, hotkeys, and language detection
- `app/audio.py` — microphone capture
- `app/vad.py` — WebRTC VAD trimming
- `app/stt.py` — Faster-Whisper transcription
- `app/llm.py` — vLLM/OpenAI-compatible client
- `app/logger.py` — console + in-memory logging
- `packaging/` — PyInstaller specs
- `scripts/` — build scripts
- `dist/` — generated artifacts
