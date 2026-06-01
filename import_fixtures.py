import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine


REQUIRED_COLUMNS = {
    "match_number",
    "stage",
    "group_letter",
    "home_team",
    "away_team",
    "kickoff_time",
    "venue",
    "city",
    "country",
}


class FixtureImportError(Exception):
    pass


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_match_number(value: str | None, row_number: int) -> int:
    try:
        match_number = int(clean(value) or "")
    except ValueError as exc:
        raise FixtureImportError(f"Fila {row_number}: match_number debe ser un entero.") from exc
    if match_number <= 0:
        raise FixtureImportError(f"Fila {row_number}: match_number debe ser mayor que cero.")
    return match_number


def parse_kickoff_time(value: str | None, row_number: int) -> datetime:
    raw_value = clean(value)
    if not raw_value:
        raise FixtureImportError(f"Fila {row_number}: kickoff_time es obligatorio.")
    try:
        kickoff_time = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FixtureImportError(
            f"Fila {row_number}: kickoff_time no tiene formato ISO válido: {raw_value}"
        ) from exc
    if kickoff_time.tzinfo is None:
        raise FixtureImportError(
            f"Fila {row_number}: kickoff_time debe incluir zona horaria: {raw_value}"
        )
    return kickoff_time


def read_csv(csv_path: Path) -> list[dict]:
    if not csv_path.is_file():
        raise FixtureImportError(f"No existe el archivo CSV: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        headers = set(reader.fieldnames or [])
        missing_columns = sorted(REQUIRED_COLUMNS - headers)
        if missing_columns:
            raise FixtureImportError(
                "Faltan columnas obligatorias: " + ", ".join(missing_columns)
            )

        rows = []
        seen_match_numbers = set()
        for row_number, raw_row in enumerate(reader, start=2):
            match_number = parse_match_number(raw_row.get("match_number"), row_number)
            if match_number in seen_match_numbers:
                raise FixtureImportError(
                    f"Fila {row_number}: match_number duplicado en el CSV: {match_number}"
                )
            seen_match_numbers.add(match_number)

            stage = clean(raw_row.get("stage"))
            home_team = clean(raw_row.get("home_team"))
            away_team = clean(raw_row.get("away_team"))
            if not stage:
                raise FixtureImportError(f"Fila {row_number}: stage es obligatorio.")
            if not home_team or not away_team:
                raise FixtureImportError(
                    f"Fila {row_number}: home_team y away_team son obligatorios."
                )
            if home_team == away_team:
                raise FixtureImportError(
                    f"Fila {row_number}: un equipo no puede jugar contra sí mismo."
                )

            rows.append(
                {
                    "row_number": row_number,
                    "match_number": match_number,
                    "stage": stage,
                    "group_letter": clean(raw_row.get("group_letter")),
                    "home_team": home_team,
                    "away_team": away_team,
                    "kickoff_time": parse_kickoff_time(
                        raw_row.get("kickoff_time"), row_number
                    ),
                    "venue": clean(raw_row.get("venue")),
                    "city": clean(raw_row.get("city")),
                    "country": clean(raw_row.get("country")),
                }
            )

    if not rows:
        raise FixtureImportError("El CSV no contiene partidos.")
    return rows


def load_teams(conn) -> dict[str, object]:
    rows = conn.execute(text("SELECT id, name FROM teams")).mappings().all()
    return {row["name"].strip(): row["id"] for row in rows}


def validate_teams(rows: list[dict], teams_by_name: dict[str, object]) -> None:
    csv_teams = {
        team_name
        for row in rows
        for team_name in (row["home_team"], row["away_team"])
    }
    missing_teams = sorted(csv_teams - set(teams_by_name))
    if missing_teams:
        formatted = "\n".join(f"  - {team}" for team in missing_teams)
        raise FixtureImportError(
            "Hay equipos del CSV que no existen en teams.name:\n" + formatted
        )


def fixture_values(row: dict, teams_by_name: dict[str, object]) -> dict:
    return {
        "match_number": row["match_number"],
        "stage": row["stage"],
        "group_letter": row["group_letter"],
        "home_team_id": teams_by_name[row["home_team"]],
        "away_team_id": teams_by_name[row["away_team"]],
        "kickoff_time": row["kickoff_time"],
        "venue": row["venue"],
        "city": row["city"],
        "country": row["country"],
        "source": "manual",
    }


def find_existing_fixture(conn, values: dict):
    existing = conn.execute(
        text("SELECT id FROM matches WHERE match_number = :match_number"),
        {"match_number": values["match_number"]},
    ).mappings().first()
    if existing:
        return existing

    # Reutiliza cruces creados previamente por seed_matches.py para no duplicarlos.
    return conn.execute(
        text(
            """
            SELECT id
            FROM matches
            WHERE match_number IS NULL
              AND stage = :stage
              AND group_letter IS NOT DISTINCT FROM :group_letter
              AND (
                    (home_team_id = :home_team_id AND away_team_id = :away_team_id)
                 OR (home_team_id = :away_team_id AND away_team_id = :home_team_id)
              )
            LIMIT 1
            """
        ),
        values,
    ).mappings().first()


def import_fixtures(csv_path: Path) -> dict[str, int]:
    rows = read_csv(csv_path)
    inserted = 0
    updated = 0

    with get_engine().begin() as conn:
        teams_by_name = load_teams(conn)
        validate_teams(rows, teams_by_name)

        for row in rows:
            values = fixture_values(row, teams_by_name)
            existing = find_existing_fixture(conn, values)
            if existing:
                conn.execute(
                    text(
                        """
                        UPDATE matches
                        SET match_number = :match_number,
                            stage = :stage,
                            group_letter = :group_letter,
                            home_team_id = :home_team_id,
                            away_team_id = :away_team_id,
                            kickoff_time = :kickoff_time,
                            venue = :venue,
                            city = :city,
                            country = :country,
                            source = 'manual',
                            source_updated_at = NOW(),
                            updated_at = NOW()
                        WHERE id = :id
                        """
                    ),
                    values | {"id": existing["id"]},
                )
                updated += 1
            else:
                conn.execute(
                    text(
                        """
                        INSERT INTO matches (
                            match_number,
                            stage,
                            group_letter,
                            home_team_id,
                            away_team_id,
                            kickoff_time,
                            venue,
                            city,
                            country,
                            status,
                            source,
                            source_updated_at
                        )
                        VALUES (
                            :match_number,
                            :stage,
                            :group_letter,
                            :home_team_id,
                            :away_team_id,
                            :kickoff_time,
                            :venue,
                            :city,
                            :country,
                            'scheduled',
                            'manual',
                            NOW()
                        )
                        """
                    ),
                    values,
                )
                inserted += 1

    return {
        "rows_read": len(rows),
        "inserted": inserted,
        "updated": updated,
        "teams_validated": len(
            {
                team_name
                for row in rows
                for team_name in (row["home_team"], row["away_team"])
            }
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Importa el calendario oficial del Mundial 2026 desde CSV."
    )
    parser.add_argument("csv_path", type=Path, help="Ruta al archivo CSV.")
    args = parser.parse_args()

    try:
        summary = import_fixtures(args.csv_path)
    except FixtureImportError as exc:
        print("Importación cancelada. No se guardó ningún cambio.")
        print(f"Error: {exc}")
        return 1
    except SQLAlchemyError as exc:
        print("Importación cancelada. PostgreSQL hizo rollback.")
        print(f"Error de base de datos: {exc}")
        return 1
    except Exception as exc:
        print("Importación cancelada. No se guardó ningún cambio.")
        print(f"Error inesperado: {exc}")
        return 1

    print("Importación completada.")
    print(f"Filas leídas: {summary['rows_read']}")
    print(f"Partidos insertados: {summary['inserted']}")
    print(f"Partidos actualizados: {summary['updated']}")
    print(f"Equipos validados: {summary['teams_validated']}")
    print("Errores: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
