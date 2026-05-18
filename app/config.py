from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppConfig:
    vllm_url: str = "http://127.0.0.1:8000/v1"
    model_name: str = "Qwen/Qwen3.5-9B-Instruct"
    microphone_device: int | str | None = None
    min_hold_seconds: float = 2.0
    record_start_delay_seconds: float = 0.2
    whisper_model: str = "medium"
    language_mode: str = "auto"
    vad_enabled: bool = True
    temperature: float = 0.1
    max_tokens: int = 512
    silence_rms_threshold: float = 0.005
    debug_save_wav: bool = False
    debug_wav_dir: str = "debug_recordings"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        known = {k: v for k, v in data.items() if k in cls.__annotations__}
        return cls(**known)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        cfg = AppConfig()
        save_config(config_path, cfg)
        return cfg

    with config_path.open("r", encoding="utf-8") as fp:
        raw = json.load(fp)
    return AppConfig.from_dict(raw)


def save_config(path: str | Path, config: AppConfig) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as fp:
        json.dump(config.to_dict(), fp, indent=2, ensure_ascii=False)
        fp.write("\n")
