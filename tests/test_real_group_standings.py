import unittest

from real_tournament import calculate_real_group_standings_from_matches


def match(group, home_id, away_id, home_name, away_name, home_score, away_score):
    return {
        "group_letter": group,
        "status": "finished",
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_team_name": home_name,
        "away_team_name": away_name,
        "home_score": home_score,
        "away_score": away_score,
    }


def simple_group(group, third_points_high=False):
    third_score = (1, 0) if third_points_high else (0, 0)
    return [
        match(group, f"{group}1", f"{group}2", f"{group} One", f"{group} Two", 2, 0),
        match(group, f"{group}1", f"{group}3", f"{group} One", f"{group} Three", 2, 0),
        match(group, f"{group}1", f"{group}4", f"{group} One", f"{group} Four", 2, 0),
        match(group, f"{group}2", f"{group}3", f"{group} Two", f"{group} Three", 2, 0),
        match(group, f"{group}2", f"{group}4", f"{group} Two", f"{group} Four", 2, 0),
        match(group, f"{group}3", f"{group}4", f"{group} Three", f"{group} Four", *third_score),
    ]


class RealGroupStandingsTests(unittest.TestCase):
    def test_group_orders_by_points_goal_difference_and_goals_for(self):
        rows = [
            match("A", "A", "B", "Alpha", "Beta", 1, 0),
            match("A", "A", "C", "Alpha", "Charlie", 0, 0),
            match("A", "A", "D", "Alpha", "Delta", 0, 2),
            match("A", "B", "C", "Beta", "Charlie", 4, 1),
            match("A", "B", "D", "Beta", "Delta", 0, 2),
            match("A", "C", "D", "Charlie", "Delta", 1, 0),
        ]

        tables = calculate_real_group_standings_from_matches(rows)

        self.assertEqual([row["team_id"] for row in tables["A"]], ["D", "A", "C", "B"])
        self.assertEqual(tables["A"][0]["points"], 6)
        self.assertEqual(tables["A"][0]["position"], 1)

    def test_marks_first_second_and_eight_best_thirds(self):
        rows = []
        for group in "ABCDEFGHIJKL":
            rows.extend(simple_group(group, third_points_high=group in "EFGHIJKL"))

        tables = calculate_real_group_standings_from_matches(rows)
        best_third_groups = {
            row["group_letter"]
            for group_rows in tables.values()
            for row in group_rows
            if row["position"] == 3 and row["qualified_as"] == "best_third"
        }

        self.assertEqual(best_third_groups, set("EFGHIJKL"))
        self.assertTrue(tables["A"][0]["qualified"])
        self.assertEqual(tables["A"][0]["qualified_as"], "1st")
        self.assertEqual(tables["A"][1]["qualified_as"], "2nd")


if __name__ == "__main__":
    unittest.main()
