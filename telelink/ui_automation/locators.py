"""Shared Phone Link UI locator constants."""

from __future__ import annotations

# Legacy substring keys — do not use for top-level window find (see session.phone_link_title_match).
PHONE_LINK_TITLE_KEYS = ("phone link", "your phone")

COMPOSE_CONTROL_TYPES = ("Edit", "Document")

FAILURE_PATTERNS = (
    "not delivered",
    "failed to send",
    "message failed",
    "couldn't be sent",
    "could not be sent",
    "try again",
    "not sent",
    "send failed",
    # Phone Link en français
    "non remis",
    "non envoyé",
    "échec de l'envoi",
    "échec d'envoi",
    "impossible d'envoyer",
    "réessayer",
)

# Phone Link a perdu l'iPhone (Bluetooth) : rien ne peut partir, même si la liste affiche le message.
DISCONNECTED_PATTERNS = (
    "problèmes de connexion à votre appareil",
    "pas pu nous connecter à votre appareil",
    "trouble connecting to your",
    "couldn't connect to your",
    "can't connect to your",
)

# Phone Link suit la langue de Windows : « Send » en anglais, « Envoyer » en français.
SEND_BUTTON_SPECS: tuple[dict[str, str], ...] = (
    {"title_re": r"(?i)^(send|envoyer)$", "control_type": "Button"},
    {"title_re": r"(?i)^(send|envoyer)\b", "control_type": "Button"},
    {"auto_id_re": r"(?i).*send.*", "control_type": "Button"},
    {"title_re": r"(?i)(send|envoyer)", "control_type": "Button"},
)


def send_button_specs(config: dict | None = None) -> tuple[dict[str, str], ...]:
    """Specs du bouton Envoyer ; ``messaging.send_button_names`` permet d'ajouter les noms vus sur ce PC."""
    import re

    names = ((config or {}).get("messaging") or {}).get("send_button_names") or []
    extra = tuple(
        {"title_re": r"(?i)^\s*" + re.escape(str(n).strip()) + r"\b", "control_type": "Button"}
        for n in names
        if str(n).strip()
    )
    return extra + SEND_BUTTON_SPECS

MINIMIZE_BUTTON_SPECS: tuple[dict[str, str], ...] = (
    {"title_re": r"(?i)^minimize$", "control_type": "Button"},
    {"title": "Minimize", "control_type": "Button"},
    {"auto_id_re": r"(?i).*minimize.*", "control_type": "Button"},
)

TITLE_BAR_SPECS: tuple[dict[str, str], ...] = (
    {"control_type": "TitleBar"},
    {"class_name": "TitleBar"},
)
