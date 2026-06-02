from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from telelink.ui_automation.engines.appium_engine import DEFAULT_SERVER_URL

_PHONE_LINK_TITLE_KEYS = ("phone link", "your phone", "messages", "messaging")


def _boolish(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _appium_config(config: dict[str, Any]) -> dict[str, Any]:
    automation = (config.get("automation") if isinstance(config, dict) else {}) or {}
    appium = (automation.get("appium") if isinstance(automation, dict) else {}) or {}
    return appium if isinstance(appium, dict) else {}


def _server_url(config: dict[str, Any]) -> str:
    appium_cfg = _appium_config(config)
    url = str(appium_cfg.get("server_url") or DEFAULT_SERVER_URL).rstrip("/")
    if _boolish(appium_cfg.get("use_appium_server", False)):
        parsed = urllib.parse.urlparse(url)
        if parsed.path in ("", "/") and not url.lower().endswith("/wd/hub"):
            return f"{url}/wd/hub"
    return url


def _check_pywinauto_import() -> dict[str, str]:
    try:
        import pywinauto  # noqa: F401

        return {
            "id": "pywinauto_import",
            "status": "ok",
            "message": "pywinauto importable",
        }
    except Exception as exc:
        return {
            "id": "pywinauto_import",
            "status": "fail",
            "message": f"pywinauto unavailable ({exc})",
        }


def _check_phone_link_window() -> dict[str, str]:
    try:
        from telelink.ui_automation.session import find_phone_link_window
    except Exception:
        return {
            "id": "phone_link_window",
            "status": "warn",
            "message": "skipped (session helper missing)",
        }

    try:
        if find_phone_link_window(timeout_s=0.5):
            return {
                "id": "phone_link_window",
                "status": "ok",
                "message": "Phone Link window detected",
            }
    except Exception as exc:
        return {
            "id": "phone_link_window",
            "status": "warn",
            "message": f"window scan failed ({exc})",
        }

    return {
        "id": "phone_link_window",
        "status": "warn",
        "message": "Phone Link not open (optional for now)",
    }


def _http_request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 2.0,
) -> tuple[int, dict[str, Any] | None]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url=url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        body = None
        if raw:
            try:
                body = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                body = None
        return int(getattr(response, "status", 200)), body


def _probe_winappdriver(server_url: str) -> tuple[str, str]:
    status_urls = [urllib.parse.urljoin(f"{server_url}/", "status"), server_url]
    reachable = False
    for status_url in status_urls:
        try:
            code, _ = _http_request_json("GET", status_url, timeout=2.0)
            reachable = True
            status_note = f"reachable (GET {status_url} -> HTTP {code})"
            break
        except urllib.error.HTTPError as exc:
            reachable = True
            status_note = f"reachable (GET {status_url} -> HTTP {exc.code})"
            break
        except urllib.error.URLError:
            continue
        except OSError:
            continue
    if not reachable:
        return "fail", "cannot reach WinAppDriver/Appium server"

    probe_payload = {
        "capabilities": {
            "alwaysMatch": {
                "platformName": "Windows",
                "deviceName": "WindowsPC",
                "app": "Root",
            },
            "firstMatch": [{}],
        },
        "desiredCapabilities": {
            "platformName": "Windows",
            "deviceName": "WindowsPC",
            "app": "Root",
        },
    }
    session_url = urllib.parse.urljoin(f"{server_url}/", "session")
    session_id = ""
    try:
        _, body = _http_request_json(
            "POST",
            session_url,
            payload=probe_payload,
            timeout=3.0,
        )
        if isinstance(body, dict):
            session_id = str(body.get("sessionId") or (body.get("value") or {}).get("sessionId") or "")
        if session_id:
            try:
                delete_url = urllib.parse.urljoin(f"{session_url}/", session_id)
                _http_request_json("DELETE", delete_url, timeout=2.0)
            except Exception:
                pass
            return "ok", f"{status_note}; session probe passed"
        return "warn", f"{status_note}; session probe did not return sessionId"
    except urllib.error.HTTPError as exc:
        return "warn", f"{status_note}; session probe HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return "warn", f"{status_note}; session probe failed ({exc.reason})"
    except OSError as exc:
        return "warn", f"{status_note}; session probe failed ({exc})"


def _check_winappdriver(config: dict[str, Any]) -> dict[str, str]:
    url = _server_url(config)
    status, message = _probe_winappdriver(url)
    return {
        "id": "winappdriver_reachable",
        "status": status,
        "message": f"{message} [{url}]",
    }


def _check_appium_import() -> dict[str, str]:
    try:
        import appium.webdriver  # noqa: F401

        return {
            "id": "appium_import",
            "status": "ok",
            "message": "Appium-Python-Client importable",
        }
    except Exception as exc:
        return {
            "id": "appium_import",
            "status": "warn",
            "message": f"Appium-Python-Client missing ({exc})",
        }


def check_automation_health(config: dict[str, Any] | None) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else {}
    checks = [
        _check_pywinauto_import(),
        _check_phone_link_window(),
        _check_winappdriver(cfg),
        _check_appium_import(),
    ]

    failures = sum(1 for check in checks if check.get("status") == "fail")
    warnings = sum(1 for check in checks if check.get("status") == "warn")
    overall = "ok" if failures == 0 and warnings == 0 else ("warn" if failures == 0 else "fail")

    return {
        "ok": failures == 0,
        "status": overall,
        "failures": failures,
        "warnings": warnings,
        "server_url": _server_url(cfg),
        "checks": checks,
    }


def format_doctor_report(report: dict[str, Any]) -> str:
    status = str(report.get("status") or "unknown").upper()
    lines = [f"status: {status}"]
    for check in report.get("checks") or []:
        check_status = str(check.get("status") or "unknown").upper()
        lines.append(f"[{check_status}] {check.get('id')}: {check.get('message')}")
    return "\n".join(lines)
