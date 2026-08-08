"""Heuristic triage for a candidate prospectus PDF -- no model calls, and
no per-institution profile needed, since the whole point is to sort
documents BEFORE anyone builds one. Distinguishes a full prospectus (many
per-programme requirement tables) from a summary brochure (few or none):
CPUT's 15-page file has exactly TWO real tables, TUT's has zero
qualification codes and calls itself "Part 1 of the Prospectus" -- both
looked like real prospectuses until read page by page.

Self-contained by default: does NOT import extract/classify.py or
extract/text_repair.py unless --repair-rotated is explicitly passed. This
tool's candidate code patterns are deliberately generic and plural
(institutions use different shapes, and none is known yet at triage
time), unlike classify.py's single registry-driven pattern per
institution -- reusing that machinery here would be the wrong tool, not
just an off-limits one.

--repair-rotated is the one deliberate exception: ul and vut are
demonstrably corrupted by the exact rotated-text problem
extract/text_repair.py already solves (confirmed by hand, e.g.
"SECNEICSLARENIM&LACISYHP" reversed is "PHYSICAL&MINERAL SCIENCES"), so
judging them on unrepaired text specifically wastes evidence that's
already sitting in this codebase. The flag imports
normalise_page_text() -- read-only, extract/text_repair.py itself is
never modified -- and defaults to OFF so the tool's normal behaviour and
existing verdicts stay exactly as they were without it.

Does not move or stage anything. Prints the exact staging command for a
human to run by hand for each LIKELY_FULL file.
"""

import argparse
import re
import sys
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
_MIN_ESTIMATED_ROWS_FOR_FULL = 50

# A programme-row line either (a) looks like a name followed by a run of
# numeric requirement values (level/score/year columns), or (b) contains
# both a code-shaped token and a plausible APS value. Deliberately NOT
# gated on the same code+header-vocab test as _page_code_matches/
# _page_has_header_vocab: UFH's real admission table uses a pure-numeric
# SAQA ID as its "code" column (no letters at all), so it scores zero
# code_matches under every _CANDIDATE_CODE_PATTERNS shape and would never
# be recognised as a table page by that gate -- exactly the bug this
# correction exists to fix. Row density is measured on every page's raw
# text instead and summed across the whole document.
_ROW_NAME_NUMBERS_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z .,&()'/-]{2,80}?\s+\d{1,3}(?:[.,]\d+)?(?:\s+\d{1,3}(?:[.,]\d+)?){1,6}\s*$"
)
# Standalone 2-digit token in the real-world APS range (15-48) -- wide
# enough to cover every institution's minimum score seen so far (UJ's
# range tops out at 42; CPUT's raw-percentage-sum method reaches into the
# 40s) without also matching a page/year number.
_APS_NUMBER_PATTERN = re.compile(r"\b(?:1[5-9]|[2-3]\d|4[0-8])\b")

# Third signal, added after the first two patterns still missed real
# tables on 5 downloaded documents: an NSC achievement-level cell, e.g.
# "4 (50%-59%)" (UFH's range form) or "2 (30%)" (VUT's single-percentage
# form) -- a digit immediately followed by a parenthetical percentage.
# Checked directly against real text before adding, not assumed: this
# shape occurs ~97/page on UFH's genuine dense table and only ~0.1-0.2/page
# on UJ/CPUT/TUT's real pages (prose mentioning an isolated percentage,
# not a dense repeating cell), so it doesn't trip the negative controls.
# One requirement cell exists per subject a programme requires, not per
# programme, so raw matches are divided by an estimated subjects-per-
# programme count before being added to the row estimate.
_ACHIEVEMENT_LEVEL_PATTERN = re.compile(r"\b\d\s*\(\s*\d{1,3}%?(?:\s*-\s*\d{1,3}%?)?\s*\)")
_ESTIMATED_SUBJECTS_PER_PROGRAMME = 4


def _page_code_matches(text: str) -> int:
    # Best of the candidate patterns for this one page -- institutions use
    # different code shapes (UJ requires a digit in position 2, CPUT's is
    # pure uppercase letters), and no institution profile exists yet at
    # triage time, so try them all and take whichever fits this page best.
    return max(len(pattern.findall(text)) for pattern in _CANDIDATE_CODE_PATTERNS.values())


def _page_has_header_vocab(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in _HEADER_VOCAB)


def _line_has_code_and_aps_number(line: str) -> bool:
    has_code = any(pattern.search(line) for pattern in _CANDIDATE_CODE_PATTERNS.values())
    return has_code and bool(_APS_NUMBER_PATTERN.search(line))


def _line_looks_like_programme_row(line: str) -> bool:
    line = line.strip()
    if not line:
        return False
    if _ROW_NAME_NUMBERS_PATTERN.match(line):
        return True
    return _line_has_code_and_aps_number(line)


def _page_estimated_rows(text: str) -> int:
    line_based = sum(1 for line in text.split("\n") if _line_looks_like_programme_row(line))
    achievement_cells = len(_ACHIEVEMENT_LEVEL_PATTERN.findall(text))
    return line_based + achievement_cells // _ESTIMATED_SUBJECTS_PER_PROGRAMME


def _verdict(
    page_count: int,
    plausible_table_pages: int,
    estimated_programme_rows: int,
    any_text_extracted: bool,
) -> str:
    """Pure verdict logic, kept separate from PDF I/O so it's testable
    against synthetic page-stat inputs -- same separation classify.py
    uses between signal computation and pdfplumber itself.

    Row count, not page count, decides LIKELY_FULL: a 2-page document
    with 80 dense programme rows is more useful than a 100-page one with
    40 sparse tables. plausible_table_pages stays as a second, independent
    path to LIKELY_FULL (an OR, not a replacement) for documents like UJ's
    that spread genuinely many table pages across the whole prospectus."""
    if page_count == 0 or not any_text_extracted:
        return "UNREADABLE"
    if estimated_programme_rows >= _MIN_ESTIMATED_ROWS_FOR_FULL or plausible_table_pages >= _MIN_PLAUSIBLE_TABLE_PAGES_FOR_FULL:
        return "LIKELY_FULL"
    return "LIKELY_SUMMARY"


def _load_normalise_page_text():
    # Imported lazily, only when --repair-rotated is actually passed, so
    # the default (and every existing) invocation stays genuinely
    # self-contained -- extract/text_repair.py is never touched, only
    # read from.
    sys.path.insert(0, str(Path(__file__).parent.parent / "extract"))
    from text_repair import normalise_page_text  # noqa: PLC0415
    return normalise_page_text


def triage_pdf(pdf_path: Path, repair_rotated: bool = False) -> dict:
    plausible_table_pages = 0
    estimated_programme_rows = 0
    rotated_pages = 0
    any_text_extracted = False
    text_chunks: list[str] = []

    normalise = _load_normalise_page_text() if repair_rotated else None

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text = normalise(page) if normalise is not None else (page.extract_text() or "")
            if text.strip():
                any_text_extracted = True
            text_chunks.append(text.lower())
            code_matches = _page_code_matches(text)
            has_vocab = _page_has_header_vocab(text)
            if code_matches >= _MIN_CODE_MATCHES_FOR_TABLE_PAGE and has_vocab:
                plausible_table_pages += 1
            estimated_programme_rows += _page_estimated_rows(text)
            if any(not c.get("upright", True) for c in page.chars):
                rotated_pages += 1

    full_text_lower = " ".join(text_chunks)
    self_describes_partial = [m for m in _PARTIAL_MARKERS if m in full_text_lower]

    verdict = _verdict(page_count, plausible_table_pages, estimated_programme_rows, any_text_extracted)

    return {
        "pdf_path": str(pdf_path),
        "page_count": page_count,
        "plausible_table_pages": plausible_table_pages,
        "estimated_programme_rows": estimated_programme_rows,
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
    ap.add_argument(
        "--repair-rotated", action="store_true",
        help="apply extract/text_repair.py's normalise_page_text() before scoring pages; off by default",
    )
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
        result = triage_pdf(pdf_path, repair_rotated=args.repair_rotated)
        institution_id, year = _identify(pdf_path, args.year)
        result["institution_id"] = institution_id
        result["year"] = year
        results.append(result)

    results.sort(key=lambda r: -r["estimated_programme_rows"])

    report_dir = Path("scripts/reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"triage_{date.today().isoformat()}.md"

    lines = ["# Prospectus triage", ""]
    lines.append("| institution | verdict | pages | estimated rows | plausible tables | rotated pages | self-describes partial |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        partial = ", ".join(r["self_describes_partial"]) or "-"
        lines.append(
            f"| {r['institution_id']} | {r['verdict']} | {r['page_count']} | "
            f"{r['estimated_programme_rows']} | {r['plausible_table_pages']} | {r['rotated_pages']} | {partial} |"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nwrote {report_path}\n")
    for r in results:
        print(
            f"{r['institution_id']:<10} {r['verdict']:<15} pages={r['page_count']:<4} "
            f"estimated_rows={r['estimated_programme_rows']:<5} "
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
