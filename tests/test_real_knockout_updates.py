import unittest

from real_tournament import (
    build_real_knockout_next_round_updates,
    build_real_round_of_32_match_updates,
    build_tournament_results_payload_from_matches,
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
    def test_round_of_32_uses_official_third_place_json(self):
        key, updates = build_real_round_of_32_match_updates(standings_tables_for_thirds("DEFGIJKL"))

        self.assertEqual(key, "DEFGIJKL")
        self.assertEqual(updates[73], ("A2", "B2"))
        self.assertEqual(updates[74], ("E1", "D3"))

    def test_winners_of_73_and_74_fill_match_89(self):
        updates, missing = build_real_knockout_next_round_updates(
            {
                73: finished_match("A2", "B2", "A2"),
                74: finished_match("E1", "D3", "D3"),
            }
        )

        self.assertEqual(updates[89], ("A2", "D3"))
        self.assertIn(90, missing)

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
