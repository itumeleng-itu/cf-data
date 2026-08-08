"""Print seed-encoding burn-down: count per faculty file, confidence
breakdown, and which of the 8 UJ faculty files still have zero records."""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
from seed_loader import load_with_sources  # noqa: E402

# The 8 UJ faculties being encoded, by seed-file stem (seeds/uj/<stem>.json).
UJ_FACULTY_FILES = ["science", "cbe", "febe", "health", "law", "humanities", "education", "fada"]

TOTAL_UJ_PROGRAMMES = 179  # stated ballpark for the 2027 prospectus, for burn-down context only


def main() -> int:
    data, sources = load_with_sources()
    programmes = data["programmes"]

    by_file: dict[str, list[dict]] = {}
    for p in programmes:
        source = sources.get((p["institution_id"], p["qualification_code"]))
        stem = source.stem if source else "?"
        by_file.setdefault(stem, []).append(p)

    print(f"Total encoded: {len(programmes)} / ~{TOTAL_UJ_PROGRAMMES} UJ 2027 programmes\n")

    print("Per faculty file:")
    empty: list[str] = []
    for stem in UJ_FACULTY_FILES:
        progs = by_file.get(stem, [])
        if not progs:
            empty.append(stem)
            print(f"  {stem:12s}  0 records  <-- EMPTY")
            continue
        faculty_name = progs[0].get("faculty") or "?"
        by_confidence: dict[str, int] = {}
        for p in progs:
            by_confidence[p["confidence"]] = by_confidence.get(p["confidence"], 0) + 1
        confidence_str = ", ".join(f"{k}={v}" for k, v in sorted(by_confidence.items()))
        print(f"  {stem:12s}  {len(progs)} records  [{faculty_name}]  ({confidence_str})")

    extra = sorted(set(by_file) - set(UJ_FACULTY_FILES))
    for stem in extra:
        print(f"  {stem:12s}  {len(by_file[stem])} records  (unexpected file, not one of the 8)")

    print("\nBy confidence (all faculties):")
    overall_confidence: dict[str, int] = {}
    for p in programmes:
        overall_confidence[p["confidence"]] = overall_confidence.get(p["confidence"], 0) + 1
    for k, v in sorted(overall_confidence.items()):
        print(f"  {k:10s} {v}")

    if empty:
        print(f"\nFaculties with zero records ({len(empty)}/8): {', '.join(empty)}")
    else:
        print("\nAll 8 UJ faculties have at least one record.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
