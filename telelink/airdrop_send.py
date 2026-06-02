"""Apple AirDrop via OpenDrop — discover receivers and send files (PC → iPhone).

Requires AWDL: macOS built-in, or Linux with OWL (https://github.com/seemoo-lab/owl).
Native Windows Wi-Fi cannot run AirDrop; use SSH mode to a Mac/Linux helper host.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from telelink import chalk, pretty
from telelink.duration import format_duration, parse_duration
from telelink.outtake_share import prepare_share_file, resolve_local_paths

_OPENDROP_REPO = "https://github.com/seemoo-lab/opendrop"
_PI_INTEGRATION_LABEL = (
    "Waiting on Raspberry Pi integration — AirDrop from this PC will route through "
    "a Pi on your LAN (OWL + OpenDrop). Use outtake for sharing until then."
)
_FOUND_LINE = re.compile(
    r"Found\s+index\s+(\d+)\s+ID\s+([0-9a-fA-F]+)\s+name\s+(.+)$",
    re.IGNORECASE,
)


def _airdrop_cfg(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("airdrop", {}) or {}


def airdrop_enabled(config: dict[str, Any]) -> bool:
    return bool(_airdrop_cfg(config).get("enabled", False))


def airdrop_find_timeout_seconds(config: dict[str, Any]) -> int:
    ad = _airdrop_cfg(config)
    sec = parse_duration(ad.get("find_timeout", "20s"))
    return int(sec) if sec and sec > 0 else 20


def airdrop_discovery_ttl_seconds(config: dict[str, Any]) -> int:
    ad = _airdrop_cfg(config)
    sec = parse_duration(ad.get("discovery_ttl", "60s"))
    return int(sec) if sec and sec > 0 else 60


def airdrop_cache_dir(config: dict[str, Any]) -> Path:
    ad = _airdrop_cfg(config)
    raw = (ad.get("cache_dir") or "").strip()
    if raw:
        from telelink.config import expand_path

        return expand_path(raw)
    return Path.home() / ".opendrop"


def airdrop_mode(config: dict[str, Any]) -> str:
    mode = (_airdrop_cfg(config).get("mode") or "local").strip().lower()
    return mode if mode in ("local", "ssh") else "local"


def airdrop_ssh_host(config: dict[str, Any]) -> str:
    ssh = _airdrop_cfg(config).get("ssh", {}) or {}
    return (ssh.get("host") or "").strip()


def print_airdrop_intro() -> None:
    """Shown at the start of every `airdrop` command."""
    pretty.info("AIRDROP", _PI_INTEGRATION_LABEL)


def platform_airdrop_note() -> str:
    if sys.platform == "win32":
        return (
            "AirDrop needs AWDL (macOS or Linux+OWL). Windows Wi-Fi cannot run OpenDrop natively. "
            "Use airdrop.mode: ssh to a Mac or Linux helper, or use outtake (GitHub QR) instead."
        )
    if sys.platform == "darwin":
        return "macOS: ensure iPhone AirDrop is Everyone (or Contacts) and visible."
    return "Linux: run OWL on a compatible Wi-Fi adapter (sudo owl -i wlan0) before airdrop."


def airdrop_availability(config: dict[str, Any]) -> tuple[bool, str]:
    if not airdrop_enabled(config):
        return False, "airdrop.enabled is false — config edit airdrop_enabled true"
    try:
        resolve_opendrop_bin(config)
    except FileNotFoundError as exc:
        return False, str(exc)
    mode = airdrop_mode(config)
    if mode == "ssh":
        if not airdrop_ssh_host(config):
            return False, "airdrop.mode is ssh but airdrop.ssh.host is empty"
        return True, f"SSH helper {airdrop_ssh_host(config)}"
    if sys.platform == "win32":
        return False, platform_airdrop_note()
    return True, platform_airdrop_note()


def resolve_opendrop_bin(config: dict[str, Any]) -> str:
    ad = _airdrop_cfg(config)
    explicit = (ad.get("binary") or "").strip()
    if explicit:
        p = Path(os.path.expandvars(os.path.expanduser(explicit)))
        if p.is_file():
            return str(p)
        found = shutil.which(explicit)
        if found:
            return found
        raise FileNotFoundError(f"airdrop.binary not found: {explicit}")

    venv_bin = Path(sys.prefix) / "Scripts" / "opendrop.exe"
    if venv_bin.is_file():
        return str(venv_bin)
    venv_unix = Path(sys.prefix) / "bin" / "opendrop"
    if venv_unix.is_file():
        return str(venv_unix)

    found = shutil.which("opendrop")
    if found:
        return found

    raise FileNotFoundError(
        "opendrop not found. Install: pip install opendrop  "
        f"(see {_OPENDROP_REPO})"
    )


def _sender_flags(config: dict[str, Any]) -> list[str]:
    ad = _airdrop_cfg(config)
    owner = config.get("owner", {}) or {}
    name = (ad.get("computer_name") or owner.get("personal_name_short") or "").strip()
    model = (ad.get("computer_model") or "TeleLink").strip()
    iface = (ad.get("interface") or "awdl0").strip()
    flags: list[str] = ["-i", iface]
    if name:
        flags.extend(["-n", name])
    if model:
        flags.extend(["-m", model])
    return flags


def _build_opendrop_cmd(
    config: dict[str, Any],
    subcmd: list[str],
    *,
    timeout: int | None = None,
) -> list[str]:
    mode = airdrop_mode(config)
    bin_path = resolve_opendrop_bin(config)
    base = [bin_path, *_sender_flags(config), *subcmd]

    if mode != "ssh":
        return base

    host = airdrop_ssh_host(config)
    ssh = _airdrop_cfg(config).get("ssh", {}) or {}
    remote = (ssh.get("opendrop_path") or "opendrop").strip()
    remote_cmd = " ".join([shlex.quote(remote)] + [shlex.quote(a) for a in _sender_flags(config) + subcmd])
    ssh_args = ["ssh", "-o", "BatchMode=yes"]
    identity = (ssh.get("identity_file") or "").strip()
    if identity:
        ssh_args.extend(["-i", os.path.expanduser(identity)])
    ssh_args.append(host)
    ssh_args.append(remote_cmd)
    return ssh_args


def run_opendrop(
    config: dict[str, Any],
    subcmd: list[str],
    *,
    timeout: int | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = _build_opendrop_cmd(config, subcmd)
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"opendrop timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        if airdrop_mode(config) == "ssh":
            raise FileNotFoundError("ssh not found on PATH") from exc
        raise


def _parse_find_stdout(text: str) -> list[dict[str, Any]]:
    receivers: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        m = _FOUND_LINE.search(line.strip())
        if m:
            receivers.append(
                {
                    "index": int(m.group(1)),
                    "id": m.group(2).lower(),
                    "name": m.group(3).strip(),
                }
            )
    return receivers


def read_discovery_cache(config: dict[str, Any]) -> list[dict[str, Any]]:
    cache = airdrop_cache_dir(config) / "discover.last.json"
    if not cache.is_file():
        return []
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [_normalize_receiver(r) for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        items = data.get("receivers") or data.get("devices") or []
        if isinstance(items, list):
            return [_normalize_receiver(r) for r in items if isinstance(r, dict)]
    return []


def _normalize_receiver(raw: dict[str, Any]) -> dict[str, Any]:
    idx = raw.get("index", raw.get("idx", -1))
    rid = str(raw.get("id", raw.get("device_id", ""))).lower()
    name = str(raw.get("name", raw.get("display_name", ""))).strip()
    try:
        index = int(idx)
    except (TypeError, ValueError):
        index = -1
    return {"index": index, "id": rid, "name": name}


def discovery_cache_age_seconds(config: dict[str, Any]) -> float | None:
    cache = airdrop_cache_dir(config) / "discover.last.json"
    if not cache.is_file():
        return None
    return time.time() - cache.stat().st_mtime


def run_find(config: dict[str, Any], *, timeout: int | None = None) -> list[dict[str, Any]]:
    timeout = timeout if timeout is not None else airdrop_find_timeout_seconds(config)
    proc = run_opendrop(config, ["find"], timeout=timeout, check=False)
    stdout = (proc.stdout or "") + (proc.stderr or "")
    receivers = _parse_find_stdout(stdout)
    if not receivers:
        receivers = read_discovery_cache(config)
    return receivers


def resolve_receiver(
    query: str,
    receivers: list[dict[str, Any]],
    config: dict[str, Any],
) -> str:
    q = (query or "").strip()
    if not q:
        default = (_airdrop_cfg(config).get("default_receiver") or "").strip()
        if default:
            q = default
        else:
            raise ValueError("no receiver specified")

    aliases = _airdrop_cfg(config).get("receivers") or []
    if isinstance(aliases, list):
        for entry in aliases:
            if not isinstance(entry, dict):
                continue
            alias = str(entry.get("alias", "")).strip()
            match = str(entry.get("match", entry.get("name", ""))).strip()
            if alias and q.lower() == alias.lower():
                q = match
                break

    if q.isdigit():
        idx = int(q)
        for r in receivers:
            if r.get("index") == idx:
                return str(idx)
        if 0 <= idx < len(receivers):
            return str(idx)

    q_lower = q.lower()
    for r in receivers:
        if r.get("id", "").lower().startswith(q_lower) or q_lower == r.get("id", "").lower():
            return r.get("id") or q
        if r.get("name", "").lower() == q_lower:
            return r.get("name") or q
        if q_lower in r.get("name", "").lower():
            return r.get("name") or q

    return q


def format_receivers_table(receivers: list[dict[str, Any]]) -> str:
    from telelink.table import Table

    if not receivers:
        return chalk.muted("  (no receivers found — open AirDrop on iPhone, set visibility to Everyone)")

    table = Table(
        head=["Index", "ID", "Name"],
        col_widths=[8, 14, 36],
        value_cols=[0, 1, 2],
    )
    for r in receivers:
        table.push([str(r.get("index", "")), str(r.get("id", "")), str(r.get("name", ""))])
    return table.to_string()


def send_file(
    receiver: str,
    file_path: Path | str,
    config: dict[str, Any],
    *,
    as_url: bool = False,
) -> None:
    target = str(file_path)
    if not as_url and not Path(target).is_file():
        raise FileNotFoundError(f"not a file: {target}")

    age = discovery_cache_age_seconds(config)
    ttl = airdrop_discovery_ttl_seconds(config)
    if age is not None and age > ttl:
        pretty.warn(
            f"discovery cache is {int(age)}s old (>{ttl}s) — run airdrop again to refresh receivers"
        )

    subcmd = ["send", "-r", receiver, "-f", target]
    if as_url:
        subcmd.append("--url")

    label = Path(target).name if not as_url else target
    pretty.info("AIRDROP", f"sending {label} to {receiver} …")
    proc = run_opendrop(config, subcmd, timeout=300, check=False)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if out:
        for line in out.splitlines():
            pretty.info("AIRDROP", line.strip())

    combined = out.lower()
    if proc.returncode != 0:
        if "declined" in combined or "rejected" in combined:
            raise RuntimeError("receiver declined — tap Accept on the iPhone")
        raise RuntimeError(out or f"opendrop send failed (exit {proc.returncode})")

    if "successful" in combined or "accepted" in combined or proc.returncode == 0:
        pretty.info("AIRDROP", "upload complete — check iPhone for the file")
        return
    pretty.info("AIRDROP", "send finished — confirm on iPhone if prompted")


def send_paths(
    parts: list[str],
    receiver: str,
    config: dict[str, Any],
    *,
    as_url: bool = False,
) -> None:
    locals_ = resolve_local_paths(parts)
    if locals_ is None:
        from telelink.intake_runtime import normalize_share_url

        try:
            url = normalize_share_url(" ".join(parts))
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        send_file(receiver, url, config, as_url=True)
        return

    upload, is_temp = prepare_share_file(locals_)
    try:
        send_file(receiver, upload, config, as_url=as_url)
    finally:
        if is_temp:
            upload.unlink(missing_ok=True)


def outtake_prefers_airdrop(config: dict[str, Any], *, force: bool = False) -> bool:
    if force:
        return True
    ot = config.get("outtake", {}) or {}
    transport = (ot.get("transport") or "auto").strip().lower()
    if transport == "airdrop":
        return True
    if transport == "github":
        return False
    if transport == "auto" and airdrop_enabled(config):
        ok, _ = airdrop_availability(config)
        return ok
    return False


def print_airdrop_status(config: dict[str, Any]) -> None:
    ad = _airdrop_cfg(config)
    enabled = airdrop_enabled(config)
    if not enabled:
        print(f"  airdrop: {chalk.value('off')} ({chalk.muted('config edit airdrop_enabled true')})")
        print(f"    {chalk.muted(_PI_INTEGRATION_LABEL)}")
        return

    ok, note = airdrop_availability(config)
    mode = airdrop_mode(config)
    try:
        bin_label = Path(resolve_opendrop_bin(config)).name
    except FileNotFoundError:
        bin_label = "missing"

    state = chalk.value("ready") if ok else chalk.muted("limited")
    timeout = format_duration(airdrop_find_timeout_seconds(config))
    print(
        f"  airdrop: {state} mode={chalk.value(mode)} bin={chalk.value(bin_label)} "
        f"find={chalk.value(timeout)}"
    )
    print(f"    {chalk.muted(note)}")
