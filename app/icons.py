"""Tray icon rendering: load the base mic glyph, fit it to the canvas, and tint
it green (active) or red (paused). Kept separate from the tray controller so the
pure PIL logic is testable without pystray/Qt."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

_BASE_ICON: Image.Image | None = None


def fit_icon_to_canvas(img: Image.Image, margin: int = 0) -> Image.Image:
    """Crop to the glyph's alpha bounding box and center it on the full canvas."""
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return rgba

    left, top, right, bottom = bbox
    if (left, top, right, bottom) == (0, 0, rgba.width, rgba.height):
        return rgba

    cropped = rgba.crop(bbox)
    target_width = max(1, rgba.width - margin * 2)
    target_height = max(1, rgba.height - margin * 2)
    scale = min(target_width / cropped.width, target_height / cropped.height)
    resized = cropped.resize(
        (max(1, round(cropped.width * scale)), max(1, round(cropped.height * scale))),
        Image.Resampling.LANCZOS,
    )

    fitted = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    offset_x = (rgba.width - resized.width) // 2
    offset_y = (rgba.height - resized.height) // 2
    fitted.paste(resized, (offset_x, offset_y), resized)
    return fitted


def _resolve_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "app" / "mic.ico"  # type: ignore[attr-defined]
    return Path(__file__).parent / "mic.ico"


def load_base_icon() -> Image.Image:
    global _BASE_ICON
    if _BASE_ICON is None:
        _BASE_ICON = fit_icon_to_canvas(Image.open(_resolve_icon_path()))
    return _BASE_ICON


def tint_icon(paused: bool = False, processing: bool = False) -> Image.Image:
    """Return a tinted copy of the base icon.

    Colors:
    - Green (default): active, idle.
    - Yellow (processing): actively transcribing or running LLM.
    - Red (paused): hotkeys disabled.
    """
    img = load_base_icon().copy()
    alpha = img.getchannel("A")
    luminance = ImageOps.grayscale(img)

    if paused:
        dark_color = (90, 20, 20)
        light_color = (220, 50, 50)
    elif processing:
        dark_color = (90, 80, 10)
        light_color = (230, 200, 50)
    else:
        dark_color = (20, 60, 30)
        light_color = (50, 200, 80)

    tinted = ImageOps.colorize(luminance, black=dark_color, white=light_color).convert("RGBA")
    tinted.putalpha(alpha)

    enhancer = ImageEnhance.Color(tinted)
    tinted = enhancer.enhance(1.4 if paused else 1.2)

    return tinted
