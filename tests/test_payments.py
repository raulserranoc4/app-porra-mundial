import unittest
from math import nan

from utils.payments import is_paid, paid_status_label, player_display_name


class PaymentHelpersTests(unittest.TestCase):
    def test_paid_values_are_normalized(self):
        self.assertTrue(is_paid(True))
        self.assertTrue(is_paid("true"))
        self.assertFalse(is_paid(False))
        self.assertFalse(is_paid(None))
        self.assertFalse(is_paid(nan))

    def test_paid_status_label_is_visual(self):
        self.assertEqual(paid_status_label(True), "✅ Pagado")
        self.assertEqual(paid_status_label(False), "❌ Pendiente")

    def test_player_display_name_adds_optional_badge(self):
        self.assertEqual(player_display_name("Raul", paid=True), "Raul 💰")
        self.assertEqual(player_display_name("Raul", paid=True, show_badge=False), "Raul")


if __name__ == "__main__":
    unittest.main()
