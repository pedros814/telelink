"""Place / follow / hang up an iPhone call through Phone Link, keeping its windows minimised.

Phone Link is the only way Windows can drive an iPhone call (Bluetooth). There is no API, so this is
UI automation (pywinauto / UIA), best effort:

* dial:    open ``tel:+33…`` (Phone Link fills the dialer), click its Call button if the call did not
           start by itself, then minimise every Phone Link window.
* in call: an "End call / Raccrocher" button exists in a Phone Link window.
* hang up: invoke that button (without bringing the window to front when UIA allows it).
* duration: read from Phone Link's calling.db after the call when possible, else measured.

Button names differ by Windows language / Phone Link version: they are configurable
(``zeronoshow.call_button_names`` / ``zeronoshow.end_call_button_names``) and
``telelink zns ui-dump`` writes the real UI tree to data/phone_link_ui_dump.txt to adjust them.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# One Phone Link automation at a time (SMS sending and calls share the same window).
UI_LOCK = threading.RLock()

PHONE_LINK_PROCESSES = ("phoneexperiencehost.exe", "yourphone.exe")
# « Appel » (auto_id ButtonCall) : nom réel du bouton du clavier de Phone Link en français (relevé le 10/11 sur le PC).
DEFAULT_CALL_NAMES = ("Appel", "Appeler", "Call", "Passer l'appel", "Composer", "Dial")
DEFAULT_END_NAMES = ("Raccrocher", "Terminer l'appel", "Mettre fin à l'appel", "End call", "Hang up", "Hangup")


def _names(config: dict[str, Any], key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = (config.get("zeronoshow") or {}).get(key)
    if isinstance(raw, list) and raw:
        return tuple(str(x) for x in raw if str(x).strip())
    return default


def name_regex(names: tuple[str, ...]) -> str:
    """Case-insensitive regex matching any of the names (exact or as a prefix, e.g. 'Call +33…')."""
    return r"(?i)^\s*(" + "|".join(re.escape(n) for n in names) + r")\b"


def dial_uri(phone: str) -> str:
    digits = re.sub(r"[^\d+]", "", phone or "")
    return "tel:" + digits


def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _phone_link_windows() -> list[Any]:
    """All top-level windows owned by Phone Link (main window and the small in-call window)."""
    if sys.platform != "win32":
        return []
    try:
        from pywinauto import Desktop

        from telelink.ui_automation.session import _window_process_name
    except ImportError:
        return []
    out = []
    try:
        for win in Desktop(backend="uia").windows():
            try:
                if _window_process_name(win).lower() in PHONE_LINK_PROCESSES:
                    out.append(win)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return []
    return out


def _find_button(names: tuple[str, ...], auto_id_re: str) -> Any | None:
    from telelink.ui_automation.find import find_control

    rx = name_regex(names)
    for win in _phone_link_windows():
        for spec in (
            {"title_re": rx, "control_type": "Button"},
            {"auto_id_re": auto_id_re, "control_type": "Button"},
        ):
            btn = find_control(win, spec, timeout=0.2)
            if btn is not None:
                return btn
    return None


def end_call_button(config: dict[str, Any]) -> Any | None:
    return _find_button(_names(config, "end_call_button_names", DEFAULT_END_NAMES), r"(?i).*(endcall|hangup|end_call|hang_up).*")


def call_button(config: dict[str, Any]) -> Any | None:
    return _find_button(_names(config, "call_button_names", DEFAULT_CALL_NAMES), r"(?i).*(callbutton|buttoncall|dialbutton|startcall|^call$).*")


def in_call(config: dict[str, Any]) -> bool:
    return end_call_button(config) is not None


def minimize_all(config: dict[str, Any]) -> None:
    if (config.get("zeronoshow") or {}).get("calls_show_window"):
        return
    from telelink.ui_stealth import minimize_window_stealth

    for win in _phone_link_windows():
        try:
            minimize_window_stealth(win, config)
        except Exception:  # noqa: BLE001
            continue


def _press(btn: Any) -> bool:
    from telelink.ui_automation.find import press

    if press(btn):
        return True
    # invoke() works through UIA without focusing the window; click_input() as fallback.
    for method in ("invoke", "click", "click_input"):
        try:
            getattr(btn.wrapper_object() if hasattr(btn, "wrapper_object") else btn, method)()
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def dial(phone: str, config: dict[str, Any], *, timeout_s: float = 12.0) -> tuple[bool, str]:
    """Start the call. Returns (started, detail)."""
    if sys.platform != "win32":
        return False, "Windows uniquement"
    with UI_LOCK:
        try:
            from telelink.messaging_auto import iphone_deconnecte, reconnecter_iphone

            if iphone_deconnecte(config) and not reconnecter_iphone(config, intervalle_min_s=0):
                return False, "iPhone non connecté à Phone Link (Bluetooth) : rapprochez l'iPhone, Bluetooth activé"
        except ImportError:
            pass
        try:
            from telelink.phone_link_hide import hide_all

            hide_all(config)  # hors écran AVANT d'ouvrir le lien tel: → aucune apparition
            subprocess.run(["cmd", "/c", "start", "", dial_uri(phone)], check=False, creationflags=_flags())
        except OSError as exc:
            return False, f"tel: non ouvert ({exc})"
        deadline = time.monotonic() + timeout_s
        clicked = False
        seen_button = False
        while time.monotonic() < deadline:
            time.sleep(0.5)
            if in_call(config):
                minimize_all(config)
                return True, "appel lancé"
            if not clicked:
                btn = call_button(config)
                if btn is None:
                    continue
                seen_button = True
                # On n'appuie qu'une fois le numéro affiché par Phone Link (sinon : appel vide, rien ne se passe).
                if number_ready(btn, phone) and press_call(btn):
                    clicked = True
                    # Phone Link crée sa fenêtre d'appel à ce moment : on la range aussitôt créée.
                    hide_new_windows(config, seconds=3.0)
        minimize_all(config)
        if clicked:
            return False, "Phone Link n'a pas démarré l'appel (iPhone connecté ?)"
        if seen_button:
            return False, "Le numéro ne s'est pas affiché dans Phone Link"
        return False, "Phone Link n'a pas lancé l'appel (bouton introuvable : lancez `telelink zns ui-dump`)"


def hide_new_windows(config: dict[str, Any], *, seconds: float, interval: float = 0.05) -> None:
    """Range hors écran toute fenêtre Phone Link dès qu'elle apparaît (fenêtre d'appel au 1er appel)."""
    try:
        from telelink.phone_link_hide import hide_hwnd, is_offscreen, phone_link_hwnds, window_mode, _rect
    except ImportError:
        return
    if window_mode(config) != "offscreen":
        return
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        for hwnd in phone_link_hwnds():
            try:
                rect = _rect(hwnd)
                if rect is not None and not is_offscreen(rect):
                    hide_hwnd(hwnd)
            except Exception:  # noqa: BLE001
                continue
        time.sleep(interval)


def number_ready(btn: Any, phone: str) -> bool:
    """Le bouton « Appel » de Phone Link porte le numéro composé (« Appel Numéro composé + 3 3 7 … »)."""
    want = re.sub(r"\D", "", phone or "")[-9:]
    try:
        got = re.sub(r"\D", "", str(btn.element_info.name or ""))
    except Exception:  # noqa: BLE001
        return True  # nom illisible : on tente quand même
    return not want or want in got


def press_call(btn: Any) -> bool:
    """Relevé sur le PC : Phone Link ignore UIA Invoke sur « Appel » ; focus + Espace lance l'appel.

    La fenêtre reste hors écran (invisible) ; la fenêtre de l'utilisateur reprend le premier plan juste après.
    """
    try:
        from pywinauto.keyboard import send_keys

        from telelink.win_console import get_foreground_hwnd, restore_foreground
    except ImportError:
        return _press(btn)
    previous = get_foreground_hwnd()
    try:
        top = btn.top_level_parent()
        top.set_focus()
        time.sleep(0.3)
        btn.set_focus()
        time.sleep(0.2)
        send_keys("{SPACE}")
        return True
    except Exception:  # noqa: BLE001
        return _press(btn)
    finally:
        time.sleep(0.3)
        if previous:
            try:
                restore_foreground(previous)
            except Exception:  # noqa: BLE001
                pass


def hang_up(config: dict[str, Any]) -> bool:
    with UI_LOCK:
        btn = end_call_button(config)
        return bool(btn is not None and _press(btn))


def last_call_duration(config: dict[str, Any], phone: str, since: datetime) -> int | None:
    """Duration (s) of the latest call to this number in Phone Link's calling.db, if found."""
    try:
        from telelink.phone_link_calls import read_call_history, resolve_calling_db_path
    except ImportError:
        return None
    db_path = resolve_calling_db_path(config)
    if not db_path:
        return None
    key = re.sub(r"\D", "", phone)[-9:]
    try:
        rows = read_call_history(Path(db_path), limit=10, since=since - timedelta(minutes=1))
    except Exception:  # noqa: BLE001
        return None
    for row in rows:
        if re.sub(r"\D", "", str(row.get("phone_number") or ""))[-9:] == key:
            try:
                return int(row.get("duration") or 0)
            except (TypeError, ValueError):
                return None
    return None


def ui_dump(config: dict[str, Any], out: Path) -> Path:
    """Write every Phone Link window's control tree (names, types, automation ids) for diagnosis."""
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"Phone Link UI dump — {datetime.now(timezone.utc).isoformat()}"]
    wins = _phone_link_windows()
    if not wins:
        lines.append("Aucune fenêtre Phone Link trouvée (Phone Link est-il ouvert ?).")
    for win in wins:
        try:
            lines.append(f"\n=== Fenêtre : {win.window_text()!r}")
            for el in win.descendants():
                try:
                    info = el.element_info
                    lines.append(f"{info.control_type:<14} name={info.name!r} auto_id={info.automation_id!r}")
                except Exception:  # noqa: BLE001
                    continue
        except Exception as exc:  # noqa: BLE001
            lines.append(f"(erreur : {exc})")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
