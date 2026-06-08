from sqlalchemy import text

from db import db_session, table_columns


REQUIRED_COLUMNS = {
    "predicted_home_team_id",
    "predicted_away_team_id",
}


def main() -> None:
    missing_columns = REQUIRED_COLUMNS - table_columns("predictions")
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise RuntimeError(
            "Faltan columnas de snapshot en predictions: "
            f"{missing}. Aplica primero la migracion indicada."
        )

    with db_session() as conn:
        result = conn.execute(
            text(
                """
                UPDATE predictions p
                SET predicted_home_team_id = m.home_team_id,
                    predicted_away_team_id = m.away_team_id
                FROM matches m
                WHERE p.match_id = m.id
                  AND m.stage = 'group'
                  AND m.home_team_id IS NOT NULL
                  AND m.away_team_id IS NOT NULL
                  AND (
                      p.predicted_home_team_id IS NULL
                      OR p.predicted_away_team_id IS NULL
                  )
                """
            )
        )
        updated = int(result.rowcount or 0)

    print(f"Snapshots de fase de grupos actualizados: {updated}.")
    print("Las predicciones eliminatorias antiguas no se han modificado.")


if __name__ == "__main__":
    main()
