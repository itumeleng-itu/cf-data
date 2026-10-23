#!/usr/bin/env python3
"""Recover TUT's campus field from data already in the seed.

WHY THIS EXISTS AND WHY IT IS NOT A PATCH

convert_tut_programmes.py now reads the prospectus's per-programme
campus column into `campus` (see campuses_for). The correct way to
apply that is to re-run the conversion -- but the conversion starts
from tut_first_year_course_information_2027.pdf, and sources/ is
gitignored, so the input is not in the repository.

Both of campuses_for's inputs are nonetheless still present in the
seed. The page banner is the existing `campus` value, and the column
survives verbatim inside the note the old converter wrote:

    "Also offered at: SS E Po."

So this reconstructs the converter's input and calls the converter's
own function on it. It is the same code path, not a parallel
implementation, which is the whole point: when the PDF comes back and
convert_tut_programmes.py runs properly, it must produce exactly what
this produced, and `--check` asserts that it does.

It invents nothing. A code the legend does not cover is reported and
left out rather than guessed at -- "D", on Dip (Fire Technology), is
the only one.

ONE SHOT, AND IT CHECKS

Running it consumes the note it reads from, so a second run would see
an empty column, take campus[0] as the banner, and throw the rest of
the campuses away. It therefore refuses to run once the notes are
gone, rather than quietly destroying the field it just populated.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from convert_tut_programmes import UNRESOLVED_CODES, campuses_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seeds" / "tut" / "tut_2027.json"

NOTE = re.compile(r"^Also offered at:\s*(.+?)\.?$")


def reconstruct(record: dict) -> tuple[dict, list[str]]:
    """The converter's input for this record, and the notes without it."""
    kept: list[str] = []
    column = ""
    for note in record.get("selection_notes") or []:
        match = NOTE.match(note)
        if match:
            column = match.group(1).strip()
        else:
            kept.append(note)

    return (
        {
            "campus": (record.get("campus") or [None])[0],
            "other_campuses": column or None,
            "name": record["name"],
        },
        kept,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--check",
        action="store_true",
        help="Report what would change and exit non-zero if anything would, "
        "without writing. Use this after a real re-run to prove the two agree.",
    )
    args = ap.parse_args()

    records = json.loads(SEED.read_text(encoding="utf-8"))

    # The note is this script's input. Once it has been consumed the
    # input is gone, and running again would reduce every multi-campus
    # programme back to its first campus.
    remaining = sum(
        1
        for record in records
        for note in record.get("selection_notes") or []
        if NOTE.match(note)
    )
    if remaining == 0:
        print("Already applied: no 'Also offered at' notes remain. Nothing to do.")
        print("Re-run convert_tut_programmes.py from the PDF to regenerate properly.")
        return 0

    changed = 0
    gained: dict[str, int] = {}

    for record in records:
        source, kept_notes = reconstruct(record)
        campuses = campuses_for(source)
        if campuses != record.get("campus"):
            changed += 1
            for campus in campuses:
                if campus not in (record.get("campus") or []):
                    gained[campus] = gained.get(campus, 0) + 1
        if not args.check:
            record["campus"] = campuses
            record["selection_notes"] = kept_notes

    print(f"{changed} of {len(records)} records change")
    for campus, count in sorted(gained.items(), key=lambda kv: -kv[1]):
        print(f"  +{count:3}  {campus}")

    if UNRESOLVED_CODES:
        print("\nCodes the legend does not cover (left out, not guessed):")
        for code, names in UNRESOLVED_CODES.items():
            print(f"  {code!r}: {', '.join(n[:50] for n in names)}")

    if args.check:
        return 1 if changed else 0

    SEED.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {SEED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
