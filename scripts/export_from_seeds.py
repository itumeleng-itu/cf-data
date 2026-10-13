"""Builds api/src/app/data/programmes.json straight from seeds/, with no
database in the path.

WHY THIS EXISTS ALONGSIDE export_data.py
----------------------------------------
The API has never read a database. It loads one JSON file
(api/src/app/main.py::_DEFAULT_DATA_PATH) and serves from memory. Postgres
sits one step upstream purely as the EDITORIAL layer: ingest_bundle.py
diffs a bundle against what is stored, an operator reviews the report and
promotes records to confidence='verified', and export_data.py then selects
only those.

That editorial loop is worth keeping for a re-ingest, where the question is
"what changed since last time and has a human seen it". It is dead weight
when the records are already in git: a pull request diff on seeds/ answers
the same question with better tooling and permanent history, and the review
is the PR approval.

So this script is the git-native path:

    seeds/*.json  ->  programmes.json  ->  Docker image

and export_data.py remains the path for anything that went through Postgres.
Both emit byte-identical shape, so the API cannot tell them apart.

WHAT IT WILL NOT DO
-------------------
It will not invent a confidence level. A seed record carries whatever
confidence it was written with, exactly as the database would, and
--verified-only filters on that same field. A record transcribed by an
operator and never reviewed is 'extracted' in git just as it is in
Postgres, and is excluded from a --verified-only export either way. The gate
moves from a database column to a reviewed file; it does not disappear.

    uv run python scripts/export_from_seeds.py --years 2027
    uv run python scripts/export_from_seeds.py --years 2027,2028 --verified-only
"""

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
SEEDS = ROOT / "seeds"


def load_institutions() -> list[dict]:
    data = json.loads((SEEDS / "institutions.json").read_text(encoding="utf-8"))
    return data["institutions"] if isinstance(data, dict) else data


def load_programmes() -> list[dict]:
    """Every seeds/<institution>/*.json file. Each holds a list of records
    already in tree form - the same shape convert_bundle.py produces and
    the same shape the programmes table stores."""
    records: list[dict] = []
    for path in sorted(SEEDS.glob("*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            print(f"  skipped {path.relative_to(ROOT)} (not a list of records)")
            continue
        records.extend(payload)
    return records


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2027")
    ap.add_argument("--out", default="api/src/app/data/programmes.json")
    ap.add_argument("--verified-only", action="store_true")
    ap.add_argument("--min-records", type=int, default=1)
    args = ap.parse_args()

    years = {int(y) for y in args.years.split(",")}

    institutions = load_institutions()
    programmes = [p for p in load_programmes() if p.get("academic_year") in years]
    if args.verified_only:
        programmes = [p for p in programmes if p.get("confidence") == "verified"]

    if len(programmes) < args.min_records:
        print(f"refusing to export {len(programmes)} records "
              f"(expected at least {args.min_records}) — are the seeds present"
              + (", and has anything been marked verified?" if args.verified_only else "?"))
        return 1

    # export_data.py casts this out of a numeric column; match it exactly so
    # the two exporters stay byte-comparable.
    for p in programmes:
        p["duration_years"] = float(p["duration_years"]) if p.get("duration_years") else None

    programmes.sort(key=lambda p: (p.get("institution_id") or "",
                                   p.get("faculty") or "",
                                   p.get("qualification_code") or ""))

    out = ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"institutions": institutions, "programmes": programmes},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    by_inst: dict[str, int] = {}
    for p in programmes:
        by_inst[p["institution_id"]] = by_inst.get(p["institution_id"], 0) + 1
    print(f"exported {len(programmes)} programmes → {out} ({out.stat().st_size / 1024:.0f} KB)")
    print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(by_inst.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
