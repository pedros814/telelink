"""Tests for ARS state transitions."""

from __future__ import annotations

import unittest

from telelink.ars_state import ArsEvent, fold_events, transition


def _base(state: str) -> dict:
    return {
        "session": "demo",
        "state": state,
        "turn_count": 0,
        "cooldown_seconds": 30,
        "thread_cursor": {},
        "pending": {},
        "errors": [],
    }


class ArsStateTests(unittest.TestCase):
    def test_starting_bootstrap_done_needs_reply(self) -> None:
        current = _base("starting")
        nxt = transition(current, ArsEvent.BOOTSTRAP_DONE, {"needs_tending": True, "pending": {"inbound_id": "1"}})
        self.assertEqual(nxt["state"], "need_reply")
        self.assertEqual(nxt["pending"]["inbound_id"], "1")

    def test_starting_bootstrap_done_waiting(self) -> None:
        current = _base("starting")
        nxt = transition(current, ArsEvent.BOOTSTRAP_DONE, {"needs_tending": False, "thread_cursor": {"last_inbound_id": "x"}})
        self.assertEqual(nxt["state"], "waiting")
        self.assertEqual(nxt["thread_cursor"]["last_inbound_id"], "x")

    def test_waiting_inbound_needs_reply(self) -> None:
        nxt = transition(_base("waiting"), ArsEvent.INBOUND_NEEDS_REPLY, {"pending": {"inbound_id": "2"}})
        self.assertEqual(nxt["state"], "need_reply")
        self.assertEqual(nxt["pending"]["inbound_id"], "2")

    def test_waiting_inbound_satisfied_stays_waiting(self) -> None:
        nxt = transition(_base("waiting"), ArsEvent.INBOUND_SATISFIED, {"thread_cursor": {"last_inbound_id": "3"}})
        self.assertEqual(nxt["state"], "waiting")
        self.assertEqual(nxt["thread_cursor"]["last_inbound_id"], "3")

    def test_need_reply_agent_ack_to_awaiting(self) -> None:
        current = _base("need_reply")
        current["pending"] = {"inbound_id": "7"}
        nxt = transition(current, ArsEvent.AGENT_ACK, {})
        self.assertEqual(nxt["state"], "awaiting_agent")
        self.assertIn("ack_at", nxt["pending"])

    def test_need_reply_outbound_detected_to_cooldown(self) -> None:
        current = _base("need_reply")
        current["pending"] = {"inbound_id": "7"}
        nxt = transition(current, ArsEvent.OUTBOUND_DETECTED, {"thread_cursor": {"last_outbound_at": "x"}})
        self.assertEqual(nxt["state"], "cooldown")
        self.assertEqual(nxt["pending"], {})
        self.assertEqual(nxt["thread_cursor"]["last_outbound_at"], "x")

    def test_need_reply_tick_no_change(self) -> None:
        nxt = transition(_base("need_reply"), ArsEvent.TICK, {})
        self.assertEqual(nxt["state"], "need_reply")

    def test_awaiting_outbound_detected_to_cooldown_and_turn_increment(self) -> None:
        current = _base("awaiting_agent")
        current["turn_count"] = 2
        nxt = transition(current, ArsEvent.OUTBOUND_DETECTED, {})
        self.assertEqual(nxt["state"], "cooldown")
        self.assertEqual(nxt["turn_count"], 3)

    def test_awaiting_agent_ack_with_already_outbound_to_cooldown(self) -> None:
        current = _base("awaiting_agent")
        nxt = transition(current, ArsEvent.AGENT_ACK, {"already_outbound": True})
        self.assertEqual(nxt["state"], "cooldown")

    def test_awaiting_outbound_timeout_returns_need_reply_with_stale(self) -> None:
        nxt = transition(_base("awaiting_agent"), ArsEvent.OUTBOUND_TIMEOUT, {})
        self.assertEqual(nxt["state"], "need_reply")
        self.assertTrue(nxt["stale_agent"])

    def test_awaiting_new_inbound_replaces_pending(self) -> None:
        current = _base("awaiting_agent")
        current["pending"] = {"inbound_id": "old"}
        nxt = transition(current, ArsEvent.INBOUND_NEEDS_REPLY, {"pending": {"inbound_id": "new"}})
        self.assertEqual(nxt["state"], "need_reply")
        self.assertEqual(nxt["pending"]["inbound_id"], "new")
        self.assertTrue(nxt["superseded_pending"])

    def test_cooldown_tick_remains_cooldown_when_not_elapsed(self) -> None:
        nxt = transition(_base("cooldown"), ArsEvent.TICK, {"cooldown_elapsed": False})
        self.assertEqual(nxt["state"], "cooldown")

    def test_cooldown_tick_to_waiting_when_elapsed(self) -> None:
        nxt = transition(_base("cooldown"), ArsEvent.TICK, {"cooldown_elapsed": True})
        self.assertEqual(nxt["state"], "waiting")

    def test_contact_replied_again_from_waiting_and_cooldown(self) -> None:
        wait = transition(_base("waiting"), ArsEvent.CONTACT_REPLIED_AGAIN, {"pending": {"inbound_id": "1"}})
        cool = transition(_base("cooldown"), ArsEvent.CONTACT_REPLIED_AGAIN, {"pending": {"inbound_id": "2"}})
        self.assertEqual(wait["state"], "need_reply")
        self.assertEqual(cool["state"], "need_reply")
        self.assertEqual(cool["pending"]["inbound_id"], "2")

    def test_pause_resume_restore(self) -> None:
        paused = transition(_base("waiting"), ArsEvent.PAUSE, {})
        resumed = transition(paused, ArsEvent.RESUME, {})
        self.assertEqual(paused["state"], "paused")
        self.assertEqual(paused["paused_from"], "waiting")
        self.assertEqual(resumed["state"], "waiting")
        self.assertNotIn("paused_from", resumed)

    def test_stop_clears_pid(self) -> None:
        current = _base("need_reply")
        current["pid"] = 1234
        nxt = transition(current, ArsEvent.STOP, {})
        self.assertEqual(nxt["state"], "stopped")
        self.assertNotIn("pid", nxt)

    def test_unhandled_error_transition(self) -> None:
        nxt = transition(_base("waiting"), ArsEvent.UNHANDLED_ERROR, {"error": "boom"})
        self.assertEqual(nxt["state"], "error")
        self.assertEqual(len(nxt["errors"]), 1)
        self.assertIn("boom", nxt["errors"][0]["error"])

    def test_fold_events_applies_in_order(self) -> None:
        session = _base("starting")
        events = [
            (ArsEvent.BOOTSTRAP_DONE, {"needs_tending": True, "pending": {"inbound_id": "1"}}),
            ArsEvent.AGENT_ACK,
            (ArsEvent.OUTBOUND_DETECTED, {}),
        ]
        final = fold_events(session, events)
        self.assertEqual(final["state"], "cooldown")


if __name__ == "__main__":
    unittest.main()

