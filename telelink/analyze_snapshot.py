"""Short-lived centered PNG snapshots in data/.analyze for AI assistants."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from telelink.duration import parse_duration
from telelink.preview_media import is_visual_file, load_rgba

_CANVAS_BG = (10, 18, 28)


def analyze_dir(config: dict[str, Any]) -> Path:
    out = config.get("output") or {}
    base = Path(out.get("dir", "./data"))
    analyze = config.get("analyze") if isinstance(config.get("analyze"), dict) else {}
    name = str(analyze.get("dir", ".analyze")).strip() or ".analyze"
    path = base / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def analyze_options(config: dict[str, Any]) -> dict[str, Any]:
    analyze = config.get("analyze") if isinstance(config.get("analyze"), dict) else {}
    enabled = analyze.get("screenshot", analyze.get("enabled", True))
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in ("0", "false", "off", "no", "disabled")
    ttl = parse_duration(analyze.get("ttl", analyze.get("ttl_seconds", "4m")))
    return {
        "enabled": bool(enabled),
        "ttl_seconds": ttl if ttl else 240,
        "width": int(analyze.get("width", 700)),
        "height": int(analyze.get("height", 500)),
        "margin": int(analyze.get("margin", 24)),
    }


def screenshot_enabled(config: dict[str, Any] | None) -> bool:
    if not config or os.environ.get("TELELINK_NO_IMAGE_PREVIEW") == "1":
        return False
    return analyze_options(config)["enabled"]


def render_centered_snapshot(
    source: Path,
    *,
    width: int = 700,
    height: int = 500,
    margin: int = 24,
) -> Any | None:
    """Letterboxed RGB canvas with the attachment centered."""
    from PIL import Image

    frame = load_rgba(source, allow_video=True)
    if frame is None:
        return None

    canvas = Image.new("RGB", (width, height), _CANVAS_BG)
    inner_w = max(32, width - margin * 2)
    inner_h = max(32, height - margin * 2)
    fitted = frame.copy()
    fitted.thumbnail((inner_w, inner_h), Image.Resampling.LANCZOS)
    x = (width - fitted.width) // 2
    y = (height - fitted.height) // 2
    if fitted.mode == "RGBA":
        canvas.paste(fitted, (x, y), fitted)
    else:
        canvas.paste(fitted, (x, y))
    return canvas


def capture_analyze_snapshot(
    source: Path,
    config: dict[str, Any],
    *,
    task_id: str = "",
    sender: str = "",
    channel: str = "",
    message_kind: str = "",
) -> Path | None:
    """Write latest.png and latest.json; returns the PNG path."""
    opts = analyze_options(config)
    if not opts["enabled"]:
        return None

    src = Path(source)
    if not is_visual_file(src):
        return None

    canvas = render_centered_snapshot(
        src,
        width=opts["width"],
        height=opts["height"],
        margin=opts["margin"],
    )
    if canvas is None:
        return None

    dest_dir = analyze_dir(config)
    png_path = dest_dir / "latest.png"
    json_path = dest_dir / "latest.json"
    tmp = dest_dir / f".latest-{int(time.time() * 1000)}.png"
    canvas.save(tmp, format="PNG", optimize=True)
    tmp.replace(png_path)

    meta = {
        "at": time.time(),
        "task_id": task_id,
        "sender": sender,
        "channel": channel,
        "message_kind": message_kind,
        "source_file": src.name,
        "source_path": str(src.resolve()),
        "width": opts["width"],
        "height": opts["height"],
        "ttl_seconds": opts["ttl_seconds"],
    }
    json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    prune_analyze_dir(config)
    return png_path


def prune_analyze_dir(config: dict[str, Any]) -> int:
    opts = analyze_options(config)
    ttl = opts["ttl_seconds"]
    if not ttl or ttl <= 0:
        return 0

    dest = analyze_dir(config)
    cutoff = time.time() - ttl
    removed = 0
    for path in dest.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            pass
    return removed


def capture_if_enabled(
    source: str | Path,
    config: dict[str, Any],
    *,
    task_id: str = "",
    sender: str = "",
    channel: str = "",
    message_kind: str = "",
) -> Path | None:
    try:
        return capture_analyze_snapshot(
            Path(source),
            config,
            task_id=task_id,
            sender=sender,
            channel=channel,
            message_kind=message_kind,
        )
    except Exception:
        return None
