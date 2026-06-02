"""Deliver a shareable URL via QR or SMS — used by intake and outtake."""

from __future__ import annotations

import sys
from typing import Any

from telelink import chalk, ink_ui, pretty
from telelink.qr_terminal import print_qr

MARGIN = ink_ui.MARGIN


def share_link_sms_body(label: str, url: str) -> str:
    """Single-line SMS body — no newlines; URLs must not pass through /n tag expansion."""
    return f"{label.strip()}: {url.strip()}"


def pick_share_delivery(*, prompt: str = "How do you want to share the link?") -> str:
    print(f"{MARGIN}{chalk.label(prompt)}", flush=True)
    print(f"{MARGIN}{chalk.baby('1')}  {chalk.plain('QR code — scan with your phone camera')}", flush=True)
    print(
        f"{MARGIN}{chalk.baby('2')}  {chalk.plain('Text message — open Phone Link SMS with the link')}",
        flush=True,
    )
    print(f"{MARGIN}{ink_ui.hint_bars()}", flush=True)
    if not sys.stdin.isatty():
        return "qr"
    sys.stdout.write(f"{MARGIN}{chalk.prompt('Choice')} {chalk.prompt('>')} ")
    sys.stdout.flush()
    from telelink.keys import read_line

    raw = read_line().strip().lower()
    if raw in ("2", "sms", "text", "message", "msg"):
        return "sms"
    return "qr"


def deliver_share_qr(
    url: str,
    *,
    caption: str,
    tag: str = "SHARE",
    hint: str = "",
) -> None:
    if hint:
        pretty.info(tag, hint)
    print(f"{MARGIN}{chalk.muted('URL')} {pretty.link(url)}", flush=True)
    print(flush=True)
    print_qr(url, caption=caption)


def deliver_share_sms(
    url: str,
    *,
    body: str,
    config: dict[str, Any] | None = None,
    tag: str = "SHARE",
    qr_caption: str = "Scan to open",
    qr_hint: str = "",
) -> None:
    from urllib.parse import quote

    from telelink import prompts
    from telelink.config import load_config
    from telelink.messaging import _open_uri, send_to_target
    from telelink.session import get_session

    config = config or load_config()
    who = prompts.text("Send to (contact name or +phone, Enter = compose only)")
    if who.strip():
        try:
            record = send_to_target(
                who.strip(),
                body,
                store=get_session().contact_store,
                config=config,
                raw=True,
            )
            pretty.info(tag, f"SMS compose opened for {record['to_phone']}")
        except ValueError as exc:
            pretty.warn(str(exc))
            deliver_share_qr(url, caption=qr_caption, tag=tag, hint=qr_hint)
    else:
        uri = f"sms:?body={quote(body)}"
        if _open_uri(uri, method="sms_uri"):
            pretty.info(tag, "SMS compose opened — tap Send in Phone Link")
        else:
            pretty.warn("could not open SMS — showing QR instead")
            deliver_share_qr(url, caption=qr_caption, tag=tag, hint=qr_hint)
    print(f"{MARGIN}{chalk.muted('URL')} {pretty.link(url)}", flush=True)


def run_share_delivery(
    url: str,
    *,
    config: dict[str, Any] | None = None,
    mode: str | None = None,
    prompt: str = "How do you want to share the link?",
    qr_caption: str = "Scan to open",
    tag: str = "SHARE",
    qr_hint: str = "",
    sms_body: str | None = None,
) -> None:
    """Pick QR or SMS (unless mode is set), then deliver the URL."""
    choice = (mode or "").lower() or pick_share_delivery(prompt=prompt)
    body = sms_body if sms_body is not None else url
    if choice in ("sms", "text", "message", "msg", "2"):
        deliver_share_sms(
            url,
            body=body,
            config=config,
            tag=tag,
            qr_caption=qr_caption,
            qr_hint=qr_hint,
        )
    else:
        deliver_share_qr(url, caption=qr_caption, tag=tag, hint=qr_hint)
