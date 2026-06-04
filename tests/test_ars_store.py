"""Tests for ARS session persistence helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from telelink.ars_store import (
    ars_dir,
    list_sessions,
    load_session,
    new_session,
    pid_path,
    save_session,
    session_path,
    validate_session_slug,
)


class ArsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {"output": {"dir": self.tmp.name}, "ars": {"poll_interval": "60s", "cooldown": "45s"}}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_validate_session_slug_accepts_and_normalizes(self) -> None:
        self.assertEqual(validate_session_slug("Client-ARS_1"), "client-ars_1")

    def test_validate_session_slug_rejects_invalid_values(self) -> None:
        for bad in ("", "../x", "bad/name", "bad\\name", "space name", "UP!"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_session_slug(bad)

    def test_paths_and_dir(self) -> None:
        folder = ars_dir(self.config)
        self.assertTrue(folder.exists())
        self.assertEqual(session_path(self.config, "alpha").name, "alpha.json")
        self.assertEqual(pid_path(self.config, "alpha").name, "alpha.pid")

    def test_new_session_defaults(self) -> None:
        payload = new_session("alpha", "Mom", {"name": "Mom", "phone": "+15550001111"}, config=self.config)
        self.assertEqual(payload["session"], "alpha")
        self.assertEqual(payload["state"], "starting")
        self.assertEqual(payload["poll_interval_seconds"], 60)
        self.assertEqual(payload["cooldown_seconds"], 45)
        self.assertEqual(payload["contact_query"], "Mom")

    def test_save_and_load_roundtrip_atomic(self) -> None:
        payload = new_session("alpha", "Mom", {"name": "Mom", "phone": "+15550001111"}, config=self.config)
        save_session(self.config, payload)
        path = session_path(self.config, "alpha")
        loaded = load_session(self.config, "alpha")
        self.assertTrue(path.exists())
        self.assertEqual(loaded["session"], "alpha")
        self.assertEqual(loaded["contact_resolved"]["phone"], "+15550001111")
        # Atomic writer should not leave temp files behind.
        tmp_files = list(Path(self.tmp.name).rglob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_list_sessions(self) -> None:
        one = new_session("one", "Mom", {"name": "Mom", "phone": "+1"}, config=self.config)
        two = new_session("two", "Dad", {"name": "Dad", "phone": "+2"}, config=self.config)
        one["updated_at"] = "2026-06-01T10:00:00+00:00"
        two["updated_at"] = "2026-06-01T11:00:00+00:00"
        save_session(self.config, one)
        save_session(self.config, two)
        sessions = list_sessions(self.config)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]["session"], "two")
        self.assertEqual(sessions[1]["session"], "one")


if __name__ == "__main__":
    unittest.main()

