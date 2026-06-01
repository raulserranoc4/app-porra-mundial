import json
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from sqlalchemy import text


GROUP_LETTERS = tuple("ABCDEFGHIJKL")
ROUND_OF_32_MATCH_NUMBERS = tuple(range(73, 89))
THIRD_PLACE_ASSIGNMENT_PATH = (
    Path(__file__).resolve().parent / "data" / "third_place_assignment_2026.json"
)
THIRD_PLACE_WINNER_SLOTS = {"1A", "1B", "1D", "1E", "1G", "1I", "1K", "1L"}

ROUND_OF_32_SLOTS = {
    73: ("2A", "2B"),
    74: ("1E", "third:1E"),
    75: ("1F", "2C"),
    76: ("1C", "2F"),
    77: ("1I", "third:1I"),
    78: ("2E", "2I"),
    79: ("1A", "third:1A"),
    80: ("1L", "third:1L"),
    81: ("1D", "third:1D"),
    82: ("1G", "third:1G"),
    83: ("2K", "2L"),
    84: ("1H", "2J"),
    85: ("1B", "third:1B"),
    86: ("1J", "2H"),
    87: ("1K", "third:1K"),
    88: ("2D", "2G"),
}
KNOCKOUT_BRACKET_STRUCTURE = {
    "round_of_16": {
        89: (("winner", 73), ("winner", 74)),
        90: (("winner", 75), ("winner", 76)),
        91: (("winner", 77), ("winner", 78)),
        92: (("winner", 79), ("winner", 80)),
        93: (("winner", 81), ("winner", 82)),
        94: (("winner", 83), ("winner", 84)),
        95: (("winner", 85), ("winner", 86)),
        96: (("winner", 87), ("winner", 88)),
    },
    "quarter_final": {
        97: (("winner", 89), ("winner", 90)),
        98: (("winner", 91), ("winner", 92)),
        99: (("winner", 93), ("winner", 94)),
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
}
KNOCKOUT_STAGE_ORDER = (
    "round_of_32",
    "round_of_16",
    "quarter_final",
    "semi_final",
    "third_place",
    "final",
)


class BracketProjectionError(Exception):
    pass


class MissingThirdPlaceAssignmentError(BracketProjectionError):
    pass


@dataclass(frozen=True)
class ProjectedBracket:
    tables: dict[str, list[dict]]
    best_thirds: list[dict]
    third_place_key: str
    matches: list[dict]
    alphabetical_tiebreak_used: bool


@lru_cache(maxsize=1)
def load_third_place_assignment_map() -> dict[str, dict[str, str]]:
    """Load and validate the FIFA World Cup 2026 third-place assignment table."""
    try:
        raw_data = json.loads(THIRD_PLACE_ASSIGNMENT_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MissingThirdPlaceAssignmentError(
            f"No existe el archivo de asignaciones: {THIRD_PLACE_ASSIGNMENT_PATH}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise MissingThirdPlaceAssignmentError(
            f"El archivo de asignaciones no contiene JSON válido: {exc}"
        ) from exc

    assignments = raw_data.get("assignments") if isinstance(raw_data, dict) else None
    if not isinstance(assignments, dict):
        raise MissingThirdPlaceAssignmentError(
            "El archivo de asignaciones debe contener un objeto 'assignments'."
        )

    validated = {}
    for combination, assignment in assignments.items():
        if (
            not isinstance(combination, str)
            or len(combination) != 8
            or combination != "".join(sorted(combination))
            or len(set(combination)) != 8
            or not set(combination).issubset(GROUP_LETTERS)
        ):
            raise MissingThirdPlaceAssignmentError(
                f"Combinación de terceros no válida en el JSON: {combination!r}"
            )
        if not isinstance(assignment, dict) or set(assignment) != THIRD_PLACE_WINNER_SLOTS:
            raise MissingThirdPlaceAssignmentError(
                f"Asignación incompleta para la combinación {combination}."
            )
        expected_thirds = {f"3{group_letter}" for group_letter in combination}
        if set(assignment.values()) != expected_thirds:
            raise MissingThirdPlaceAssignmentError(
                f"Asignación de terceros inconsistente para {combination}."
            )
        validated[combination] = dict(assignment)
    return validated


def get_player_group_predictions(session, player_id) -> list[dict]:
    rows = session.execute(
        text(
            """
            SELECT
                m.id AS match_id,
                m.group_letter,
                m.home_team_id,
                m.away_team_id,
                ht.name AS home_team_name,
                at.name AS away_team_name,
                p.predicted_home_score,
                p.predicted_away_score
            FROM matches m
            JOIN teams ht ON ht.id = m.home_team_id
            JOIN teams at ON at.id = m.away_team_id
            LEFT JOIN predictions p
                ON p.match_id = m.id
               AND p.player_id = :player_id
            WHERE m.stage = 'group'
            ORDER BY m.group_letter, m.match_number, m.id
            """
        ),
        {"player_id": player_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def get_player_group_match_predictions(session, player_id) -> list[dict]:
    """Backward-compatible alias used by previous integrations."""
    return get_player_group_predictions(session, player_id)


def _empty_team(team_id, name: str, group_letter: str) -> dict:
    return {
        "team_id": team_id,
        "name": name,
        "group_letter": group_letter,
        "played": 0,
        "won": 0,
        "drawn": 0,
        "lost": 0,
        "goals_for": 0,
        "goals_against": 0,
        "goal_difference": 0,
        "points": 0,
    }


def _prediction_for_match(player_predictions, match_id):
    if isinstance(player_predictions, dict):
        return player_predictions.get(match_id)
    return next(
        (
            prediction
            for prediction in player_predictions
            if prediction.get("match_id") == match_id
        ),
        None,
    )


def rank_group_table(group_table: Iterable[dict]) -> tuple[list[dict], bool]:
    ranked = sorted(
        (dict(row) for row in group_table),
        key=lambda row: (
            -int(row["points"]),
            -int(row["goal_difference"]),
            -int(row["goals_for"]),
            str(row["name"]),
        ),
    )
    alphabetical_tiebreak_used = any(
        (left["points"], left["goal_difference"], left["goals_for"])
        == (right["points"], right["goal_difference"], right["goals_for"])
        for left, right in zip(ranked, ranked[1:])
    )
    for position, row in enumerate(ranked, start=1):
        row["position"] = position
        row["slot"] = f"{position}{row['group_letter']}"
    return ranked, alphabetical_tiebreak_used


def calculate_projected_group_tables(
    group_matches: Iterable[dict],
    player_predictions: Iterable[dict] | dict,
) -> tuple[dict[str, list[dict]], bool]:
    teams_by_group = defaultdict(dict)
    for match in group_matches:
        group_letter = match["group_letter"]
        teams_by_group[group_letter].setdefault(
            match["home_team_id"],
            _empty_team(match["home_team_id"], match["home_team_name"], group_letter),
        )
        teams_by_group[group_letter].setdefault(
            match["away_team_id"],
            _empty_team(match["away_team_id"], match["away_team_name"], group_letter),
        )
        prediction = _prediction_for_match(player_predictions, match["match_id"])
        if not prediction:
            continue
        home_score = prediction.get("predicted_home_score")
        away_score = prediction.get("predicted_away_score")
        if home_score is None or away_score is None:
            continue

        home = teams_by_group[group_letter][match["home_team_id"]]
        away = teams_by_group[group_letter][match["away_team_id"]]
        home["played"] += 1
        away["played"] += 1
        home["goals_for"] += int(home_score)
        home["goals_against"] += int(away_score)
        away["goals_for"] += int(away_score)
        away["goals_against"] += int(home_score)
        if home_score > away_score:
            home["won"] += 1
            away["lost"] += 1
            home["points"] += 3
        elif away_score > home_score:
            away["won"] += 1
            home["lost"] += 1
            away["points"] += 3
        else:
            home["drawn"] += 1
            away["drawn"] += 1
            home["points"] += 1
            away["points"] += 1

    projected_tables = {}
    alphabetical_tiebreak_used = False
    for group_letter, group_teams in teams_by_group.items():
        for team in group_teams.values():
            team["goal_difference"] = team["goals_for"] - team["goals_against"]
        ranked, used_fallback = rank_group_table(group_teams.values())
        projected_tables[group_letter] = ranked
        alphabetical_tiebreak_used = alphabetical_tiebreak_used or used_fallback
    return projected_tables, alphabetical_tiebreak_used


def calculate_best_third_placed(projected_tables: dict[str, list[dict]]) -> list[dict]:
    third_placed = [
        dict(projected_tables[group_letter][2])
        for group_letter in sorted(projected_tables)
    ]
    return sorted(
        third_placed,
        key=lambda row: (
            -int(row["points"]),
            -int(row["goal_difference"]),
            -int(row["goals_for"]),
            row["group_letter"],
        ),
    )[:8]


def _slot_teams(projected_tables: dict[str, list[dict]]) -> dict[str, dict]:
    return {
        row["slot"]: row
        for rows in projected_tables.values()
        for row in rows
    }


def resolve_third_place_slots(
    projected_tables: dict[str, list[dict]],
) -> tuple[str, dict[str, str]]:
    best_thirds = calculate_best_third_placed(projected_tables)
    third_place_key = "".join(sorted(row["group_letter"] for row in best_thirds))
    assignment = load_third_place_assignment_map().get(third_place_key)
    if not assignment:
        raise MissingThirdPlaceAssignmentError(
            "No se encontró la combinación oficial de mejores terceros para esta "
            "proyección. Revisa data/third_place_assignment_2026.json."
        )
    return third_place_key, dict(assignment)


def resolve_round_of_32_slots(projected_tables: dict[str, list[dict]]) -> dict[str, str]:
    """Backward-compatible helper returning only the slot assignment."""
    _, assignment = resolve_third_place_slots(projected_tables)
    return assignment


def build_projected_round_of_32_matches(projected_tables: dict[str, list[dict]]) -> list[dict]:
    slot_teams = _slot_teams(projected_tables)
    _, third_assignments = resolve_third_place_slots(projected_tables)
    matches = []
    for match_number, (home_slot, away_slot) in ROUND_OF_32_SLOTS.items():
        resolved_away_slot = (
            third_assignments[away_slot.split(":", 1)[1]]
            if away_slot.startswith("third:")
            else away_slot
        )
        matches.append(
            {
                "match_number": match_number,
                "home_slot": home_slot,
                "away_slot": resolved_away_slot,
                "home_team": slot_teams[home_slot],
                "away_team": slot_teams[resolved_away_slot],
            }
        )
    return matches


def get_projected_bracket_for_player(session, player_id) -> ProjectedBracket:
    rows = get_player_group_predictions(session, player_id)
    completed = [
        row
        for row in rows
        if row.get("predicted_home_score") is not None
        and row.get("predicted_away_score") is not None
    ]
    if len(rows) != 72 or len(completed) != 72:
        raise BracketProjectionError(
            "Para generar tus dieciseisavos proyectados necesitas completar todas "
            "las apuestas de fase de grupos."
        )
    projected_tables, alphabetical_tiebreak_used = calculate_projected_group_tables(rows, rows)
    best_thirds = calculate_best_third_placed(projected_tables)
    third_place_key, _ = resolve_third_place_slots(projected_tables)
    matches = build_projected_round_of_32_matches(projected_tables)
    return ProjectedBracket(
        tables=projected_tables,
        best_thirds=best_thirds,
        third_place_key=third_place_key,
        matches=matches,
        alphabetical_tiebreak_used=alphabetical_tiebreak_used,
    )


def get_projected_round_of_32_for_player(session, player_id) -> list[dict]:
    return get_projected_bracket_for_player(session, player_id).matches


def get_prediction_for_match(session, player_id, match_number: int) -> dict | None:
    row = session.execute(
        text(
            """
            SELECT p.*
            FROM predictions p
            JOIN matches m ON m.id = p.match_id
            WHERE p.player_id = :player_id
              AND m.match_number = :match_number
            """
        ),
        {"player_id": player_id, "match_number": match_number},
    ).mappings().first()
    return dict(row) if row else None


def _team_from_projected_match(projected_match: dict, side: str) -> dict | None:
    team_id = projected_match.get(f"{side}_team_id")
    if not team_id:
        return None
    return {
        "team_id": team_id,
        "name": projected_match.get(f"{side}_team_name") or "Por definir",
    }


def get_projected_winner_from_prediction(
    prediction: dict | None,
    projected_match: dict,
) -> tuple[dict | None, str | None]:
    if not prediction or not prediction.get("predicted_advancing_team_id"):
        return None, None
    advancing_team_id = prediction["predicted_advancing_team_id"]
    valid_team_ids = {
        projected_match.get("home_team_id"),
        projected_match.get("away_team_id"),
    }
    if advancing_team_id not in valid_team_ids:
        return (
            None,
            "Esta apuesta guardada ya no coincide con el cruce proyectado actual. "
            "Vuelve a guardarla.",
        )
    home_score = prediction.get("predicted_home_score")
    away_score = prediction.get("predicted_away_score")
    if home_score is not None and away_score is not None:
        is_valid, _ = validate_knockout_prediction(
            home_score=int(home_score),
            away_score=int(away_score),
            home_team_id=projected_match.get("home_team_id"),
            away_team_id=projected_match.get("away_team_id"),
            advancing_team_id=advancing_team_id,
            goes_to_penalties=bool(prediction.get("predicted_goes_to_penalties")),
        )
        if not is_valid:
            return (
                None,
                "Esta apuesta guardada es inconsistente con el marcador. "
                "Corrígela y vuelve a guardar.",
            )
    side = "home" if advancing_team_id == projected_match.get("home_team_id") else "away"
    return _team_from_projected_match(projected_match, side), None


def get_projected_loser_from_prediction(
    prediction: dict | None,
    projected_match: dict,
) -> tuple[dict | None, str | None]:
    winner, warning = get_projected_winner_from_prediction(prediction, projected_match)
    if not winner:
        return None, warning
    side = "away" if winner["team_id"] == projected_match.get("home_team_id") else "home"
    return _team_from_projected_match(projected_match, side), warning


def _projected_match(
    match_number: int,
    stage: str,
    home_source: str,
    away_source: str,
    home_team: dict | None,
    away_team: dict | None,
    prediction: dict | None = None,
    warning: str | None = None,
) -> dict:
    match = {
        "match_number": match_number,
        "stage": stage,
        "home_source": home_source,
        "away_source": away_source,
        "home_team_id": home_team.get("team_id") if home_team else None,
        "home_team_name": home_team.get("name") if home_team else None,
        "away_team_id": away_team.get("team_id") if away_team else None,
        "away_team_name": away_team.get("name") if away_team else None,
        "existing_prediction": prediction,
        "warning": warning,
    }
    match["is_available"] = can_bet_projected_match(match)
    if not match["is_available"]:
        missing_sources = [
            source
            for source, team in ((home_source, home_team), (away_source, away_team))
            if not team
        ]
        match["missing_reason"] = (
            "Pendiente de que apuestes " + " y ".join(missing_sources)
        )
    else:
        match["missing_reason"] = None
    return match


def can_bet_projected_match(projected_match: dict) -> bool:
    return bool(
        projected_match.get("home_team_id")
        and projected_match.get("away_team_id")
    )


def validate_knockout_prediction(
    home_score: int,
    away_score: int,
    home_team_id,
    away_team_id,
    advancing_team_id,
    goes_to_penalties: bool = False,
) -> tuple[bool, str | None]:
    if not home_team_id or not away_team_id:
        return False, "El cruce proyectado todavía no tiene los dos equipos definidos."
    if advancing_team_id not in {home_team_id, away_team_id}:
        return False, "El equipo que avanza debe pertenecer al cruce proyectado actual."
    if home_score != away_score and goes_to_penalties:
        return False, "Solo puede haber penales si el marcador a 90 minutos es empate."
    if home_score > away_score and advancing_team_id != home_team_id:
        return False, "Con ese marcador solo puede avanzar el equipo local."
    if away_score > home_score and advancing_team_id != away_team_id:
        return False, "Con ese marcador solo puede avanzar el equipo visitante."
    return True, None


def _resolve_source_team(
    source: tuple[str, int],
    matches_by_number: dict[int, dict],
) -> tuple[dict | None, str | None]:
    result_type, source_match_number = source
    source_match = matches_by_number[source_match_number]
    prediction = source_match.get("existing_prediction")
    if result_type == "loser":
        return get_projected_loser_from_prediction(prediction, source_match)
    return get_projected_winner_from_prediction(prediction, source_match)


def build_projected_knockout_from_round_of_32(
    round_of_32: list[dict],
    predictions: dict[int, dict | None],
) -> dict[str, list[dict]]:
    bracket = {stage: [] for stage in KNOCKOUT_STAGE_ORDER}
    matches_by_number = {}

    for row in round_of_32:
        match_number = row["match_number"]
        home_team = {
            "team_id": row["home_team"]["team_id"],
            "name": row["home_team"]["name"],
        }
        away_team = {
            "team_id": row["away_team"]["team_id"],
            "name": row["away_team"]["name"],
        }
        match = _projected_match(
            match_number=match_number,
            stage="round_of_32",
            home_source=row["home_slot"],
            away_source=row["away_slot"],
            home_team=home_team,
            away_team=away_team,
            prediction=predictions.get(match_number),
        )
        _, warning = get_projected_winner_from_prediction(
            predictions.get(match_number),
            match,
        )
        match["warning"] = warning
        bracket["round_of_32"].append(match)
        matches_by_number[match_number] = match

    for stage in KNOCKOUT_STAGE_ORDER[1:]:
        for match_number, (home_source, away_source) in KNOCKOUT_BRACKET_STRUCTURE[stage].items():
            home_team, home_warning = _resolve_source_team(home_source, matches_by_number)
            away_team, away_warning = _resolve_source_team(away_source, matches_by_number)
            home_label = f"{'Perdedor' if home_source[0] == 'loser' else 'Ganador'} partido {home_source[1]}"
            away_label = f"{'Perdedor' if away_source[0] == 'loser' else 'Ganador'} partido {away_source[1]}"
            match = _projected_match(
                match_number=match_number,
                stage=stage,
                home_source=home_label,
                away_source=away_label,
                home_team=home_team,
                away_team=away_team,
                prediction=predictions.get(match_number),
                warning=home_warning or away_warning,
            )
            _, current_warning = get_projected_winner_from_prediction(
                predictions.get(match_number),
                match,
            )
            match["warning"] = match["warning"] or current_warning
            bracket[stage].append(match)
            matches_by_number[match_number] = match
    return bracket


def build_full_projected_knockout_bracket(session, player_id) -> dict[str, list[dict]]:
    round_of_32 = get_projected_round_of_32_for_player(session, player_id)
    predictions = {
        match_number: get_prediction_for_match(session, player_id, match_number)
        for match_number in range(73, 105)
    }
    return build_projected_knockout_from_round_of_32(round_of_32, predictions)


def save_knockout_round_predictions(
    session,
    player_id,
    round_name: str,
    projected_matches_payload: list[dict],
) -> dict:
    from db import predictions_are_open

    if not predictions_are_open():
        raise BracketProjectionError("Las apuestas están cerradas.")
    if round_name not in KNOCKOUT_STAGE_ORDER:
        raise BracketProjectionError(f"Ronda eliminatoria no válida: {round_name}.")
    if not projected_matches_payload:
        return {
            "guardadas": 0,
            "actualizadas": 0,
            "errores": ["No hay partidos disponibles para guardar en esta ronda."],
        }

    bracket = build_full_projected_knockout_bracket(session, player_id)
    projected_by_number = {
        match["match_number"]: match
        for match in bracket[round_name]
        if can_bet_projected_match(match)
    }
    errors = []
    validated = []
    seen_match_numbers = set()
    for payload in projected_matches_payload:
        match_number = payload.get("match_number")
        projected_match = projected_by_number.get(match_number)
        if match_number in seen_match_numbers:
            errors.append(f"Match {match_number}: el partido está repetido en el formulario.")
            continue
        seen_match_numbers.add(match_number)
        if not projected_match:
            errors.append(f"Match {match_number}: el partido todavía no está disponible en esta ronda.")
            continue

        home_score = payload.get("predicted_home_score")
        away_score = payload.get("predicted_away_score")
        advancing_team_id = payload.get("predicted_advancing_team_id")
        goes_to_penalties = bool(payload.get("predicted_goes_to_penalties"))
        if (
            not isinstance(home_score, int)
            or isinstance(home_score, bool)
            or not 0 <= home_score <= 30
            or not isinstance(away_score, int)
            or isinstance(away_score, bool)
            or not 0 <= away_score <= 30
        ):
            errors.append(f"Match {match_number}: los marcadores deben ser enteros entre 0 y 30.")
            continue
        is_valid, error_message = validate_knockout_prediction(
            home_score=home_score,
            away_score=away_score,
            home_team_id=projected_match["home_team_id"],
            away_team_id=projected_match["away_team_id"],
            advancing_team_id=advancing_team_id,
            goes_to_penalties=goes_to_penalties,
        )
        if not is_valid:
            errors.append(f"Match {match_number}: {error_message}")
            continue
        validated.append(
            {
                "match_number": match_number,
                "predicted_home_score": home_score,
                "predicted_away_score": away_score,
                "predicted_advancing_team_id": advancing_team_id,
                "predicted_goes_to_penalties": goes_to_penalties,
            }
        )

    if errors:
        return {"guardadas": 0, "actualizadas": 0, "errores": errors}

    match_numbers = [payload["match_number"] for payload in validated]
    stored_matches = session.execute(
        text(
            """
            SELECT id, match_number
            FROM matches
            WHERE match_number = ANY(:match_numbers)
            """
        ),
        {"match_numbers": match_numbers},
    ).mappings().all()
    match_ids_by_number = {row["match_number"]: row["id"] for row in stored_matches}
    missing_numbers = sorted(set(match_numbers) - set(match_ids_by_number))
    if missing_numbers:
        return {
            "guardadas": 0,
            "actualizadas": 0,
            "errores": [
                f"Match {match_number}: no existe el placeholder en matches."
                for match_number in missing_numbers
            ],
        }

    existing_rows = session.execute(
        text(
            """
            SELECT match_id
            FROM predictions
            WHERE player_id = :player_id
              AND match_id = ANY(:match_ids)
            """
        ),
        {
            "player_id": player_id,
            "match_ids": list(match_ids_by_number.values()),
        },
    ).mappings().all()
    existing_match_ids = {row["match_id"] for row in existing_rows}
    inserted = 0
    updated = 0
    for payload in validated:
        match_id = match_ids_by_number[payload["match_number"]]
        values = {
            "player_id": player_id,
            "match_id": match_id,
            "predicted_home_score": payload["predicted_home_score"],
            "predicted_away_score": payload["predicted_away_score"],
            "predicted_advancing_team_id": payload["predicted_advancing_team_id"],
            "predicted_goes_to_penalties": payload["predicted_goes_to_penalties"],
        }
        if match_id in existing_match_ids:
            session.execute(
                text(
                    """
                    UPDATE predictions
                    SET predicted_home_score = :predicted_home_score,
                        predicted_away_score = :predicted_away_score,
                        predicted_advancing_team_id = :predicted_advancing_team_id,
                        predicted_goes_to_penalties = :predicted_goes_to_penalties
                    WHERE player_id = :player_id
                      AND match_id = :match_id
                    """
                ),
                values,
            )
            updated += 1
        else:
            session.execute(
                text(
                    """
                    INSERT INTO predictions (
                        player_id,
                        match_id,
                        predicted_home_score,
                        predicted_away_score,
                        predicted_advancing_team_id,
                        predicted_goes_to_penalties
                    )
                    VALUES (
                        :player_id,
                        :match_id,
                        :predicted_home_score,
                        :predicted_away_score,
                        :predicted_advancing_team_id,
                        :predicted_goes_to_penalties
                    )
                    """
                ),
                values,
            )
            inserted += 1
    return {"guardadas": inserted, "actualizadas": updated, "errores": []}


def save_knockout_prediction(
    session,
    player_id,
    match_number: int,
    home_score: int,
    away_score: int,
    advancing_team_id,
    goes_to_penalties: bool,
) -> None:
    bracket = build_full_projected_knockout_bracket(session, player_id)
    projected_match = next(
        (
            match
            for matches in bracket.values()
            for match in matches
            if match["match_number"] == match_number
        ),
        None,
    )
    if not projected_match or not can_bet_projected_match(projected_match):
        raise BracketProjectionError("El partido proyectado todavía no está disponible.")
    result = save_knockout_round_predictions(
        session,
        player_id=player_id,
        round_name=projected_match["stage"],
        projected_matches_payload=[
            {
                "match_number": match_number,
                "predicted_home_score": int(home_score),
                "predicted_away_score": int(away_score),
                "predicted_advancing_team_id": advancing_team_id,
                "predicted_goes_to_penalties": bool(goes_to_penalties),
            }
        ],
    )
    if result["errores"]:
        raise BracketProjectionError(result["errores"][0])
