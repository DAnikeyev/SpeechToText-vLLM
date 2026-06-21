from __future__ import annotations

import os
import sys


def ensure_cuda_libs_on_path() -> None:
    """Prepend NVIDIA pip-packaged CUDA library directories to PATH on Windows.

    faster-whisper / CTranslate2 needs cublas64_12.dll and friends at runtime.
    When installed via pip (nvidia-cublas-cu12 etc.) the DLLs live inside
    site-packages but are not placed on PATH automatically, so CTranslate2
    cannot locate them unless we add them here.
    """
    if sys.platform != "win32":
        return
    try:
        import nvidia.cublas
        import nvidia.cuda_nvrtc
        import nvidia.cuda_runtime
    except Exception:
        return
    bins = [
        os.path.join(next(iter(nvidia.cublas.__path__)), "bin"),
        os.path.join(next(iter(nvidia.cuda_runtime.__path__)), "bin"),
        os.path.join(next(iter(nvidia.cuda_nvrtc.__path__)), "bin"),
    ]
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep)
    extra = [bin_dir for bin_dir in bins if bin_dir not in parts]
    if extra:
        os.environ["PATH"] = os.pathsep.join([*extra, *parts])
