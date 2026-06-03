import unittest

from utils.prediction_result import (
    allowed_advancing_options_from_score,
    derive_result_from_score,
    prediction_result_db_value,
    result_label_from_score,
)


class PredictionResultTests(unittest.TestCase):
    def test_derive_result_from_score(self):
        self.assertEqual(derive_result_from_score(2, 1), "home")
        self.assertEqual(derive_result_from_score(1, 2), "away")
        self.assertEqual(derive_result_from_score(0, 0), "draw")

    def test_prediction_result_db_value_uses_legacy_codes(self):
        self.assertEqual(prediction_result_db_value(2, 1), "H")
        self.assertEqual(prediction_result_db_value(1, 2), "A")
        self.assertEqual(prediction_result_db_value(0, 0), "D")

    def test_result_label_from_score(self):
        self.assertEqual(result_label_from_score(2, 0, "Brasil", "Espana"), "Resultado calculado: gana Brasil")
        self.assertEqual(result_label_from_score(1, 1, "Brasil", "Espana"), "Resultado calculado: empate")
        self.assertEqual(result_label_from_score(0, 2, "Brasil", "Espana"), "Resultado calculado: gana Espana")

    def test_knockout_advancing_options_follow_score(self):
        self.assertEqual(allowed_advancing_options_from_score(2, 1, "Local", "Visitante"), ["Local"])
        self.assertEqual(allowed_advancing_options_from_score(1, 2, "Local", "Visitante"), ["Visitante"])
        self.assertEqual(allowed_advancing_options_from_score(1, 1, "Local", "Visitante"), ["Local", "Visitante"])


if __name__ == "__main__":
    unittest.main()
