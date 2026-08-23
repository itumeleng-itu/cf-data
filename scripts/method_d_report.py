"""Phase 8.5 step 7's acceptance gate: runs Method D (and, for the
regression baseline, Method B) over the real UJ 2027 prospectus and
compares each against the 29 hand-verified seeds/uj/*.json records,
field by field, using extract/selftest.py's own corrected comparison
helpers (_names_equal, _scores_equal, _tree_key) so "correct" never
drifts between this report and the production gate.

Deliberately NOT wired into selftest.py's run_ensemble (which stays
A+B+C only, per phase 8.5's constraint #1) -- this is a standalone,
one-off verification script, not new production pipeline wiring.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent / "extract"))
from ground_truth import UJ_2027_TABLE_PAGES  # noqa: E402
from methods.coordinate import extract_coordinate  # noqa: E402
from methods.geometric import extract_geometric  # noqa: E402
from profiles import get_profile  # noqa: E402
from selftest import _GROUND_TRUTH_FIELDS, _get  # noqa: E402


def _load_uj_ground_truth() -> list[dict]:
    seeds_dir = Path(__file__).parent.parent / "seeds" / "uj"
    records: list[dict] = []
    for f in sorted(seeds_dir.glob("*.json")):
        records.extend(json.loads(f.read_text(encoding="utf-8")))
    return records


def _report(label: str, records: list[dict], ground_truth: list[dict]) -> dict[str, float]:
    by_code = {r["qualification_code"]: r for r in records}
    gt_by_code = {r["qualification_code"]: r for r in ground_truth}

    recall = sum(1 for code in gt_by_code if code in by_code) / len(gt_by_code)

    rates: dict[str, float] = {"code": recall}
    for field_name, path, equals_fn in _GROUND_TRUTH_FIELDS:
        if field_name == "qualification_code":
            continue
        matched = 0
        compared = 0
        for code, gt in gt_by_code.items():
            record = by_code.get(code)
            if record is None:
                continue
            compared += 1
            if equals_fn(_get(gt, path), _get(record, path)):
                matched += 1
        rates[field_name] = (matched / compared) if compared else 0.0

    print(f"\n{label} vs UJ seeds ({len(gt_by_code)} hand-verified records):")
    print(f"  code recall:              {rates['code']:.1%} ({sum(1 for c in gt_by_code if c in by_code)}/{len(gt_by_code)})")
    print(f"  name match:               {rates['name']:.1%}")
    print(f"  campus match:             {rates['campus']:.1%}")
    print(f"  score match:              {rates['requirements.nsc.score']:.1%}")
    print(f"  subjects match:           {rates['requirements.nsc.subjects']:.1%}")
    print(f"  excluded_subjects match:  {rates['requirements.nsc.excluded_subjects']:.1%}")
    return rates


def _mismatches(label: str, records: list[dict], ground_truth: list[dict], field_name: str) -> None:
    by_code = {r["qualification_code"]: r for r in records}
    field = next(f for f in _GROUND_TRUTH_FIELDS if f[0] == field_name)
    _name, path, equals_fn = field
    print(f"\n{label} mismatches on {field_name}:")
    for gt in ground_truth:
        code = gt["qualification_code"]
        record = by_code.get(code)
        if record is None:
            continue
        gt_val, rec_val = _get(gt, path), _get(record, path)
        if not equals_fn(gt_val, rec_val):
            print(f"  {code}: seed={gt_val!r}  got={rec_val!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="data/downloads/uj_2027.pdf")
    ap.add_argument("--show-mismatches", action="store_true")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"no such file: {pdf_path}")
        return 1

    profile = get_profile("uj")
    pages = sorted(UJ_2027_TABLE_PAGES)
    ground_truth = _load_uj_ground_truth()

    b_records = extract_geometric(pdf_path, profile, pages)
    d_records, d_stats = extract_coordinate(pdf_path, profile, pages)

    print(f"Method D stats: {d_stats}")

    b_rates = _report("Method B", b_records, ground_truth)
    d_rates = _report("Method D", d_records, ground_truth)

    if args.show_mismatches:
        for field_name in ("requirements.nsc.subjects", "requirements.nsc.score", "campus"):
            _mismatches("Method D", d_records, ground_truth, field_name)

    print("\nMethod D vs Method B, field by field:")
    worse = []
    for key in ("code", "name", "campus", "requirements.nsc.score", "requirements.nsc.subjects", "requirements.nsc.excluded_subjects"):
        d_val, b_val = d_rates[key], b_rates[key]
        flag = "" if d_val >= b_val else "  <-- WORSE than Method B"
        print(f"  {key:<32} B={b_val:.1%}  D={d_val:.1%}{flag}")
        if d_val < b_val:
            worse.append(key)

    if worse:
        print(f"\nFAILED: Method D is worse than Method B on: {worse}")
        return 1
    print("\nPASSED: Method D is >= Method B on every field.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
