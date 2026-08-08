"""Verifies extract/text_repair.py's rotated-text correction against a
real PDF, run-by-run. This is the real gate for that fix -- NOT
code_matches, which can look clean on a page whose one code got repaired
while its column headers stayed broken (exactly page 38's bug: 'B8BA3Q'
fixed, 'PROGRAMME'/'Qualification Code' left reversed). For every
non-upright run on every requested page, prints the corrected text and
flags any that still looks reversed after correction.
"""

import argparse
import sys
from pathlib import Path

import pdfplumber

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent / "extract"))
from text_repair import _group_runs, looks_reversed  # noqa: E402

_CODE_PATTERN = r"[A-Z]\d[A-Z0-9]{3,4}"

# Known reversed forms of this document's own column headers -- a run
# whose corrected text still contains one of these was not actually
# repaired, regardless of what looks_reversed's generic heuristic says.
_KNOWN_REVERSED_HEADER_WORDS = [
    "EMMARGORP", "edoC", "noitacfiilauQ", "SPA", "muminiM", "SUPMAC", "REERAC",
]


def _still_reversed(corrected: str) -> bool:
    if looks_reversed(corrected, _CODE_PATTERN):
        return True
    return any(word in corrected for word in _KNOWN_REVERSED_HEADER_WORDS)


def _parse_page_range(spec: str | None, page_count: int) -> range:
    if spec is None:
        return range(1, page_count + 1)
    start, _sep, end = spec.partition("-")
    start_i = int(start)
    end_i = int(end) if end else start_i
    return range(start_i, end_i + 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--pages", default=None, help="e.g. 32-95; defaults to every page")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"no such file: {pdf_path}")
        return 1

    total_runs = 0
    pages_with_runs = 0
    still_reversed: list[tuple[int, str]] = []

    with pdfplumber.open(pdf_path) as pdf:
        page_range = _parse_page_range(args.pages, len(pdf.pages))
        for page_number in page_range:
            if page_number < 1 or page_number > len(pdf.pages):
                continue
            page = pdf.pages[page_number - 1]
            non_upright = [c for c in page.chars if not c.get("upright", True)]
            if not non_upright:
                continue

            runs = _group_runs(non_upright)
            pages_with_runs += 1
            print(f"--- page {page_number}: {len(runs)} non-upright run(s) ---")
            for run in runs:
                corrected = "".join(c["text"] for c in run)
                total_runs += 1
                flag = ""
                if _still_reversed(corrected):
                    still_reversed.append((page_number, corrected))
                    flag = "  <-- STILL REVERSED"
                print(f"  {corrected!r}{flag}")

    print()
    print(f"{total_runs} non-upright runs checked across {pages_with_runs} page(s) with rotated text")

    if still_reversed:
        print(f"\n{len(still_reversed)} STILL-REVERSED run(s):")
        for page_number, text in still_reversed:
            print(f"  page {page_number}: {text!r}")
        print(f"\nGATE FAILED: {len(still_reversed)} still-reversed run(s) -- repair is incomplete.")
        return 1

    print("\nGATE PASSED: zero still-reversed runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
