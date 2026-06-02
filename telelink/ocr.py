from __future__ import annotations

from pathlib import Path
from typing import Any


def run_ocr(image_path: Path, config: dict[str, Any]) -> str:
    if not config.get("ocr", {}).get("enabled", False):
        return ""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    cmd = config.get("ocr", {}).get("tesseract_cmd") or ""
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    try:
        with Image.open(image_path) as img:
            return pytesseract.image_to_string(img).strip()
    except Exception:
        return ""
