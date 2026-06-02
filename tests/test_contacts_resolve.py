"""Contact resolution for agent queries (mom, Mom?, match rules)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from telelink.contacts import ContactStore


class ContactResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "contacts.jsonl"
        self.store = ContactStore(self.path)
        self.store.upsert(
            name="Mom🩵",
            phone="+15551234567",
            match=["mom", "+15551234567"],
            platform="imessage",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_resolve_mom_via_match(self) -> None:
        r = self.store.resolve("mom")
        self.assertEqual(r["phone"], "+15551234567")
        self.assertIn("Mom", r["name"])

    def test_resolve_mom_question_mark_display_name(self) -> None:
        r = self.store.resolve("Mom?")
        self.assertEqual(r["phone"], "+15551234567")

    def test_resolve_phone(self) -> None:
        r = self.store.resolve("+15551234567")
        self.assertEqual(r["phone"], "+15551234567")


class ConvoParseFlagTests(unittest.TestCase):
    def test_strip_raw_flag_from_remainder(self) -> None:
        from telelink.convo_parse import parse_convo_tokens, strip_cli_flags

        rest, raw, json_mode = strip_cli_flags(["last", "10", "mom", "--raw"])
        self.assertTrue(raw)
        self.assertFalse(json_mode)
        q = parse_convo_tokens(rest)
        self.assertEqual(q.target, "mom")
        self.assertEqual(q.limit, 10)

    def test_incoming_scope(self) -> None:
        from telelink.convo_parse import parse_convo_tokens

        q = parse_convo_tokens(["incoming", "last", "5", "mom"])
        self.assertTrue(q.incoming_only)
        self.assertEqual(q.target, "mom")
        self.assertEqual(q.limit, 5)


class IncomingRowTests(unittest.TestCase):
    def test_direction_in(self) -> None:
        from telelink.received import is_incoming_row

        self.assertTrue(is_incoming_row({"direction": "in", "body": "hi"}))
        self.assertFalse(is_incoming_row({"direction": "out", "body": "hi"}))


if __name__ == "__main__":
    unittest.main()
