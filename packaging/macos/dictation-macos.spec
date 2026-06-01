# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

REPO_ROOT = Path(SPECPATH).resolve().parents[1]


a = Analysis(
    [str(REPO_ROOT / 'app' / 'main.py')],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[(str(REPO_ROOT / 'app' / 'mic.ico'), 'app')],
    hiddenimports=[
        'app',
        'app.main',
        'app.config',
        'app.hotkeys',
        'app.audio',
        'app.clipboard',
        'app.inject',
        'app.llm',
        'app.logger',
        'app.stt',
        'app.vad',
        'app.tray',
        'app.platform',
        'app.platform.base',
        'app.platform.macos',
        'pystray',
        'pystray._darwin',
        'PIL',
        'PIL._tkinter_finder',
        'sounddevice',
        'faster_whisper',
        'pynput',
    ],
    hookspath=[str(REPO_ROOT / 'hooks')],
    runtime_hooks=[],
    excludes=[],
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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

app = BUNDLE(
    exe,
    name='DictationAssistant.app',
    icon=None,
    bundle_identifier='local.speechtotext.vllm',
)



