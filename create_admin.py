import argparse

from auth import upsert_admin


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea o actualiza un administrador.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    upsert_admin(args.name, args.email, args.password)
    print(f"Admin creado o actualizado: {args.email}")


if __name__ == "__main__":
    main()
