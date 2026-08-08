"""Discovers prospectus documents for a given year from one or more
aggregator sources -- downloads nothing. Writes
data/discovery/{source}_{year}.json and prints every entry with its
mapped institution_id, UNMAPPED, or SKIPPED_MULTI_INSTITUTION status,
plus a coverage table against all 26 SA public universities: present,
missing, and (for each missing one) which earlier years the source does
carry it for.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent / "extract"))
from institution_map import (  # noqa: E402
    INSTITUTIONS,
    MULTI_INSTITUTION_DOCUMENTS,
    find_multi_institution_document,
    resolve_institution_id,
)
from sources.apply_org_za import ApplyOrgZaSource  # noqa: E402
from sources.universityqualifications import UniversityQualificationsSource  # noqa: E402

_SOURCES = {
    "universityqualifications": UniversityQualificationsSource,
    "apply": ApplyOrgZaSource,
}

# How many years back to check for a missing institution. Meaningful for
# universityqualifications.co.za (year-parametrized listing URL); for
# apply.org.za (one evergreen, year-agnostic listing) this just re-checks
# the same page each time and degrades to "same result every year" --
# harmless, just not informative for that source specifically.
_HISTORICAL_YEARS_TO_CHECK = 4


def _annotate(entry) -> dict:
    record = asdict(entry)
    multi_key = find_multi_institution_document(entry.display_name, entry.source_id)
    if multi_key:
        record["status"] = "SKIPPED_MULTI_INSTITUTION"
        record["institution_id"] = None
        record["multi_institution_key"] = multi_key
        record["skip_reason"] = MULTI_INSTITUTION_DOCUMENTS[multi_key]["skip_reason"]
        return record

    institution_id = resolve_institution_id(entry.display_name)
    if institution_id is None:
        record["status"] = "UNMAPPED"
    else:
        record["status"] = "MAPPED"
        record["institution_id"] = institution_id
    return record


def _historical_coverage(source, missing_ids: list[str], year: int) -> dict[str, list[int]]:
    coverage: dict[str, list[int]] = {inst_id: [] for inst_id in missing_ids}
    for offset in range(1, _HISTORICAL_YEARS_TO_CHECK + 1):
        check_year = year - offset
        try:
            entries = source.discover(check_year)
        except Exception as exc:  # noqa: BLE001 -- a bad historical year must not kill the report
            print(f"    (could not check {check_year}: {exc})")
            continue
        found_ids = {resolve_institution_id(e.display_name) for e in entries}
        for inst_id in missing_ids:
            if inst_id in found_ids:
                coverage[inst_id].append(check_year)
    return coverage


def _run_source(source_name: str, year: int, out_dir: Path) -> None:
    source = _SOURCES[source_name]()
    print(f"=== {source_name} {year} ===")
    entries = source.discover(year)
    records = [_annotate(e) for e in entries]

    for r in records:
        status = r["status"]
        if status == "MAPPED":
            print(f"  {r['institution_id']:<10} {r['display_name']}")
        elif status == "SKIPPED_MULTI_INSTITUTION":
            print(f"  SKIPPED_MULTI_INSTITUTION  {r['display_name']}")
            print(f"      reason: {r['skip_reason']}")
        else:
            print(f"  UNMAPPED   {r['display_name']!r} -- add to extract/institution_map.py")

    mapped_ids = {r["institution_id"] for r in records if r["status"] == "MAPPED"}
    present = sorted(mapped_ids)
    missing = sorted(set(INSTITUTIONS) - mapped_ids)

    print(f"\ncoverage: {len(present)}/{len(INSTITUTIONS)} present")
    print(f"  present: {[p.upper() for p in present]}")
    print(f"  missing: {[m.upper() for m in missing]}")

    if missing:
        print(f"  checking the last {_HISTORICAL_YEARS_TO_CHECK} years for missing institutions...")
        historical = _historical_coverage(source, missing, year)
        for inst_id in missing:
            years_found = historical.get(inst_id, [])
            if years_found:
                print(f"    {inst_id.upper()}: carried for {years_found}")
            else:
                print(f"    {inst_id.upper()}: not found in the last {_HISTORICAL_YEARS_TO_CHECK} years either")

    out_path = out_dir / f"{source_name}_{year}.json"
    out_path.write_text(
        json.dumps({"source": source_name, "year": year, "entries": records}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nwrote {out_path}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=[*_SOURCES.keys(), "all"], required=True)
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    source_names = list(_SOURCES) if args.source == "all" else [args.source]

    out_dir = Path("data/discovery")
    out_dir.mkdir(parents=True, exist_ok=True)

    for source_name in source_names:
        _run_source(source_name, args.year, out_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
