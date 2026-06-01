import json
from typing import Any

from sqlalchemy import text

from db import db_session, fetch_df, fetch_one, insert_dynamic


def _result(home: int | None, away: int | None) -> str | None:
    if home is None or away is None:
        return None
    if home > away:
        return "H"
    if away > home:
        return "A"
    return "D"


def _has_penalties(match: dict) -> bool:
    return match.get("home_score_penalties") is not None or match.get("away_score_penalties") is not None


def _is_knockout(match: dict) -> bool:
    stage = str(match.get("phase") or match.get("stage") or "").lower()
    return stage not in {"group", "groups", "fase de grupos", "group_stage"}


def calculate_match_prediction_points(prediction: dict, match: dict) -> tuple[int, list[str], dict[str, Any]]:
    if match.get("home_score") is None or match.get("away_score") is None:
        return 0, ["Partido sin resultado final."], {}

    ph = prediction.get("predicted_home_score")
    pa = prediction.get("predicted_away_score")
    ah = match.get("home_score")
    aa = match.get("away_score")
    points = 0
    reasons: list[str] = []

    if ph == ah and pa == aa:
        points += 7
        reasons.append("Marcador exacto (+7).")
    else:
        if _result(ph, pa) == _result(ah, aa):
            points += 3
            reasons.append("Signo correcto (+3).")
        if ph is not None and pa is not None and (ph - pa) == (ah - aa):
            points += 2
            reasons.append("Diferencia correcta (+2).")
        if ph == ah:
            points += 1
            reasons.append("Goles local correctos (+1).")
        if pa == aa:
            points += 1
            reasons.append("Goles visitante correctos (+1).")

    if _is_knockout(match):
        if prediction.get("predicted_advancing_team_id") and prediction.get("predicted_advancing_team_id") == match.get("advancing_team_id"):
            points += 3
            reasons.append("Equipo que avanza correcto (+3).")
        if prediction.get("predicted_goes_to_penalties") and _has_penalties(match):
            points += 2
            reasons.append("Penales correctos (+2).")

    return points, reasons or ["Sin puntos."], {
        "prediction": {
            "home": ph,
            "away": pa,
            "advancing_team_id": prediction.get("predicted_advancing_team_id"),
            "goes_to_penalties": prediction.get("predicted_goes_to_penalties"),
        },
        "match": {
            "home": ah,
            "away": aa,
            "advancing_team_id": match.get("advancing_team_id"),
            "has_penalties": _has_penalties(match),
        },
    }


def _insert_score_event(conn, values: dict) -> None:
    insert_dynamic(
        conn,
        "score_events",
        values
        | {
            "reason_json": json.dumps(values.get("reason_json", {}), default=str),
        },
    )


def recalculate_match_scores(match_id: int) -> None:
    with db_session() as conn:
        conn.execute(text("DELETE FROM score_events WHERE match_id = :match_id"), {"match_id": match_id})
        match = conn.execute(text("SELECT * FROM matches WHERE id = :id"), {"id": match_id}).mappings().first()
        if not match:
            return
        predictions = conn.execute(text("SELECT * FROM predictions WHERE match_id = :match_id"), {"match_id": match_id}).mappings().all()
        for prediction in predictions:
            points, reasons, details = calculate_match_prediction_points(dict(prediction), dict(match))
            _insert_score_event(
                conn,
                {
                    "player_id": prediction.get("player_id"),
                    "prediction_id": prediction.get("id"),
                    "match_id": match_id,
                    "category": "match",
                    "points": points,
                    "reason": " ".join(reasons),
                    "reason_json": details,
                },
            )


def recalculate_group_scores() -> None:
    actual = fetch_df("SELECT * FROM group_standings")
    predictions = fetch_df("SELECT * FROM group_predictions")
    if actual.empty or predictions.empty:
        return

    actual_by_team = {row["team_id"]: row for row in actual.to_dict("records")}
    prediction_position_keys = [
        "predicted_first_team_id",
        "predicted_second_team_id",
        "predicted_third_team_id",
        "predicted_fourth_team_id",
    ]
    with db_session() as conn:
        conn.execute(text("DELETE FROM score_events WHERE category = 'group'"))
        for row in predictions.to_dict("records"):
            points = 0
            reasons = []
            details = []
            for predicted_position, key in enumerate(prediction_position_keys, start=1):
                team_id = row.get(key)
                if not team_id or team_id not in actual_by_team:
                    continue
                actual_row = actual_by_team[team_id]
                actual_position = actual_row.get("position") or actual_row.get("rank")
                if actual_position and int(actual_position) <= 2 and predicted_position <= 2:
                    points += 3
                    reasons.append("Clasificado correcto (+3).")
                if actual_position and int(actual_position) == predicted_position:
                    points += 2
                    reasons.append("Posición exacta (+2).")
                details.append({"team_id": team_id, "predicted_position": predicted_position, "actual_position": actual_position})
            _insert_score_event(
                conn,
                {
                    "player_id": row.get("player_id"),
                    "group_prediction_id": row.get("id"),
                    "category": "group",
                    "points": points,
                    "reason": " ".join(reasons) or "Sin puntos.",
                    "reason_json": {"teams": details},
                },
            )


def _tournament_value(rows: list[dict], keys: set[str]) -> Any:
    for row in rows:
        key = str(row.get("key") or row.get("result_key") or row.get("type") or "").lower()
        if key in keys:
            return row.get("team_id") or row.get("player_name") or row.get("value")
    return None


def recalculate_special_scores() -> None:
    rows = fetch_df("SELECT * FROM tournament_results").to_dict("records")
    predictions = fetch_df("SELECT * FROM special_predictions").to_dict("records")
    if not rows or not predictions:
        return

    result = rows[0]
    champion = result.get("champion_team_id") or _tournament_value(rows, {"champion", "campeon", "campeón"})
    runner_up = result.get("runner_up_team_id") or _tournament_value(rows, {"runner_up", "subcampeon", "subcampeón"})
    top_scorer = result.get("top_scorer_name") or _tournament_value(rows, {"top_scorer", "goleador"})
    mvp = result.get("mvp_name") or _tournament_value(rows, {"mvp"})
    semifinalists = {
        result.get("semifinalist_1_team_id"),
        result.get("semifinalist_2_team_id"),
        result.get("semifinalist_3_team_id"),
        result.get("semifinalist_4_team_id"),
    }
    semifinalists.update(
        row.get("team_id") or row.get("value")
        for row in rows
        if str(row.get("key") or row.get("result_key") or row.get("type") or "").lower() in {"semifinalist", "semifinalista"}
    )
    semifinalists.discard(None)

    with db_session() as conn:
        conn.execute(text("DELETE FROM score_events WHERE category = 'special'"))
        for prediction in predictions:
            points = 0
            reasons = []
            if prediction.get("champion_team_id") == champion:
                points += 20
                reasons.append("Campeón correcto (+20).")
            if prediction.get("runner_up_team_id") == runner_up:
                points += 12
                reasons.append("Subcampeón correcto (+12).")
            for key in ["semifinalist_1_team_id", "semifinalist_2_team_id", "semifinalist_3_team_id", "semifinalist_4_team_id"]:
                if prediction.get(key) in semifinalists:
                    points += 8
            if points and any(prediction.get(key) in semifinalists for key in ["semifinalist_1_team_id", "semifinalist_2_team_id", "semifinalist_3_team_id", "semifinalist_4_team_id"]):
                reasons.append("Semifinalistas acertados (+8 por equipo).")
            if (prediction.get("top_scorer_name") or prediction.get("top_scorer")) and (prediction.get("top_scorer_name") or prediction.get("top_scorer")) == top_scorer:
                points += 15
                reasons.append("Goleador correcto (+15).")
            if (prediction.get("mvp_name") or prediction.get("mvp")) and (prediction.get("mvp_name") or prediction.get("mvp")) == mvp:
                points += 10
                reasons.append("MVP correcto (+10).")
            _insert_score_event(
                conn,
                {
                    "player_id": prediction.get("player_id"),
                    "special_prediction_id": prediction.get("id"),
                    "category": "special",
                    "points": points,
                    "reason": " ".join(reasons) or "Sin puntos.",
                    "reason_json": prediction,
                },
            )


def recalculate_all_scores() -> None:
    matches = fetch_df("SELECT id FROM matches").to_dict("records")
    for match in matches:
        recalculate_match_scores(int(match["id"]))
    recalculate_group_scores()
    recalculate_special_scores()
