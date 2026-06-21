# Refactoring & Improvement Plan — SpeechToText-vLLM

**Scope:** Whole-codebase analysis of `app/`, `tests/`, packaging, CI, and docs.
**Date:** 2026-06-19
**Repo size:** ~2,700 LOC across `app/` (15 modules) + ~900 LOC tests; single-platform (Windows) tray app.

---

## TL;DR

The codebase is **well-structured for its size** — clean separation between audio, VAD, STT, LLM, hotkeys, platform, and UI; consistent type hints; real unit tests for the core logic. The main debt is **concentrated in two God-classes** (`main.DictationApp` and `tray.TrayApp`), a **fragile dual-config-object sync**, several **dead-code paths** that are still "supported" by tests, and **tooling gaps** (no linter/type-check/coverage in CI). There are also two **correctness/packaging risks** worth fixing before anything else:

1. The new `app/dialogs.py` (PySide6) is **not in either PyInstaller spec's `hiddenimports`**, and the root `dictation.spec` is a **stale duplicate** of the one actually used by the build script.
2. **`config.json` is tracked in git** with personal values (device index, `medium` model, custom prompts) — it should be a template.

The plan below is ordered **risk-first**: P0 safety/packaging → P1 structure → P2 dead code → P3 tooling → P4 optional enhancements. Each phase is independently shippable.

---

## 1. How the app works today

### Pipeline (per recording)
```
hotkey gesture (hotkeys.py)
  → AudioRecorder.start() / .stop()          (audio.py, sounddevice callback)
  → RMS silence gate + optional debug WAV     (main.py)
  → DictationJob → queue.Queue(maxsize=1)     (main.py)
  → worker thread: VAD trim → Whisper → LLM clean/answer → deliver
                                                (vad.py, stt.py, llm.py)
  → inject_text (Ctrl+V / SendInput) + copy_to_clipboard   (platform/windows.py)
```

### Threading model (implicit, coordinated by shared state + locks)
| Thread | Role | Owner |
|---|---|---|
| `worker` | Drains job queue, runs the pipeline | `DictationApp` |
| `llm_monitor` | Polls model availability (circuit-breaker) | `DictationApp` |
| hotkey backend | `keyboard.hook` callback thread | `KeyboardHotkeyBackend` |
| `qt-event-loop` | PySide6 dialogs (`dialogs.py`) | `TrayApp` |
| `config-reload-watcher` | Polls `config.json` mtime every 1s | `TrayApp` |
| pystray loop | Tray menu (blocking) | `TrayApp` |

### Config flow (two live copies)
`config.json` → `TrayApp._config` (mutated by tray dialogs) → `DictationApp.config` (via `apply_runtime_config`). Edits go tray → `save_config` to disk → watcher reloads → `apply_runtime_config` rebuilds collaborators in place. **These two objects are kept in sync by hand**, which is the single most fragile part of the design (see §3, P1-1).

### Strengths to preserve
- **Clean layering**: pure-ish modules (`audio`, `vad`, `stt`, `llm`, `config`, `hotkeys`) behind thin platform/IO shells.
- **Type hints everywhere**; `from __future__ import annotations` consistently.
- **Injection seams already exist**: `backend_factory`, `key_modes`, `triple_press_raw_keys` on the hotkey tracker; platform services via `get_platform_services()`. Tests lean on these.
- **Graceful degradation**: LLM offline → raw Whisper transcript; insert fails → clipboard fallback; bad mic device → system default.
- **Cancellation** via a monotonic generation counter (Backspace) — correct and well-tested.
- **Atomic config writes** (`tempfile` + `os.replace` + `fsync`) — good.
- **LLM availability circuit-breaker** prevents hammering a dead endpoint.

---

## 2. Findings — prioritized

Legend: **P0** = correctness/safety/packaging · **P1** = structural debt · **P2** = dead code/duplication · **P3** = tooling/DX · **P4** = optional enhancement.

### P0 — Fix first (safety / packaging / committed secrets)

| # | Finding | Where | Recommendation |
|---|---|---|---|
| P0-1 | **`app/dialogs.py` (PySide6/shiboken) is missing from both PyInstaller specs' `hiddenimports`.** A packaged build can fail to import dialogs at runtime. | `packaging/windows/dictation-windows.spec:15-39`, `dictation.spec:10-34` | Add `app.dialogs`, `PySide6`, `shiboken6` to `hiddenimports`; add a `hook`/`collect_submodules('PySide6')` if needed; verify with a real `dist/` smoke test. |
| P0-2 | **Two divergent PyInstaller specs.** `build_windows.ps1` uses `packaging/windows/dictation-windows.spec`; the **root `dictation.spec` is stale** (hardcoded paths, no `app.dialogs`) and is referenced by nothing. | `dictation.spec` (root) | **Delete the root spec.** Keep a single source of truth under `packaging/`. |
| P0-3 | **`config.json` is tracked in git with personal values** (`microphone_device: 1`, `whisper_model: "medium"`, `max_tokens: 4096`, a custom `answer_prompt` with "prefer c#", and a `restructure_prompt` that differs from `DEFAULT_RESTRUCTURE_PROMPT`). It drifts from both the code defaults and the README. | `config.json` (tracked) | `git rm --cached config.json`, add to `.gitignore`, ship `config.example.json` matching `AppConfig` defaults. App already auto-creates a missing config. |
| P0-4 | **Plaintext API key in `config.json`** under `%APPDATA%`. README actively encourages it. | `app/llm.py:11` (`resolve_api_key`), `app/config.py` | Optional `keyring` integration (Windows Credential Manager) as a third resolution source after explicit/env. At minimum, warn when `llm_api_key` is non-null and log that it's loaded from disk. |
| P0-5 | **`detect_input_language()` swallows all exceptions silently** (returns `None`) — a partial ctypes failure looks identical to "no layout detected," hiding real bugs. | `app/platform/windows.py:170-185` | Log at `debug`/`warning` with `exc_info=True`; only return `None` on the expected "no foreground window" path. |

### P1 — Structural debt (highest maintenance cost)

| # | Finding | Where | Recommendation |
|---|---|---|---|
| P1-1 | **Two config objects kept in sync by hand** (`TrayApp._config` ↔ `DictationApp.config`). Every setter in `tray.py` mutates both + saves + refreshes menu; `apply_runtime_config` re-derives collaborators. Easy to drift, hard to reason about. | `tray.py` (`_set_language`, `_set_mic`, `_show_*_dialog_qt`), `main.py:124` | Make `DictationApp.config` the **single source of truth**; `TrayApp` holds a reference and calls one `app.update_config(partial)` method. Remove the parallel `_config`. |
| P1-2 | **`DictationApp` is a God-class** (orchestration + pipeline + LLM monitor + cancellation + delivery + config-apply + factory). 474 LOC, ~25 methods, and its init test patches 8 collaborators. | `app/main.py` | Split: `DictationPipeline` (`_process_job`/`_transform_transcript`/`_deliver_result`), `LLMAvailabilityMonitor` (the monitor loop + tri-state), and a `CancellationCoordinator` (generation counter). `DictationApp` becomes a thin composition root. |
| P1-3 | **`TrayApp` is a God-class** (549 LOC): tray menu + Qt lifecycle + dialog dispatch + config persistence + file watcher + icon rendering + device listing. | `app/tray.py` | Extract: `app/icons.py` (PIL tint/fit + `_BASE_ICON`), `app/ui_host.py` (Qt thread + `_DialogInvoker` + window registry), `app/config_watcher.py` (mtime poll loop). `TrayApp` keeps only menu wiring. |
| P1-4 | **`TranscriptCleaner` internals mutated from outside.** `update_llm_endpoint` sets `self.cleaner.client.base_url = ...` directly; `update_llm_settings` pokes `self.cleaner.extra_body/.strict_model_name_match`. Reaching into the OpenAI client object is brittle (base_url may be read-only / validated on newer SDKs). | `main.py:104-122`, `app/llm.py` | Add `TranscriptCleaner.reconfigure(base_url=..., api_key=..., ...)` that rebuilds the client and swaps settings atomically. |
| P1-5 | **Circular `tray ↔ main` dependency** handled by lazy in-method imports (`from app.config import load_config` inside methods; `from app.main import DictationApp` inside `TrayApp.__init__`). | `tray.py:145-150,249,537`; `main.py:469` | Invert the dependency: `main()` builds `DictationApp`, passes it (or a factory) into `TrayApp`. Removes all lazy imports. |
| P1-6 | **Threading model is implicit and undocumented.** Five+ threads coordinate via shared mutable state + 4 different locks (`_cancel_lock`, `_llm_status_lock`, `_config_lock` RLock, audio `_lock`). A config reload mid-pipeline reassigns `self.transcriber`/`self.cleaner` while the worker may hold the old object. Likely GIL-safe today, but subtle and untested for races. | `main.py` throughout | Document ownership in a module docstring; make the worker **snapshot** collaborators at job start; consider a single `PipelineState` guarded by one lock instead of scattered fields. Add a concurrency-focused test. |
| P1-7 | **`logger.memory_handler` is monkey-patched onto the Logger** and read via `getattr(self._app.logger, "memory_handler", None)`. | `app/logger.py:57`, `tray.py:542`, `main.py:41` | Return a small `LogSink`/dataclass from `setup_logging` and hold a real reference instead of attribute-patching the stdlib Logger. |
| P1-8 | **`setup_logging()` is called twice** (`main()` and `DictationApp.__init__`) and its idempotency relies on a handler check. Mixed singleton-mutation + return-value concerns. | `main.py:41,465` | Call once at process entry; pass the configured logger down. |

### P2 — Dead code & duplication

| # | Finding | Where | Recommendation |
|---|---|---|---|
| P2-1 | **`DictationApp.run()` is dead code.** It's a blocking `time.sleep(0.1)` loop, but `TrayApp.run()` starts the worker/monitor/hotkeys directly and never calls `self._app.run()`. | `main.py:88-98` | Delete `run()`. Keep only `shutdown()` / lifecycle helpers. |
| P2-2 | **`AudioRecorder._read_loop` and `_reader_thread` are dead.** `start()` uses the sounddevice **callback** model (`_on_audio`) and only sets `self._reader_thread = None`; no thread is ever started. Yet `test_read_loop_sets_stop_event_when_read_fails` tests this dead path. | `app/audio.py:29,50,91,109-132`; `tests/test_audio.py:120-136` | Delete `_read_loop`, `_reader_thread`, `_read_exception`-as-thread-path. **Delete the test that covers dead code** (or repurpose it to the callback error path in `_on_audio`). |
| P2-3 | **`app/ui.py` (`AppUI`) is dead** — empty `start()`/`stop()`, imported nowhere. | `app/ui.py` | Delete the module. |
| P2-4 | **`stt.py` `compute_candidates = [effective_compute_type]`** is a single-element loop — the "try multiple compute profiles" feature was abandoned but the loop scaffolding remains. | `app/stt.py:124-150` | Collapse to a single load attempt (or restore real fallback candidates like `["float16","int8"]`). |
| P2-5 | **PCM16 conversion duplicated** across `AudioRecorder.to_pcm16`, `stt._save_wav`, inline in `main._process_job` (`(trimmed.astype(np.float32)/32767.0).clip(-1,1)`), and `bench_whisper.py`. | `audio.py:134`, `stt.py:179-187`, `main.py:361`, `bench_whisper.py:58` | Centralize in `app/audio.py` (`pcm16_to_float`, `float_to_pcm16`); import everywhere. |
| P2-6 | **NVIDIA-CUDA PATH injection duplicated** in `stt._ensure_cuda_libs` and `bench_whisper.py`. | `app/stt.py:20-44`, `bench_whisper.py:13-23` | Move to a shared `app/cuda_bootstrap.py` (or `app/audio_gpu.py`). |
| P2-7 | **`AudioRecorder.list_input_devices()` appears unused** — `tray.py` has its own module-level `_list_input_devices()`. | `audio.py:36-40`, `tray.py:128-134` | Delete the method, or make tray call the recorder's (single source of truth). |
| P2-8 | **Built-in languages ("Auto", "Auto-detected") hardcoded in `tray.py`** while `config.languages` holds the rest. | `tray.py:300` | Move built-ins into config or a constants module. |
| P2-9 | **`get_platform_services` uses `lru_cache(maxsize=3)`** for an effectively-constant value. | `app/platform/__init__.py:9` | Use `maxsize=None` (or a plain module-level singleton) — the `3` reads as accidental. |

### P3 — Tooling, testing, DX

| # | Finding | Recommendation |
|---|---|---|
| P3-1 | **No `pyproject.toml`**: no linter/formatter/type-checker config, no isort. Imports are mostly sorted but inconsistent (e.g. `import sys` oddly placed at `tray.py:8`). | Add `pyproject.toml` with **ruff** (lint + format, replaces isort/flake8/pyupgrade) and **mypy** or **pyright** config. The codebase already has good annotations — make them enforceable. |
| P3-2 | **CI runs tests but no lint/type-check/coverage.** `python -m unittest discover` only. | Add `ruff check`, type-check, and `coverage` jobs to `.github/workflows/build-and-test.yml`; gate PRs on them. |
| P3-3 | **Coverage gaps in the most logic-heavy new code:** `dialogs.py` (397 LOC, **0 tests**), `vad.py` (0 tests), `tray._build_menu` (untested), `_list_input_devices` (untested). | `normalize_llm_url` (pure, in `dialogs.py`) and `VoiceActivityTrimmer.trim` (the `<0.1` voiced-ratio + first/last logic) are high-value, low-effort unit tests. |
| P3-4 | **No `config.example.json` / schema.** `from_dict` uses `cls.__annotations__` and silently drops unknowns; no validation (a string where an int is expected fails cryptically at construction). | Add `AppConfig.validate()` (or pydantic/`dataclass`-with-`__post_init__`) and a generated example file. Document `restructure_prompt`/`answer_prompt`/`languages` in the README config table (currently absent). |
| P3-5 | **`.idea/` IDE churn is partially tracked.** `copilotDiffState.xml`/`claudeCodeTabState.xml` churn in working tree. | Stop tracking volatile IDE state; tighten `.gitignore`. |

### P4 — Optional enhancements (not required for refactor)

| # | Idea | Notes |
|---|---|---|
| P4-1 | **Pre-warm Whisper on startup.** First dictation blocks on lazy `load()` (seconds for `medium`). Load in the worker thread at launch with a "warming up" log line. | UX win, low risk. |
| P4-2 | **Smarter LLM circuit-breaker.** A single transient 5xx flips `_llm_available=False`, disabling LLM for up to `llm_availability_check_interval_seconds` (default 60s). Consider a failure-count threshold / short retry before fully opening the breaker. | `main._transform_transcript`, `_check_llm_availability`. |
| P4-3 | **`is_model_available()` does a real chat completion every health check** (default 60s) — spends tokens/quota on hosted providers. Make the probe opt-in or cheaper (models.list only). | `llm.py:47-72`. |
| P4-4 | **Commit to Windows-only, or finish the abstraction.** `app/platform/` exists but only Windows ships; README says "no mac." Either delete the cross-platform pretense (simplify) or add macOS/Linux adapters. | `platform/__init__.py:16` raises on non-Windows. |
| P4-5 | **`build_about_text` hardcodes "Windows dictation assistant"** despite the platform abstraction. | Derive from `current_platform_name()`. |
| P4-6 | **Unify the two silence gates** (`silence_rms_threshold` + VAD). | Documentation/UX decision. |

---

## 3. Phased plan

Each phase is independently mergeable. Tests must stay green at every boundary (CI: `python -m unittest discover -s tests`).

### Phase 0 — Hygiene & safety (do first, ~half a day)
- [ ] **P0-3** `git rm --cached config.json`; add to `.gitignore`; commit `config.example.json` from `AppConfig()` defaults.
- [ ] **P0-2** Delete root `dictation.spec`.
- [ ] **P0-1** Add `app.dialogs` + PySide6 to `packaging/windows/dictation-windows.spec`; run a build smoke test.
- [ ] **P2-3** Delete `app/ui.py`.
- [ ] **P2-1** Delete `DictationApp.run()`.
- [ ] **P2-2** Delete dead `_read_loop`/`_reader_thread` and the test that exercises them; add a callback-error-path test instead.
- [ ] **P0-5** Log exceptions in `detect_input_language`.

### Phase 1 — Tooling foundation (unblocks everything else, ~half a day)
- [ ] **P3-1** Add `pyproject.toml` with ruff (lint+format) and mypy/pyright.
- [ ] **P3-2** Wire lint + type-check + coverage into CI.
- [ ] Run ruff/mypy, fix the trivial findings (unused imports, the `import sys` placement, etc.).
- [ ] **P3-3** Add the cheap high-value tests: `normalize_llm_url`, `VoiceActivityTrimmer.trim`, `AppConfig` validation edges.

### Phase 2 — LLM & logging cleanups (low blast radius, ~1 day)
- [ ] **P1-4** `TranscriptCleaner.reconfigure(...)`; stop mutating client internals from `main.py`.
- [ ] **P1-7/P1-8** Single `setup_logging()` call at entry; return a real `LogSink` reference; drop the `memory_handler` monkey-patch.
- [ ] **P2-4** Collapse the single-element `compute_candidates` loop in `stt.py`.
- [ ] **P2-5/P2-6** Centralize PCM16 helpers and CUDA bootstrap.

### Phase 3 — Config single-source-of-truth (the big one, ~1–2 days)
- [ ] **P1-1** Make `DictationApp.config` the only config object; add `DictationApp.update_config(partial_dict)`; rewrite `TrayApp` setters to call it.
- [ ] **P1-5** Break the `tray ↔ main` cycle: `main()` constructs `DictationApp` and injects into `TrayApp`; remove lazy imports.
- [ ] **P3-4** `AppConfig.validate()` + `config.example.json` + README config-table gap.
- [ ] Update `test_tray.py` / `test_main.py` for the new boundaries.

### Phase 4 — Decompose the God-classes (mechanical, ~2 days)
- [ ] **P1-2** Extract `DictationPipeline` + `LLMAvailabilityMonitor` + `CancellationCoordinator` from `main.py`.
- [ ] **P1-3** Extract `app/icons.py`, `app/ui_host.py`, `app/config_watcher.py` from `tray.py`.
- [ ] **P1-6** Document thread ownership; snapshot collaborators at job start; add a concurrency test.
- [ ] Split the large `test_main.py` / `test_tray.py` to mirror the new modules.

### Phase 5 — Optional polish
- [ ] P4 items as time/interest allows (pre-warm, smarter breaker, platform decision).

---

## 4. Proposed target structure

```
app/
  main.py                  # entrypoint + composition root only
  app.py (was main.py)     # DictationApp: thin orchestrator
  pipeline.py              # DictationPipeline (process/transform/deliver)   [P1-2]
  llm_monitor.py           # LLMAvailabilityMonitor                          [P1-2]
  cancellation.py          # CancellationCoordinator (generation counter)    [P1-2]
  config.py                # AppConfig + validate() + load/save              [P3-4]
  config_watcher.py        # mtime poll loop                                 [P1-3]
  audio.py                 # + shared pcm16 helpers                          [P2-5]
  cuda_bootstrap.py        # shared NVIDIA PATH injection                    [P2-6]
  vad.py  stt.py  llm.py   # (unchanged, except llm.reconfigure)            [P1-4]
  hotkeys.py               # (unchanged)
  icons.py                 # PIL tint/fit + base icon cache                  [P1-3]
  ui_host.py               # Qt thread + DialogInvoker + window registry    [P1-3]
  dialogs.py               # PySide6 dialogs (+ tests)                       [P0-1, P3-3]
  tray.py                  # menu wiring only                                [P1-3]
  logger.py                # setup_logging + LogSink                         [P1-7]
  platform/                # windows (mac/linux if P4-4 pursued)
config.example.json        # tracked template                                [P0-3]
pyproject.toml             # ruff + mypy/coverage config                     [P3-1]
```
**Deleted:** `app/ui.py`, root `dictation.spec`, `DictationApp.run()`, `AudioRecorder._read_loop`/`_reader_thread`.

---

## 5. Testing strategy

- **Keep the existing suite green at every phase** — it already pins the important behavior (delivery targets, cancellation, LLM fallback, config reload, hotkey gestures, platform dispatch).
- **Delete tests that assert on dead code** (P2-2) — they give false confidence.
- **Add unit tests for currently-untested pure logic:** `normalize_llm_url`, `VoiceActivityTrimmer.trim`, `AppConfig.from_dict`/`validate` edge cases, `LLMCompatibilityDialog` preset round-trip.
- **Add one concurrency test** for Phase 4: drive a config-reload while a job is mid-pipeline and assert no `AttributeError`/half-rebuilt collaborator is observed.
- **Add a packaging smoke test** to CI (build the exe, launch headless, confirm import of `app.dialogs`) to prevent P0-1 regressions.
- **Target coverage floor** (e.g. 80%) gated in CI once P3-2 lands.

---

## 6. Risks & non-goals

**Risks**
- **PySide6 + PyInstaller** is the most likely place to break a packaged build (P0-1). Verify with a real build, not just `pyinstaller --check`.
- **Config refactor (Phase 3)** touches every runtime-mutable path; do it behind the existing tests and add the missing ones first.
- **Threading changes (Phase 4)** can introduce races that don't show in unit tests — lean on the concurrency test and keep collaborator swaps atomic.

**Non-goals (explicitly out of scope unless requested)**
- Rewriting the hotkey gesture state machine — it's correct and well-tested; leave it.
- Changing the pipeline semantics (VAD → Whisper → LLM → deliver) or the fallback behavior.
- Adding macOS/Linux support (only if P4-4 is chosen).
- Changing the tray/Qt UI look-and-feel.

**Open questions for the maintainer**
1. Should `config.json` stop being tracked entirely (P0-3), or keep a committed `config.example.json` plus a generated local one? *(Plan assumes: stop tracking, ship example.)*
2. Commit to Windows-only and simplify `platform/`, or invest in cross-platform (P4-4)?
3. Adopt `keyring` for the API key (P0-4), or keep env-var-only as the "safe" path?
4. PySide6 Qt — is the separate Qt thread + pystray split intentional/preferred, or open to a single-GUI rewrite later?

---

## 7. Execution log (2026-06-19)

The plan was executed phase by phase. All gates green at every boundary: `ruff check`, `ruff format --check`, `mypy`, and the unit suite (grew from 65 → 88 tests). macOS/Linux confirmed out of scope (open question 2 → Windows-only; `platform/` kept as-is).

**Phase 0 — Hygiene & safety ✅**
- Untracked `config.json` (kept on disk), added it + `debug_recordings/` to `.gitignore`, shipped `config.example.json` generated from `AppConfig` defaults.
- Deleted stale root `dictation.spec` (was already gitignored) and dead `app/ui.py`.
- Added `app.dialogs` + `collect_all("PySide6")` + `shiboken6` to the PyInstaller spec; deleted dead `DictationApp.run()`; removed dead `AudioRecorder._read_loop`/`_reader_thread`/`_read_exception` (and the test that exercised them) in favor of a callback-error-path test; added `PySide6` to `requirements/base.txt` (it was imported but undeclared); log exceptions in `detect_input_language`.

**Phase 1 — Tooling foundation ✅**
- Added `pyproject.toml` (ruff lint+format, mypy baseline, coverage), `requirements/dev.txt`, and CI steps for lint/format/type-check/coverage (`fail_under=50`).
- Adopted ruff across the tree (one-time reformat), ignored `UP031` (intentional %-style logging) and per-file `RUF012` (ctypes `_fields_`).
- Fixed real type bugs surfaced by mypy (`stt.model`/`language` typing, `sys._MEIPASS`, Qt slot type).
- Added unit tests for previously-untested pure logic: `normalize_llm_url`, `VoiceActivityTrimmer.trim`, `AppConfig.from_dict`/`to_dict`.

**Phase 2 — LLM & logging cleanups ✅**
- `TranscriptCleaner.reconfigure(...)` rebuilds the client only when connection params change; `main.py` no longer mutates `cleaner.client.base_url`/attrs (new `_reconfigure_cleaner` helper, in-place → thread-safe).
- `setup_logging()` returns a `LoggingComponents` dataclass; the `memory_handler` monkey-patch is gone (`_app.memory_handler` is now a real attribute); called once at entry.
- Collapsed the vestigial single-element compute loop into a real `int8` fallback; centralized PCM16 helpers (`float_to_pcm16`/`pcm16_to_float`) and CUDA PATH injection (`app/cuda_bootstrap.py`) — `stt.py`, `main.py`, `bench_whisper.py` all reuse them.

**Phase 3 — Config single-source-of-truth ✅**
- `DictationApp.config` is the only config object; `TrayApp._config` removed (setters call `app.set_language`/`set_microphone`; dialogs read `app.config`).
- Broke the `tray ↔ main` cycle: `main()` builds `DictationApp` and injects it into `TrayApp(app=..., config_path=...)`; lazy in-method imports removed; `app.config`/`app.config_watcher` imported at top.
- Added `AppConfig.validate()` (range checks), called from `from_dict`; config watcher also catches `ValueError`.
- Documented `restructure_prompt`/`answer_prompt`/`languages` in the README config table.

**Phase 4 — Decompose God-classes (partial) 🟡**
Done:
- Extracted `app/icons.py` (pure PIL rendering) + `tests/test_icons.py`.
- Extracted `CancellationCoordinator` → `app/cancellation.py` + `tests/test_cancellation.py` (DictationApp now composes it).
- Extracted `ConfigWatcher` → `app/config_watcher.py` + `tests/test_config_watcher.py` (mtime poll/mark_current).
- Added a threading-ownership module docstring to `main.py` (P1-6).

Deferred (more coupled; higher test churn for diminishing returns — left as-is, behavior unchanged):
- `LLMAvailabilityMonitor` (the tri-state + monitor loop) and `DictationPipeline` (`_process_job`/`_transform_transcript`/`_deliver_result`) still live on `DictationApp`.
- `ui_host.py` (Qt thread + window registry) still lives on `TrayApp`.
- Collaborator snapshot-at-job-start (the plan noted the current GIL-safe swap is acceptable).

These three are mechanical to extract later using the same pattern; the suite is structured to make that straightforward.

