"""DUT-specific prose-driven extraction. NOT a generalisation of Method D
(coordinate.py, built for UJ) -- ported from direct inspection of
dut_2027.pdf (175 pages), because DUT's document shape defeats Method
D's whole model: the qualification code and programme name live in PAGE
PROSE above the requirements table, never in a table cell (confirmed
directly, p.100/p.61/p.133), and a programme's code/name and its
requirements table are not always on the same page (confirmed, p.61's
code sits on p.61, its table on p.62). Phase 8.5 step 8 already proved
Method D produces only false positives here (ordinary words like
'TOTAL'/'PERSON' coincidentally matching the loose code_pattern inside
the fee/module table) -- this module never looks at a table for the
code at all, so that whole failure class doesn't apply here.

Reuses (never reimplements) extract/methods/shared.py:
  - extract_row_subject_cells: DUT's NSC sub-table is exactly the
    "subject name is DATA, not a column header" shape this already
    handles -- 'Compulsory Subjects' / 'NSC Rating Code' as two
    adjacent columns, one row per subject. The subject-name column's
    OWN position varies (p.100/p.62: column 0; p.117: column 1, behind
    an empty spacer column from a more finely-split lattice table), so
    it is located by its cell CONTENT ('Compulsory Subjects'), never
    assumed to be a fixed index -- see _find_compulsory_subjects_cell.
  - build_subject_tree + profile.layout.mutually_exclusive_subjects:
    "Mathematics OR" (one row) then "Technical Mathematics" (the next
    row) both become plain 'subject' nodes and get auto-merged into an
    `any` -- no OR-marker mechanism needed at all, unlike UJ's column
    layout.
  - scan_page_exclusions: catches DUT's own NB-note exclusions (e.g.
    "NSC Mathematical Literacy will not be accepted as a substitute for
    the subject NSC Mathematics") the same way it already does for UJ.

rotated_headers is false for this document (confirmed, zero non-upright
characters across all 175 pages) -- no rotation repair needed anywhere;
plain page.extract_text() is reading-order-correct.

KNOWN GAPS, reported rather than hidden:
  - DUT's own scoring convention is not a UJ-style APS sum at all -- it
    is stated in prose ("ranked according to the sum of their scores for
    Mathematics and Physical Science, subject to a minimum combined
    score of 100%", p.100) and DIFFERS by programme. No numeric score is
    invented; the raw prose is attached to selection_notes instead (the
    same "surface, don't guess" policy this whole codebase already
    applies to footnotes and unconvertible conditions).
  - A row naming no single specific subject ("In addition: TWO
    recognized NSC 20 credit subjects...") has no schema node to become
    -- extract_row_subject_cells already skips it (find_subject_alias
    returns None), so this genuine requirement is silently absent from
    the tree. Same class of gap as UFH's own "additional subjects" rows.
  - Full-document run (2026-08-23): 98 unique codes, 0 duplicates, 92/98
    (94%) with a real non-empty subjects tree. The remaining 6 (BCCYC3,
    BHDRD1, DISOMI, DISMF1, DIPAP1, DIPPM1) were not diagnosed further
    this pass -- likely a further table-shape variant this module
    doesn't yet handle, not re-tuned to force a result.
  - Duration/extended is only recognised from the "(N-YRS ...)" -style
    annotation (p.133's 'BCHNSG (4-YRS MAINSTREAM)'); a same-meaning but
    differently-worded annotation seen elsewhere ('DIACCF (DBN -4 Year
    Extended Curriculum Programme)', p.16) is not matched, so those
    records get duration_years=None rather than a guessed value.
"""

import re
import sys
from pathlib import Path
from typing import Any

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from footnotes import find_footnotes_for_code  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coordinate_cells import cell_text  # noqa: E402
from shared import (  # noqa: E402
    build_subject_tree,
    extract_row_subject_cells,
    scan_page_exclusions,
)

_CODE_LABEL = re.compile(r"^qualification code\s*:\s*(.*)$", re.I)
_LOCATION_LABEL = re.compile(r"^location\s*:\s*(.*)$", re.I)
_NQF_LABEL = re.compile(r"^nqf level\s*:", re.I)
_CODE_BLOCK_STOP = re.compile(r"^(location|description|nqf level|saqa id)\s*:", re.I)
_DURATION_ANNOTATION = re.compile(r"\((\d)[-\s]?YRS?\.?\s*([A-Za-z ]*)\)", re.I)
_COMPULSORY_SUBJECTS_CELL = re.compile(r"^compulsory subjects$", re.I)
_NUMBERED_NOTE = re.compile(r"^\d+\.\s+")
_SCORE_NOTE = re.compile(r"\b(rank|score|combined|percent|%|aps)\b", re.I)


def _score_notes(text: str) -> list[str]:
    """DUT states its own scoring rule in a numbered NB note, not a
    clean numeric column (e.g. p.100: '3. Applicants with a NSC will be
    ranked according to the sum of their scores for Mathematics and
    Physical Science, subject to a minimum combined score of 100%.') --
    never invented as a fake numeric score; the raw sentence is
    attached to selection_notes so a human (or a future DUT-specific
    scorer) sees the real rule."""
    return [line.strip() for line in text.splitlines() if _NUMBERED_NOTE.match(line.strip()) and _SCORE_NOTE.search(line)]


def _parse_code_block(lines: list[str], start_idx: int, code_pattern: re.Pattern) -> list[tuple[str, int | None, bool]]:
    """From the 'Qualification Code:' line onward, gather this line plus
    up to a few continuation lines (p.133's two-code, two-duration case:
    'BCHNSG (4-YRS MAINSTREAM)' / 'BCHNSE (5-YRS EXTENDED CURRICULUM)'
    each on their own line), stopping at the next recognised label.
    Returns [(code, duration_years, extended), ...]."""
    m = _CODE_LABEL.match(lines[start_idx].strip())
    buf = [m.group(1)] if m else []
    i = start_idx + 1
    while i < len(lines) and len(buf) < 4:
        line = lines[i].strip()
        if not line or _CODE_BLOCK_STOP.match(line):
            break
        buf.append(line)
        i += 1
    blob = " ".join(buf)

    results = []
    for match in code_pattern.finditer(blob):
        code = match.group(0)
        tail = blob[match.end():match.end() + 40]
        dm = _DURATION_ANNOTATION.search(tail)
        duration = int(dm.group(1)) if dm else None
        extended = bool(dm and "extend" in dm.group(2).lower())
        results.append((code, duration, extended))
    return results


def _programme_name(lines: list[str]) -> str | None:
    """The programme name is the prose line immediately before 'NQF
    Level:' -- confirmed on every sampled page (p.100, p.61); no name is
    invented if that anchor isn't found."""
    idx = next((i for i, line in enumerate(lines) if _NQF_LABEL.match(line.strip())), None)
    if idx is None or idx == 0:
        return None
    return lines[idx - 1].strip() or None


def _location(lines: list[str]) -> str | None:
    for line in lines:
        m = _LOCATION_LABEL.match(line.strip())
        if m:
            return m.group(1).strip() or None
    return None


def _find_compulsory_subjects_cell(row: list[str]) -> int | None:
    """Column index of a 'Compulsory Subjects' cell in this row, or None.
    NOT assumed to be column 0 -- confirmed directly (p.117) that some
    pages' lattice detection splits the table into many sparse,
    mostly-empty sub-columns (21 columns for a 3-system comparison that
    elsewhere is 3 or 7), pushing 'Compulsory Subjects' to column 1 with
    an empty spacer column before it. Searching the row's cells directly,
    rather than assuming a position, is the same fix already applied
    twice this pass (table detection, page-break continuation) for the
    same underlying reason: DUT's lattice tables are not uniformly
    shaped across 175 pages."""
    for idx, cell in enumerate(row):
        if _COMPULSORY_SUBJECTS_CELL.match(flat(cell or "")):
            return idx
    return None


def _find_requirements_table(page: Any, profile: dict) -> Any:
    """The first table on this page containing a 'Compulsory Subjects'
    cell -- NOT a header-row keyword-hit-count check (tried first,
    dropped): confirmed directly on p.17 that this document's row0
    header cell can be GARBLED by the same overlapping-text-layer
    artefact found on UFH (e.g. 'CERTIFICATEEn (tNrSyC R) equire
    NATIONAL SENIOR' where 'Entry Requirements:' and 'NATIONAL SENIOR
    CERTIFICATE' interleave), which breaks any multi-word keyword
    substring match on that row -- while the 'Compulsory Subjects' cell
    itself reads perfectly clean on the SAME table. Anchoring on the
    exact cell _read_nsc_columns needs anyway is both more robust and
    one fewer independent assumption than a separate header-row check."""
    table_settings = profile["layout"]["table_settings"]
    for table in page.find_tables(table_settings):
        for row in table.rows:
            texts = [cell_text(page, c) for c in row.cells]
            if _find_compulsory_subjects_cell(texts) is not None:
                return table
    return None


def flat(text: str) -> str:
    return " ".join((text or "").split())


def _table_rows_text(page: Any, table: Any) -> list[list[str]]:
    return [[cell_text(page, c) for c in row.cells] for row in table.rows]


def _read_nsc_columns(
    page: Any, table: Any, profile: dict, next_page: Any = None,
) -> tuple[dict, set[str]]:
    """NSC's own 'Compulsory Subjects' cell marks its subject-name
    column; the next non-empty cell to its right in that SAME row is the
    rating column (its own header cell, e.g. 'NSC Rating Code', may
    itself be split across further empty spacer columns -- see
    _find_compulsory_subjects_cell). Every row after the header row is a
    subject row; feeds through shared.extract_row_subject_cells exactly
    like a UFH-style rows_per_programme:"many" institution would.

    next_page: if the table's own last row IS the header (no data rows
    follow it in the SAME table object), fall back to the first table's
    rows on the NEXT page as a continuation -- confirmed directly (p.92):
    the ruling-line table object ends right at 'Compulsory Subjects'
    because of an ordinary page break, and the actual subject rows
    resume on p.93 with NO repeated header at all (so a second
    'Compulsory Subjects' anchor search there would find nothing). The
    continuation page's rows are trusted at face value, in table order,
    with no re-validation -- there is no header left to validate against.
    The subject/rating column indices found on THIS page's header are
    reused for the continuation page's rows, since it carries no header
    of its own to re-derive them from."""
    rows_text = _table_rows_text(page, table)
    header_idx = subj_col = None
    for i, row in enumerate(rows_text):
        col = _find_compulsory_subjects_cell(row)
        if col is not None:
            header_idx, subj_col = i, col
            break
    if header_idx is None:
        return {"kind": "all", "rules": []}, set()

    header_row = rows_text[header_idx]
    rating_col = next(
        (j for j in range(subj_col + 1, len(header_row)) if flat(header_row[j] or "")),
        subj_col + 1,
    )

    data_rows = rows_text[header_idx + 1:]
    if not data_rows and next_page is not None:
        tables = next_page.find_tables(profile["layout"]["table_settings"])
        if tables:
            data_rows = _table_rows_text(next_page, tables[0])

    pairs = []
    for row in data_rows:
        if len(row) <= rating_col:
            continue
        pairs.extend(extract_row_subject_cells([row[subj_col], row[rating_col]], profile))

    return build_subject_tree(pairs, profile)


def extract_dut(pdf_path: Path, profile: dict, table_pages: list[int]) -> tuple[list[dict], dict]:
    """Contract-compatible with Method D's (pdf_path, profile,
    table_pages) -> (records, stats) shape. table_pages is accepted for
    contract consistency but not used to filter -- DUT's code/table
    pages are discovered by page-prose content, not pre-classified."""
    layout = profile["layout"]
    code_pattern = re.compile(layout["code_pattern"])

    records: list[dict] = []
    seen: set[str] = set()
    pending: dict | None = None  # {"codes", "name", "campus", "page"}

    def _emit(
        pdf: Any, pending: dict, tree: dict | None, excluded: set[str],
        page_number: int | None, score_notes: list[str] | None = None,
    ) -> None:
        for code, duration, extended in pending["codes"]:
            if code in seen:
                continue
            seen.add(code)
            footnotes = find_footnotes_for_code(pdf, page_number, code, profile) if page_number and layout.get("footnote_markers") else []
            notes = list(score_notes or []) + [f"Footnote {fn['marker']}: {fn['footnote_text']}" for fn in footnotes]
            records.append({
                "qualification_code": code,
                "name": pending["name"],
                "faculty": None,
                "campus": [pending["campus"]] if pending.get("campus") else [],
                "duration_years": duration,
                "extended": extended,
                "requirements": {
                    "nsc": {
                        "score": None,
                        "subjects": tree or {"kind": "all", "rules": []},
                        "excluded_subjects": sorted(excluded),
                    },
                },
                "selection_notes": notes,
                "career_text": None,
                "source_page": page_number or pending["page"],
                "confidence": "flagged",  # no numeric score ever derived here -- always review
            })

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lines = text.splitlines()
            page_number = page_index + 1

            code_line_idx = next((i for i, line in enumerate(lines) if _CODE_LABEL.match(line.strip())), None)
            if code_line_idx is not None:
                if pending is not None:
                    _emit(pdf, pending, None, set(), None)  # no table ever found for the previous programme
                codes = _parse_code_block(lines, code_line_idx, code_pattern)
                if codes:
                    pending = {
                        "codes": codes,
                        "name": _programme_name(lines),
                        "campus": _location(lines),
                        "page": page_number,
                    }
                else:
                    pending = None

            if pending is not None:
                table = _find_requirements_table(page, profile)
                if table is not None:
                    next_page = pdf.pages[page_index + 1] if page_index + 1 < len(pdf.pages) else None
                    tree, excluded = _read_nsc_columns(page, table, profile, next_page)
                    excluded = excluded | set(scan_page_exclusions(text, profile))
                    _emit(pdf, pending, tree, excluded, page_number, _score_notes(text))
                    pending = None

        if pending is not None:
            _emit(pdf, pending, None, set(), None)

    stats = {
        "records": len(records),
        "unique_codes": len({r["qualification_code"] for r in records}),
        "with_subjects": sum(1 for r in records if r["requirements"]["nsc"]["subjects"]["rules"]),
        "with_excluded": sum(1 for r in records if r["requirements"]["nsc"]["excluded_subjects"]),
    }
    return records, stats
