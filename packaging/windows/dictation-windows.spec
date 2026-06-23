# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

REPO_ROOT = Path(SPECPATH).resolve().parents[1]

# PySide6 (Qt) ships plugins, translations, and the shiboken binding generator
# that PyInstaller cannot discover by static analysis. collect_all gathers them.
_pyside_datas, _pyside_binaries, _pyside_hiddenimports = collect_all("PySide6")

# ctranslate2 (faster-whisper backend) + the NVIDIA CUDA 12 runtime wheels it loads
# at runtime (cublas64_12.dll, cudart, nvrtc). These wheels are declared explicitly
# in requirements/windows.txt — they are NOT transitive deps of faster-whisper — so
# without collecting them the frozen exe raises "Library cublas64_12.dll is not found"
# at transcription. collect_all preserves the nvidia/<pkg>/bin layout that
# app.cuda_bootstrap relies on to put the DLLs on PATH at startup.
_ct2_datas, _ct2_binaries, _ct2_hiddenimports = collect_all("ctranslate2")
_nv_cublas_d, _nv_cublas_b, _nv_cublas_h = collect_all("nvidia.cublas")
_nv_rt_d, _nv_rt_b, _nv_rt_h = collect_all("nvidia.cuda_runtime")
_nv_nvrtc_d, _nv_nvrtc_b, _nv_nvrtc_h = collect_all("nvidia.cuda_nvrtc")

# httpx (HTTP client used by openai SDK) depends on certifi, httpcore, and h11,
# all of which are lazy-imported inside function bodies. PyInstaller's static
# analysis cannot discover them. collect_all ensures every submodule is bundled
# and the hook-httpx.py in hooks/ collects certifi's cacert.pem data file.
_httpx_datas, _httpx_binaries, _httpx_hiddenimports = collect_all("httpx")


a = Analysis(
    [str(REPO_ROOT / 'app' / 'main.py')],
    pathex=[str(REPO_ROOT)],
    binaries=(
        _pyside_binaries
        + _ct2_binaries
        + _nv_cublas_b
        + _nv_rt_b
        + _nv_nvrtc_b
    ),
    datas=[(str(REPO_ROOT / 'app' / 'mic.ico'), 'app')]
    + _pyside_datas
    + _ct2_datas
    + _nv_cublas_d
    + _nv_rt_d
    + _nv_nvrtc_d
    + _httpx_datas,
    hiddenimports=[
        'app',
        'app.main',
        'app.config',
        'app.hotkeys',
        'app.audio',
        'app.cancellation',
        'app.clipboard',
        'app.config',
        'app.config_watcher',
        'app.cuda_bootstrap',
        'app.icons',
        'app.inject',
        'app.llm',
        'app.logger',
        'app.main',
        'app.stt',
        'app.vad',
        'app.tray',
        'app.dialogs',
        'app.platform',
        'app.platform.base',
        'app.platform.windows',
        'shiboken6',
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL._tkinter_finder',
        'sounddevice',
        'faster_whisper',
        'keyboard',
        'win32clipboard',
        # CUDA backend for faster-whisper; the bulk of these packages is collected
        # via collect_all above (binaries + datas + this hidden-import list).
        'ctranslate2',
        'nvidia',
        'nvidia.cublas',
        'nvidia.cuda_runtime',
        'nvidia.cuda_nvrtc',
        # openai SDK HTTP chain (lazy-imported submodules that
        # PyInstaller would otherwise miss).
        'openai',
        'openai._types',
        'openai._models',
        'openai._streaming',
        'openai._response',
        'openai._base_client',
        'openai._utils',
        'openai._utils._json',
        'certifi',
        'httpcore',
        'httpcore._sync',
        'httpcore._sync.http11',
        'httpcore._sync.connection',
        'httpcore._sync.connection_pool',
        'h11',
        'jiter',
        'pydantic_core',
        'anyio',
        'sniffio',
        'distro',
        'idna',
        'tqdm',
    ]
    + _pyside_hiddenimports
    + _ct2_hiddenimports
    + _nv_cublas_h
    + _nv_rt_h
    + _nv_nvrtc_h
    + _httpx_hiddenimports,
    hookspath=[str(REPO_ROOT / 'hooks')],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DictationAssistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(REPO_ROOT / 'app' / 'mic.ico'),
)
