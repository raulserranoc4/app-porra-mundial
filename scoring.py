import json
import os
import re
from inspect import signature
from typing import Any

from sqlalchemy import text

from bracket import calculate_projected_group_tables, get_player_group_predictions
from db import db_session, fetch_df, insert_dynamic, table_columns

try:
    from derived_predictions import sync_derived_special_predictions
except ImportError:  # pragma: no cover - keeps legacy/script use resilient.
    sync_derived_special_predictions = None


MATCH_FLAG_KEYS = (
    "exact_score",
    "correct_result",
    "correct_goal_difference",
    "correct_home_goals",
    "correct_away_goals",
    "correct_advancing_team",
    "correct_penalties",
    "knockout_matchup_matches",
    "knockout_matchup_reversed",
    "knockout_score_points_allowed",
    "advancement_points_allowed",
    "advanced_team_in_stage",
    "advancement_scored_by_stage",
)

KNOCKOUT_STAGE_MATCH_NUMBERS = {
    "round_of_32": tuple(range(73, 89)),
    "round_of_16": tuple(range(89, 97)),
    "quarter_final": tuple(range(97, 101)),
    "semi_final": tuple(range(101, 103)),
    "third_place": (103,),
    "final": (104,),
}


def get_knockout_stage_match_numbers(stage: str) -> tuple[int, ...]:
    normalized_stage = str(stage or "").strip().lower()
    if normalized_stage not in KNOCKOUT_STAGE_MATCH_NUMBERS:
        raise ValueError(f"Fase eliminatoria no soportada: {stage!r}.")
    return KNOCKOUT_STAGE_MATCH_NUMBERS[normalized_stage]


def _knockout_stage_for_match(match: dict) -> str:
    stage = str(match.get("stage") or match.get("phase") or "").strip().lower()
    if stage in KNOCKOUT_STAGE_MATCH_NUMBERS:
        return stage
    match_number = match.get("match_number")
    if match_number is not None:
        for stage_name, match_numbers in KNOCKOUT_STAGE_MATCH_NUMBERS.items():
            if int(match_number) in match_numbers:
                return stage_name
    raise ValueError(f"No se pudo determinar la ronda eliminatoria del partido {match.get('id')!r}.")


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


def _match_details(prediction: dict, match: dict, flags: dict[str, bool]) -> dict[str, Any]:
    predicted_home_team_id = prediction.get("predicted_home_team_id")
    predicted_away_team_id = prediction.get("predicted_away_team_id")
    real_home_team_id = match.get("home_team_id")
    real_away_team_id = match.get("away_team_id")
    return {
        **flags,
        "predicted_home_team_id": predicted_home_team_id,
        "predicted_away_team_id": predicted_away_team_id,
        "real_home_team_id": real_home_team_id,
        "real_away_team_id": real_away_team_id,
        "predicted_matchup": [predicted_home_team_id, predicted_away_team_id],
        "real_matchup": [real_home_team_id, real_away_team_id],
        "prediction": {
            "home": prediction.get("predicted_home_score"),
            "away": prediction.get("predicted_away_score"),
            "advancing_team_id": prediction.get("predicted_advancing_team_id"),
            "goes_to_penalties": prediction.get("predicted_goes_to_penalties"),
        },
        "match": {
            "home": match.get("home_score"),
            "away": match.get("away_score"),
            "advancing_team_id": match.get("advancing_team_id"),
            "has_penalties": _has_penalties(match),
        },
    }


def _allow_legacy_knockout_scoring() -> bool:
    return os.getenv("ALLOW_LEGACY_KNOCKOUT_SCORING", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "si",
        "sí",
    }


def calculate_match_prediction_points(
    prediction: dict,
    match: dict,
    *,
    advanced_team_in_stage: bool | None = None,
    advancement_points_allowed: bool = True,
    advancement_scored_by_stage: bool = False,
) -> tuple[int, list[str], dict[str, Any]]:
    ph = prediction.get("predicted_home_score")
    pa = prediction.get("predicted_away_score")
    ah = match.get("home_score")
    aa = match.get("away_score")
    points = 0
    reasons: list[str] = []
    flags = {key: False for key in MATCH_FLAG_KEYS}
    knockout = _is_knockout(match)
    score_points_allowed = True
    match_status = str(match.get("status") or "").strip().lower()

    # Marcadores provisionales o valores 0-0 guardados en partidos programados
    # nunca deben considerarse resultados reales.
    if match_status and match_status != "finished":
        score_points_allowed = False
        reasons.append("Partido todavía no finalizado: no puntúa marcador.")

    if knockout:
        predicted_home_team_id = prediction.get("predicted_home_team_id")
        predicted_away_team_id = prediction.get("predicted_away_team_id")
        real_home_team_id = match.get("home_team_id")
        real_away_team_id = match.get("away_team_id")
        has_snapshot = bool(predicted_home_team_id and predicted_away_team_id)

        if not has_snapshot and not _allow_legacy_knockout_scoring():
            score_points_allowed = False
            reasons.append("Apuesta antigua sin snapshot de cruce; no se puede validar el marcador.")
        if has_snapshot:
            flags["knockout_matchup_matches"] = bool(
                predicted_home_team_id == real_home_team_id
                and predicted_away_team_id == real_away_team_id
            )
            flags["knockout_matchup_reversed"] = bool(
                predicted_home_team_id == real_away_team_id
                and predicted_away_team_id == real_home_team_id
            )
            if not flags["knockout_matchup_matches"] and not flags["knockout_matchup_reversed"]:
                score_points_allowed = False
                reasons.append("El cruce apostado no coincide con el cruce real: no puntúa marcador.")
            else:
                flags["knockout_matchup_matches"] = True
                if flags["knockout_matchup_reversed"]:
                    ph, pa = pa, ph
        flags["knockout_score_points_allowed"] = score_points_allowed

    if score_points_allowed:
        if ah is None or aa is None:
            reasons.append("Partido sin resultado final.")
        else:
            flags["exact_score"] = ph == ah and pa == aa
            flags["correct_result"] = _result(ph, pa) == _result(ah, aa)
            flags["correct_goal_difference"] = ph is not None and pa is not None and (ph - pa) == (ah - aa)
            flags["correct_home_goals"] = ph == ah
            flags["correct_away_goals"] = pa == aa

            if flags["exact_score"]:
                points += 7
                reasons.append("Marcador exacto (+7).")
            else:
                if flags["correct_result"]:
                    points += 3
                    reasons.append("Signo correcto (+3).")
                if flags["correct_goal_difference"]:
                    points += 2
                    reasons.append("Diferencia correcta (+2).")
                if flags["correct_home_goals"]:
                    points += 1
                    reasons.append("Goles local correctos (+1).")
                if flags["correct_away_goals"]:
                    points += 1
                    reasons.append("Goles visitante correctos (+1).")

    if knockout:
        predicted_advancing_team_id = prediction.get("predicted_advancing_team_id")
        team_advanced = (
            bool(advanced_team_in_stage)
            if advanced_team_in_stage is not None
            else bool(
                predicted_advancing_team_id
                and predicted_advancing_team_id == match.get("advancing_team_id")
            )
        )
        flags["advanced_team_in_stage"] = team_advanced
        flags["advancement_points_allowed"] = bool(predicted_advancing_team_id and advancement_points_allowed)
        flags["correct_advancing_team"] = bool(
            predicted_advancing_team_id
            and team_advanced
            and advancement_points_allowed
        )
        flags["advancement_scored_by_stage"] = bool(
            flags["correct_advancing_team"] and advancement_scored_by_stage
        )
        flags["correct_penalties"] = bool(
            score_points_allowed
            and prediction.get("predicted_goes_to_penalties")
            and _has_penalties(match)
        )
        if flags["correct_advancing_team"]:
            points += 3
            reasons.append("Equipo clasificado a la siguiente ronda correcto (+3).")
        elif predicted_advancing_team_id and advanced_team_in_stage is not None and not team_advanced:
            reasons.append("El equipo elegido no avanzó en esta ronda.")
        elif predicted_advancing_team_id and team_advanced and not advancement_points_allowed:
            reasons.append("Equipo clasificado correcto, ya puntuado en otra apuesta de esta ronda.")
        if flags["correct_penalties"]:
            points += 2
            reasons.append("Penales correctos (+2).")

    return points, reasons or ["Sin puntos."], _match_details(prediction, match, flags)


def _insert_score_event(conn, values: dict) -> None:
    payload = values | {"reason_json": json.dumps(values.get("reason_json", {}), default=str)}
    filtered = {key: value for key, value in payload.items() if key in table_columns("score_events")}
    if filtered:
        insert_dynamic(conn, "score_events", filtered)


def team_advanced_in_stage(conn, team_id, stage: str) -> bool:
    if not team_id:
        return False
    match_numbers = get_knockout_stage_match_numbers(stage)
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM matches
            WHERE status = 'finished'
              AND advancing_team_id = :team_id
              AND match_number BETWEEN :first_match AND :last_match
            LIMIT 1
            """
        ),
        {
            "team_id": team_id,
            "first_match": match_numbers[0],
            "last_match": match_numbers[-1],
        },
    ).first()
    return row is not None


def _claim_advancement_points(
    player_id,
    team_id,
    advanced_team_ids: set,
    scored_advancements: set[tuple],
) -> tuple[bool, bool]:
    team_advanced = bool(team_id and team_id in advanced_team_ids)
    key = (player_id, team_id)
    points_allowed = bool(team_id and (not team_advanced or key not in scored_advancements))
    if team_advanced and points_allowed:
        scored_advancements.add(key)
    return team_advanced, points_allowed


def _insert_match_score_event(conn, prediction: dict, match: dict, **scoring_context) -> None:
    points, reasons, details = calculate_match_prediction_points(
        prediction,
        match,
        **scoring_context,
    )
    _insert_score_event(
        conn,
        {
            "player_id": prediction.get("player_id"),
            "prediction_id": prediction.get("id"),
            "match_id": match.get("id"),
            "category": "match",
            "points": points,
            "reason": " ".join(reasons),
            "reason_json": details,
        },
    )


def recalculate_knockout_stage_scores(stage: str) -> None:
    match_numbers = get_knockout_stage_match_numbers(stage)
    with db_session() as conn:
        matches = [
            dict(row)
            for row in conn.execute(
                text(
                    """
                    SELECT *
                    FROM matches
                    WHERE match_number BETWEEN :first_match AND :last_match
                    ORDER BY match_number
                    """
                ),
                {"first_match": match_numbers[0], "last_match": match_numbers[-1]},
            ).mappings().all()
        ]
        if not matches:
            return
        conn.execute(
            text(
                """
                DELETE FROM score_events
                WHERE category = 'match'
                  AND match_id IN (
                      SELECT id
                      FROM matches
                      WHERE match_number BETWEEN :first_match AND :last_match
                  )
                """
            ),
            {"first_match": match_numbers[0], "last_match": match_numbers[-1]},
        )
        advanced_team_ids = {
            match.get("advancing_team_id")
            for match in matches
            if str(match.get("status") or "").lower() == "finished"
            and match.get("advancing_team_id")
        }
        scored_advancements: set[tuple] = set()
        for match in matches:
            predictions = [
                dict(row)
                for row in conn.execute(
                    text(
                        """
                        SELECT *
                        FROM predictions
                        WHERE match_id = :match_id
                        ORDER BY player_id, id
                        """
                    ),
                    {"match_id": match["id"]},
                ).mappings().all()
            ]
            for prediction in predictions:
                team_advanced, advancement_allowed = _claim_advancement_points(
                    prediction.get("player_id"),
                    prediction.get("predicted_advancing_team_id"),
                    advanced_team_ids,
                    scored_advancements,
                )
                _insert_match_score_event(
                    conn,
                    prediction,
                    match,
                    advanced_team_in_stage=team_advanced,
                    advancement_points_allowed=advancement_allowed,
                    advancement_scored_by_stage=advancement_allowed,
                )


def recalculate_match_scores(match_id) -> None:
    with db_session() as conn:
        match = conn.execute(text("SELECT * FROM matches WHERE id = :id"), {"id": match_id}).mappings().first()
        if not match:
            return
        match = dict(match)

    if _is_knockout(match):
        recalculate_knockout_stage_scores(_knockout_stage_for_match(match))
        return

    with db_session() as conn:
        conn.execute(
            text("DELETE FROM score_events WHERE category = 'match' AND match_id = :match_id"),
            {"match_id": match_id},
        )
        predictions = conn.execute(text("SELECT * FROM predictions WHERE match_id = :match_id"), {"match_id": match_id}).mappings().all()
        for prediction in predictions:
            _insert_match_score_event(conn, dict(prediction), match)


def _actual_group_positions(rows: list[dict]) -> dict:
    positions = {}
    for row in rows:
        group_letter = row.get("group_letter")
        team_id = row.get("team_id")
        actual_position = row.get("position") or row.get("rank")
        if not group_letter or not team_id or actual_position is None:
            continue
        positions.setdefault(group_letter, {})[team_id] = int(actual_position)
    return positions


def calculate_group_prediction_points(projected_rows: list[dict], actual_positions: dict) -> tuple[int, list[str], dict[str, Any]]:
    predicted_positions = {
        row["team_id"]: int(row["position"])
        for row in projected_rows
        if row.get("team_id") and row.get("position") is not None
    }
    actual_positions = {
        team_id: int(position)
        for team_id, position in actual_positions.items()
        if position is not None
    }
    qualified_correct_count = len(
        {
            team_id
            for team_id, predicted_position in predicted_positions.items()
            if predicted_position <= 2 and actual_positions.get(team_id, 99) <= 2
        }
    )
    exact_position_count = len(
        {
            team_id
            for team_id, predicted_position in predicted_positions.items()
            if actual_positions.get(team_id) == predicted_position
        }
    )
    points = qualified_correct_count * 3 + exact_position_count * 2
    reasons = []
    if qualified_correct_count:
        reasons.append(f"Clasificados correctos (+{qualified_correct_count * 3}).")
    if exact_position_count:
        reasons.append(f"Posiciones exactas (+{exact_position_count * 2}).")
    return points, reasons or ["Sin puntos."], {
        "group_letter": projected_rows[0].get("group_letter") if projected_rows else None,
        "predicted_positions": predicted_positions,
        "actual_positions": actual_positions,
        "qualified_correct_count": qualified_correct_count,
        "exact_position_count": exact_position_count,
    }


def _completed_group_letters(group_rows: list[dict]) -> set:
    completed_counts = {}
    for row in group_rows:
        if row.get("predicted_home_score") is None or row.get("predicted_away_score") is None:
            continue
        group_letter = row.get("group_letter")
        if not group_letter:
            continue
        completed_counts[group_letter] = completed_counts.get(group_letter, 0) + 1
    return {group_letter for group_letter, count in completed_counts.items() if count == 6}


def _calculate_projected_tables_for_scoring(group_rows: list[dict], player_id) -> dict[str, list[dict]]:
    try:
        parameters = signature(calculate_projected_group_tables).parameters
        positional_parameters = [
            parameter
            for parameter in parameters.values()
            if parameter.kind
            in {
                parameter.POSITIONAL_ONLY,
                parameter.POSITIONAL_OR_KEYWORD,
            }
            and parameter.default is parameter.empty
        ]
        if len(positional_parameters) <= 1:
            projected_tables, _ = calculate_projected_group_tables(group_rows)
        else:
            projected_tables, _ = calculate_projected_group_tables(group_rows, group_rows)
        return projected_tables
    except Exception as exc:
        raise RuntimeError(
            f"No se pudieron calcular las clasificaciones proyectadas para player_id={player_id}."
        ) from exc


def _insert_legacy_group_scores(conn, actual_rows: list[dict]) -> int:
    # Group predictions are legacy. Group standings in the current UI are derived from match predictions.
    actual_by_team = {row["team_id"]: row for row in actual_rows}
    predictions = conn.execute(text("SELECT * FROM group_predictions")).mappings().all()
    inserted = 0
    if not actual_by_team or not predictions:
        return inserted

    prediction_position_keys = [
        "predicted_first_team_id",
        "predicted_second_team_id",
        "predicted_third_team_id",
        "predicted_fourth_team_id",
    ]
    for row in predictions:
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
                reasons.append("Posicion exacta (+2).")
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
        inserted += 1
    return inserted


def recalculate_derived_group_scores() -> None:
    actual = fetch_df("SELECT * FROM group_standings")
    actual_rows = actual.to_dict("records")
    actual_by_group = _actual_group_positions(actual_rows)
    with db_session() as conn:
        conn.execute(text("DELETE FROM score_events WHERE category = 'group'"))
        player_rows = conn.execute(
            text(
                """
                SELECT DISTINCT p.player_id
                FROM predictions p
                JOIN matches m ON m.id = p.match_id
                WHERE m.stage = 'group'
                """
            )
        ).mappings().all()
        inserted = 0
        for player_row in player_rows:
            player_id = player_row["player_id"]
            group_rows = get_player_group_predictions(conn, player_id)
            completed_groups = _completed_group_letters(group_rows)
            projected_tables = _calculate_projected_tables_for_scoring(group_rows, player_id)
            for group_letter, projected_rows in projected_tables.items():
                if group_letter not in completed_groups or group_letter not in actual_by_group:
                    continue
                points, reasons, details = calculate_group_prediction_points(projected_rows, actual_by_group[group_letter])
                _insert_score_event(
                    conn,
                    {
                        "player_id": player_id,
                        "category": "group",
                        "points": points,
                        "reason": " ".join(reasons) or "Sin puntos.",
                        "reason_json": details,
                    },
                )
                inserted += 1
        if inserted == 0:
            _insert_legacy_group_scores(conn, actual_rows)


def recalculate_group_scores() -> None:
    recalculate_derived_group_scores()


def _tournament_value(rows: list[dict], keys: set[str]) -> Any:
    for row in rows:
        key = str(row.get("key") or row.get("result_key") or row.get("type") or "").lower()
        if key in keys:
            return row.get("team_id") or row.get("player_name") or row.get("value")
    return None


def _normalize_award_name(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _special_result_from_rows(rows: list[dict]) -> tuple[dict, set]:
    result = rows[0] if rows else {}
    champion = result.get("champion_team_id") or _tournament_value(rows, {"champion", "campeon", "campe\u00f3n"})
    runner_up = result.get("runner_up_team_id") or _tournament_value(rows, {"runner_up", "subcampeon", "subcampe\u00f3n"})
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
    return {
        "champion": champion,
        "runner_up": runner_up,
        "top_scorer": top_scorer,
        "mvp": mvp,
    }, semifinalists


def calculate_special_prediction_points(prediction: dict, result: dict, actual_semifinalists: set) -> tuple[int, list[str], dict[str, Any]]:
    predicted_semifinalists = {
        prediction.get("semifinalist_1_team_id"),
        prediction.get("semifinalist_2_team_id"),
        prediction.get("semifinalist_3_team_id"),
        prediction.get("semifinalist_4_team_id"),
    }
    predicted_semifinalists.discard(None)

    predicted_top_scorer = prediction.get("top_scorer_name") or prediction.get("top_scorer")
    predicted_mvp = prediction.get("mvp_name") or prediction.get("mvp")
    champion_correct = bool(prediction.get("champion_team_id") and prediction.get("champion_team_id") == result.get("champion"))
    runner_up_correct = bool(prediction.get("runner_up_team_id") and prediction.get("runner_up_team_id") == result.get("runner_up"))
    semifinalists_correct_count = len(predicted_semifinalists & actual_semifinalists)
    top_scorer_correct = bool(
        _normalize_award_name(predicted_top_scorer)
        and _normalize_award_name(predicted_top_scorer) == _normalize_award_name(result.get("top_scorer"))
    )
    mvp_correct = bool(
        _normalize_award_name(predicted_mvp)
        and _normalize_award_name(predicted_mvp) == _normalize_award_name(result.get("mvp"))
    )

    points = 0
    reasons = []
    if champion_correct:
        points += 20
        reasons.append("Campeon correcto (+20).")
    if runner_up_correct:
        points += 12
        reasons.append("Subcampeon correcto (+12).")
    if semifinalists_correct_count:
        points += semifinalists_correct_count * 8
        reasons.append(f"Semifinalistas acertados (+{semifinalists_correct_count * 8}).")
    if top_scorer_correct:
        points += 15
        reasons.append("Goleador correcto (+15).")
    if mvp_correct:
        points += 10
        reasons.append("MVP correcto (+10).")

    return points, reasons or ["Sin puntos."], {
        "champion_correct": champion_correct,
        "runner_up_correct": runner_up_correct,
        "semifinalists_correct_count": semifinalists_correct_count,
        "top_scorer_correct": top_scorer_correct,
        "mvp_correct": mvp_correct,
    }


def _sync_derived_specials(conn) -> None:
    if sync_derived_special_predictions is None:
        return
    player_rows = conn.execute(text("SELECT DISTINCT player_id FROM predictions")).mappings().all()
    for row in player_rows:
        try:
            sync_derived_special_predictions(conn, row["player_id"])
        except Exception:
            continue


def recalculate_special_scores() -> None:
    rows = fetch_df("SELECT * FROM tournament_results").to_dict("records")
    with db_session() as conn:
        conn.execute(text("DELETE FROM score_events WHERE category = 'special'"))
        if not rows:
            return
        _sync_derived_specials(conn)
        predictions = [dict(row) for row in conn.execute(text("SELECT * FROM special_predictions")).mappings().all()]
        if not predictions:
            return
        result, semifinalists = _special_result_from_rows(rows)
        for prediction in predictions:
            points, reasons, details = calculate_special_prediction_points(prediction, result, semifinalists)
            _insert_score_event(
                conn,
                {
                    "player_id": prediction.get("player_id"),
                    "special_prediction_id": prediction.get("id"),
                    "category": "special",
                    "points": points,
                    "reason": " ".join(reasons) or "Sin puntos.",
                    "reason_json": details,
                },
            )


def recalculate_all_scores() -> None:
    matches = fetch_df("SELECT * FROM matches").to_dict("records")
    knockout_stages = set()
    for match in matches:
        if _is_knockout(match):
            knockout_stages.add(_knockout_stage_for_match(match))
        else:
            recalculate_match_scores(match["id"])
    for stage in KNOCKOUT_STAGE_MATCH_NUMBERS:
        if stage in knockout_stages:
            recalculate_knockout_stage_scores(stage)
    recalculate_group_scores()
    recalculate_special_scores()
