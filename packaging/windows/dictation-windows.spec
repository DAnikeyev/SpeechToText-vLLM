# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

REPO_ROOT = Path(SPECPATH).resolve().parents[1]

# PySide6 (Qt) ships plugins, translations, and the shiboken binding generator
# that PyInstaller cannot discover by static analysis. collect_all gathers them.
_pyside_datas, _pyside_binaries, _pyside_hiddenimports = collect_all("PySide6")


a = Analysis(
    [str(REPO_ROOT / 'app' / 'main.py')],
    pathex=[str(REPO_ROOT)],
    binaries=_pyside_binaries,
    datas=[(str(REPO_ROOT / 'app' / 'mic.ico'), 'app')] + _pyside_datas,
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
    ] + _pyside_hiddenimports,
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
