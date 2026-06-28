import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from bracket import KNOCKOUT_BRACKET_STRUCTURE
from real_tournament import (
    build_real_knockout_next_round_updates,
    build_real_round_of_32_match_updates,
    build_tournament_results_payload_from_matches,
    update_real_round_of_32_from_group_standings,
)


def standing_team(group_letter, position, points):
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
        "goals_for": 5 - position,
        "goals_against": position,
        "goal_difference": 5 - (position * 2),
        "points": points,
    }


def standings_tables_for_thirds(selected_thirds):
    tables = {}
    for group_letter in "ABCDEFGHIJKL":
        third_points = 4 if group_letter in selected_thirds else 1
        tables[group_letter] = [
            standing_team(group_letter, 1, 9),
            standing_team(group_letter, 2, 6),
            standing_team(group_letter, 3, third_points),
            standing_team(group_letter, 4, 0),
        ]
    return tables


def finished_match(home, away, advancing):
    return {
        "status": "finished",
        "home_team_id": home,
        "away_team_id": away,
        "advancing_team_id": advancing,
    }


class RealKnockoutUpdateTests(unittest.TestCase):
    def test_knockout_structure_matches_official_2026_tree(self):
        self.assertEqual(
            KNOCKOUT_BRACKET_STRUCTURE,
            {
                "round_of_16": {
                    89: (("winner", 74), ("winner", 77)),
                    90: (("winner", 73), ("winner", 75)),
                    91: (("winner", 76), ("winner", 78)),
                    92: (("winner", 79), ("winner", 80)),
                    93: (("winner", 83), ("winner", 84)),
                    94: (("winner", 81), ("winner", 82)),
                    95: (("winner", 86), ("winner", 88)),
                    96: (("winner", 85), ("winner", 87)),
                },
                "quarter_final": {
                    97: (("winner", 89), ("winner", 90)),
                    98: (("winner", 93), ("winner", 94)),
                    99: (("winner", 91), ("winner", 92)),
                    100: (("winner", 95), ("winner", 96)),
                },
                "semi_final": {
                    101: (("winner", 97), ("winner", 98)),
                    102: (("winner", 99), ("winner", 100)),
                },
                "third_place": {
                    103: (("loser", 101), ("loser", 102)),
                },
                "final": {
                    104: (("winner", 101), ("winner", 102)),
                },
            },
        )

    def test_round_of_32_uses_official_third_place_json(self):
        key, updates = build_real_round_of_32_match_updates(standings_tables_for_thirds("DEFGIJKL"))

        self.assertEqual(key, "DEFGIJKL")
        self.assertEqual(updates[73], ("A2", "B2"))
        self.assertEqual(updates[74], ("E1", "D3"))

    def test_round_of_32_update_recalculates_standings_before_building_matches(self):
        calls = []
        conn = Mock()

        @contextmanager
        def fake_session():
            yield conn

        def recalculate(_conn):
            calls.append("recalculate")
            return {"updated": 48, "groups": 12}

        def load_tables(_conn):
            calls.append("load_tables")
            return standings_tables_for_thirds("DEFGIJKL")

        with (
            patch("real_tournament.db_session", fake_session),
            patch("real_tournament._missing_finished_group_matches", return_value=0),
            patch("real_tournament._recalculate_real_group_standings", side_effect=recalculate),
            patch("real_tournament._group_standings_tables", side_effect=load_tables),
            patch(
                "real_tournament.build_real_round_of_32_match_updates",
                return_value=("DEFGIJKL", {73: ("A2", "B2")}),
            ),
            patch("real_tournament.update_dynamic") as update_dynamic,
        ):
            result = update_real_round_of_32_from_group_standings()

        self.assertEqual(calls, ["recalculate", "load_tables"])
        self.assertEqual(result["standings_updated"], 48)
        self.assertEqual(result["standings_groups"], 12)
        update_dynamic.assert_called_once()

    def test_round_of_16_uses_official_bracket_sources(self):
        updates, missing = build_real_knockout_next_round_updates(
            {
                73: finished_match("A2", "B2", "A2"),
                74: finished_match("E1", "D3", "D3"),
                75: finished_match("F1", "C2", "F1"),
                77: finished_match("I1", "A3", "I1"),
            }
        )

        self.assertEqual(updates[89], ("D3", "I1"))
        self.assertEqual(updates[90], ("A2", "F1"))
        self.assertNotIn(89, missing)
        self.assertNotIn(90, missing)

    def test_quarter_finals_use_official_bracket_sources(self):
        updates, missing = build_real_knockout_next_round_updates(
            {
                89: finished_match("A", "B", "A"),
                90: finished_match("C", "D", "C"),
                91: finished_match("E", "F", "E"),
                92: finished_match("G", "H", "G"),
                93: finished_match("I", "J", "I"),
                94: finished_match("K", "L", "K"),
                95: finished_match("M", "N", "M"),
                96: finished_match("O", "P", "O"),
            }
        )

        self.assertEqual(updates[97], ("A", "C"))
        self.assertEqual(updates[98], ("I", "K"))
        self.assertEqual(updates[99], ("E", "G"))
        self.assertEqual(updates[100], ("M", "O"))
        self.assertNotIn(97, missing)
        self.assertNotIn(100, missing)

    def test_semifinal_winners_fill_final_and_losers_fill_third_place(self):
        updates, _missing = build_real_knockout_next_round_updates(
            {
                101: finished_match("BRA", "ESP", "BRA"),
                102: finished_match("ARG", "FRA", "FRA"),
            }
        )

        self.assertEqual(updates[104], ("BRA", "FRA"))
        self.assertEqual(updates[103], ("ESP", "ARG"))

    def test_final_finished_updates_champion_and_runner_up_payload(self):
        payload = build_tournament_results_payload_from_matches(
            {
                101: finished_match("BRA", "ESP", "BRA"),
                102: finished_match("ARG", "FRA", "FRA"),
                104: finished_match("BRA", "FRA", "BRA"),
            }
        )

        self.assertEqual(payload["champion_team_id"], "BRA")
        self.assertEqual(payload["runner_up_team_id"], "FRA")
        self.assertEqual(
            [
                payload["semifinalist_1_team_id"],
                payload["semifinalist_2_team_id"],
                payload["semifinalist_3_team_id"],
                payload["semifinalist_4_team_id"],
            ],
            ["BRA", "ESP", "ARG", "FRA"],
        )


if __name__ == "__main__":
    unittest.main()
