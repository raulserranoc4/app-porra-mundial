from sqlalchemy import text

from bracket import KNOCKOUT_BRACKET_STRUCTURE
from db import db_session


def source_label(source: tuple[str, int]) -> str:
    result_type, match_number = source
    prefix = "Loser" if result_type == "loser" else "Winner"
    return f"{prefix} Match {match_number}"


def main() -> None:
    inserted = 0
    with db_session() as conn:
        for stage, matches in KNOCKOUT_BRACKET_STRUCTURE.items():
            for match_number, (home_source, away_source) in matches.items():
                exists = conn.execute(
                    text("SELECT 1 FROM matches WHERE match_number = :match_number"),
                    {"match_number": match_number},
                ).first()
                if exists:
                    continue
                conn.execute(
                    text(
                        """
                        INSERT INTO matches (
                            match_number,
                            stage,
                            home_placeholder,
                            away_placeholder,
                            status,
                            source
                        )
                        VALUES (
                            :match_number,
                            :stage,
                            :home_placeholder,
                            :away_placeholder,
                            'scheduled',
                            'manual'
                        )
                        """
                    ),
                    {
                        "match_number": match_number,
                        "stage": stage,
                        "home_placeholder": source_label(home_source),
                        "away_placeholder": source_label(away_source),
                    },
                )
                inserted += 1
    print(f"Placeholders eliminatorios creados: {inserted}.")


if __name__ == "__main__":
    main()
