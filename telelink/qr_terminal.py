"""Terminal QR codes — qrterminal CLI when available, half-block fallback (mdp/qrterminal style)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from io import StringIO

from telelink import chalk, ink_ui

MARGIN = ink_ui.MARGIN


def _try_qrterminal_cli(text: str) -> str | None:
    exe = shutil.which("qrterminal")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, text, "-l", "M"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.rstrip("\n")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _half_block_matrix(matrix: list[list[bool]]) -> list[str]:
    """Two QR rows per terminal row (▀▄█), like qrterminal HalfBlocks."""
    chars = []
    rows = len(matrix)
    cols = len(matrix[0]) if matrix else 0
    for r in range(0, rows, 2):
        line: list[str] = []
        for c in range(cols):
            top = matrix[r][c]
            bot = matrix[r + 1][c] if r + 1 < rows else False
            if top and bot:
                line.append("█")
            elif top:
                line.append("▀")
            elif bot:
                line.append("▄")
            else:
                line.append(" ")
        chars.append("".join(line))
    return chars


def _render_qrcode_lib(text: str, *, invert: bool = False) -> str:
    import qrcode

    err = getattr(qrcode, "ERROR_CORRECT_M", None) or qrcode.constants.ERROR_CORRECT_M
    qr = qrcode.QRCode(version=None, error_correction=err, box_size=1, border=1)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    if invert:
        matrix = [[not cell for cell in row] for row in matrix]
    return "\n".join(_half_block_matrix(matrix))


def render_qr_block(text: str) -> str:
    """Render QR for terminal display with TeleLink margin and colors."""
    raw = _try_qrterminal_cli(text) or _render_qrcode_lib(text)
    lines = raw.splitlines()
    styled = []
    for line in lines:
        if line.strip():
            styled.append(f"{MARGIN}{chalk.baby(line)}")
        else:
            styled.append("")
    return "\n".join(styled)


def print_qr(text: str, *, caption: str = "") -> None:
    if caption:
        print(f"{MARGIN}{chalk.label(caption)}", flush=True)
    print(render_qr_block(text), flush=True)
    print(flush=True)
