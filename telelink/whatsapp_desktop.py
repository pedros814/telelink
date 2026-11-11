"""Send a WhatsApp message from the user's own WhatsApp for Windows, after a human click in ZeroNoShow.

Relevé sur le PC (WhatsApp Desktop 2.26, interface en français) :
- ``whatsapp://send?phone=<chiffres>&text=<texte>`` ouvre la conversation, texte pré-rempli ;
- zone de saisie : Edit « Écrivez un message à <nom> » ; bouton « Envoyer » (« Message vocal » si vide) ;
- numéro sans compte WhatsApp : écran avec « Inviter un proche » / « Ajouter le contact ».

Règles :
- ZeroNoShow n'enfile un WhatsApp que sur un clic humain (jamais Julie ni un rappel automatique) ;
- un seul appui sur Envoyer par message (jamais de second envoi) ;
- WhatsApp est l'application de l'utilisateur : on ne la cache pas en permanence, on la remet
  exactement dans l'état où elle était (position, réduite ou non) et on rend le premier plan.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from typing import Any
from urllib.parse import quote

WA_PROCESSES = ("whatsapp.root.exe", "whatsapp.exe")
COMPOSER_RE = r"(?i)^(écrivez un message|ecrivez un message|type a message|saisissez un message)"
SEND_RE = r"(?i)^(envoyer|send)$"
NO_ACCOUNT_RE = r"(?i)^(inviter un proche|invite to whatsapp|inviter sur whatsapp)"


def wa_uri(phone: str, text: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    elif len(digits) == 10 and digits.startswith("0"):
        digits = "33" + digits[1:]
    return f"whatsapp://send?phone={digits}&text={quote(text or '', safe='')}"


def _norm(text: str) -> str:
    return " ".join((text or "").split()).lower()


def wa_windows() -> list[Any]:
    if sys.platform != "win32":
        return []
    try:
        from pywinauto import Desktop

        from telelink.ui_automation.session import _window_process_name
    except ImportError:
        return []
    out = []
    for w in Desktop(backend="uia").windows():
        try:
            if _window_process_name(w).lower() in WA_PROCESSES:
                out.append(w)
        except Exception:  # noqa: BLE001
            continue
    return out


def _composer(win: Any) -> Any | None:
    from telelink.ui_automation.find import find_control

    return find_control(win, {"title_re": COMPOSER_RE, "control_type": "Edit"})


def _composer_text(edit: Any) -> str:
    for getter in ("get_value", "window_text"):
        try:
            v = getattr(edit, getter)()
            if v and not re.match(COMPOSER_RE, v):
                return str(v)
        except Exception:  # noqa: BLE001
            continue
    try:
        return str(edit.iface_value.CurrentValue or "")
    except Exception:  # noqa: BLE001
        return ""


def _clipboard_paste(win: Any, edit: Any, text: str) -> None:
    """Colle le texte dans la zone de saisie (retours à la ligne, emojis : intacts, jamais d'Entrée).

    Le presse-papiers de l'utilisateur est remis tel qu'il était.
    """
    import ctypes
    from ctypes import wintypes

    from pywinauto.keyboard import send_keys

    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalLock.restype = ctypes.c_void_p
    u32.GetClipboardData.restype = wintypes.HANDLE
    CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002

    def _get() -> str | None:
        if not u32.OpenClipboard(0):
            return None
        try:
            h = u32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return None
            p = k32.GlobalLock(h)
            try:
                return ctypes.wstring_at(p) if p else None
            finally:
                k32.GlobalUnlock(h)
        finally:
            u32.CloseClipboard()

    def _set(value: str) -> bool:
        data = (value + "\0").encode("utf-16-le")
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        p = k32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        for _ in range(10):
            if u32.OpenClipboard(0):
                try:
                    u32.EmptyClipboard()
                    return bool(u32.SetClipboardData(CF_UNICODETEXT, h))
                finally:
                    u32.CloseClipboard()
            time.sleep(0.05)
        return False

    previous = _get()
    try:
        if not _set(text):
            raise RuntimeError("presse-papiers indisponible")
        win.set_focus()
        time.sleep(0.25)
        edit.set_focus()
        time.sleep(0.15)
        send_keys("^v")
        time.sleep(0.4)
    finally:
        if previous is not None:
            _set(previous)


def _no_account(win: Any) -> bool:
    from telelink.ui_automation.find import find_control

    return find_control(win, {"title_re": NO_ACCOUNT_RE, "control_type": "Button"}) is not None


def _placements(hwnds: list[int]) -> dict[int, Any]:
    import ctypes
    from ctypes import wintypes

    class WP(ctypes.Structure):
        _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT),
                    ("ptMin", wintypes.POINT), ("ptMax", wintypes.POINT), ("rc", wintypes.RECT)]

    out = {}
    for h in hwnds:
        wp = WP()
        wp.length = ctypes.sizeof(WP)
        if ctypes.windll.user32.GetWindowPlacement(h, ctypes.byref(wp)):
            out[h] = wp
    return out


def _restore_placements(saved: dict[int, Any]) -> None:
    import ctypes

    for h, wp in saved.items():
        try:
            ctypes.windll.user32.SetWindowPlacement(h, ctypes.byref(wp))
        except Exception:  # noqa: BLE001
            continue


def send_whatsapp(phone: str, text: str, *, config: dict[str, Any] | None = None, timeout_s: float = 15.0) -> dict[str, Any]:
    """Returns a record like messaging.send_message: auto_sent / send_clicked / note / verify_method."""
    base = {"method": "whatsapp_desktop", "to_phone": phone, "auto_sent": False, "send_clicked": False, "send_verified": False}
    if sys.platform != "win32":
        return {**base, "note": "Windows uniquement", "verify_method": "unsupported"}
    text = (text or "").strip()
    if not text:
        return {**base, "note": "message vide", "verify_method": "empty"}

    from telelink.phone_link_dial import UI_LOCK
    from telelink.phone_link_hide import hide_hwnd
    from telelink.ui_automation.find import find_control, press
    from telelink.win_console import get_foreground_hwnd, restore_foreground

    with UI_LOCK:
        previous = get_foreground_hwnd()
        before = [int(w.handle) for w in wa_windows()]
        saved = _placements(before)
        user_in_whatsapp = previous in before
        if not user_in_whatsapp:
            # L'utilisateur ne regarde pas WhatsApp : on travaille fenêtre hors écran, sans la montrer.
            for h in before:
                hide_hwnd(h)
        try:
            subprocess.run(["cmd", "/c", "start", "", wa_uri(phone, text)], check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            want = _norm(text)[:40]
            deadline = time.monotonic() + timeout_s
            win = edit = None
            while time.monotonic() < deadline:
                time.sleep(0.4)
                for w in wa_windows():
                    if not user_in_whatsapp and int(w.handle) not in before:
                        hide_hwnd(int(w.handle))  # WhatsApp était fermé : sa fenêtre neuve reste hors écran
                    if _no_account(w) and _composer(w) is None:
                        return {**base, "note": "Ce numéro n'a pas de compte WhatsApp", "verify_method": "no_whatsapp_account"}
                    e = _composer(w)
                    if e is None:
                        continue
                    current = _norm(_composer_text(e))
                    if want and want[:20] in current:
                        win, edit = w, e
                        break
                    if not current:
                        # Relevé sur le PC : WhatsApp Desktop ignore le texte du lien ; zone vide → on colle le message.
                        _clipboard_paste(w, e, text)
                        if want[:20] in _norm(_composer_text(e)):
                            win, edit = w, e
                            break
                        continue
                    if current and time.monotonic() > deadline - timeout_s + 3:
                        # WhatsApp garde un brouillon existant et ignore le texte du lien : on n'envoie JAMAIS
                        # un brouillon qui n'est pas le nôtre.
                        return {**base, "note": "Un brouillon est déjà en cours dans cette conversation WhatsApp : message non envoyé",
                                "verify_method": "draft_present"}
                if edit is not None:
                    break
            if edit is None:
                return {**base, "note": "WhatsApp n'a pas ouvert la conversation avec le message", "verify_method": "composer_not_ready"}

            btn = find_control(win, {"title_re": SEND_RE, "control_type": "Button"})
            if btn is None or not press(btn):
                return {**base, "note": "Bouton « Envoyer » de WhatsApp introuvable", "verify_method": "send_button_not_found"}
            # Un seul appui : à partir d'ici, on ne fait plus que vérifier.
            for _ in range(20):
                time.sleep(0.4)
                if want[:20] not in _norm(_composer_text(edit)):
                    return {**base, "send_clicked": True, "send_verified": True, "auto_sent": True,
                            "note": "Envoyé par WhatsApp (zone de saisie vidée)", "verify_method": "compose_empty"}
            return {**base, "send_clicked": True, "note": "Envoyer appuyé mais message encore dans la zone de saisie",
                    "verify_method": "not_verified"}
        finally:
            time.sleep(0.3)
            if not user_in_whatsapp:
                _restore_placements(saved)
                for w in wa_windows():
                    if int(w.handle) not in saved:
                        try:
                            import ctypes

                            ctypes.windll.user32.ShowWindow(int(w.handle), 6)  # était fermé : on le réduit
                        except Exception:  # noqa: BLE001
                            pass
            if previous:
                try:
                    restore_foreground(previous)
                except Exception:  # noqa: BLE001
                    pass
