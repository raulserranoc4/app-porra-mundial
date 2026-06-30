import json
import os
import unittest
from uuid import uuid4
from unittest.mock import patch

import pandas as pd

from scoring import (
    _claim_advancement_points,
    _calculate_projected_tables_for_scoring,
    _completed_group_letters,
    _insert_score_event,
    calculate_group_prediction_points,
    calculate_match_prediction_points,
    calculate_special_prediction_points,
    get_knockout_stage_match_numbers,
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

    def test_scheduled_match_with_scores_does_not_score(self):
        points, reasons, details = calculate_match_prediction_points(
            {"predicted_home_score": 0, "predicted_away_score": 0},
            {
                "home_score": 0,
                "away_score": 0,
                "stage": "group",
                "status": "scheduled",
            },
        )

        self.assertEqual(points, 0)
        self.assertTrue(any("no finalizado" in reason for reason in reasons))
        self.assertFalse(details["exact_score"])
        self.assertFalse(details["correct_result"])

    def test_knockout_matching_snapshot_scores_normally(self):
        points, _reasons, details = calculate_match_prediction_points(
            {
                "predicted_home_score": 2,
                "predicted_away_score": 1,
                "predicted_home_team_id": "BRA",
                "predicted_away_team_id": "ESP",
            },
            {
                "home_score": 2,
                "away_score": 1,
                "home_team_id": "BRA",
                "away_team_id": "ESP",
                "stage": "round_of_32",
            },
        )

        self.assertEqual(points, 7)
        self.assertTrue(details["exact_score"])
        self.assertTrue(details["knockout_matchup_matches"])
        self.assertFalse(details["knockout_matchup_reversed"])

    def test_knockout_reversed_snapshot_swaps_score_for_scoring(self):
        points, _reasons, details = calculate_match_prediction_points(
            {
                "predicted_home_score": 2,
                "predicted_away_score": 1,
                "predicted_home_team_id": "BRA",
                "predicted_away_team_id": "ESP",
            },
            {
                "home_score": 1,
                "away_score": 2,
                "home_team_id": "ESP",
                "away_team_id": "BRA",
                "stage": "round_of_32",
            },
        )

        self.assertEqual(points, 7)
        self.assertTrue(details["exact_score"])
        self.assertTrue(details["knockout_matchup_matches"])
        self.assertTrue(details["knockout_matchup_reversed"])

    def test_knockout_different_matchup_scores_zero(self):
        points, reasons, details = calculate_match_prediction_points(
            {
                "predicted_home_score": 2,
                "predicted_away_score": 1,
                "predicted_home_team_id": "BRA",
                "predicted_away_team_id": "ESP",
                "predicted_advancing_team_id": "BRA",
                "predicted_goes_to_penalties": True,
            },
            {
                "home_score": 2,
                "away_score": 1,
                "home_team_id": "ESP",
                "away_team_id": "GER",
                "advancing_team_id": "ESP",
                "home_score_penalties": 4,
                "away_score_penalties": 3,
                "stage": "round_of_32",
            },
        )

        self.assertEqual(points, 0)
        self.assertIn("no coincide", reasons[0])
        self.assertFalse(details["knockout_matchup_matches"])
        self.assertFalse(details["correct_advancing_team"])
        self.assertFalse(details["correct_penalties"])
        self.assertEqual(details["predicted_matchup"], ["BRA", "ESP"])
        self.assertEqual(details["real_matchup"], ["ESP", "GER"])

    def test_knockout_one_matching_team_scores_zero(self):
        points, _reasons, _details = calculate_match_prediction_points(
            {
                "predicted_home_score": 2,
                "predicted_away_score": 1,
                "predicted_home_team_id": "BRA",
                "predicted_away_team_id": "ESP",
            },
            {
                "home_score": 2,
                "away_score": 1,
                "home_team_id": "BRA",
                "away_team_id": "SWE",
                "stage": "round_of_32",
            },
        )

        self.assertEqual(points, 0)

    def test_knockout_advancing_team_scores_even_when_matchup_differs(self):
        matching_points, _reasons, matching_details = calculate_match_prediction_points(
            {
                "predicted_home_score": 0,
                "predicted_away_score": 0,
                "predicted_home_team_id": "BRA",
                "predicted_away_team_id": "ESP",
                "predicted_advancing_team_id": "BRA",
            },
            {
                "home_score": 1,
                "away_score": 1,
                "home_team_id": "BRA",
                "away_team_id": "ESP",
                "advancing_team_id": "BRA",
                "stage": "round_of_32",
            },
        )
        mismatching_points, _reasons, mismatching_details = calculate_match_prediction_points(
            {
                "predicted_home_score": 0,
                "predicted_away_score": 0,
                "predicted_home_team_id": "BRA",
                "predicted_away_team_id": "ESP",
                "predicted_advancing_team_id": "BRA",
            },
            {
                "home_score": 1,
                "away_score": 1,
                "home_team_id": "BRA",
                "away_team_id": "SWE",
                "advancing_team_id": "SWE",
                "stage": "round_of_32",
            },
            advanced_team_in_stage=True,
            advancement_points_allowed=True,
            advancement_scored_by_stage=True,
        )

        self.assertEqual(matching_points, 8)
        self.assertTrue(matching_details["correct_advancing_team"])
        self.assertEqual(mismatching_points, 3)
        self.assertTrue(mismatching_details["correct_advancing_team"])
        self.assertFalse(mismatching_details["knockout_score_points_allowed"])
        self.assertTrue(mismatching_details["advancement_scored_by_stage"])

    def test_knockout_matching_matchup_exact_score_and_stage_advancement_scores_ten(self):
        points, _reasons, details = calculate_match_prediction_points(
            {
                "predicted_home_score": 2,
                "predicted_away_score": 1,
                "predicted_home_team_id": "BRA",
                "predicted_away_team_id": "ESP",
                "predicted_advancing_team_id": "BRA",
            },
            {
                "home_score": 2,
                "away_score": 1,
                "home_team_id": "BRA",
                "away_team_id": "ESP",
                "advancing_team_id": "BRA",
                "stage": "round_of_32",
            },
            advanced_team_in_stage=True,
            advancement_points_allowed=True,
            advancement_scored_by_stage=True,
        )

        self.assertEqual(points, 10)
        self.assertTrue(details["exact_score"])
        self.assertTrue(details["correct_advancing_team"])

    def test_knockout_reversed_matchup_exact_score_and_stage_advancement_scores_ten(self):
        points, _reasons, details = calculate_match_prediction_points(
            {
                "predicted_home_score": 2,
                "predicted_away_score": 1,
                "predicted_home_team_id": "BRA",
                "predicted_away_team_id": "ESP",
                "predicted_advancing_team_id": "BRA",
            },
            {
                "home_score": 1,
                "away_score": 2,
                "home_team_id": "ESP",
                "away_team_id": "BRA",
                "advancing_team_id": "BRA",
                "stage": "round_of_32",
            },
            advanced_team_in_stage=True,
            advancement_points_allowed=True,
            advancement_scored_by_stage=True,
        )

        self.assertEqual(points, 10)
        self.assertTrue(details["knockout_matchup_reversed"])

    def test_final_advancing_team_scores_twenty(self):
        points, reasons, details = calculate_match_prediction_points(
            {
                "predicted_home_score": 2,
                "predicted_away_score": 1,
                "predicted_home_team_id": "BRA",
                "predicted_away_team_id": "ESP",
                "predicted_advancing_team_id": "BRA",
            },
            {
                "home_score": 2,
                "away_score": 1,
                "home_team_id": "BRA",
                "away_team_id": "ESP",
                "advancing_team_id": "BRA",
                "stage": "final",
            },
            advanced_team_in_stage=True,
            advancement_points_allowed=True,
            advancement_scored_by_stage=True,
        )

        self.assertEqual(points, 27)
        self.assertTrue(details["exact_score"])
        self.assertTrue(details["correct_advancing_team"])
        self.assertTrue(any("+20" in reason for reason in reasons))

    def test_knockout_different_matchup_and_team_not_advanced_scores_zero(self):
        points, reasons, details = calculate_match_prediction_points(
            {
                "predicted_home_score": 2,
                "predicted_away_score": 1,
                "predicted_home_team_id": "BRA",
                "predicted_away_team_id": "ESP",
                "predicted_advancing_team_id": "BRA",
            },
            {
                "home_score": 2,
                "away_score": 1,
                "home_team_id": "ESP",
                "away_team_id": "GER",
                "advancing_team_id": "ESP",
                "stage": "round_of_32",
            },
            advanced_team_in_stage=False,
            advancement_points_allowed=False,
            advancement_scored_by_stage=False,
        )

        self.assertEqual(points, 0)
        self.assertTrue(any("no avanzó" in reason for reason in reasons))
        self.assertFalse(details["advanced_team_in_stage"])

    def test_knockout_penalties_do_not_score_when_matchup_differs(self):
        points, _reasons, details = calculate_match_prediction_points(
            {
                "predicted_home_score": 1,
                "predicted_away_score": 1,
                "predicted_home_team_id": "BRA",
                "predicted_away_team_id": "ESP",
                "predicted_advancing_team_id": "BRA",
                "predicted_goes_to_penalties": True,
            },
            {
                "home_score": 1,
                "away_score": 1,
                "home_team_id": "ESP",
                "away_team_id": "GER",
                "advancing_team_id": "ESP",
                "home_score_penalties": 4,
                "away_score_penalties": 3,
                "stage": "round_of_32",
            },
            advanced_team_in_stage=True,
            advancement_points_allowed=True,
            advancement_scored_by_stage=True,
        )

        self.assertEqual(points, 3)
        self.assertFalse(details["correct_penalties"])

    def test_same_team_advancement_only_scores_once_per_player_and_stage(self):
        scored_advancements = set()
        advanced_team_ids = {"BRA"}

        first = _claim_advancement_points(7, "BRA", advanced_team_ids, scored_advancements)
        duplicate = _claim_advancement_points(7, "BRA", advanced_team_ids, scored_advancements)
        other_player = _claim_advancement_points(8, "BRA", advanced_team_ids, scored_advancements)
        did_not_advance = _claim_advancement_points(7, "ESP", advanced_team_ids, scored_advancements)

        self.assertEqual(first, (True, True))
        self.assertEqual(duplicate, (True, False))
        self.assertEqual(other_player, (True, True))
        self.assertEqual(did_not_advance, (False, True))

    def test_knockout_stage_match_number_mapping(self):
        self.assertEqual(get_knockout_stage_match_numbers("round_of_32"), tuple(range(73, 89)))
        self.assertEqual(get_knockout_stage_match_numbers("final"), (104,))

    def test_knockout_without_snapshot_scores_zero_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALLOW_LEGACY_KNOCKOUT_SCORING", None)
            points, reasons, details = calculate_match_prediction_points(
                {"predicted_home_score": 2, "predicted_away_score": 1},
                {
                    "home_score": 2,
                    "away_score": 1,
                    "home_team_id": "BRA",
                    "away_team_id": "ESP",
                    "stage": "round_of_32",
                },
            )

        self.assertEqual(points, 0)
        self.assertIn("sin snapshot", reasons[0])
        self.assertFalse(details["knockout_matchup_matches"])

    def test_knockout_legacy_scoring_can_be_enabled_explicitly(self):
        with patch.dict(os.environ, {"ALLOW_LEGACY_KNOCKOUT_SCORING": "true"}):
            points, _reasons, _details = calculate_match_prediction_points(
                {"predicted_home_score": 2, "predicted_away_score": 1},
                {
                    "home_score": 2,
                    "away_score": 1,
                    "home_team_id": "BRA",
                    "away_team_id": "ESP",
                    "stage": "round_of_32",
                },
            )

        self.assertEqual(points, 7)

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

    def test_insert_score_event_ignores_group_category(self):
        with patch("scoring.insert_dynamic") as insert_dynamic:
            _insert_score_event(
                object(),
                {
                    "player_id": 1,
                    "category": "group",
                    "points": 14,
                    "reason_json": {"group_letter": "A"},
                },
            )

        insert_dynamic.assert_not_called()

    def test_derived_group_scoring_does_not_award_points(self):
        points, _reasons, details = calculate_group_prediction_points(
            [
                {"team_id": "ESP", "group_letter": "A", "position": 1},
                {"team_id": "FRA", "group_letter": "A", "position": 2},
                {"team_id": "BRA", "group_letter": "A", "position": 3},
                {"team_id": "ARG", "group_letter": "A", "position": 4},
            ],
            {"FRA": 1, "ESP": 2, "BRA": 3, "ARG": 4},
        )

        self.assertEqual(points, 0)
        self.assertEqual(details["group_letter"], "A")
        self.assertEqual(details["qualified_correct_count"], 0)
        self.assertEqual(details["exact_position_count"], 0)
        self.assertEqual(details["predicted_positions"]["ESP"], 1)
        self.assertEqual(details["actual_positions"]["ESP"], 2)

    def test_derived_group_scoring_details_are_json_serializable_with_uuid_team_ids(self):
        first_team_id = uuid4()
        second_team_id = uuid4()

        points, _reasons, details = calculate_group_prediction_points(
            [
                {"team_id": first_team_id, "group_letter": "A", "position": 1},
                {"team_id": second_team_id, "group_letter": "A", "position": 2},
            ],
            {
                first_team_id: 1,
                second_team_id: 2,
            },
        )

        self.assertEqual(points, 0)
        json.dumps(details)
        self.assertEqual(details["predicted_positions"][str(first_team_id)], 1)

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
