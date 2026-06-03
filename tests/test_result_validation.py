import unittest

from real_tournament import RealTournamentError, validate_real_match_result


class ResultValidationTests(unittest.TestCase):
    def setUp(self):
        self.group_match = {
            "stage": "group",
            "home_team_id": "BRA",
            "away_team_id": "ESP",
        }
        self.knockout_match = {
            "stage": "round_of_32",
            "home_team_id": "BRA",
            "away_team_id": "ESP",
        }

    def test_group_result_derives_home_winner(self):
        payload = validate_real_match_result(self.group_match, "finished", 2, 1)

        self.assertEqual(payload["winner_team_id"], "BRA")
        self.assertIsNone(payload["advancing_team_id"])

    def test_group_draw_leaves_winner_null(self):
        payload = validate_real_match_result(self.group_match, "finished", 1, 1)

        self.assertIsNone(payload["winner_team_id"])
        self.assertIsNone(payload["advancing_team_id"])

    def test_knockout_requires_advancing_team_when_finished(self):
        with self.assertRaisesRegex(RealTournamentError, "avanza"):
            validate_real_match_result(self.knockout_match, "finished", 1, 1)

    def test_knockout_non_draw_must_advance_score_winner(self):
        with self.assertRaisesRegex(RealTournamentError, "ganador del marcador"):
            validate_real_match_result(self.knockout_match, "finished", 2, 1, advancing_team_id="ESP")

    def test_knockout_draw_can_advance_either_team(self):
        payload = validate_real_match_result(self.knockout_match, "finished", 1, 1, advancing_team_id="ESP")

        self.assertIsNone(payload["winner_team_id"])
        self.assertEqual(payload["advancing_team_id"], "ESP")

    def test_penalties_only_allowed_on_draw(self):
        with self.assertRaisesRegex(RealTournamentError, "Solo puede haber penales"):
            validate_real_match_result(
                self.knockout_match,
                "finished",
                2,
                1,
                home_score_penalties=4,
                away_score_penalties=3,
                advancing_team_id="BRA",
            )


if __name__ == "__main__":
    unittest.main()
