"""Terminal inline preview for caught attachments (Pillow 24-bit half-blocks)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from telelink.preview_media import (
    VISUAL_EXTENSIONS,
    load_rgba,
    parse_size_spec,
)

_HALF_BLOCK = "\u2584"
_RESET = "\033[0m"
_ALPHA_CUTOFF = 16


def _pillow_available() -> bool:
    try:
        from PIL import Image  # noqa: F401

        return True
    except ImportError:
        return False


def is_available(config: dict[str, Any] | None = None) -> bool:
    del config
    from telelink.terminal import color_capable

    return _pillow_available() and color_capable()


def preview_options(config: dict[str, Any] | None = None) -> dict[str, str]:
    media = (config or {}).get("media", {})
    preview = media.get("preview") if isinstance(media.get("preview"), dict) else {}
    opts: dict[str, str] = {"width": str(preview.get("width", "58%"))}
    height = preview.get("height")
    if height is not None and str(height).strip():
        opts["height"] = str(height)
    if preview.get("max_edge"):
        opts["max_edge"] = str(int(preview["max_edge"]))
    return opts


def preview_enabled(config: dict[str, Any] | None = None) -> bool:
    if os.environ.get("TELELINK_NO_IMAGE_PREVIEW") == "1":
        return False
    preview = ((config or {}).get("media") or {}).get("preview") or {}
    if isinstance(preview, dict) and preview.get("enabled") is False:
        return False
    return is_available(config)


def _fit_pixel_size(
    img_w: int,
    img_h: int,
    *,
    term_cols: int,
    term_rows: int,
    width: str | int,
    height: str | int | None,
) -> tuple[int, int]:
    """Pixel size for half-block render (height is 2× terminal row count)."""
    out_w = parse_size_spec(width, term_cols)
    out_h = max(2, int(out_w * img_h / max(img_w, 1)))
    if out_h % 2:
        out_h += 1

    if height is not None:
        max_rows = parse_size_spec(height, term_rows, default_pct=0.45)
        max_h = max(2, max_rows * 2)
        if out_h > max_h:
            out_h = max_h
            out_w = max(16, int(out_h * img_w / max(img_h, 1)))

    out_w = min(out_w, max(16, term_cols - 2))
    return out_w, out_h


def _ansi_rgb(r: int, g: int, b: int, *, background: bool = False) -> str:
    code = 48 if background else 38
    return f"\033[{code};2;{r};{g};{b}m"


def _render_half_blocks(img: Any) -> str:
    w, h = img.size
    pixels = img.load()
    lines: list[str] = []

    for y in range(0, h, 2):
        row: list[str] = []
        y2 = y + 1 if y + 1 < h else y
        for x in range(w):
            r1, g1, b1, a1 = pixels[x, y]
            r2, g2, b2, a2 = pixels[x, y2]

            if a1 < _ALPHA_CUTOFF and a2 < _ALPHA_CUTOFF:
                row.append(" ")
            elif a1 < _ALPHA_CUTOFF:
                row.append(f"{_ansi_rgb(r2, g2, b2, background=True)} {_RESET}")
            elif a2 < _ALPHA_CUTOFF or (r1, g1, b1) == (r2, g2, b2):
                row.append(f"{_ansi_rgb(r1, g1, b1, background=True)} {_RESET}")
            else:
                row.append(
                    f"{_ansi_rgb(r1, g1, b1)}"
                    f"{_ansi_rgb(r2, g2, b2, background=True)}"
                    f"{_HALF_BLOCK}{_RESET}"
                )
        lines.append("".join(row))
    return "\n".join(lines)


def render_file(
    path: Path,
    *,
    width: str | int = "58%",
    height: str | int | None = None,
    max_edge: int = 960,
    config: dict[str, Any] | None = None,
) -> str | None:
    """Return ANSI lines for an inline watcher preview, or None if unavailable."""
    del config
    src = Path(path)
    if src.suffix.lower() not in VISUAL_EXTENSIONS or not preview_enabled():
        return None

    img = load_rgba(src, max_edge=max_edge, allow_video=True)
    if img is None:
        return None

    from telelink.terminal import terminal_size

    cols, rows = terminal_size()
    tw, th = _fit_pixel_size(
        *img.size,
        term_cols=cols,
        term_rows=rows,
        width=width,
        height=height,
    )
    if img.size != (tw, th):
        from PIL import Image

        img = img.resize((tw, th), Image.Resampling.LANCZOS)

    return _render_half_blocks(img)
