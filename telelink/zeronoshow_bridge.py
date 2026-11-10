"""ZeroNoShow bridge: send ZeroNoShow SMS from the paired iPhone via Phone Link.

ZeroNoShow (server) queues SMS for its "telelink" provider. This bridge:

1. makes sure Phone Link is running (the iPhone reconnects over Bluetooth by itself),
2. claims queued SMS from ZeroNoShow  (POST /api/sms/telelink/claim),
3. sends each one with TeleLink's normal Phone Link automation,
4. reports the outcome                 (POST /api/sms/telelink/report),
5. forwards replies from numbers it texted (POST /api/sms/telelink/inbound),
   read from Phone Link's phone.db. Personal SMS from anyone else never leave the PC.

Run:  .\\telelink.ps1 zns run      (loop)   ·   zns once   ·   zns status
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

STATE_FILE = "zeronoshow_bridge.json"
TOKEN_ENV = "ZERONOSHOW_BRIDGE_TOKEN"
PHONE_LINK_PROCESSES = ("PhoneExperienceHost.exe", "YourPhone.exe")
DEFAULT_AUMID = "Microsoft.YourPhone_8wekyb3d8bbwe!App"


# ---------------------------------------------------------------- config / state


def bridge_settings(config: dict[str, Any]) -> dict[str, Any]:
    raw = dict(config.get("zeronoshow") or {})
    token = str(os.environ.get(TOKEN_ENV) or raw.get("token") or "").strip()
    return {
        "enabled": bool(raw.get("enabled", True)),
        "url": str(raw.get("url") or "").strip().rstrip("/"),
        "token": token,
        "poll_seconds": max(5, int(raw.get("poll_seconds", 20))),
        "batch": max(1, min(20, int(raw.get("batch", 3)))),
        "send_gap_seconds": max(0.0, float(raw.get("send_gap_seconds", 6))),
        "inbound": bool(raw.get("inbound", True)),
        "inbound_window_days": max(1, int(raw.get("inbound_window_days", 14))),
        "launch_phone_link": bool(raw.get("launch_phone_link", True)),
        "timeout_seconds": max(5, int(raw.get("timeout_seconds", 20))),
    }


def state_path(config: dict[str, Any]) -> Path:
    out = config.get("output") or {}
    return Path(out.get("dir", "./data")) / STATE_FILE


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("recipients", {})
            data.setdefault("inbound_seen", [])
            return data
    except (OSError, ValueError):
        pass
    return {"recipients": {}, "inbound_watermark": None, "inbound_seen": []}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def phone_key(value: str) -> str:
    """Last 9 digits: matches +33612345678, 0612345678 and 33612345678 alike."""
    digits = re.sub(r"\D", "", value or "")
    return digits[-9:] if len(digits) >= 9 else ""


def remember_recipient(state: dict[str, Any], phone: str, now: datetime) -> None:
    key = phone_key(phone)
    if key:
        state.setdefault("recipients", {})[key] = now.isoformat()


def prune_recipients(state: dict[str, Any], now: datetime, window_days: int) -> None:
    cutoff = now - timedelta(days=window_days)
    kept: dict[str, str] = {}
    for key, iso in (state.get("recipients") or {}).items():
        try:
            when = datetime.fromisoformat(iso)
        except ValueError:
            continue
        if when >= cutoff:
            kept[key] = iso
    state["recipients"] = kept


def is_known_recipient(state: dict[str, Any], phone: str) -> bool:
    key = phone_key(phone)
    return bool(key) and key in (state.get("recipients") or {})


# ---------------------------------------------------------------- HTTP


class BridgeHttpError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def api_post(settings: dict[str, Any], path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not settings["url"]:
        raise RuntimeError("zeronoshow.url is not set in config.yaml")
    if not settings["token"]:
        raise RuntimeError(f"bridge token missing — set {TOKEN_ENV} or zeronoshow.token")
    req = urllib.request.Request(
        settings["url"] + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {settings['token']}",
            "Content-Type": "application/json",
            "User-Agent": "TeleLink-ZeroNoShow-Bridge",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=settings["timeout_seconds"]) as resp:
            body = resp.read().decode("utf-8") or "{}"
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise BridgeHttpError(exc.code, detail) from exc


# ---------------------------------------------------------------- Phone Link


def phone_link_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.lower()
    except OSError:
        return False
    return any(name.lower() in out for name in PHONE_LINK_PROCESSES)


def ensure_phone_link(config: dict[str, Any], *, launch: bool) -> bool:
    """Start Phone Link if needed. The iPhone then reconnects over Bluetooth on its own."""
    if phone_link_running():
        return True
    if not launch or sys.platform != "win32":
        return False
    ids = (config.get("phone_link") or {}).get("app_user_model_ids") or [DEFAULT_AUMID]
    try:
        subprocess.run(
            ["explorer.exe", f"shell:AppsFolder\\{ids[0]}"],
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    for _ in range(15):
        time.sleep(1)
        if phone_link_running():
            time.sleep(4)  # let the Bluetooth link come up
            return True
    return False


# ---------------------------------------------------------------- outbound


def classify_send_result(record: dict[str, Any]) -> tuple[str, str | None]:
    """Map TeleLink send_message() output to a ZeroNoShow report ('sent'|'failed', error)."""
    if record.get("auto_sent"):
        return "sent", None
    if record.get("send_clicked"):
        # Phone Link UI did not confirm. Report failure (never retried server-side,
        # so no duplicate), but say the SMS may have left.
        return "failed", "envoi non vérifié dans Phone Link (peut être parti) — " + str(
            record.get("note") or ""
        )
    if "send_clicked" not in record:
        return "failed", "messaging.method doit être 'auto' pour le pont ZeroNoShow"
    return "failed", str(record.get("note") or "Send introuvable dans Phone Link")


def process_outbound(
    config: dict[str, Any],
    settings: dict[str, Any],
    state: dict[str, Any],
    *,
    send: Callable[..., dict[str, Any]] | None = None,
    post: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]] = api_post,
    log: Callable[[str], None] = print,
) -> int:
    if send is None:
        from telelink.messaging import send_message as send

    claimed = post(settings, "/api/sms/telelink/claim", {"limit": settings["batch"]})
    messages = list(claimed.get("messages") or [])
    done = 0
    for index, msg in enumerate(messages):
        if index and settings["send_gap_seconds"]:
            time.sleep(settings["send_gap_seconds"])
        to = str(msg.get("to") or "")
        try:
            record = send(to, str(msg.get("body") or ""), config=config, raw=True)
            status, error = classify_send_result(record)
        except Exception as exc:  # noqa: BLE001 — any failure must be reported, not retried
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:300]

        payload: dict[str, Any] = {"id": msg["id"], "status": status}
        if error:
            payload["error"] = error[:480]
        if status == "sent":
            remember_recipient(state, to, datetime.now(timezone.utc))

        for attempt in range(3):
            try:
                post(settings, "/api/sms/telelink/report", payload)
                break
            except (urllib.error.URLError, OSError, BridgeHttpError) as exc:
                if isinstance(exc, BridgeHttpError) and exc.status < 500:
                    log(f"[zns] report refused for {msg['id']}: {exc}")
                    break
                time.sleep(2 * (attempt + 1))
        log(f"[zns] {status.upper():6} → {_mask(to)}" + (f"  ({error})" if error else ""))
        done += 1
    return done


def _mask(phone: str) -> str:
    return phone[:4] + "****" + phone[-3:] if len(phone) > 7 else "***"


# ---------------------------------------------------------------- inbound


def _phone_db(config: dict[str, Any]) -> Path | None:
    try:
        from telelink.phone_link_messages import resolve_phone_db_path

        return resolve_phone_db_path(config)
    except Exception:  # noqa: BLE001
        return None


def read_incoming_since(db_path: Path, watermark: Any, limit: int = 200) -> list[dict[str, Any]]:
    """Incoming rows from Phone Link phone.db with timestamp >= watermark (classic layout)."""
    from telelink.phone_link_messages import (
        _connect_readonly,
        _message_direction,
        _row_timestamp_iso,
    )

    conn = _connect_readonly(db_path)
    if not conn:
        return []
    try:
        if watermark is None:
            rows = conn.execute(
                "SELECT message_id, timestamp, type AS msg_type, from_address, body "
                "FROM message ORDER BY timestamp DESC LIMIT 1"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT message_id, timestamp, type AS msg_type, from_address, body "
                "FROM message WHERE timestamp >= ? ORDER BY timestamp ASC LIMIT ?",
                (watermark, limit),
            ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out = []
    for row in rows:
        rd = dict(row)
        out.append(
            {
                "message_id": str(rd.get("message_id")),
                "raw_ts": rd.get("timestamp"),
                "direction": _message_direction(rd.get("msg_type")),
                "from": str(rd.get("from_address") or "").strip(),
                "body": str(rd.get("body") or "").strip(),
                "at": _row_timestamp_iso(rd),
            }
        )
    return out


def select_inbound(rows: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
    seen = set(state.get("inbound_seen") or [])
    return [
        r
        for r in rows
        if r["direction"] == "in"
        and r["message_id"] not in seen
        and r["body"]
        and is_known_recipient(state, r["from"])
    ]


def process_inbound(
    config: dict[str, Any],
    settings: dict[str, Any],
    state: dict[str, Any],
    *,
    post: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]] = api_post,
    log: Callable[[str], None] = print,
) -> int:
    db_path = _phone_db(config)
    if not db_path:
        return 0
    if state.get("inbound_watermark") is None:
        # First run: start from "now", never upload history.
        latest = read_incoming_since(db_path, None)
        state["inbound_watermark"] = latest[0]["raw_ts"] if latest else 0
        return 0

    rows = read_incoming_since(db_path, state["inbound_watermark"])
    forwarded = 0
    seen: list[str] = list(state.get("inbound_seen") or [])
    for row in select_inbound(rows, state):
        post(
            settings,
            "/api/sms/telelink/inbound",
            {
                "externalId": f"plink-{row['message_id']}-{row['raw_ts']}",
                "from": row["from"],
                "body": row["body"][:1600],
                "receivedAt": row["at"],
            },
        )
        seen.append(row["message_id"])
        forwarded += 1
        log(f"[zns] reply  ← {_mask(row['from'])}")
    if rows:
        state["inbound_watermark"] = rows[-1]["raw_ts"]
    state["inbound_seen"] = seen[-500:]
    return forwarded


# ---------------------------------------------------------------- loop / CLI


def run_once(config: dict[str, Any], *, log: Callable[[str], None] = print) -> dict[str, int]:
    settings = bridge_settings(config)
    path = state_path(config)
    state = load_state(path)
    now = datetime.now(timezone.utc)
    prune_recipients(state, now, settings["inbound_window_days"])

    result = {"sent": 0, "replies": 0}
    if not ensure_phone_link(config, launch=settings["launch_phone_link"]):
        log("[zns] Phone Link not running — waiting (open Phone Link, iPhone Bluetooth on)")
        save_state(path, state)
        return result
    try:
        result["sent"] = process_outbound(config, settings, state, log=log)
    finally:
        save_state(path, state)
    if settings["inbound"]:
        try:
            result["replies"] = process_inbound(config, settings, state, log=log)
        finally:
            save_state(path, state)
    return result


def cmd_zns(args: Namespace) -> int:
    from telelink.session import get_session

    action = str(getattr(args, "zns_action", None) or "status")
    config = get_session().config_fresh()
    settings = bridge_settings(config)

    if action == "status":
        print(
            json.dumps(
                {
                    "url": settings["url"] or None,
                    "token_set": bool(settings["token"]),
                    "messaging_method": (config.get("messaging") or {}).get("method"),
                    "phone_link_running": phone_link_running(),
                    "phone_db": str(_phone_db(config) or "") or None,
                    "state_file": str(state_path(config)),
                },
                indent=2,
            )
        )
        if settings["url"] and settings["token"]:
            try:
                probe = api_post(settings, "/api/sms/telelink/claim", {"limit": 1, "dryRun": True})
            except BridgeHttpError as exc:
                if exc.status in (401, 503):
                    print(f"server check failed: {exc}")
                    return 1
            except Exception as exc:  # noqa: BLE001
                print(f"server unreachable: {exc}")
                return 1
            print(f"server: OK (token accepted) · SMS en attente: {probe.get('pending', '?')}")
        return 0

    if not settings["url"] or not settings["token"]:
        print(f"Configure zeronoshow.url in config.yaml and set {TOKEN_ENV}.")
        return 1
    if str((config.get("messaging") or {}).get("method", "")).lower() not in ("auto", "phone_link_auto"):
        print("messaging.method must be 'auto' so SMS are sent without a manual click.")
        return 1

    if action == "once":
        print(json.dumps(run_once(config)))
        return 0

    print(
        f"[zns] ZeroNoShow bridge → {settings['url']}  (every {settings['poll_seconds']}s, Ctrl+C to stop)"
    )
    while True:
        try:
            config = get_session().config_fresh()
            run_once(config)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 — keep the bridge alive
            print(f"[zns] error: {exc}")
        time.sleep(settings["poll_seconds"])
