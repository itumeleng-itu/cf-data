"""The gate: runs all three extraction methods against a PDF and compares
against hand-verified ground truth (seeds/uj/*.json for UJ). Reports two
numbers per the task's explicit thresholds:
  completeness recall  > 98%  -- programmes found / present
  false agreement       < 2%  -- fields every method that ran agreed on
                                  (confidence 1.0) that are WRONG. This is
                                  the residual error reaching production
                                  UNREVIEWED (a record only skips human
                                  review when every field hits 1.0), and
                                  it is the number that decides whether
                                  the pipeline is trustworthy at all.

Method C is deliberately NOT run over every page. Methods A and B run
first; Method C only runs on pages where A and B GENUINELY disagree --
both produced a value for some field and those values differ (not a
one-sided coverage gap, where only one method found something at all;
confirmed against real UJ data that campus/score gaps are 100%
one-sided, zero genuine conflicts, so including them would spend real
money resolving a recall problem, not a disagreement). Do not run this
against a second institution until both gates pass on UJ.
"""

import json
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ground_truth import UJ_2027_TABLE_PAGES  # noqa: E402
from methods.geometric import extract_geometric  # noqa: E402
from methods.textlayer import extract_textlayer  # noqa: E402
from methods.vision import extract_vision  # noqa: E402
from profiles import get_profile  # noqa: E402
from reconcile import _score_key, _set_key, _tree_key, reconcile  # noqa: E402

_GROUND_TRUTH_FIELDS: list[tuple[str, tuple[str, ...], Callable[[Any], Any]]] = [
    ("qualification_code", ("qualification_code",), lambda v: v),
    ("name", ("name",), lambda v: v),
    ("campus", ("campus",), _set_key),
    ("requirements.nsc.score", ("requirements", "nsc", "score"), _score_key),
    ("requirements.nsc.subjects", ("requirements", "nsc", "subjects"), _tree_key),
    ("requirements.nsc.excluded_subjects", ("requirements", "nsc", "excluded_subjects"), _set_key),
]


def _get(record: dict, path: tuple[str, ...]) -> Any:
    current: Any = record
    for part in path:
        if current is None:
            return None
        current = current.get(part)
    return current


def find_genuine_conflict_pages(a_records: list[dict], b_records: list[dict]) -> set[int]:
    """Pages containing at least one code where A and B BOTH produced a
    value for some field and disagreed -- not pages where one method
    simply found something the other didn't (that's a coverage gap, a
    reason to improve A/B's own recall later, not to spend on Method C
    now)."""
    a_idx = {r["qualification_code"]: r for r in a_records}
    b_idx = {r["qualification_code"]: r for r in b_records}
    pages: set[int] = set()
    for code in set(a_idx) & set(b_idx):
        a, b = a_idx[code], b_idx[code]
        for _name, path, key_fn in _GROUND_TRUTH_FIELDS:
            a_val, b_val = _get(a, path), _get(b, path)
            if a_val is None or b_val is None:
                continue
            if key_fn(a_val) != key_fn(b_val):
                page = a.get("source_page")
                if page is not None:
                    pages.add(page)
                break
    return pages


_EMPTY_VISION_STATS: dict[str, Any] = {
    "model": None, "pages_attempted": 0, "pages_parsed": 0, "pages_abstained": 0,
}


def run_ensemble(
    pdf_path: Path,
    profile: dict,
    table_pages: list[int],
    api_key: str,
    model: str | None = None,
    extract_vision_fn: Callable[..., tuple[list[dict], dict[str, Any]]] = extract_vision,
) -> tuple[dict[str, tuple[dict, dict[str, float]]], set[int], dict[str, Any]]:
    """Returns ({code: (merged_record, field_confidence)}, c_pages_run,
    vision_stats). vision_stats is _EMPTY_VISION_STATS (model=None) when
    A and B already agreed everywhere and Method C never ran at all --
    that's a valid, zero-cost outcome, not a missing result."""
    a_records = extract_textlayer(pdf_path, profile, table_pages)
    b_records = extract_geometric(pdf_path, profile, table_pages)

    c_pages = find_genuine_conflict_pages(a_records, b_records)
    if c_pages:
        vision_kwargs = {"model": model} if model else {}
        c_records, vision_stats = extract_vision_fn(pdf_path, profile, sorted(c_pages), api_key=api_key, **vision_kwargs)
    else:
        c_records, vision_stats = [], dict(_EMPTY_VISION_STATS)

    a_idx = {r["qualification_code"]: r for r in a_records}
    b_idx = {r["qualification_code"]: r for r in b_records}
    c_idx = {r["qualification_code"]: r for r in c_records}
    all_codes = set(a_idx) | set(b_idx) | set(c_idx)

    results: dict[str, tuple[dict, dict[str, float]]] = {}
    for code in all_codes:
        a, b, c = a_idx.get(code), b_idx.get(code), c_idx.get(code)
        results[code] = reconcile(a, b, c)
    return results, c_pages, vision_stats


def compute_gate(
    results: dict[str, tuple[dict, dict[str, float]]], ground_truth: list[dict],
) -> dict[str, Any]:
    gt_by_code = {r["qualification_code"]: r for r in ground_truth}

    found = sum(1 for code in gt_by_code if code in results)
    completeness_recall = found / len(gt_by_code) if gt_by_code else 0.0

    agreed_total = 0
    agreed_wrong = 0
    wrong_by_field: dict[str, int] = {}
    for code, gt in gt_by_code.items():
        if code not in results:
            continue
        merged, confidence = results[code]
        for field_name, path, key_fn in _GROUND_TRUTH_FIELDS:
            if confidence.get(field_name) != 1.0:
                continue
            agreed_total += 1
            gt_val = _get(gt, path)
            merged_val = _get(merged, path)
            if key_fn(gt_val) != key_fn(merged_val):
                agreed_wrong += 1
                wrong_by_field[field_name] = wrong_by_field.get(field_name, 0) + 1

    false_agreement_rate = agreed_wrong / agreed_total if agreed_total else 0.0

    # Queue size over the FULL ensemble output, not just the 29
    # ground-truth-matched codes -- queue size is a production-behaviour
    # question (how much of what the pipeline produces needs a human),
    # not a validation-sample one.
    needs_review = sum(1 for merged, _confidence in results.values() if merged.get("verification", {}).get("needs_review"))
    queue_fraction = needs_review / len(results) if results else 0.0

    return {
        "completeness_recall": completeness_recall,
        "programmes_found": found,
        "programmes_present": len(gt_by_code),
        "false_agreement_rate": false_agreement_rate,
        "fields_agreed": agreed_total,
        "fields_agreed_wrong": agreed_wrong,
        "false_agreement_by_field": wrong_by_field,
        "queue_fraction": queue_fraction,
        "records_total": len(results),
        "records_needing_review": needs_review,
    }


def _load_uj_ground_truth() -> list[dict]:
    seeds_dir = Path(__file__).resolve().parent.parent / "seeds" / "uj"
    records: list[dict] = []
    for f in sorted(seeds_dir.glob("*.json")):
        records.extend(json.loads(f.read_text(encoding="utf-8")))
    return records


def main() -> int:
    import argparse
    import os

    ap = argparse.ArgumentParser(prog="selftest")
    ap.add_argument("--pdf", default="data/downloads/uj_2027.pdf")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY not set -- cannot run Method C, aborting.")
        return 1

    profile = get_profile("uj")
    pages = sorted(UJ_2027_TABLE_PAGES)
    ground_truth = _load_uj_ground_truth()

    results, c_pages, vision_stats = run_ensemble(Path(args.pdf), profile, pages, api_key, args.model)
    gate = compute_gate(results, ground_truth)

    print(f"Method C model: {vision_stats['model']}")
    print(f"Method C ran on {len(c_pages)}/{len(pages)} pages: {sorted(c_pages)}")
    print(f"pages attempted/parsed/abstained: "
          f"{vision_stats['pages_attempted']}/{vision_stats['pages_parsed']}/{vision_stats['pages_abstained']}")
    print(f"completeness recall: {gate['completeness_recall']:.1%} "
          f"({gate['programmes_found']}/{gate['programmes_present']}) -- gate: > 98%")
    print(f"false agreement: {gate['false_agreement_rate']:.1%} "
          f"({gate['fields_agreed_wrong']}/{gate['fields_agreed']} agreed fields wrong) -- gate: < 2%")
    print(f"false agreement by field: {gate['false_agreement_by_field']}")
    print(f"human-queue size: {gate['queue_fraction']:.1%} "
          f"({gate['records_needing_review']}/{gate['records_total']} records)")

    passed = gate["completeness_recall"] > 0.98 and gate["false_agreement_rate"] < 0.02
    print("GATE PASSED" if passed else "GATE FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
