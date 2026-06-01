from __future__ import annotations

from sqlalchemy import text

from bracket import (
    build_full_projected_knockout_bracket,
    calculate_projected_group_tables,
    get_player_group_predictions,
    get_projected_winner_from_prediction,
)
from db import insert_dynamic, update_dynamic


def get_derived_group_order_for_player(session, player_id) -> dict[str, list[dict]]:
    rows = get_player_group_predictions(session, player_id)
    tables, _ = calculate_projected_group_tables(rows, rows)
    return tables


def sync_derived_group_predictions(session, player_id, group_letter: str | None = None) -> int:
    tables = get_derived_group_order_for_player(session, player_id)
    selected_tables = {
        letter: rows
        for letter, rows in tables.items()
        if group_letter is None or letter == group_letter
    }
    synced = 0
    for letter, rows in selected_tables.items():
        if len(rows) != 4:
            continue
        values = {
            "player_id": player_id,
            "group_letter": letter,
            "predicted_first_team_id": rows[0]["team_id"],
            "predicted_second_team_id": rows[1]["team_id"],
            "predicted_third_team_id": rows[2]["team_id"],
            "predicted_fourth_team_id": rows[3]["team_id"],
        }
        existing = session.execute(
            text(
                """
                SELECT id
                FROM group_predictions
                WHERE player_id = :player_id
                  AND group_letter = :group_letter
                """
            ),
            {"player_id": player_id, "group_letter": letter},
        ).mappings().first()
        if existing:
            update_dynamic(session, "group_predictions", values, "id = :id", {"id": existing["id"]})
        else:
            insert_dynamic(session, "group_predictions", values)
        synced += 1
    return synced


def derive_specials_from_knockout(knockout: dict[str, list[dict]]) -> dict:
    semi_finals = knockout.get("semi_final", [])
    final_matches = knockout.get("final", [])
    third_place_matches = knockout.get("third_place", [])
    semifinalists = [
        {
            "team_id": match.get(f"{side}_team_id"),
            "name": match.get(f"{side}_team_name"),
        }
        for match in semi_finals
        for side in ("home", "away")
        if match.get(f"{side}_team_id")
    ]
    final_match = final_matches[0] if final_matches else {}
    finalists = [
        {
            "team_id": final_match.get(f"{side}_team_id"),
            "name": final_match.get(f"{side}_team_name"),
        }
        for side in ("home", "away")
        if final_match.get(f"{side}_team_id")
    ]
    champion, _ = get_projected_winner_from_prediction(
        final_match.get("existing_prediction"),
        final_match,
    )
    runner_up = next(
        (
            team
            for team in finalists
            if champion and team["team_id"] != champion["team_id"]
        ),
        None,
    )
    third_place_match = third_place_matches[0] if third_place_matches else {}
    third_place, _ = get_projected_winner_from_prediction(
        third_place_match.get("existing_prediction"),
        third_place_match,
    )
    return {
        "champion_team_id": champion.get("team_id") if champion else None,
        "champion_team_name": champion.get("name") if champion else None,
        "runner_up_team_id": runner_up.get("team_id") if runner_up else None,
        "runner_up_team_name": runner_up.get("name") if runner_up else None,
        "semifinalists": semifinalists,
        "finalists": finalists,
        "third_place_team_id": third_place.get("team_id") if third_place else None,
        "third_place_team_name": third_place.get("name") if third_place else None,
    }


def get_derived_specials_from_bracket(session, player_id) -> dict:
    knockout = build_full_projected_knockout_bracket(session, player_id)
    return derive_specials_from_knockout(knockout)


def sync_derived_special_predictions(session, player_id) -> dict:
    derived = get_derived_specials_from_bracket(session, player_id)
    if (
        not derived["champion_team_id"]
        or not derived["runner_up_team_id"]
        or len(derived["semifinalists"]) != 4
    ):
        return derived | {"synced": False}

    values = {
        "player_id": player_id,
        "champion_team_id": derived["champion_team_id"],
        "runner_up_team_id": derived["runner_up_team_id"],
    }
    for index, team in enumerate(derived["semifinalists"], start=1):
        values[f"semifinalist_{index}_team_id"] = team["team_id"]
    existing = session.execute(
        text("SELECT id FROM special_predictions WHERE player_id = :player_id"),
        {"player_id": player_id},
    ).mappings().first()
    if existing:
        update_dynamic(session, "special_predictions", values, "id = :id", {"id": existing["id"]})
    else:
        insert_dynamic(session, "special_predictions", values)
    return derived | {"synced": True}
