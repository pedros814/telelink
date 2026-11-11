"""Shared send verification predicates for Phone Link UI automation."""

from __future__ import annotations

from telelink.ui_automation.locators import COMPOSE_CONTROL_TYPES, FAILURE_PATTERNS
from telelink.ui_automation.verify.runner import run_verify


def _normalize_body_for_match(text: str) -> str:
    return " ".join((text or "").split()).lower()[:500]


def _get_compose_text(win) -> str:
    """Best-effort read of Phone Link message compose content."""
    parts: list[str] = []
    for ctrl_type in COMPOSE_CONTROL_TYPES:
        try:
            for el in win.descendants(control_type=ctrl_type):
                try:
                    t = (el.window_text() or "").strip()
                    if not t:
                        try:
                            t = (el.get_value() or "").strip()  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    if t:
                        parts.append(t)
                except Exception:
                    continue
        except Exception:
            continue
    if not parts:
        return ""
    return max(parts, key=len)


def _compose_still_has_body(win, expected_body: str) -> bool:
    text = _get_compose_text(win)
    if not text.strip():
        return False
    exp = _normalize_body_for_match(expected_body)
    got = _normalize_body_for_match(text)
    if not exp:
        return True
    if exp in got or got in exp:
        return True
    if len(exp) >= 20 and exp[:20] in got:
        return True
    if len(got) >= 20 and got[:20] in exp:
        return True
    return bool(got)


def phone_link_disconnected(win) -> bool:
    """Phone Link affiche qu'il n'est plus connecté à l'iPhone (bandeau ou panneau de reconnexion)."""
    from telelink.ui_automation.locators import DISCONNECTED_PATTERNS

    try:
        for el in win.descendants():
            try:
                t = (el.window_text() or "").lower().replace("\u2019", "'")
                if t and any(p in t for p in DISCONNECTED_PATTERNS):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def phone_link_send_permission_missing(win) -> bool:
    """Phone Link affiche « Me montrer comment » (SendPermissionNotificationButton) : l'iPhone n'autorise pas
    l'envoi de messages depuis le PC (Réglages → Bluetooth → (i) du PC → Afficher les notifications)."""
    try:
        for el in win.descendants(control_type="Button"):
            try:
                if str(getattr(el.element_info, "automation_id", "") or "") == "SendPermissionNotificationButton":
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _ui_shows_send_failure(win) -> bool:
    try:
        for el in win.descendants():
            try:
                t = (el.window_text() or "").lower()
                if t and any(p in t for p in FAILURE_PATTERNS):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _inside_compose(el) -> bool:
    """True si l'élément est (dans) la zone de saisie : le brouillon n'est pas un message envoyé."""
    try:
        node = el
        for _ in range(8):
            ctrl = str(getattr(node.element_info, "control_type", "") or "")
            if ctrl in COMPOSE_CONTROL_TYPES:
                return True
            node = node.parent()
            if node is None:
                return False
    except Exception:
        return False
    return False


def count_sent_bubbles(win, body: str) -> int:
    """Nombre d'éléments de la conversation contenant ce texte, hors zone de saisie (brouillon exclu).

    Sert à comparer avant / après le clic : seul un nouvel élément prouve l'envoi, même quand des
    messages identiques ont déjà été envoyés (tests répétés, relances au même texte).
    """
    exp = _normalize_body_for_match(body)
    if not exp or len(exp) < 3:
        return 0
    needle = exp[:80]
    short = needle[:15] if len(needle) >= 15 else needle
    n = 0
    for ctrl_type in ("ListItem", "Text", "Group"):
        try:
            for el in win.descendants(control_type=ctrl_type):
                try:
                    t = _normalize_body_for_match(el.window_text() or "")
                    if not t or not (needle in t or (short and short in t)):
                        continue
                    if _inside_compose(el):
                        continue
                    n += 1
                except Exception:
                    continue
        except Exception:
            continue
    return n


def _thread_has_outgoing_bubble(win, body: str) -> bool:
    """Compatibilité : une bulle contenant ce texte existe (hors brouillon)."""
    return count_sent_bubbles(win, body) > 0


def compose_shows_body(win, body: str) -> bool:
    """Avant le clic : le brouillon est-il lisible dans la zone de saisie ?"""
    return _compose_still_has_body(win, body)


def verify_send_delivered(
    win,
    body: str,
    timeout_ms: int,
    poll_ms: int,
    *,
    compose_seen: bool = False,
    bubbles_before: int | None = None,
) -> tuple[bool, str]:
    """Poll Phone Link UI for send success/failure signals.

    Preuves d'envoi acceptées :
    - une bulle de plus qu'avant le clic (``bubbles_before``), hors zone de saisie ;
    - la zone de saisie vidée, seulement si le brouillon y était lisible avant le clic (``compose_seen``).
    Sans compte « avant », une bulle existante ne suffit que si la zone de saisie est vide.
    """

    def _probe() -> tuple[bool, str]:
        if phone_link_disconnected(win):
            return False, "iphone_disconnected"
        if _ui_shows_send_failure(win):
            return False, "failure_indicator"
        if bubbles_before is not None and count_sent_bubbles(win, body) > bubbles_before:
            return True, "new_bubble"
        still = _compose_still_has_body(win, body)
        if compose_seen and not still:
            return True, "compose_empty"
        if bubbles_before is None and not still and _thread_has_outgoing_bubble(win, body):
            return True, "thread_bubble"
        return False, "pending"

    return run_verify(_probe, timeout_ms=timeout_ms, poll_ms=poll_ms)
