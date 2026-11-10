"""ZeroNoShow bridge — calls: state reports, hang-up on request, failure path (Phone Link simulated)."""

from __future__ import annotations

import re
import unittest
from types import SimpleNamespace

from telelink import phone_link_dial
from telelink.zeronoshow_calls import handle_call

SETTINGS = {"url": "https://example.test", "token": "x" * 40, "timeout_seconds": 5}


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def fake_dialer(*, dial_ok=True, call_seconds=3, duration=None):
    state = {"active": False, "left": call_seconds, "hung": 0, "dialed": []}

    def dial(numero, config):
        state["dialed"].append(numero)
        state["active"] = dial_ok
        return (dial_ok, "ok" if dial_ok else "bouton introuvable")

    def in_call(config):
        if not state["active"]:
            return False
        state["left"] -= 1
        if state["left"] < 0:
            state["active"] = False
        return state["active"]

    def hang_up(config):
        state["hung"] += 1
        state["active"] = False
        return True

    return state, SimpleNamespace(dial=dial, in_call=in_call, hang_up=hang_up, minimize_all=lambda c: None,
                                  last_call_duration=lambda c, n, s: duration)


class CallTests(unittest.TestCase):
    def run_call(self, dialer, raccrocher_after=None):
        posts = []

        def post(_s, path, payload):
            posts.append(payload)
            ask = raccrocher_after is not None and len(posts) > raccrocher_after
            return {"ok": True, "raccrocher": ask}

        clock = FakeClock()
        final = handle_call({"id": "call-123456789", "numero": "+33612345678"}, {}, SETTINGS,
                            post=post, dialer=dialer, log=lambda m: None, sleep=clock.sleep, now=clock.now)
        return final, posts

    def test_normal_call_reports_states_and_duration_from_phone_link(self):
        state, dialer = fake_dialer(call_seconds=3, duration=42)
        final, posts = self.run_call(dialer)
        self.assertEqual(final, "termine")
        self.assertEqual(state["dialed"], ["+33612345678"])
        statuts = [p["statut"] for p in posts]
        self.assertEqual(statuts[0], "numerotation")
        self.assertIn("en_ligne", statuts)
        self.assertEqual(posts[-1], {"id": "call-123456789", "statut": "termine", "dureeS": 42})
        self.assertEqual(state["hung"], 0)

    def test_hangup_requested_by_zeronoshow(self):
        state, dialer = fake_dialer(call_seconds=100)
        final, posts = self.run_call(dialer, raccrocher_after=2)
        self.assertEqual(final, "termine")
        self.assertEqual(state["hung"], 1)
        self.assertEqual(posts[-1]["statut"], "termine")

    def test_dial_failure_is_reported_never_retried(self):
        state, dialer = fake_dialer(dial_ok=False)
        final, posts = self.run_call(dialer)
        self.assertEqual(final, "echec")
        self.assertEqual(len(state["dialed"]), 1)
        self.assertEqual(posts[-1]["statut"], "echec")
        self.assertIn("bouton", posts[-1]["erreur"])

    def test_cancelled_before_dialing_does_not_call(self):
        state, dialer = fake_dialer()
        final, _ = self.run_call(dialer, raccrocher_after=0)
        self.assertEqual(final, "echec")
        self.assertEqual(state["dialed"], [])


class NamesTests(unittest.TestCase):
    def test_button_names_regex(self):
        rx = re.compile(phone_link_dial.name_regex(phone_link_dial.DEFAULT_END_NAMES)[4:], re.I)
        for ok in ("Raccrocher", "End call", "Terminer l'appel", "raccrocher l'appel"):
            self.assertTrue(rx.search(ok), ok)
        self.assertFalse(rx.search("Appeler"))
        rx_call = re.compile(phone_link_dial.name_regex(phone_link_dial.DEFAULT_CALL_NAMES)[4:], re.I)
        self.assertTrue(rx_call.search("Call +33 7 49 21 98 85"))
        self.assertTrue(rx_call.search("Appeler"))

    def test_dial_uri(self):
        self.assertEqual(phone_link_dial.dial_uri("+33 7 49 21 98 85"), "tel:+33749219885")


if __name__ == "__main__":
    unittest.main()
