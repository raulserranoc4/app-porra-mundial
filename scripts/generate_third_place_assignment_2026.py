#!/usr/bin/env python3
"""
Generate data/third_place_assignment_2026.json for the FIFA World Cup 2026
Round of 32 third-place assignment table.

Source:
- Wikipedia template mirroring Annex C of the FIFA World Cup 2026 regulations:
  https://en.wikipedia.org/wiki/Template:2026_FIFA_World_Cup_third-place_table

Why this file exists:
The 8 best third-placed teams can come from 495 possible combinations of groups.
Each combination maps the third-placed teams to the R32 slots against:
1A, 1B, 1D, 1E, 1G, 1I, 1K and 1L.

This script fetches the published table and converts it to JSON.

Usage:
    python scripts/generate_third_place_assignment_2026.py

Output:
    data/third_place_assignment_2026.json

The output JSON shape is:
{
  "ABCDEFGH": {
    "1A": "3H",
    "1B": "3G",
    "1D": "3B",
    "1E": "3C",
    "1G": "3A",
    "1I": "3F",
    "1K": "3D",
    "1L": "3E"
  }
}
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


SOURCE_URL = "https://en.wikipedia.org/w/index.php?title=Template%3A2026_FIFA_World_Cup_third-place_table&printable=yes"
OUTPUT_PATH = Path("data/third_place_assignment_2026.json")

SLOTS = ["1A", "1B", "1D", "1E", "1G", "1I", "1K", "1L"]
GROUPS = set("ABCDEFGHIJKL")


def _clean_cell(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_rows_from_html(raw_html: str) -> dict[str, dict[str, str]]:
    """
    Parse table rows from the HTML.
    Expected meaningful row format after cleaning:
      495 A B C D E F G H 3H 3G 3B 3C 3A 3F 3D 3E
    """
    result: dict[str, dict[str, str]] = {}

    table_rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", raw_html, flags=re.IGNORECASE | re.DOTALL)

    for row_html in table_rows:
        cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_html, flags=re.IGNORECASE | re.DOTALL)
        cells = [_clean_cell(cell) for cell in cells]
        cells = [cell for cell in cells if cell]

        # Some rendered tables may include cells separately:
        # [No, A, B, C, D, E, F, G, H, 3H, 3G, ...]
        tokens: list[str] = []
        for cell in cells:
            tokens.extend(cell.split())

        if not tokens or not tokens[0].isdigit():
            continue

        # Keep only valid row-like structures.
        # no + 8 group letters + 8 assignments.
        if len(tokens) < 17:
            continue

        option_no = int(tokens[0])
        groups = tokens[1:9]
        assignments = tokens[9:17]

        if not (1 <= option_no <= 495):
            continue

        if len(groups) != 8 or any(g not in GROUPS for g in groups):
            continue

        if len(assignments) != 8 or any(not re.fullmatch(r"3[A-L]", a) for a in assignments):
            continue

        key = "".join(groups)
        result[key] = dict(zip(SLOTS, assignments))

    return result


def _extract_rows_from_plain_text(raw_html: str) -> dict[str, dict[str, str]]:
    """
    Fallback parser: strip tags and parse lines like:
      495  A B C D E F G H 3H 3G 3B 3C 3A 3F 3D 3E
    """
    text = re.sub(r"<[^>]+>", "\n", raw_html)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)

    # Normalize cases where cells become separate lines.
    compact = re.sub(r"\s+", " ", text)

    pattern = re.compile(
        r"\b([1-9][0-9]{0,2})\s+"
        r"([A-L])\s+([A-L])\s+([A-L])\s+([A-L])\s+([A-L])\s+([A-L])\s+([A-L])\s+([A-L])\s+"
        r"(3[A-L])\s+(3[A-L])\s+(3[A-L])\s+(3[A-L])\s+(3[A-L])\s+(3[A-L])\s+(3[A-L])\s+(3[A-L])"
    )

    result: dict[str, dict[str, str]] = {}
    for match in pattern.finditer(compact):
        option_no = int(match.group(1))
        if not (1 <= option_no <= 495):
            continue

        groups = list(match.groups()[1:9])
        assignments = list(match.groups()[9:17])

        key = "".join(groups)
        result[key] = dict(zip(SLOTS, assignments))

    return result


def fetch_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "porra-mundial-2026/1.0 (+local development script)"
        },
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def validate_mapping(mapping: dict[str, dict[str, str]]) -> None:
    if len(mapping) != 495:
        raise ValueError(f"Expected 495 combinations, got {len(mapping)}")

    for key, value in mapping.items():
        if len(key) != 8 or any(ch not in GROUPS for ch in key):
            raise ValueError(f"Invalid combination key: {key}")

        if set(value.keys()) != set(SLOTS):
            raise ValueError(f"Invalid slots for key {key}: {value.keys()}")

        for slot, assignment in value.items():
            if not re.fullmatch(r"3[A-L]", assignment):
                raise ValueError(f"Invalid assignment for {key}/{slot}: {assignment}")

            assignment_group = assignment[-1]
            if assignment_group not in key:
                raise ValueError(
                    f"Assignment {assignment} for {key}/{slot} is not one of the qualifying third groups"
                )


def main() -> int:
    print(f"Fetching third-place assignment table from: {SOURCE_URL}")
    raw_html = fetch_html(SOURCE_URL)

    mapping = _extract_rows_from_html(raw_html)
    if len(mapping) != 495:
        print(f"HTML table parser found {len(mapping)} rows; trying plain-text fallback...")
        mapping = _extract_rows_from_plain_text(raw_html)

    validate_mapping(mapping)

    payload = {
        "_metadata": {
            "source": SOURCE_URL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "description": (
                "FIFA World Cup 2026 Round of 32 assignment table for the eight best "
                "third-placed teams. Keys are the eight groups whose third-placed teams "
                "qualify; values map group-winner slots to third-placed slots."
            ),
            "slots": SLOTS,
            "combination_count": len(mapping),
        },
        "assignments": dict(sorted(mapping.items())),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"OK: wrote {len(mapping)} combinations to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
