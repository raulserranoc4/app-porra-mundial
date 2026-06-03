import json
import unittest
from unittest.mock import patch

import pandas as pd

from scoring import (
    _calculate_projected_tables_for_scoring,
    _completed_group_letters,
    _insert_score_event,
    calculate_group_prediction_points,
    calculate_match_prediction_points,
    calculate_special_prediction_points,
    recalculate_all_scores,
)


class ScoringTests(unittest.TestCase):
    def test_exact_score_sets_leaderboard_flags(self):
        points, _reasons, details = calculate_match_prediction_points(
            {"predicted_home_score": 2, "predicted_away_score": 1},
            {"home_score": 2, "away_score": 1, "stage": "group"},
        )

        self.assertEqual(points, 7)
        self.assertTrue(details["exact_score"])
        self.assertTrue(details["correct_result"])
        self.assertTrue(details["correct_goal_difference"])
        self.assertTrue(details["correct_home_goals"])
        self.assertTrue(details["correct_away_goals"])

    def test_correct_result_without_exact_score_sets_flag(self):
        points, _reasons, details = calculate_match_prediction_points(
            {"predicted_home_score": 2, "predicted_away_score": 1},
            {"home_score": 3, "away_score": 2, "stage": "group"},
        )

        self.assertEqual(points, 5)
        self.assertFalse(details["exact_score"])
        self.assertTrue(details["correct_result"])
        self.assertTrue(details["correct_goal_difference"])

    def test_insert_score_event_filters_missing_prediction_id(self):
        captured = {}

        def fake_insert(_conn, table_name, values):
            captured["table_name"] = table_name
            captured["values"] = values

        with patch("scoring.table_columns", return_value={"player_id", "category", "points", "reason_json"}):
            with patch("scoring.insert_dynamic", side_effect=fake_insert):
                _insert_score_event(
                    object(),
                    {
                        "player_id": 1,
                        "prediction_id": 99,
                        "category": "match",
                        "points": 7,
                        "reason_json": {"exact_score": True},
                    },
                )

        self.assertEqual(captured["table_name"], "score_events")
        self.assertNotIn("prediction_id", captured["values"])
        self.assertEqual(json.loads(captured["values"]["reason_json"])["exact_score"], True)

    def test_derived_group_scoring_compares_projected_positions(self):
        points, _reasons, details = calculate_group_prediction_points(
            [
                {"team_id": "ESP", "group_letter": "A", "position": 1},
                {"team_id": "FRA", "group_letter": "A", "position": 2},
                {"team_id": "BRA", "group_letter": "A", "position": 3},
                {"team_id": "ARG", "group_letter": "A", "position": 4},
            ],
            {"FRA": 1, "ESP": 2, "BRA": 3, "ARG": 4},
        )

        self.assertEqual(points, 10)
        self.assertEqual(details["group_letter"], "A")
        self.assertEqual(details["qualified_correct_count"], 2)
        self.assertEqual(details["exact_position_count"], 2)
        self.assertEqual(details["predicted_positions"]["ESP"], 1)
        self.assertEqual(details["actual_positions"]["ESP"], 2)

    def test_derived_group_scoring_requires_six_completed_matches(self):
        rows = [
            {
                "group_letter": "A",
                "predicted_home_score": index,
                "predicted_away_score": index,
            }
            for index in range(5)
        ]
        rows.extend(
            {
                "group_letter": "B",
                "predicted_home_score": index,
                "predicted_away_score": index,
            }
            for index in range(6)
        )

        self.assertEqual(_completed_group_letters(rows), {"B"})

    def test_projected_group_wrapper_supports_current_two_arg_signature(self):
        calls = []

        def current_signature(group_matches, player_predictions):
            calls.append((group_matches, player_predictions))
            return {"A": [{"team_id": "ESP", "position": 1}]}, False

        with patch("scoring.calculate_projected_group_tables", new=current_signature):
            tables = _calculate_projected_tables_for_scoring([{"match_id": 1}], player_id=7)

        self.assertEqual(tables["A"][0]["team_id"], "ESP")
        self.assertEqual(calls, [([{"match_id": 1}], [{"match_id": 1}])])

    def test_projected_group_wrapper_supports_single_arg_signature(self):
        calls = []

        def future_signature(group_matches):
            calls.append((group_matches,))
            return {"A": [{"team_id": "ESP", "position": 1}]}, False

        with patch("scoring.calculate_projected_group_tables", new=future_signature):
            tables = _calculate_projected_tables_for_scoring([{"match_id": 1}], player_id=7)

        self.assertEqual(tables["A"][0]["team_id"], "ESP")
        self.assertEqual(calls, [([{"match_id": 1}],)])

    def test_projected_group_wrapper_reports_player_context_on_error(self):
        def broken_signature(_group_matches, _player_predictions):
            raise ValueError("boom")

        with patch("scoring.calculate_projected_group_tables", new=broken_signature):
            with self.assertRaisesRegex(RuntimeError, "player_id=7"):
                _calculate_projected_tables_for_scoring([{"match_id": 1}], player_id=7)

    def test_special_semifinalists_are_not_double_counted(self):
        points, _reasons, details = calculate_special_prediction_points(
            {
                "champion_team_id": "ESP",
                "runner_up_team_id": "ARG",
                "semifinalist_1_team_id": "ESP",
                "semifinalist_2_team_id": "ESP",
                "semifinalist_3_team_id": "BRA",
                "semifinalist_4_team_id": "NED",
            },
            {"champion": "FRA", "runner_up": "GER", "top_scorer": None, "mvp": None},
            {"ESP", "ARG", "BRA", "FRA"},
        )

        self.assertEqual(points, 16)
        self.assertEqual(details["semifinalists_correct_count"], 2)

    def test_special_awards_normalize_case_and_spaces(self):
        points, _reasons, details = calculate_special_prediction_points(
            {
                "top_scorer_name": "  Kylian   Mbappe  ",
                "mvp_name": " LAMINE  YAMAL ",
            },
            {
                "champion": None,
                "runner_up": None,
                "top_scorer": "kylian mbappe",
                "mvp": "lamine yamal",
            },
            set(),
        )

        self.assertEqual(points, 25)
        self.assertTrue(details["top_scorer_correct"])
        self.assertTrue(details["mvp_correct"])

    def test_recalculate_all_scores_tolerates_incomplete_tournament(self):
        with patch("scoring.fetch_df", return_value=pd.DataFrame(columns=["id"])):
            with patch("scoring.recalculate_group_scores") as groups:
                with patch("scoring.recalculate_special_scores") as specials:
                    recalculate_all_scores()

        groups.assert_called_once()
        specials.assert_called_once()


if __name__ == "__main__":
    unittest.main()
