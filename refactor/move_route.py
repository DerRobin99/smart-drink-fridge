#!/usr/bin/env python3

"""
Move a Flask route from app.py into routes/<blueprint>.py

Usage:
    python3 refactor/move_route.py \
        --function einstellungen \
        --blueprint settings
"""

from pathlib import Path
import argparse
import ast
import shutil
from datetime import datetime


APP_FILE = Path("app.py")
ROUTES_DIR = Path("routes")


def backup_file(path: Path):
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(path.suffix + f".{ts}.bak")
    shutil.copy2(path, backup)
    print(f"Backup erstellt: {backup}")


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--function",
        required=True,
        help="Name der Flask-Funktion",
    )

    parser.add_argument(
        "--blueprint",
        required=True,
        help="Blueprint-Datei",
    )

    return parser.parse_args()


def main():

    args = parse_args()

    if not APP_FILE.exists():
        raise SystemExit("app.py nicht gefunden.")

    source = APP_FILE.read_text(encoding="utf-8")

    tree = ast.parse(source)

    target = None

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if node.name == args.function:
                target = node
                break

    if target is None:
        raise SystemExit(
            f"Funktion '{args.function}' nicht gefunden."
        )

    print()

    print("Gefunden:")
    print(f" Funktion : {args.function}")
    print(f" Blueprint: {args.blueprint}")

    print()

    print(
        "Die eigentliche Verschiebelogik kommt im nächsten Schritt."
    )


if __name__ == "__main__":
    main()
