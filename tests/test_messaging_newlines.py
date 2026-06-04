"""Newline expansion in outgoing SMS bodies (/n and \\n)."""

from __future__ import annotations

import unittest

from telelink.messaging import expand_message_body


class MessagingNewlineTests(unittest.TestCase):
    def test_spaced_slash_n(self) -> None:
        out = expand_message_body("line1 /n line2", None)
        self.assertEqual(out, "line1\nline2")

    def test_tight_slash_n_doubles(self) -> None:
        body = "project is complete./n/nWHAT WE BUILT:"
        out = expand_message_body(body, None)
        self.assertEqual(out, "project is complete.\n\nWHAT WE BUILT:")

    def test_backslash_n(self) -> None:
        out = expand_message_body("line1\\nline2", None)
        self.assertEqual(out, "line1\nline2")

    def test_url_not_split(self) -> None:
        url = "https://github.com/nicholasxdavis/repo"
        out = expand_message_body(f"see {url}", None)
        self.assertEqual(out, f"see {url}")

    def test_mixed_tight_and_spaced(self) -> None:
        out = expand_message_body("Intro./n/nBody /n tail", None)
        self.assertEqual(out, "Intro.\n\nBody\ntail")


if __name__ == "__main__":
    unittest.main()
