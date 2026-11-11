"""Vérification d'envoi Phone Link : jamais « envoyé » sur un brouillon resté dans la zone de saisie."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from telelink.ui_automation.verify import predicates as p


class El:
    def __init__(self, ctrl: str, text: str = "", parent=None):
        self.element_info = SimpleNamespace(control_type=ctrl)
        self._text = text
        self._parent = parent

    def window_text(self):
        return self._text

    def parent(self):
        return self._parent


class Win:
    def __init__(self, elements):
        self.elements = elements

    def descendants(self, control_type=None):
        return [e for e in self.elements if control_type is None or e.element_info.control_type == control_type]


BODY = "Bonjour Camille Martin, votre livraison est prévue jeudi 12 novembre."


def fast(win, **kw):
    return p.verify_send_delivered(win, BODY, timeout_ms=50, poll_ms=10, **kw)


class VerifyTests(unittest.TestCase):
    def test_draft_still_in_compose_is_not_sent(self):
        edit = El("Edit", BODY)
        inner = El("ListItem", BODY, parent=edit)  # texte du brouillon exposé sous la zone de saisie
        ok, _ = fast(Win([edit, inner]), compose_seen=True)
        self.assertFalse(ok)

    def test_unreadable_compose_is_not_proof(self):
        # Zone de saisie illisible (vide pour UIA) et aucune bulle : pas d'envoi déclaré.
        ok, method = fast(Win([El("Edit", "")]), compose_seen=False)
        self.assertFalse(ok)
        self.assertEqual(method, "timeout")

    def test_compose_cleared_after_being_seen_is_sent(self):
        ok, method = fast(Win([El("Edit", "")]), compose_seen=True)
        self.assertTrue(ok)
        self.assertEqual(method, "compose_empty")

    def test_bubble_in_conversation_is_sent(self):
        ok, method = fast(Win([El("Edit", ""), El("ListItem", "Vous : " + BODY)]), compose_seen=False)
        self.assertTrue(ok)
        self.assertEqual(method, "thread_bubble")

    def test_french_failure_text(self):
        ok, method = fast(Win([El("Edit", ""), El("Text", "Message non remis. Réessayer")]), compose_seen=True)
        self.assertFalse(ok)
        self.assertEqual(method, "failure_indicator")


if __name__ == "__main__":
    unittest.main()


class DisconnectedTests(unittest.TestCase):
    def test_banner_means_not_sent(self) -> None:
        from telelink.ui_automation.verify.predicates import phone_link_disconnected

        class El:
            def __init__(self, t):
                self.t = t

            def window_text(self):
                return self.t

        class Win:
            def __init__(self, textes):
                self.textes = textes

            def descendants(self, **_):
                return [El(t) for t in self.textes]

        self.assertTrue(phone_link_disconnected(Win(["Nous rencontrons des problèmes de connexion à votre appareil"])))
        self.assertTrue(phone_link_disconnected(Win(["Nous n’avons pas pu nous connecter à votre appareil mobile"])))
        self.assertFalse(phone_link_disconnected(Win(["Bonjour Camille", "Envoyer"])))

    def test_classify_disconnected(self) -> None:
        from telelink import zeronoshow_bridge as zns

        st, err = zns.classify_send_result({"send_clicked": False, "verify_method": "iphone_disconnected", "note": "x"})
        self.assertEqual(st, "failed")
        self.assertIn("iPhone non connecté", err or "")


class SameTextTests(unittest.TestCase):
    def test_old_identical_bubble_is_not_proof(self):
        old = El("ListItem", BODY)  # même texte envoyé lors d'un test précédent
        draft = El("Edit", BODY)    # Phone Link a remis le texte dans la zone de saisie
        win = Win([old, draft])
        before = p.count_sent_bubbles(win, BODY)
        ok, _ = fast(win, compose_seen=True, bubbles_before=before)
        self.assertFalse(ok)

    def test_new_bubble_is_proof_even_if_draft_refilled(self):
        draft = El("Edit", BODY)
        win = Win([El("ListItem", BODY), draft])
        before = p.count_sent_bubbles(win, BODY)
        win.elements.append(El("ListItem", BODY))  # la nouvelle bulle apparaît
        ok, method = fast(win, compose_seen=True, bubbles_before=before)
        self.assertTrue(ok)
        self.assertEqual(method, "new_bubble")


class SingleClickTests(unittest.TestCase):
    def test_send_is_never_clicked_twice(self):
        from telelink.ui_automation.actions import send as send_mod

        clicks = []

        class FakeEngine:
            name = "fake"

            def available(self):
                return True

            def find_phone_link_window(self, session=None):
                return Win([El("Edit", BODY)])

            def click_send(self, win, body):
                clicks.append(body)
                return True

        original = send_mod._build_engine_chain
        send_mod._build_engine_chain = lambda config: ([FakeEngine(), FakeEngine()], False)
        try:
            cfg = {"automation": {"verify_timeout_ms": 50, "verify_poll_ms": 10, "max_attempts_per_engine": 3},
                   "messaging": {"auto_send_attempts": 3}}
            session = SimpleNamespace(pywinauto_window=None)
            result = send_mod.click_send_with_orchestrator(BODY, cfg, session, timeout_seconds=1)
        finally:
            send_mod._build_engine_chain = original
        self.assertEqual(len(clicks), 1, "un SMS non confirmé ne doit jamais être recliqué")
        self.assertFalse(result["send_verified"])


class FindControlTests(unittest.TestCase):
    def test_wrapper_without_child_window_finds_send_button(self):
        from telelink.ui_automation.find import find_control
        from telelink.ui_automation.locators import send_button_specs

        btn = El("Button", "Envoyer")
        btn.element_info.name = "Envoyer"
        btn.element_info.automation_id = "SendMessageButton"
        btn.element_info.class_name = ""
        other = El("Button", "Appel")
        other.element_info.name = "Appel"
        other.element_info.automation_id = "ButtonCall"
        other.element_info.class_name = ""
        win = Win([other, btn])           # comme un UIAWrapper : descendants(), pas de child_window()
        self.assertFalse(hasattr(win, "child_window"))
        found = next((find_control(win, s) for s in send_button_specs({}) if find_control(win, s)), None)
        self.assertIs(found, btn)
