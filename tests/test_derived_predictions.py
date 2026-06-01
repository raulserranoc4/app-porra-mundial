import unittest
from unittest.mock import patch

from derived_predictions import (
    derive_specials_from_knockout,
    sync_derived_group_predictions,
    sync_derived_special_predictions,
)


def projected_match(home_id, home_name, away_id, away_name, advancing_id=None):
    return {
        "home_team_id": home_id,
        "home_team_name": home_name,
        "away_team_id": away_id,
        "away_team_name": away_name,
        "existing_prediction": (
            {"predicted_advancing_team_id": advancing_id}
            if advancing_id
            else None
        ),
    }


class DerivedPredictionTests(unittest.TestCase):
    def test_syncs_derived_group_order_for_legacy_scoring(self):
        class Rows:
            def mappings(self):
                return self

            def first(self):
                return {"id": "group-legacy"}

        class Session:
            def execute(self, *_args, **_kwargs):
                return Rows()

        captured = {}
        tables = {
            "A": [
                {"team_id": "ESP"},
                {"team_id": "FRA"},
                {"team_id": "BRA"},
                {"team_id": "ARG"},
            ]
        }

        with patch(
            "derived_predictions.get_derived_group_order_for_player",
            return_value=tables,
        ):
            with patch(
                "derived_predictions.update_dynamic",
                side_effect=lambda _session, _table, values, _where, _params: captured.update(values),
            ):
                synced = sync_derived_group_predictions(Session(), "player", "A")

        self.assertEqual(synced, 1)
        self.assertEqual(captured["predicted_first_team_id"], "ESP")
        self.assertEqual(captured["predicted_fourth_team_id"], "ARG")

    def test_derives_champion_runner_up_and_semifinalists(self):
        knockout = {
            "semi_final": [
                projected_match("ESP", "España", "FRA", "Francia", "ESP"),
                projected_match("ARG", "Argentina", "BRA", "Brasil", "ARG"),
            ],
            "final": [
                projected_match("ESP", "España", "ARG", "Argentina", "ESP"),
            ],
            "third_place": [
                projected_match("FRA", "Francia", "BRA", "Brasil", "BRA"),
            ],
        }

        derived = derive_specials_from_knockout(knockout)

        self.assertEqual(derived["champion_team_id"], "ESP")
        self.assertEqual(derived["runner_up_team_id"], "ARG")
        self.assertEqual(
            [team["team_id"] for team in derived["semifinalists"]],
            ["ESP", "FRA", "ARG", "BRA"],
        )
        self.assertEqual(derived["third_place_team_id"], "BRA")

    def test_sync_preserves_manual_individual_awards(self):
        class Rows:
            def mappings(self):
                return self

            def first(self):
                return {"id": "special-1"}

        class Session:
            def execute(self, *_args, **_kwargs):
                return Rows()

        captured = {}
        derived = {
            "champion_team_id": "ESP",
            "champion_team_name": "España",
            "runner_up_team_id": "ARG",
            "runner_up_team_name": "Argentina",
            "semifinalists": [
                {"team_id": "ESP", "name": "España"},
                {"team_id": "FRA", "name": "Francia"},
                {"team_id": "ARG", "name": "Argentina"},
                {"team_id": "BRA", "name": "Brasil"},
            ],
            "finalists": [],
            "third_place_team_id": None,
            "third_place_team_name": None,
        }

        with patch(
            "derived_predictions.get_derived_specials_from_bracket",
            return_value=derived,
        ):
            with patch(
                "derived_predictions.update_dynamic",
                side_effect=lambda _session, _table, values, _where, _params: captured.update(values),
            ):
                result = sync_derived_special_predictions(Session(), "player")

        self.assertTrue(result["synced"])
        self.assertEqual(captured["champion_team_id"], "ESP")
        self.assertNotIn("top_scorer_name", captured)
        self.assertNotIn("mvp_name", captured)


if __name__ == "__main__":
    unittest.main()
