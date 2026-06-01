from collections import defaultdict
from itertools import combinations

from sqlalchemy import text

from db import db_session, get_engine, insert_dynamic, table_columns


def match_stage_column() -> str:
    cols = table_columns("matches")
    if "phase" in cols:
        return "phase"
    if "stage" in cols:
        return "stage"
    raise RuntimeError("La tabla matches no tiene columna phase ni stage.")


def main() -> None:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, name, group_letter
                FROM teams
                WHERE group_letter IS NOT NULL
                ORDER BY group_letter, name
                """
            )
        ).mappings().all()

    if not rows:
        print("No hay equipos con group_letter en teams.")
        return

    teams_by_group = defaultdict(list)
    for row in rows:
        teams_by_group[row["group_letter"]].append(dict(row))

    created = 0
    stage_col = match_stage_column()
    with db_session() as conn:
        for group_letter, group_teams in teams_by_group.items():
            for home, away in combinations(group_teams[:4], 2):
                exists = conn.execute(
                    text(
                        f"""
                        SELECT 1 FROM matches
                        WHERE {stage_col} = 'group'
                          AND group_letter = :group_letter
                          AND home_team_id = :home_team_id
                          AND away_team_id = :away_team_id
                        LIMIT 1
                        """
                    ),
                    {"group_letter": group_letter, "home_team_id": home["id"], "away_team_id": away["id"]},
                ).first()
                if exists:
                    continue
                insert_dynamic(
                    conn,
                    "matches",
                    {
                        stage_col: "group",
                        "group_letter": group_letter,
                        "home_team_id": home["id"],
                        "away_team_id": away["id"],
                        "kickoff_time": None,
                        "status": "scheduled",
                    },
                )
                created += 1
    print(f"Partidos de fase de grupos creados: {created}.")


if __name__ == "__main__":
    main()
