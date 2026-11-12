"""Best-effort auto-send through Phone Link (UI automation)."""

from __future__ import annotations

import subprocess
import sys
from typing import Any
from urllib.parse import quote

from telelink.contacts import dial_digits, looks_like_phone, normalize_phone
from telelink.ui_automation import UiAutomationSession
from telelink.ui_automation.actions.send import click_send_with_orchestrator
from telelink.ui_automation.actions.window import minimize_orchestrated, unfocus_compose_orchestrated
from telelink.ui_automation.config_helpers import get_automation_config
from telelink.ui_stealth import stealth_ui


def _open_sms_uri(phone: str, body: str) -> str:
    norm = normalize_phone(phone)
    if not norm or not looks_like_phone(norm):
        raise ValueError(f"invalid phone number: {phone!r}")
    dial = dial_digits(norm)
    uri = f"sms:{dial}?body={quote(body)}"
    if sys.platform == "win32":
        subprocess.run(
            ["cmd", "/c", "start", "", uri],
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )
    return uri


def _method_from_send_result(send_result: dict[str, Any], auto_cfg: dict[str, Any]) -> str:
    engine = str(send_result.get("engine") or "")
    fallback_used = bool(send_result.get("fallback_used"))
    chain = [str(e).strip().lower() for e in auto_cfg.get("engine_chain", ["pywinauto"])]
    primary = chain[0] if chain else "pywinauto"

    if engine == "last_resort":
        return "auto_fallback_keys"
    if engine == "keys" and primary == "keys":
        return "auto_keys"
    if engine == "keys" and fallback_used:
        return "auto_fallback_keys"
    if engine == "appium":
        return "auto_appium"
    return "auto_pywinauto"


def autorisation_envoi_manquante(cfg: dict[str, Any]) -> bool:
    """Phone Link demande l'autorisation d'envoyer des messages (bouton « Me montrer comment »)."""
    try:
        from telelink.ui_automation.session import find_phone_link_window
        from telelink.ui_automation.verify.predicates import phone_link_send_permission_missing

        win = find_phone_link_window(config=cfg)
        return bool(win is not None and phone_link_send_permission_missing(win))
    except Exception:
        return False


_DERNIER_ESSAI_RECONNEXION = 0.0


def reconnecter_iphone(cfg: dict[str, Any], *, attente_s: float = 10.0, intervalle_min_s: float = 15.0) -> bool:
    """iPhone déconnecté de Phone Link : appuie sur « Réessayer » (Phone Link ne réessaie pas seul).

    Relevé sur le PC : après une coupure Bluetooth (iPhone éloigné, la nuit), Phone Link reste sur son
    écran « Réessayer » ; un appui reconnecte en ~2 s dès que l'iPhone est à portée.
    Retourne True si l'iPhone est (de nouveau) connecté.
    """
    global _DERNIER_ESSAI_RECONNEXION
    import time as _t

    try:
        from telelink.phone_link_dial import UI_LOCK
        from telelink.ui_automation.find import find_control, press
        from telelink.ui_automation.session import find_phone_link_window
        from telelink.ui_automation.verify.predicates import phone_link_disconnected
    except ImportError:
        return False
    win = find_phone_link_window(config=cfg)
    if win is None:
        return False
    if not phone_link_disconnected(win):
        return True
    if _t.monotonic() - _DERNIER_ESSAI_RECONNEXION < intervalle_min_s:
        return False
    _DERNIER_ESSAI_RECONNEXION = _t.monotonic()
    with UI_LOCK:
        btn = find_control(win, {"title_re": r"(?i)^(r.essayer|retry|reconnect|se reconnecter)$", "control_type": "Button"})
        if btn is None or not press(btn):
            return False
        fin = _t.monotonic() + attente_s
        while _t.monotonic() < fin:
            _t.sleep(1.0)
            if not phone_link_disconnected(win):
                return True
    return False


def iphone_deconnecte(cfg: dict[str, Any]) -> bool:
    """Fenêtre Phone Link trouvée et affichant la perte de connexion avec l'iPhone."""
    try:
        from telelink.ui_automation.session import find_phone_link_window
        from telelink.ui_automation.verify.predicates import phone_link_disconnected

        win = find_phone_link_window(config=cfg)
        return bool(win is not None and phone_link_disconnected(win))
    except Exception:
        return False


def auto_send_phone_link(
    phone: str,
    body: str,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Try to send without manual click (best effort)."""
    cfg = config or {}
    messaging = cfg.get("messaging") or {}
    auto_cfg = get_automation_config(cfg)

    timeout = float(messaging.get("auto_timeout_seconds", 12))
    verify_before_unfocus = bool(messaging.get("auto_verify_before_unfocus", True))
    requires_verify = bool(messaging.get("auto_sent_requires_verify", True))
    do_unfocus = bool(messaging.get("auto_unfocus_titlebar", True))
    do_minimize = bool(messaging.get("auto_minimize_after_send", True))

    # iPhone déconnecté de Phone Link : on n'écrit même pas le message (il resterait en brouillon,
    # et la liste de Phone Link l'afficherait comme s'il était parti).
    if autorisation_envoi_manquante(cfg):
        return {
            "method": "auto", "uri": "", "send_clicked": False, "send_verified": False, "verify_method": "send_permission_missing",
            "auto_sent": False, "unfocused_compose": False, "minimized_phone_link": False,
            "note": "L'iPhone n'autorise pas l'envoi de SMS depuis le PC : Réglages → Bluetooth → (i) à côté du PC → activer « Afficher les notifications »",
            "engine": "", "fallback_used": False, "attempts": [],
        }
    if iphone_deconnecte(cfg) and not reconnecter_iphone(cfg, intervalle_min_s=0):
        return {
            "method": "auto", "uri": "", "send_clicked": False, "send_verified": False, "verify_method": "iphone_disconnected",
            "auto_sent": False, "unfocused_compose": False, "minimized_phone_link": False,
            "note": "iPhone non connecté à Phone Link (Bluetooth) : SMS non envoyé", "engine": "", "fallback_used": False, "attempts": [],
        }

    from telelink.phone_link_hide import hide_all

    hide_all(cfg)  # hors écran AVANT d'ouvrir le lien sms: → aucune apparition
    uri = _open_sms_uri(phone, body)
    session = UiAutomationSession()
    with stealth_ui(cfg) as stealth:
        send_result = click_send_with_orchestrator(
            body,
            cfg,
            session,
            timeout_seconds=timeout,
        )
        stealth.track(session.pywinauto_window)

        attempts = list(send_result.get("attempts") or [])
        send_clicked = bool(send_result.get("send_clicked"))
        send_verified = bool(send_result.get("send_verified"))
        verify_method = str(send_result.get("verify_method") or "")
        engine = str(send_result.get("engine") or "")
        fallback_used = bool(send_result.get("fallback_used"))
        method = _method_from_send_result(send_result, auto_cfg)

        unfocused = False
        minimized = False
        cleanup_ok = send_verified or not verify_before_unfocus

        if send_clicked and cleanup_ok:
            if do_unfocus:
                unfocus_result = unfocus_compose_orchestrated(cfg, session)
                unfocused = bool(unfocus_result.get("ok"))
            if do_minimize:
                minimize_result = minimize_orchestrated(cfg, session)
                minimized = bool(minimize_result.get("ok"))

    auto_sent = send_verified if requires_verify else send_clicked

    if send_verified:
        note = f"Send verified ({verify_method})"
    elif send_clicked:
        note = "Send clicked but not verified — compose may still have text"
        if verify_method == "failure_indicator":
            note = "Phone Link shows send failure — message may not have been sent"
        elif verify_method == "iphone_disconnected":
            note = "iPhone non connecté à Phone Link (Bluetooth) : SMS non envoyé"
    else:
        note = "Could not click Send in Phone Link UI"

    if fallback_used:
        note += "; fallback path used"
    if do_unfocus and cleanup_ok:
        note += "; unfocused compose" if unfocused else "; title bar unfocus skipped or failed"
    if do_minimize and cleanup_ok:
        note += "; minimized Phone Link" if minimized else "; minimize skipped or failed"
    if send_clicked and not send_verified and verify_before_unfocus:
        note += "; skipped unfocus/minimize (not verified)"

    return {
        "method": method,
        "uri": uri,
        "send_clicked": send_clicked,
        "send_verified": send_verified,
        "verify_method": verify_method,
        "auto_sent": auto_sent,
        "unfocused_compose": unfocused,
        "minimized_phone_link": minimized,
        "note": note,
        "engine": engine,
        "fallback_used": fallback_used,
        "attempts": attempts,
    }
