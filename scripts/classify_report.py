"""Print per-page classification with signal values for a real prospectus
PDF, then precision/recall against hand-verified ground truth. This is
sub-phase 8.2's validation gate: recall must exceed 95% before extraction
(8.3) starts. Ground truth only exists for UJ 2027 today -- pass
--institution/--year matching a set registered in extract/ground_truth.py,
or the report has nothing to compare against and refuses to run.
"""

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent / "extract"))
from classify import PageClass, classify_pages  # noqa: E402
from profiles import get_profile  # noqa: E402

_GROUND_TRUTH = {
    ("uj", 2027): "UJ_2027_TABLE_PAGES",
    ("cput", 2027): "CPUT_2027_TABLE_PAGES",
}


def _load_ground_truth(institution: str, year: int) -> frozenset[int] | None:
    attr = _GROUND_TRUTH.get((institution, year))
    if attr is None:
        return None
    import ground_truth
    return getattr(ground_truth, attr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--institution", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--pdf", required=True)
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"no such file: {pdf_path}")
        return 1

    ground_truth_pages = _load_ground_truth(args.institution, args.year)
    if ground_truth_pages is None:
        print(
            f"no ground truth registered for {args.institution} {args.year} "
            f"in extract/ground_truth.py -- cannot report precision/recall"
        )
        return 1

    profile = get_profile(args.institution)
    classifications, signal_report = classify_pages(pdf_path, profile)

    print(f"{'page':>5}  {'class':<20}  signals")
    for page in sorted(classifications):
        report = signal_report[page]
        signals_str = ", ".join(f"{k}={v:.3g}" if isinstance(v, float) else f"{k}={v}"
                                 for k, v in report["signals"].items())
        print(f"{page:>5}  {report['class']:<20}  {signals_str}")

    predicted = {page for page, cls in classifications.items() if cls == PageClass.PROGRAMME_TABLE}
    true_positives = ground_truth_pages & predicted
    false_negatives = sorted(ground_truth_pages - predicted)
    false_positives = sorted(predicted - ground_truth_pages)

    recall = len(true_positives) / len(ground_truth_pages) if ground_truth_pages else 0.0
    precision = len(true_positives) / len(predicted) if predicted else 0.0

    print(f"\n{args.institution} {args.year}: {len(classifications)} pages classified")
    print(f"recall:    {recall:.1%}  ({len(true_positives)}/{len(ground_truth_pages)} ground-truth table pages found)")
    print(f"precision: {precision:.1%}  ({len(true_positives)}/{len(predicted)} predicted table pages correct)")

    if false_negatives:
        print(f"\nfalse negatives ({len(false_negatives)} pages) -- missed table pages, with their signals:")
        for page in false_negatives:
            report = signal_report[page]
            signals_str = ", ".join(f"{k}={v:.3g}" if isinstance(v, float) else f"{k}={v}"
                                     for k, v in report["signals"].items())
            print(f"  page {page}: classified as {report['class']}, signals: {signals_str}")

    if false_positives:
        print(f"\nfalse positives ({len(false_positives)} pages): {false_positives}")

    if recall <= 0.95:
        print(f"\nGATE FAILED: recall {recall:.1%} does not exceed 95% -- do not proceed to sub-phase 8.3.")
        return 1

    print(f"\nGATE PASSED: recall {recall:.1%} exceeds 95%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
