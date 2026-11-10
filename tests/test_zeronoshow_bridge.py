"""ZeroNoShow bridge: outcome mapping, recipient filter, claim/report loop."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from telelink import zeronoshow_bridge as zns


SETTINGS = {
    "url": "https://example.test",
    "token": "x" * 40,
    "batch": 3,
    "send_gap_seconds": 0,
    "timeout_seconds": 5,
}


class ClassifyTests(unittest.TestCase):
    def test_verified_is_sent(self) -> None:
        self.assertEqual(zns.classify_send_result({"auto_sent": True, "send_clicked": True}), ("sent", None))

    def test_unverified_click_is_failed_with_warning(self) -> None:
        status, error = zns.classify_send_result({"auto_sent": False, "send_clicked": True, "note": "n"})
        self.assertEqual(status, "failed")
        self.assertIn("peut être parti", error or "")

    def test_compose_only_method_is_rejected(self) -> None:
        status, error = zns.classify_send_result({"auto_sent": False, "opened": True})
        self.assertEqual(status, "failed")
        self.assertIn("auto", error or "")


class RecipientTests(unittest.TestCase):
    def test_formats_match(self) -> None:
        state: dict = {"recipients": {}}
        zns.remember_recipient(state, "+33612345678", datetime.now(timezone.utc))
        for variant in ("0612345678", "33612345678", "+33 6 12 34 56 78"):
            self.assertTrue(zns.is_known_recipient(state, variant), variant)
        self.assertFalse(zns.is_known_recipient(state, "+33699999999"))

    def test_prune_window(self) -> None:
        now = datetime.now(timezone.utc)
        state = {"recipients": {"612345678": (now - timedelta(days=30)).isoformat(), "611111111": now.isoformat()}}
        zns.prune_recipients(state, now, 14)
        self.assertEqual(list(state["recipients"]), ["611111111"])

    def test_inbound_only_from_known_numbers(self) -> None:
        state = {"recipients": {"612345678": "x"}, "inbound_seen": ["old"]}
        rows = [
            {"message_id": "1", "direction": "in", "from": "+33612345678", "body": "OUI"},
            {"message_id": "2", "direction": "in", "from": "+33700000000", "body": "perso"},
            {"message_id": "3", "direction": "out", "from": "", "body": "rappel"},
            {"message_id": "old", "direction": "in", "from": "+33612345678", "body": "déjà vu"},
        ]
        self.assertEqual([r["message_id"] for r in zns.select_inbound(rows, state)], ["1"])

    def test_inbound_from_team_members(self) -> None:
        state = {"recipients": {}, "team_phones": ["749219885"]}
        rows = [
            {"message_id": "a", "direction": "in", "from": "07 49 21 98 85", "body": "je suis en retard"},
            {"message_id": "b", "direction": "in", "from": "+33700000000", "body": "perso"},
        ]
        self.assertEqual([r["message_id"] for r in zns.select_inbound(rows, state)], ["a"])

    def test_team_phones_refresh(self) -> None:
        now = datetime.now(timezone.utc)
        state: dict = {}
        zns.refresh_team_phones({}, state, now, post=lambda *_: {"phones": ["+33749219885", "bad"]})
        self.assertEqual(state["team_phones"], ["749219885"])
        zns.refresh_team_phones({}, state, now, post=lambda *_: {"phones": []})  # trop tôt : liste gardée
        self.assertEqual(state["team_phones"], ["749219885"])


class OutboundLoopTests(unittest.TestCase):
    def test_claim_send_report(self) -> None:
        posts: list = []

        def post(_settings, path, payload):
            posts.append((path, payload))
            if path.endswith("/claim"):
                return {"messages": [
                    {"id": "ok-message-1", "to": "+33612345678", "body": "Rappel"},
                    {"id": "ko-message-2", "to": "+33600000000", "body": "Rappel"},
                ]}
            return {"ok": True}

        def send(to, body, *, config, raw):
            self.assertTrue(raw)
            if to.endswith("678"):
                return {"auto_sent": True, "send_clicked": True}
            raise RuntimeError("Phone Link closed")

        state: dict = {"recipients": {}}
        done = zns.process_outbound({}, SETTINGS, state, send=send, post=post, log=lambda _m: None)
        self.assertEqual(done, 2)
        reports = [p for path, p in posts if path.endswith("/report")]
        self.assertEqual(reports[0], {"id": "ok-message-1", "status": "sent"})
        self.assertEqual(reports[1]["status"], "failed")
        self.assertIn("Phone Link closed", reports[1]["error"])
        self.assertTrue(zns.is_known_recipient(state, "0612345678"))
        self.assertFalse(zns.is_known_recipient(state, "0600000000"))


if __name__ == "__main__":
    unittest.main()
