"""Tests for ARS needs-tending logic."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from telelink.ars_logic import (
    body_hash,
    last_inbound_row,
    last_outbound_row,
    needs_tending,
    parse_thread_rows,
)


def _row(message_id: str, *, direction: str, body: str, timestamp: str) -> dict[str, Any]:
    return {
        "id": message_id,
        "direction": direction,
        "body": body,
        "timestamp": timestamp,
    }


class ArsLogicTests(unittest.TestCase):
    def test_parse_rows_chronological(self) -> None:
        rows = [
            _row("3", direction="out", body="later", timestamp="2026-06-01T10:03:00+00:00"),
            _row("1", direction="in", body="early", timestamp="2026-06-01T10:01:00+00:00"),
            _row("2", direction="in", body="mid", timestamp="2026-06-01T10:02:00+00:00"),
        ]
        ordered = parse_thread_rows(rows)
        self.assertEqual([r["id"] for r in ordered], ["1", "2", "3"])

    def test_last_inbound_and_outbound_helpers(self) -> None:
        rows = [
            _row("1", direction="in", body="hello", timestamp="2026-06-01T10:00:00+00:00"),
            _row("2", direction="out", body="hi", timestamp="2026-06-01T10:01:00+00:00"),
            _row("3", direction="in", body="question", timestamp="2026-06-01T10:02:00+00:00"),
        ]
        self.assertEqual(last_inbound_row(rows)["id"], "3")
        self.assertEqual(last_outbound_row(rows)["id"], "2")

    def test_empty_thread_reason(self) -> None:
        result = needs_tending([_row("1", direction="in", body="   ", timestamp="2026-06-01T10:00:00+00:00")])
        self.assertFalse(result.needs_tending)
        self.assertEqual(result.reason, "empty_thread")

    def test_no_inbound_reason(self) -> None:
        rows = [_row("1", direction="out", body="sent", timestamp="2026-06-01T10:00:00+00:00")]
        result = needs_tending(rows)
        self.assertFalse(result.needs_tending)
        self.assertEqual(result.reason, "no_inbound")

    def test_never_replied_reason(self) -> None:
        rows = [_row("1", direction="in", body="need help", timestamp="2026-06-01T10:00:00+00:00")]
        result = needs_tending(rows)
        self.assertTrue(result.needs_tending)
        self.assertEqual(result.reason, "never_replied")

    def test_inbound_after_outbound_reason(self) -> None:
        rows = [
            _row("1", direction="out", body="old reply", timestamp="2026-06-01T10:00:00+00:00"),
            _row("2", direction="in", body="new question", timestamp="2026-06-01T10:05:00+00:00"),
        ]
        result = needs_tending(rows)
        self.assertTrue(result.needs_tending)
        self.assertEqual(result.reason, "inbound_after_last_outbound")

    def test_same_timestamp_with_higher_inbound_id_needs_reply(self) -> None:
        rows = [
            _row("100", direction="out", body="done", timestamp="2026-06-01T10:00:00+00:00"),
            _row("101", direction="in", body="follow up", timestamp="2026-06-01T10:00:00+00:00"),
        ]
        result = needs_tending(rows)
        self.assertTrue(result.needs_tending)
        self.assertEqual(result.reason, "inbound_after_last_outbound")

    def test_tapback_only_reason(self) -> None:
        rows = [
            _row("1", direction="out", body="Thanks", timestamp="2026-06-01T10:00:00+00:00"),
            _row("2", direction="in", body="Liked “Thanks”", timestamp="2026-06-01T10:01:00+00:00"),
        ]
        result = needs_tending(rows, config={"ars": {"tapback_patterns": [r"^Liked "]}})
        self.assertFalse(result.needs_tending)
        self.assertEqual(result.reason, "tapback_only")

    def test_stale_reason_and_force_override(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=10)).replace(microsecond=0).isoformat()
        rows = [_row("1", direction="in", body="old ping", timestamp=old)]
        result = needs_tending(rows, config={"ars": {"ignore_stale_hours": 24}})
        self.assertFalse(result.needs_tending)
        self.assertEqual(result.reason, "stale")

        forced = needs_tending(rows, config={"ars": {"ignore_stale_hours": 24}}, force=True)
        self.assertTrue(forced.needs_tending)
        self.assertEqual(forced.reason, "never_replied")

    def test_already_handled_reason_from_cursor(self) -> None:
        rows = [
            _row("1", direction="in", body="question", timestamp="2026-06-01T10:00:00+00:00"),
            _row("2", direction="out", body="answer", timestamp="2026-06-01T10:01:00+00:00"),
        ]
        session = {
            "thread_cursor": {
                "last_inbound_id": "1",
                "last_inbound_body_hash": body_hash("question"),
                "last_outbound_body_hash": body_hash("answer"),
                "last_outbound_at": "2026-06-01T10:01:00+00:00",
            }
        }
        result = needs_tending(rows, session=session)
        self.assertFalse(result.needs_tending)
        self.assertEqual(result.reason, "already_handled")

    def test_already_replied_reason(self) -> None:
        rows = [
            _row("1", direction="in", body="question", timestamp="2026-06-01T10:00:00+00:00"),
            _row("2", direction="out", body="answer", timestamp="2026-06-01T10:01:00+00:00"),
        ]
        result = needs_tending(rows)
        self.assertFalse(result.needs_tending)
        self.assertEqual(result.reason, "already_replied")


if __name__ == "__main__":
    unittest.main()

