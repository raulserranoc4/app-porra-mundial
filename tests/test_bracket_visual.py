import unittest

from utils.bracket_visual import bracket_match_card_html, champion_card_html, projected_bracket_summary_html


def projected_match(advancing_id=None, available=True, warning=None):
    return {
        "match_number": 104,
        "home_team_id": "ESP" if available else None,
        "home_team_name": "España" if available else None,
        "away_team_id": "ARG" if available else None,
        "away_team_name": "Argentina" if available else None,
        "is_available": available,
        "missing_reason": None if available else "Pendiente de que apuestes Ganador partido 101",
        "warning": warning,
        "existing_prediction": (
            {
                "predicted_home_score": 2,
                "predicted_away_score": 1,
                "predicted_advancing_team_id": advancing_id,
                "predicted_goes_to_penalties": False,
            }
            if advancing_id
            else None
        ),
    }


class BracketVisualTests(unittest.TestCase):
    def test_match_card_highlights_projected_winner(self):
        rendered = bracket_match_card_html(projected_match("ESP"))

        self.assertIn("Match 104", rendered)
        self.assertIn("2 - 1", rendered)
        self.assertIn("bracket-winner", rendered)
        self.assertIn("avanza", rendered)
        self.assertIn("España", rendered)

    def test_locked_match_card_shows_pending_source(self):
        rendered = bracket_match_card_html(projected_match(available=False))

        self.assertIn("Por definir", rendered)
        self.assertIn("Ganador partido 101", rendered)

    def test_champion_card_shows_projected_champion(self):
        rendered = champion_card_html(projected_match("ESP"))

        self.assertIn("Campeón proyectado", rendered)
        self.assertIn("España", rendered)

    def test_warning_is_rendered_inside_match_card(self):
        rendered = bracket_match_card_html(
            projected_match("ESP", warning="Revisa esta apuesta.")
        )

        self.assertIn("Revisa esta apuesta.", rendered)

    def test_summary_includes_mobile_round_fallback(self):
        rendered = projected_bracket_summary_html(
            {
                "round_of_32": [projected_match("ESP")],
                "round_of_16": [],
                "quarter_final": [],
                "semi_final": [],
                "final": [projected_match("ESP")],
            }
        )

        self.assertIn("desktop-only bracket-scroll", rendered)
        self.assertIn("mobile-only", rendered)
        self.assertIn('<details class="mobile-round">', rendered)


if __name__ == "__main__":
    unittest.main()
