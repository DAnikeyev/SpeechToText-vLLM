#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 -m pip install -r requirements/macos.txt
python3 -m pip install pyinstaller

python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath dist/macos \
  --workpath build/macos \
  packaging/macos/dictation-macos.spec

