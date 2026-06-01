import unittest
from unittest.mock import patch

from bracket import (
    MissingThirdPlaceAssignmentError,
    build_projected_round_of_32_matches,
    build_projected_knockout_from_round_of_32,
    calculate_best_third_placed,
    calculate_projected_group_tables,
    load_third_place_assignment_map,
    rank_group_table,
    resolve_third_place_slots,
    get_projected_loser_from_prediction,
    get_projected_winner_from_prediction,
    save_knockout_round_predictions,
    validate_knockout_prediction,
)


def team(group_letter: str, position: int, points: int, goal_difference: int, goals_for: int):
    return {
        "team_id": f"{group_letter}{position}",
        "name": f"Team {group_letter}{position}",
        "group_letter": group_letter,
        "position": position,
        "slot": f"{position}{group_letter}",
        "played": 3,
        "won": 0,
        "drawn": 0,
        "lost": 0,
        "goals_for": goals_for,
        "goals_against": goals_for - goal_difference,
        "goal_difference": goal_difference,
        "points": points,
    }


def projected_tables_for_thirds(selected_thirds: str):
    tables = {}
    for group_letter in "ABCDEFGHIJKL":
        third_points = 4 if group_letter in selected_thirds else 1
        tables[group_letter] = [
            team(group_letter, 1, 9, 5, 8),
            team(group_letter, 2, 6, 2, 5),
            team(group_letter, 3, third_points, 0, 3),
            team(group_letter, 4, 0, -7, 1),
        ]
    return tables


def projected_round_of_32():
    return [
        {
            "match_number": match_number,
            "home_slot": f"home:{match_number}",
            "away_slot": f"away:{match_number}",
            "home_team": {"team_id": f"H{match_number}", "name": f"Home {match_number}"},
            "away_team": {"team_id": f"A{match_number}", "name": f"Away {match_number}"},
        }
        for match_number in range(73, 89)
    ]


def winner_predictions():
    return {
        match_number: {"predicted_advancing_team_id": f"H{match_number}"}
        for match_number in range(73, 89)
    }


class BracketTests(unittest.TestCase):
    def test_knockout_round_upserts_without_duplicates(self):
        class Rows:
            def __init__(self, rows=None):
                self.rows = rows or []

            def mappings(self):
                return self

            def all(self):
                return self.rows

        class RecordingSession:
            def __init__(self):
                self.writes = []

            def execute(self, statement, params=None):
                sql = str(statement)
                if "SELECT id, match_number" in sql:
                    return Rows(
                        [
                            {"id": "match-89", "match_number": 89},
                            {"id": "match-90", "match_number": 90},
                        ]
                    )
                if "SELECT match_id" in sql:
                    return Rows([{"match_id": "match-89"}])
                self.writes.append((sql, params))
                return Rows()

        projected_matches = {
            "round_of_16": [
                {
                    "match_number": 89,
                    "home_team_id": "SWE",
                    "away_team_id": "BRA",
                    "is_available": True,
                },
                {
                    "match_number": 90,
                    "home_team_id": "ESP",
                    "away_team_id": "ARG",
                    "is_available": True,
                },
            ]
        }
        payloads = [
            {
                "match_number": 89,
                "predicted_home_score": 0,
                "predicted_away_score": 1,
                "predicted_advancing_team_id": "BRA",
                "predicted_goes_to_penalties": False,
            },
            {
                "match_number": 90,
                "predicted_home_score": 2,
                "predicted_away_score": 0,
                "predicted_advancing_team_id": "ESP",
                "predicted_goes_to_penalties": False,
            },
        ]
        session = RecordingSession()

        with patch("db.predictions_are_open", return_value=True):
            with patch(
                "bracket.build_full_projected_knockout_bracket",
                return_value=projected_matches,
            ):
                result = save_knockout_round_predictions(
                    session,
                    player_id="player",
                    round_name="round_of_16",
                    projected_matches_payload=payloads,
                )

        self.assertEqual(result, {"guardadas": 1, "actualizadas": 1, "errores": []})
        self.assertEqual(len(session.writes), 2)
        self.assertIn("UPDATE predictions", session.writes[0][0])
        self.assertIn("INSERT INTO predictions", session.writes[1][0])

    def test_knockout_round_validation_does_not_write_partial_results(self):
        class NoWriteSession:
            def execute(self, *_args, **_kwargs):
                raise AssertionError("No debe escribir si una apuesta de la ronda es inválida.")

        projected_matches = {
            "round_of_16": [
                {
                    "match_number": 89,
                    "home_team_id": "SWE",
                    "away_team_id": "BRA",
                    "is_available": True,
                },
                {
                    "match_number": 90,
                    "home_team_id": "ESP",
                    "away_team_id": "ARG",
                    "is_available": True,
                },
            ]
        }
        payloads = [
            {
                "match_number": 89,
                "predicted_home_score": 0,
                "predicted_away_score": 1,
                "predicted_advancing_team_id": "BRA",
                "predicted_goes_to_penalties": False,
            },
            {
                "match_number": 90,
                "predicted_home_score": 0,
                "predicted_away_score": 1,
                "predicted_advancing_team_id": "ESP",
                "predicted_goes_to_penalties": False,
            },
        ]

        with patch("db.predictions_are_open", return_value=True):
            with patch(
                "bracket.build_full_projected_knockout_bracket",
                return_value=projected_matches,
            ):
                result = save_knockout_round_predictions(
                    NoWriteSession(),
                    player_id="player",
                    round_name="round_of_16",
                    projected_matches_payload=payloads,
                )

        self.assertEqual(result["guardadas"], 0)
        self.assertEqual(result["actualizadas"], 0)
        self.assertIn("Match 90", result["errores"][0])

    def test_validate_knockout_prediction_score_rules(self):
        cases = [
            ((0, 1, "SWE", "BRA", "SWE", False), False),
            ((0, 1, "SWE", "BRA", "BRA", False), True),
            ((2, 0, "SWE", "BRA", "SWE", False), True),
            ((2, 0, "SWE", "BRA", "BRA", False), False),
            ((1, 1, "SWE", "BRA", "SWE", False), True),
            ((1, 1, "SWE", "BRA", "BRA", False), True),
            ((2, 1, "SWE", "BRA", "SWE", True), False),
            ((1, 1, "SWE", "BRA", "SWE", True), True),
        ]

        for args, expected in cases:
            with self.subTest(args=args):
                is_valid, _ = validate_knockout_prediction(*args)
                self.assertEqual(is_valid, expected)

    def test_loads_all_third_place_combinations(self):
        assignments = load_third_place_assignment_map()

        self.assertEqual(len(assignments), 495)
        self.assertIn("ABCDEFGH", assignments)

    def test_calculates_group_table_from_six_predictions(self):
        matches = [
            {"match_id": 1, "group_letter": "A", "home_team_id": "A", "away_team_id": "B", "home_team_name": "Alpha", "away_team_name": "Beta"},
            {"match_id": 2, "group_letter": "A", "home_team_id": "A", "away_team_id": "C", "home_team_name": "Alpha", "away_team_name": "Charlie"},
            {"match_id": 3, "group_letter": "A", "home_team_id": "A", "away_team_id": "D", "home_team_name": "Alpha", "away_team_name": "Delta"},
            {"match_id": 4, "group_letter": "A", "home_team_id": "B", "away_team_id": "C", "home_team_name": "Beta", "away_team_name": "Charlie"},
            {"match_id": 5, "group_letter": "A", "home_team_id": "B", "away_team_id": "D", "home_team_name": "Beta", "away_team_name": "Delta"},
            {"match_id": 6, "group_letter": "A", "home_team_id": "C", "away_team_id": "D", "home_team_name": "Charlie", "away_team_name": "Delta"},
        ]
        predictions = {
            1: {"predicted_home_score": 2, "predicted_away_score": 0},
            2: {"predicted_home_score": 1, "predicted_away_score": 1},
            3: {"predicted_home_score": 3, "predicted_away_score": 0},
            4: {"predicted_home_score": 2, "predicted_away_score": 1},
            5: {"predicted_home_score": 1, "predicted_away_score": 0},
            6: {"predicted_home_score": 0, "predicted_away_score": 0},
        }

        tables, _ = calculate_projected_group_tables(matches, predictions)

        self.assertEqual(tables["A"][0]["name"], "Alpha")
        self.assertEqual(tables["A"][0]["points"], 7)
        self.assertEqual(tables["A"][0]["goal_difference"], 5)
        self.assertEqual(tables["A"][1]["name"], "Beta")
        self.assertEqual(tables["A"][1]["points"], 6)

    def test_ranks_by_points_goal_difference_and_goals(self):
        rows = [
            team("A", 1, 4, 1, 3),
            team("A", 2, 5, 0, 2),
            team("A", 3, 4, 2, 2),
            team("A", 4, 4, 2, 5),
        ]

        ranked, _ = rank_group_table(rows)

        self.assertEqual([row["team_id"] for row in ranked], ["A2", "A4", "A3", "A1"])

    def test_selects_eight_best_thirds(self):
        tables = projected_tables_for_thirds("DEFGIJKL")

        best_thirds = calculate_best_third_placed(tables)

        self.assertEqual("".join(row["group_letter"] for row in best_thirds), "DEFGIJKL")

    def test_builds_fixed_round_of_32_matches(self):
        tables = projected_tables_for_thirds("DEFGIJKL")

        matches = build_projected_round_of_32_matches(tables)
        third_place_key, _ = resolve_third_place_slots(tables)
        by_number = {match["match_number"]: match for match in matches}

        self.assertEqual(third_place_key, "DEFGIJKL")
        self.assertEqual(by_number[73]["home_slot"], "2A")
        self.assertEqual(by_number[73]["away_slot"], "2B")
        self.assertEqual(by_number[75]["home_slot"], "1F")
        self.assertEqual(by_number[75]["away_slot"], "2C")
        self.assertEqual(by_number[74]["away_slot"], "3D")

    def test_missing_annex_c_combination_returns_controlled_error(self):
        tables = projected_tables_for_thirds("ABCDEFGH")

        with patch("bracket.load_third_place_assignment_map", return_value={}):
            with self.assertRaisesRegex(
                MissingThirdPlaceAssignmentError,
                "Revisa data/third_place_assignment_2026.json",
            ):
                build_projected_round_of_32_matches(tables)

    def test_projected_winner_and_loser_are_resolved(self):
        match = {
            "home_team_id": "A",
            "home_team_name": "Alpha",
            "away_team_id": "B",
            "away_team_name": "Beta",
        }
        prediction = {"predicted_advancing_team_id": "A"}

        winner, warning = get_projected_winner_from_prediction(prediction, match)
        loser, loser_warning = get_projected_loser_from_prediction(prediction, match)

        self.assertEqual(winner, {"team_id": "A", "name": "Alpha"})
        self.assertEqual(loser, {"team_id": "B", "name": "Beta"})
        self.assertIsNone(warning)
        self.assertIsNone(loser_warning)

    def test_invalid_advancing_team_generates_warning(self):
        match = {
            "home_team_id": "A",
            "home_team_name": "Alpha",
            "away_team_id": "B",
            "away_team_name": "Beta",
        }

        winner, warning = get_projected_winner_from_prediction(
            {"predicted_advancing_team_id": "Z"},
            match,
        )

        self.assertIsNone(winner)
        self.assertIn("ya no coincide", warning)

    def test_inconsistent_saved_score_does_not_propagate(self):
        match = {
            "home_team_id": "SWE",
            "home_team_name": "Suecia",
            "away_team_id": "BRA",
            "away_team_name": "Brasil",
        }

        winner, warning = get_projected_winner_from_prediction(
            {
                "predicted_home_score": 0,
                "predicted_away_score": 1,
                "predicted_advancing_team_id": "SWE",
                "predicted_goes_to_penalties": False,
            },
            match,
        )

        self.assertIsNone(winner)
        self.assertIn("inconsistente con el marcador", warning)

    def test_builds_full_knockout_bracket_from_previous_winners(self):
        predictions = winner_predictions()
        for match_number in range(89, 103):
            predictions[match_number] = {
                "predicted_advancing_team_id": "H73",
            }
        predictions[89] = {"predicted_advancing_team_id": "H73"}
        predictions[90] = {"predicted_advancing_team_id": "H75"}
        predictions[91] = {"predicted_advancing_team_id": "H77"}
        predictions[92] = {"predicted_advancing_team_id": "H79"}
        predictions[93] = {"predicted_advancing_team_id": "H81"}
        predictions[94] = {"predicted_advancing_team_id": "H83"}
        predictions[95] = {"predicted_advancing_team_id": "H85"}
        predictions[96] = {"predicted_advancing_team_id": "H87"}
        predictions[97] = {"predicted_advancing_team_id": "H73"}
        predictions[98] = {"predicted_advancing_team_id": "H77"}
        predictions[99] = {"predicted_advancing_team_id": "H81"}
        predictions[100] = {"predicted_advancing_team_id": "H85"}
        predictions[101] = {"predicted_advancing_team_id": "H73"}
        predictions[102] = {"predicted_advancing_team_id": "H81"}

        bracket = build_projected_knockout_from_round_of_32(
            projected_round_of_32(),
            predictions,
        )

        self.assertEqual(bracket["round_of_16"][0]["home_team_id"], "H73")
        self.assertEqual(bracket["quarter_final"][0]["home_team_id"], "H73")
        self.assertEqual(bracket["semi_final"][0]["home_team_id"], "H73")
        self.assertEqual(bracket["final"][0]["home_team_id"], "H73")
        self.assertEqual(bracket["final"][0]["away_team_id"], "H81")
        self.assertEqual(bracket["third_place"][0]["home_team_id"], "H77")
        self.assertEqual(bracket["third_place"][0]["away_team_id"], "H85")

    def test_later_round_is_unavailable_without_previous_winner(self):
        bracket = build_projected_knockout_from_round_of_32(
            projected_round_of_32(),
            {},
        )

        first_round_of_16 = bracket["round_of_16"][0]
        self.assertFalse(first_round_of_16["is_available"])
        self.assertIn("Ganador partido 73", first_round_of_16["missing_reason"])


if __name__ == "__main__":
    unittest.main()
