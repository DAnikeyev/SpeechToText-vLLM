$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

py -3.11 -m pip install -r requirements/windows.txt
py -3.11 -m pip install pyinstaller

py -3.11 -m PyInstaller `
  --noconfirm `
  --clean `
  --distpath dist/windows `
  --workpath build/windows `
  packaging/windows/dictation-windows.spec

