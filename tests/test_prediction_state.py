import unittest

from utils.prediction_state import (
    get_or_init_pending_match_ids,
    get_progress_counts,
    init_prediction_widget_value,
    load_user_predictions_cached_or_state,
    mark_prediction_saved,
    reset_pending_match_ids,
)


class PredictionStateTests(unittest.TestCase):
    def test_cache_loads_database_after_a_local_knockout_save(self):
        state = {}
        mark_prediction_saved(
            state,
            player_id="player",
            match_number=73,
            payload={"predicted_home_score": 2, "predicted_away_score": 1},
        )

        cache = load_user_predictions_cached_or_state(
            state,
            "player",
            lambda: [
                {"match_id": "m1", "match_number": 1},
                {"match_id": "m73", "match_number": 73},
            ],
        )

        self.assertEqual(set(cache), {"m1", "m73"})

    def test_cache_and_pending_snapshot_stay_stable_until_refresh(self):
        state = {}
        calls = []

        def loader():
            calls.append(True)
            return [{"match_id": "m1", "match_number": 1}]

        cache = load_user_predictions_cached_or_state(state, "player", loader)
        pending = get_or_init_pending_match_ids(state, "player", {"m1", "m2"})
        mark_prediction_saved(
            state,
            player_id="player",
            match_id="m2",
            match_number=2,
            payload={"predicted_home_score": 1, "predicted_away_score": 0},
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(set(cache), {"m1", "m2"})
        self.assertEqual(pending, {"m2"})

        reset_pending_match_ids(state, "player")
        self.assertEqual(
            get_or_init_pending_match_ids(state, "player", {"m1", "m2"}),
            set(),
        )

    def test_widget_initialization_does_not_overwrite_local_value(self):
        state = {}

        self.assertEqual(init_prediction_widget_value(state, "score", 2), 2)
        state["score"] = 4
        self.assertEqual(init_prediction_widget_value(state, "score", 1), 4)

    def test_progress_counts_include_locally_saved_knockout_prediction(self):
        state = {}
        load_user_predictions_cached_or_state(
            state,
            "player",
            lambda: [{"match_id": "m1", "match_number": 1}],
        )
        mark_prediction_saved(
            state,
            player_id="player",
            match_number=73,
            payload={"predicted_home_score": 2, "predicted_away_score": 1},
        )

        self.assertEqual(
            get_progress_counts(state, "player", {"m1", "m2"}, {73, 74}),
            {
                "group_saved": 1,
                "group_total": 2,
                "knockout_saved": 1,
                "knockout_total": 2,
            },
        )


if __name__ == "__main__":
    unittest.main()
