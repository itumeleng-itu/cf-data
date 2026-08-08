"""Heuristic triage for a candidate prospectus PDF -- no model calls, and
no per-institution profile needed, since the whole point is to sort
documents BEFORE anyone builds one. Distinguishes a full prospectus (many
per-programme requirement tables) from a summary brochure (few or none):
CPUT's 15-page file has exactly TWO real tables, TUT's has zero
qualification codes and calls itself "Part 1 of the Prospectus" -- both
looked like real prospectuses until read page by page.

Self-contained: does NOT import extract/classify.py or
extract/text_repair.py. This tool's candidate code patterns are
deliberately generic and plural (institutions use different shapes, and
none is known yet at triage time), unlike classify.py's single
registry-driven pattern per institution -- reusing that machinery here
would be the wrong tool, not just an off-limits one.

Does not move or stage anything. Prints the exact staging command for a
human to run by hand for each LIKELY_FULL file.
"""

import argparse
import re
from datetime import date
from pathlib import Path

import pdfplumber

_CANDIDATE_CODE_PATTERNS = {
    "letter+digit+alnum{3,4}": re.compile(r"\b[A-Z]\d[A-Z0-9]{3,4}\b"),
    "6-char-uppercase": re.compile(r"\b[A-Z][A-Z0-9][A-Z]{4}\b"),
    "letters{2,4}+digits{2,4}": re.compile(r"\b[A-Z]{2,4}\d{2,4}\b"),
    "digit+letters{2,5}": re.compile(r"\b\d[A-Z]{2,5}\b"),
}

_HEADER_VOCAB = [
    "aps", "admission point", "minimum requirements", "minimum admission",
    "qualification", "programme", "campus",
]

_PARTIAL_MARKERS = [
    "part 1", "part 2", "summary", "brochure", "first year", "course information",
]

_MIN_CODE_MATCHES_FOR_TABLE_PAGE = 3
_MIN_PLAUSIBLE_TABLE_PAGES_FOR_FULL = 10


def _page_code_matches(text: str) -> int:
    # Best of the candidate patterns for this one page -- institutions use
    # different code shapes (UJ requires a digit in position 2, CPUT's is
    # pure uppercase letters), and no institution profile exists yet at
    # triage time, so try them all and take whichever fits this page best.
    return max(len(pattern.findall(text)) for pattern in _CANDIDATE_CODE_PATTERNS.values())


def _page_has_header_vocab(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in _HEADER_VOCAB)


def _verdict(page_count: int, plausible_table_pages: int) -> str:
    """Pure verdict logic, kept separate from PDF I/O so it's testable
    against synthetic page-stat inputs -- same separation classify.py
    uses between signal computation and pdfplumber itself."""
    if page_count == 0:
        return "UNREADABLE"
    if plausible_table_pages >= _MIN_PLAUSIBLE_TABLE_PAGES_FOR_FULL:
        return "LIKELY_FULL"
    return "LIKELY_SUMMARY"


def triage_pdf(pdf_path: Path) -> dict:
    plausible_table_pages = 0
    rotated_pages = 0
    text_chunks: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text() or ""
            text_chunks.append(text.lower())
            code_matches = _page_code_matches(text)
            has_vocab = _page_has_header_vocab(text)
            if code_matches >= _MIN_CODE_MATCHES_FOR_TABLE_PAGE and has_vocab:
                plausible_table_pages += 1
            if any(not c.get("upright", True) for c in page.chars):
                rotated_pages += 1

    full_text_lower = " ".join(text_chunks)
    self_describes_partial = [m for m in _PARTIAL_MARKERS if m in full_text_lower]

    verdict = _verdict(page_count, plausible_table_pages)

    return {
        "pdf_path": str(pdf_path),
        "page_count": page_count,
        "plausible_table_pages": plausible_table_pages,
        "rotated_pages": rotated_pages,
        "self_describes_partial": self_describes_partial,
        "verdict": verdict,
    }


def _identify(pdf_path: Path, fallback_year: int | None) -> tuple[str, int | None]:
    # Two real naming conventions in play: fetch_prospectuses.py's own
    # {institution_id}_{year}.pdf, and the ad-hoc universities/{year}/{id}.pdf
    # layout used for hand-supplied files (no year in the filename, year in
    # the parent directory name instead).
    stem = pdf_path.stem
    m = re.fullmatch(r"(?P<id>[a-z0-9]+)_(?P<year>\d{4})", stem)
    if m:
        return m.group("id"), int(m.group("year"))
    parent_name = pdf_path.parent.name
    year = int(parent_name) if re.fullmatch(r"\d{4}", parent_name) else fallback_year
    return stem, year


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="append", help="one or more PDF paths; repeatable")
    ap.add_argument("--dir", help="triage every *.pdf in this directory")
    ap.add_argument("--year", type=int, default=None, help="fallback year if it can't be inferred from the path")
    args = ap.parse_args()

    pdf_paths: list[Path] = []
    if args.pdf:
        pdf_paths.extend(Path(p) for p in args.pdf)
    if args.dir:
        pdf_paths.extend(sorted(Path(args.dir).glob("*.pdf")))

    if not pdf_paths:
        print("no PDFs given -- use --pdf (repeatable) or --dir")
        return 1

    results = []
    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            print(f"skipping missing file: {pdf_path}")
            continue
        print(f"triaging {pdf_path} ...")
        result = triage_pdf(pdf_path)
        institution_id, year = _identify(pdf_path, args.year)
        result["institution_id"] = institution_id
        result["year"] = year
        results.append(result)

    results.sort(key=lambda r: -r["plausible_table_pages"])

    report_dir = Path("scripts/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"triage_{date.today().isoformat()}.md"

    lines = ["# Prospectus triage", ""]
    lines.append("| institution | verdict | pages | plausible tables | rotated pages | self-describes partial |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        partial = ", ".join(r["self_describes_partial"]) or "-"
        lines.append(
            f"| {r['institution_id']} | {r['verdict']} | {r['page_count']} | "
            f"{r['plausible_table_pages']} | {r['rotated_pages']} | {partial} |"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nwrote {report_path}\n")
    for r in results:
        print(
            f"{r['institution_id']:<10} {r['verdict']:<15} pages={r['page_count']:<4} "
            f"plausible_tables={r['plausible_table_pages']:<4} rotated_pages={r['rotated_pages']}"
        )

    print("\nstaging commands for LIKELY_FULL files (run by hand -- not executed here):")
    for r in results:
        if r["verdict"] != "LIKELY_FULL":
            continue
        if r["year"] is None:
            print(f"  {r['institution_id']}: LIKELY_FULL but year unknown -- pass --year to get a staging command")
            continue
        print(
            f"  mkdir -p data/inbox/{r['institution_id']}/{r['year']} && "
            f"cp {r['pdf_path']} data/inbox/{r['institution_id']}/{r['year']}/prospectus.pdf"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
