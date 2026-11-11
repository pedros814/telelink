"""Phone Link hors écran : décisions du gardien (logique pure, sans Windows)."""

from __future__ import annotations

import unittest

from telelink.phone_link_hide import decide, is_offscreen, window_mode

ON = (100, 100, 1100, 850)
OFF = (-32000, -32000, -31000, -31250)


class HideTests(unittest.TestCase):
    def test_visible_and_not_used_is_hidden(self):
        self.assertEqual(decide(1, rect=ON, foreground=False, automation_running=False), "hide")

    def test_user_clicks_it_in_taskbar_it_comes_back(self):
        self.assertEqual(decide(1, rect=OFF, foreground=True, automation_running=False), "show")

    def test_user_is_using_it_we_leave_it(self):
        self.assertEqual(decide(1, rect=ON, foreground=True, automation_running=False), "keep")

    def test_never_touched_during_an_automation(self):
        # Pendant un envoi, Phone Link est au premier plan mais hors écran : surtout ne pas le montrer.
        self.assertEqual(decide(1, rect=OFF, foreground=True, automation_running=True), "keep")
        self.assertEqual(decide(1, rect=ON, foreground=False, automation_running=True), "keep")

    def test_offscreen_detection(self):
        self.assertTrue(is_offscreen(OFF))
        self.assertFalse(is_offscreen(ON))
        self.assertFalse(is_offscreen((-8, -8, 1928, 1048)))  # fenêtre maximisée : légèrement négative

    def test_mode(self):
        self.assertEqual(window_mode({}), "offscreen")
        self.assertEqual(window_mode({"automation": {"phone_link_window": "minimize"}}), "minimize")
        self.assertEqual(window_mode({"automation": {"phone_link_window": "n'importe"}}), "offscreen")


if __name__ == "__main__":
    unittest.main()
