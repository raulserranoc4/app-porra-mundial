from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from bracket import (
    GROUP_LETTERS,
    KNOCKOUT_BRACKET_STRUCTURE,
    ROUND_OF_32_SLOTS,
    load_third_place_assignment_map,
    rank_group_table,
)
from db import db_session, insert_dynamic, table_columns, update_dynamic


GROUP_MATCH_COUNT = 72
ROUND_RANGES = {
    "round_of_32": range(73, 89),
    "round_of_16": range(89, 97),
    "quarter_final": range(97, 101),
    "semi_final": range(101, 103),
    "third_place": range(103, 104),
    "final": range(104, 105),
}


class RealTournamentError(ValueError):
    pass


def _stage(match: dict) -> str:
    return str(match.get("stage") or match.get("phase") or match.get("display_stage") or "").lower()


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    if value == "":
        return None
    if isinstance(value, bool):
        raise RealTournamentError("Los marcadores deben ser numeros enteros.")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise RealTournamentError("Los marcadores deben ser numeros enteros.") from exc
    if number < 0:
        raise RealTournamentError("Los marcadores no pueden ser negativos.")
    return number


def winner_team_id_from_score(match: dict, home_score: int | None, away_score: int | None):
    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return match.get("home_team_id")
    if away_score > home_score:
        return match.get("away_team_id")
    return None


def loser_team_id(match: dict, advancing_team_id):
    if not advancing_team_id:
        return None
    if advancing_team_id == match.get("home_team_id"):
        return match.get("away_team_id")
    if advancing_team_id == match.get("away_team_id"):
        return match.get("home_team_id")
    return None


def validate_real_match_result(
    match: dict,
    status: str,
    home_score,
    away_score,
    home_score_penalties=None,
    away_score_penalties=None,
    advancing_team_id=None,
) -> dict[str, Any]:
    home = _int_or_none(home_score)
    away = _int_or_none(away_score)
    home_pen = _int_or_none(home_score_penalties)
    away_pen = _int_or_none(away_score_penalties)
    if home_pen == 0 and away_pen == 0:
        home_pen = None
        away_pen = None

    if status == "finished" and (home is None or away is None):
        raise RealTournamentError("Si el partido esta finished, debes indicar goles local y visitante.")

    match_stage = _stage(match)
    home_team_id = match.get("home_team_id")
    away_team_id = match.get("away_team_id")
    valid_team_ids = {home_team_id, away_team_id}
    if status == "finished" and (not home_team_id or not away_team_id):
        raise RealTournamentError("No se puede finalizar un partido sin los dos equipos definidos.")

    has_penalties = home_pen is not None or away_pen is not None
    if has_penalties:
        if home is None or away is None or home != away:
            raise RealTournamentError("Solo puede haber penales si el marcador del partido es empate.")
        if match_stage == "group":
            raise RealTournamentError("Los partidos de fase de grupos no pueden tener penales.")
        if home_pen is None or away_pen is None or home_pen == away_pen:
            raise RealTournamentError("Si hay penales, ambos marcadores deben existir y no pueden empatar.")

    winner_team_id = winner_team_id_from_score(match, home, away)
    clean_advancing_team_id = advancing_team_id or None
    if match_stage == "group":
        clean_advancing_team_id = None
    elif status == "finished":
        if not clean_advancing_team_id:
            raise RealTournamentError("En eliminatorias finalizadas debes indicar el equipo que avanza.")
        if clean_advancing_team_id not in valid_team_ids:
            raise RealTournamentError("El equipo que avanza debe ser uno de los dos equipos del partido.")
        if winner_team_id and clean_advancing_team_id != winner_team_id:
            raise RealTournamentError("Si no hay empate, debe avanzar el ganador del marcador.")
        if has_penalties:
            penalty_winner = home_team_id if home_pen > away_pen else away_team_id
            if clean_advancing_team_id != penalty_winner:
                raise RealTournamentError("El equipo que avanza debe coincidir con el ganador por penales.")
    elif clean_advancing_team_id and clean_advancing_team_id not in valid_team_ids:
        raise RealTournamentError("El equipo que avanza debe ser uno de los dos equipos del partido.")

    return {
        "status": status,
        "home_score": home,
        "away_score": away,
        "home_score_penalties": home_pen,
        "away_score_penalties": away_pen,
        "winner_team_id": winner_team_id,
        "advancing_team_id": clean_advancing_team_id,
        "source": "manual",
        "source_updated_at": datetime.now(timezone.utc),
    }


def calculate_real_group_standings_from_matches(matches: list[dict]) -> dict[str, list[dict]]:
    teams_by_group: dict[str, dict[Any, dict]] = defaultdict(dict)
    for match in matches:
        group_letter = str(match.get("group_letter") or "").strip()
        if not group_letter:
            continue
        for side in ("home", "away"):
            team_id = match.get(f"{side}_team_id")
            if not team_id:
                continue
            teams_by_group[group_letter].setdefault(
                team_id,
                {
                    "team_id": team_id,
                    "name": match.get(f"{side}_team_name") or str(team_id),
                    "group_letter": group_letter,
                    "played": 0,
                    "won": 0,
                    "drawn": 0,
                    "lost": 0,
                    "goals_for": 0,
                    "goals_against": 0,
                    "goal_difference": 0,
                    "points": 0,
                    "qualified": False,
                    "qualified_as": None,
                },
            )

        if match.get("status") != "finished":
            continue
        home_score = match.get("home_score")
        away_score = match.get("away_score")
        if home_score is None or away_score is None:
            continue
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        if home_id not in teams_by_group[group_letter] or away_id not in teams_by_group[group_letter]:
            continue

        home = teams_by_group[group_letter][home_id]
        away = teams_by_group[group_letter][away_id]
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

    tables = {}
    for group_letter, teams in teams_by_group.items():
        for team in teams.values():
            team["goal_difference"] = team["goals_for"] - team["goals_against"]
        ranked, _ = rank_group_table(teams.values())
        tables[group_letter] = ranked
    return mark_real_group_qualifiers(tables)


def best_third_placed_from_tables(tables: dict[str, list[dict]]) -> list[dict]:
    third_placed = [
        dict(rows[2])
        for group_letter, rows in sorted(tables.items())
        if group_letter in GROUP_LETTERS and len(rows) >= 3
    ]
    return sorted(
        third_placed,
        key=lambda row: (
            -int(row["points"]),
            -int(row["goal_difference"]),
            -int(row["goals_for"]),
            str(row["group_letter"]),
        ),
    )[:8]


def mark_real_group_qualifiers(tables: dict[str, list[dict]]) -> dict[str, list[dict]]:
    best_third_ids = {row["team_id"] for row in best_third_placed_from_tables(tables)}
    marked = {}
    for group_letter, rows in tables.items():
        marked[group_letter] = []
        for row in rows:
            row = dict(row)
            if row.get("position") == 1:
                row["qualified"] = True
                row["qualified_as"] = "1st"
            elif row.get("position") == 2:
                row["qualified"] = True
                row["qualified_as"] = "2nd"
            elif row.get("position") == 3 and row.get("team_id") in best_third_ids:
                row["qualified"] = True
                row["qualified_as"] = "best_third"
            else:
                row["qualified"] = False
                row["qualified_as"] = None
            marked[group_letter].append(row)
    return marked


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _upsert_group_standing(conn, row: dict) -> None:
    columns = table_columns("group_standings")
    values = {
        "group_letter": row.get("group_letter"),
        "team_id": row.get("team_id"),
        "position": row.get("position"),
        "played": row.get("played", 0),
        "won": row.get("won", 0),
        "drawn": row.get("drawn", 0),
        "lost": row.get("lost", 0),
        "goals_for": row.get("goals_for", 0),
        "goals_against": row.get("goals_against", 0),
        "goal_difference": row.get("goal_difference", 0),
        "points": row.get("points", 0),
        "qualified": row.get("qualified", False),
        "qualified_as": row.get("qualified_as"),
        "source": "manual",
        "source_updated_at": datetime.now(timezone.utc),
    }
    filtered = {key: value for key, value in values.items() if key in columns}
    names = ", ".join(_quote(key) for key in filtered)
    binds = ", ".join(f":{key}" for key in filtered)
    updates = ", ".join(
        f"{_quote(key)} = EXCLUDED.{_quote(key)}"
        for key in filtered
        if key not in {"group_letter", "team_id"}
    )
    conn.execute(
        text(
            f"""
            INSERT INTO group_standings ({names})
            VALUES ({binds})
            ON CONFLICT (group_letter, team_id)
            DO UPDATE SET {updates}
            """
        ),
        filtered,
    )


def _load_group_match_rows(conn) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT
                m.match_number,
                m.group_letter,
                m.status,
                m.home_team_id,
                m.away_team_id,
                ht.name AS home_team_name,
                at.name AS away_team_name,
                m.home_score,
                m.away_score
            FROM matches m
            LEFT JOIN teams ht ON ht.id = m.home_team_id
            LEFT JOIN teams at ON at.id = m.away_team_id
            WHERE m.stage = 'group'
            ORDER BY m.group_letter, m.match_number, m.id
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def _recalculate_real_group_standings(conn) -> dict[str, Any]:
    tables = calculate_real_group_standings_from_matches(_load_group_match_rows(conn))
    groups = sorted(tables)
    if groups:
        conn.execute(
            text("DELETE FROM group_standings WHERE group_letter = ANY(:groups)"),
            {"groups": groups},
        )
    updated = 0
    for group_rows in tables.values():
        for row in group_rows:
            _upsert_group_standing(conn, row)
            updated += 1
    return {"updated": updated, "groups": len(tables)}


def recalculate_real_group_standings() -> dict[str, Any]:
    with db_session() as conn:
        return _recalculate_real_group_standings(conn)


def _group_standings_tables(conn) -> dict[str, list[dict]]:
    rows = conn.execute(
        text(
            """
            SELECT gs.*, t.name
            FROM group_standings gs
            JOIN teams t ON t.id = gs.team_id
            ORDER BY gs.group_letter, gs.position, t.name
            """
        )
    ).mappings().all()
    tables: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        item = dict(row)
        item["slot"] = f"{item.get('position')}{item.get('group_letter')}"
        tables[str(item["group_letter"])].append(item)
    return dict(tables)


def _slot_teams_from_standings(tables: dict[str, list[dict]]) -> dict[str, dict]:
    return {row["slot"]: row for rows in tables.values() for row in rows if row.get("slot")}


def build_real_round_of_32_match_updates(tables: dict[str, list[dict]]) -> tuple[str, dict[int, tuple[Any, Any]]]:
    best_thirds = best_third_placed_from_tables(tables)
    third_place_key = "".join(sorted(row["group_letter"] for row in best_thirds))
    assignment = load_third_place_assignment_map().get(third_place_key)
    if not assignment:
        raise RealTournamentError(
            f"No existe asignacion oficial de mejores terceros para la clave {third_place_key}."
        )
    slot_teams = _slot_teams_from_standings(tables)
    updates = {}
    for match_number, (home_slot, away_slot) in ROUND_OF_32_SLOTS.items():
        resolved_away_slot = assignment[away_slot.split(":", 1)[1]] if away_slot.startswith("third:") else away_slot
        home_team = slot_teams.get(home_slot)
        away_team = slot_teams.get(resolved_away_slot)
        if not home_team or not away_team:
            raise RealTournamentError(f"No se pudo resolver el cruce real del partido {match_number}.")
        updates[match_number] = (home_team["team_id"], away_team["team_id"])
    return third_place_key, updates


def _missing_finished_group_matches(conn) -> int:
    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS finished_count
            FROM matches
            WHERE stage = 'group'
              AND status = 'finished'
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
            """
        )
    ).mappings().first()
    return max(GROUP_MATCH_COUNT - int(row["finished_count"]), 0)


def update_real_round_of_32_from_group_standings() -> dict[str, Any]:
    with db_session() as conn:
        missing = _missing_finished_group_matches(conn)
        if missing:
            raise RealTournamentError(f"Faltan {missing} partidos de fase de grupos por finalizar.")
        standings_result = _recalculate_real_group_standings(conn)
        tables = _group_standings_tables(conn)
        if len(tables) < 12 or any(len(rows) < 4 for rows in tables.values()):
            raise RealTournamentError("Las clasificaciones de grupos no estan completas.")
        third_place_key, updates = build_real_round_of_32_match_updates(tables)
        updated = 0
        for match_number, (home_team_id, away_team_id) in updates.items():
            update_dynamic(
                conn,
                "matches",
                {
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "source": "manual",
                    "source_updated_at": datetime.now(timezone.utc),
                },
                "match_number = :match_number",
                {"match_number": match_number},
            )
            updated += 1
    return {
        "updated": updated,
        "third_place_key": third_place_key,
        "standings_updated": standings_result["updated"],
        "standings_groups": standings_result["groups"],
    }


def _matches_by_number(conn, start: int = 73, end: int = 104) -> dict[int, dict]:
    rows = conn.execute(
        text(
            """
            SELECT *
            FROM matches
            WHERE match_number BETWEEN :start AND :end
            ORDER BY match_number
            """
        ),
        {"start": start, "end": end},
    ).mappings().all()
    return {int(row["match_number"]): dict(row) for row in rows}


def _source_team_id(source: tuple[str, int], matches: dict[int, dict]):
    source_type, match_number = source
    match = matches.get(match_number)
    if not match or match.get("status") != "finished" or not match.get("advancing_team_id"):
        return None
    if source_type == "winner":
        return match["advancing_team_id"]
    return loser_team_id(match, match["advancing_team_id"])


def build_real_knockout_next_round_updates(matches: dict[int, dict]) -> tuple[dict[int, tuple[Any, Any]], list[int]]:
    updates = {}
    working_matches = {number: dict(match) for number, match in matches.items()}
    missing_sources = []
    for _stage_name, targets in KNOCKOUT_BRACKET_STRUCTURE.items():
        for match_number, (home_source, away_source) in targets.items():
            home_team_id = _source_team_id(home_source, working_matches)
            away_team_id = _source_team_id(away_source, working_matches)
            if not home_team_id or not away_team_id:
                missing_sources.append(match_number)
                continue
            updates[match_number] = (home_team_id, away_team_id)
            working_matches[match_number] = working_matches.get(match_number, {}) | {
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
            }
    return updates, sorted(set(missing_sources))


def update_real_knockout_next_rounds() -> dict[str, Any]:
    with db_session() as conn:
        matches = _matches_by_number(conn)
        updates, missing_sources = build_real_knockout_next_round_updates(matches)
        updated = 0
        for match_number, (home_team_id, away_team_id) in updates.items():
            update_dynamic(
                conn,
                "matches",
                {
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "source": "manual",
                    "source_updated_at": datetime.now(timezone.utc),
                },
                "match_number = :match_number",
                {"match_number": match_number},
            )
            updated += 1
    return {"updated": updated, "missing_sources": missing_sources}


def _upsert_tournament_results(conn, payload: dict) -> None:
    rows = conn.execute(text("SELECT id FROM tournament_results ORDER BY created_at, id LIMIT 1")).mappings().all()
    if rows:
        update_dynamic(conn, "tournament_results", payload, "id = :id", {"id": rows[0]["id"]})
    else:
        insert_dynamic(conn, "tournament_results", payload | {"singleton": True})


def build_tournament_results_payload_from_matches(matches: dict[int, dict]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    semifinalists = []
    for match_number in (101, 102):
        match = matches.get(match_number) or {}
        for team_key in ("home_team_id", "away_team_id"):
            if match.get(team_key):
                semifinalists.append(match[team_key])
    for index, team_id in enumerate(semifinalists[:4], start=1):
        payload[f"semifinalist_{index}_team_id"] = team_id

    final = matches.get(104) or {}
    if final.get("status") == "finished" and final.get("advancing_team_id"):
        payload["champion_team_id"] = final["advancing_team_id"]
        payload["runner_up_team_id"] = loser_team_id(final, final["advancing_team_id"])
    return payload


def update_tournament_results_from_real_knockout() -> dict[str, Any]:
    with db_session() as conn:
        matches = _matches_by_number(conn, 101, 104)
        payload = build_tournament_results_payload_from_matches(matches)
        payload.update({"source": "manual", "source_updated_at": datetime.now(timezone.utc)})
        _upsert_tournament_results(conn, payload)
    return {"updated_fields": sorted(payload)}


def _count_range(conn, numbers: range) -> dict[str, int]:
    row = conn.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE home_team_id IS NOT NULL AND away_team_id IS NOT NULL) AS defined_count,
                COUNT(*) FILTER (WHERE status = 'finished') AS finished_count
            FROM matches
            WHERE match_number BETWEEN :start AND :end
            """
        ),
        {"start": min(numbers), "end": max(numbers)},
    ).mappings().first()
    return {
        "defined": int(row["defined_count"] or 0),
        "finished": int(row["finished_count"] or 0),
        "total": len(list(numbers)),
    }


def get_tournament_diagnostics() -> dict[str, Any]:
    with db_session() as conn:
        group_finished = GROUP_MATCH_COUNT - _missing_finished_group_matches(conn)
        diagnostics = {"group_matches_finished": group_finished, "group_matches_total": GROUP_MATCH_COUNT}
        for key, numbers in ROUND_RANGES.items():
            diagnostics[key] = _count_range(conn, numbers)
        standings_row = conn.execute(text("SELECT COUNT(*) AS total FROM group_standings")).mappings().first()
        score_row = conn.execute(text("SELECT COUNT(*) AS total FROM score_events")).mappings().first()
        try:
            leaderboard_row = conn.execute(text("SELECT COUNT(*) AS total FROM leaderboard")).mappings().first()
            leaderboard_generated = leaderboard_row is not None
        except Exception:
            leaderboard_generated = False
        diagnostics["group_standings_updated"] = int(standings_row["total"] or 0) >= 48
        diagnostics["score_events_total"] = int(score_row["total"] or 0)
        diagnostics["leaderboard_generated"] = leaderboard_generated
    return diagnostics
