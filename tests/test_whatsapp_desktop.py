"""WhatsApp pour Windows : lien d'ouverture (logique pure, sans Windows)."""

from __future__ import annotations

import unittest

from telelink.whatsapp_desktop import wa_uri


class WaUriTests(unittest.TestCase):
    def test_numbers_normalised(self):
        self.assertTrue(wa_uri("07 69 79 57 15", "x").startswith("whatsapp://send?phone=33769795715&"))
        self.assertTrue(wa_uri("+33 7 49 21 98 85", "x").startswith("whatsapp://send?phone=33749219885&"))
        self.assertTrue(wa_uri("0033749219885", "x").startswith("whatsapp://send?phone=33749219885&"))

    def test_text_encoded(self):
        self.assertTrue(wa_uri("0769795715", "Bonjour é & ?\nligne 2").endswith("text=Bonjour%20%C3%A9%20%26%20%3F%0Aligne%202"))


if __name__ == "__main__":
    unittest.main()
