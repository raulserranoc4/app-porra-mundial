import argparse

from scoring import recalculate_all_scores, recalculate_group_scores, recalculate_match_scores, recalculate_special_scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Recalcula eventos de puntuación.")
    parser.add_argument("--match-id", type=int)
    parser.add_argument("--groups", action="store_true")
    parser.add_argument("--specials", action="store_true")
    args = parser.parse_args()

    if args.match_id:
        recalculate_match_scores(args.match_id)
        print(f"Puntos recalculados para partido {args.match_id}.")
    elif args.groups:
        recalculate_group_scores()
        print("Puntos de grupos recalculados.")
    elif args.specials:
        recalculate_special_scores()
        print("Puntos especiales recalculados.")
    else:
        recalculate_all_scores()
        print("Todos los puntos recalculados.")


if __name__ == "__main__":
    main()
