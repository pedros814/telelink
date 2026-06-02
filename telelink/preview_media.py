"""Shared image loading and sizing for watcher preview + analyze snapshots."""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
)
VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".3gp", ".mpeg", ".mpg"}
)
VISUAL_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def parse_size_spec(
    value: str | int,
    total: int,
    *,
    default_pct: float = 0.58,
    minimum: int = 16,
) -> int:
    """Parse config width/height as columns, rows, or percent of terminal size."""
    if isinstance(value, int):
        return max(minimum, value)
    text = str(value).strip()
    if text.endswith("%"):
        try:
            pct = float(text[:-1])
        except ValueError:
            pct = default_pct * 100
        return max(minimum, int(total * pct / 100))
    try:
        return max(minimum, int(text))
    except ValueError:
        return max(minimum, int(total * default_pct))


def is_visual_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VISUAL_EXTENSIONS


def _video_frame(path: Path) -> Any | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    try:
        r = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-vframes",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "-",
            ],
            capture_output=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    from PIL import Image

    return Image.open(io.BytesIO(r.stdout)).convert("RGBA")


def _video_placeholder(path: Path) -> Any:
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (400, 200), (10, 18, 28))
    draw = ImageDraw.Draw(canvas)
    draw.multiline_text(
        (200, 100),
        f"VIDEO\n{path.name}",
        fill=(135, 215, 255),
        anchor="mm",
        align="center",
    )
    return canvas.convert("RGBA")


def load_rgba(
    path: Path,
    *,
    max_edge: int | None = None,
    allow_video: bool = False,
) -> Any | None:
    """Open a visual attachment as RGBA; optional downscale and video first frame."""
    from PIL import Image

    src = Path(path)
    ext = src.suffix.lower()
    if ext not in VISUAL_EXTENSIONS:
        return None

    try:
        if ext == ".gif":
            with Image.open(src) as img:
                img.seek(0)
                frame = img.convert("RGBA")
        elif ext in VIDEO_EXTENSIONS:
            if not allow_video:
                return None
            frame = _video_frame(src) or _video_placeholder(src)
        else:
            with Image.open(src) as img:
                frame = img.convert("RGBA")

        if max_edge and max(frame.size) > max_edge:
            w, h = frame.size
            scale = max_edge / max(w, h)
            frame = frame.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )
        return frame
    except Exception:
        return None
