# SpeechToText-vLLM

Windows-native local push-to-talk dictation assistant:

- Hold **CTRL** to record (start delay: 200ms)
- Release **CTRL** to stop
- Holds shorter than `min_hold_seconds` are ignored
- Local transcription via `faster-whisper` (`medium`, CPU, `int8`)
- Local cleanup via OpenAI-compatible vLLM endpoint
- Direct Unicode text injection via Win32 `SendInput` (no clipboard usage)

## Run

```bash
python -m app.main --config config.json
```

## Project layout

- `/app/main.py` – daemon orchestration and pipeline
- `/app/hotkeys.py` – global CTRL hold tracking
- `/app/audio.py` – callback microphone capture
- `/app/vad.py` – WebRTC VAD trimming
- `/app/stt.py` – Faster-Whisper transcription
- `/app/llm.py` – vLLM cleanup client
- `/app/inject.py` – Win32 Unicode text injection
- `/app/config.py` – JSON config loading/saving
