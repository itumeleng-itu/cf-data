"""Method B: pdfplumber's own table detection, running both "lattice"
(ruled lines) and "stream" (whitespace alignment) strategies and keeping
whichever yields more well-formed rows for the page.

Independent of Method A by construction: it never imports
extract/text_repair.py, which derives correct reading order from each
character's transform matrix (char["matrix"]). Instead, this method reads
pdfplumber's own char["upright"] flag directly for the characters inside
each table cell (via page.crop(bbox).chars, cross-referencing each
cell's bounding box from page.find_tables() back to the page's raw
characters) and reverses that cell's TEXT -- taken from Table.extract(),
pdfplumber's own multi-word cell assembly, not a second manual
page.crop(bbox).extract_text() call, which orders a multi-word rotated
cell's lines differently -- when the majority of its characters are
non-upright. upright is a coarser signal than the matrix
-- it can't reconstruct a MULTI-COLUMN run the way text_repair.py does,
only tell you "this text is sideways" -- but for a single already-
segmented table cell that's exactly the fault mode this method needs
covered, and getting it from a different, cruder mechanism than Method A
uses is what keeps the two methods' errors independent. Corrected
directly against real UJ 2027 cells (page 60): a code cell's characters
report upright=False uniformly, and reversing "Q0SC6B" once already
yields "B6CS0Q" -- no shape-based guessing, no ambiguity on symmetric
codes.

An earlier version of this method tried each cell in both its original
and reversed form against a strict recogniser and kept whichever parsed.
That produces a WRONG but plausible-looking qualification_code on any
code whose shape is symmetric under reversal (confirmed: UJ's own
[A-Z]\\d[A-Z0-9]{3,4} pattern matches "B6CS0Q" and "Q0SC6B" both), which
silently poisons reconciliation -- two methods agreeing on the wrong
code still reads as majority-confidence. Reading upright directly removes
that ambiguity outright rather than working around it.
"""

import re
import sys
from pathlib import Path
from typing import Any

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import CellValue, build_subject_tree, interpret_cell, resolve_subject_column  # noqa: E402

_APS_PATTERN = re.compile(r"^\d{2}$")
_LATTICE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
_STREAM_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}


def extract_geometric(pdf_path: Path, profile: dict, table_pages: list[int]) -> list[dict]:
    layout = profile["layout"]
    code_pattern = re.compile(layout["code_pattern"])
    records: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num in table_pages:
            if not 1 <= page_num <= len(pdf.pages):
                continue
            page = pdf.pages[page_num - 1]
            records.extend(_extract_page(page, page_num, profile, code_pattern))
    return records


def _is_reversed(page: Any, bbox: tuple[float, float, float, float] | None) -> bool:
    """True if the majority of the bbox's OWN characters report
    upright=False. A per-cell decision, not a per-page one -- on a
    rotated-headers document most cells need it and a few (names, APS
    scores, career prose) don't, sitting side by side in the same row."""
    if bbox is None:
        return False
    try:
        chars = page.crop(bbox).chars
    except ValueError:
        # The "text" (stream) strategy can propose a cell bbox that falls
        # entirely outside the page's own bounding box -- confirmed on a
        # real UJ page, a degenerate table pdfplumber's whitespace-based
        # detection found near a margin, not a real table at all. Nothing
        # reliable can be read from it either way, so this cell is
        # treated the same as one with no characters: not reversed.
        return False
    if not chars:
        return False
    return sum(1 for c in chars if not c.get("upright", True)) / len(chars) > 0.5


def _flatten_rows(page: Any, settings: dict) -> list[list[str | None]]:
    """Text comes from Table.extract() (pdfplumber's own multi-line cell
    text assembly), not a manual page.crop(bbox).extract_text() -- the
    two disagree on internal line order for a cell with more than one
    rotated word (confirmed directly: UJ's merged "Mathematics /
    Technical Mathematics" header crops to a different line order than
    Table.extract() gives), and Table.extract()'s is the one that
    reverses back into a cleanly re-splittable "Technical\\nMathematics\\n
    /\\nMathematics". Only the REVERSE/no-reverse decision comes from the
    bbox's raw chars -- the text itself still comes from the table API
    that already handles multi-word cell assembly correctly."""
    rows: list[list[str | None]] = []
    for table in page.find_tables(settings):
        extracted = table.extract()
        for row, texts in zip(table.rows, extracted):
            cells = []
            for bbox, text in zip(row.cells, texts):
                if text and _is_reversed(page, bbox):
                    text = text[::-1]
                cells.append(text)
            rows.append(cells)
    return rows


def _matching_code(cell: str | None, code_pattern: re.Pattern) -> str | None:
    if not cell:
        return None
    stripped = cell.strip()
    return stripped if code_pattern.fullmatch(stripped) else None


def _score_rows(rows: list[list[str | None]], code_pattern: re.Pattern) -> int:
    return sum(1 for row in rows if any(_matching_code(cell, code_pattern) for cell in row))


def _resolve_header_cell(text: str | None, profile: dict) -> str | list[str] | None:
    if not text:
        return None
    parts = [p.strip() for p in re.split(r"/", text) if p.strip()]
    if len(parts) > 1:
        resolved = [resolve_subject_column(p, profile) for p in parts]
        resolved = [r for r in resolved if r is not None]
        if len(resolved) > 1:
            return resolved
        return resolved[0] if resolved else None
    return resolve_subject_column(text, profile)


def _marker_redirect(row: list[str | None], resolved_columns: dict[int, str | list[str]], profile: dict) -> dict[int, int]:
    """An unresolved header cell that's just an alternative-phrase marker
    ("OR") has no subject of its own -- its data belongs to the next
    resolved column to its right, the same convention Method A uses (see
    textlayer.py). Column INDEX order stands in for x0 order here:
    pdfplumber's own table cells are already left-to-right."""
    alt_phrases = {p.strip().lower() for p in profile["layout"].get("alternative_phrases", [])}
    redirect: dict[int, int] = {}
    for col, cell in enumerate(row):
        if col in resolved_columns or not cell:
            continue
        if cell.strip().lower() not in alt_phrases:
            continue
        later = [c for c in resolved_columns if c > col]
        if later:
            redirect[col] = min(later)
    return redirect


_MIN_HEADER_KEYWORD_HITS = 2


def _is_header_row(row: list[str | None], profile: dict) -> bool:
    """A row counts as a header occurrence if at least two of its cells
    match profile.layout.header_keywords -- generic, reused from the same
    per-institution config Method A's section detection uses (see
    textlayer.py module docstring point 3). Requiring two, not one,
    matters here specifically: a single keyword like "CAREER" can appear
    inside ordinary career-description prose by coincidence ("pursue a
    career in..."), which a real header row's cell never has to compete
    with -- a genuine header always carries several keywords across
    several of its own cells at once."""
    keywords = [k.lower() for k in profile["layout"].get("header_keywords", [])]
    hits = sum(1 for cell in row if cell and any(kw in cell.strip().lower() for kw in keywords))
    return hits >= _MIN_HEADER_KEYWORD_HITS


def _build_header_mapping(
    row: list[str | None], profile: dict,
) -> tuple[dict[int, str | list[str]], dict[int, int]]:
    columns: dict[int, str | list[str]] = {}
    for col, cell in enumerate(row):
        resolved = _resolve_header_cell(cell, profile)
        if resolved is not None:
            columns[col] = resolved
    redirect = _marker_redirect(row, columns, profile)
    return columns, redirect


def _row_name(row: list[str | None], code_col: int) -> str | None:
    candidates = [cell for i, cell in enumerate(row) if i != code_col and cell and not cell.strip().isdigit()]
    if not candidates:
        return None
    return " ".join(c.strip().replace("\n", " ") for c in candidates[:1]) or None


def _row_aps(row: list[str | None]) -> int | None:
    for cell in row:
        if cell and _APS_PATTERN.fullmatch(cell.strip()):
            return int(cell.strip())
    return None


def _row_campus(row: list[str | None], profile: dict) -> list[str]:
    tokens = set(profile["layout"].get("campus_tokens", []))
    found = []
    for cell in row:
        if not cell:
            continue
        for token in tokens:
            if token in cell:
                found.append(token)
    return found


def _extract_page(page: Any, page_num: int, profile: dict, code_pattern: re.Pattern) -> list[dict]:
    lattice_rows = _flatten_rows(page, _LATTICE_SETTINGS)
    stream_rows = _flatten_rows(page, _STREAM_SETTINGS)
    rows = lattice_rows if _score_rows(lattice_rows, code_pattern) >= _score_rows(stream_rows, code_pattern) else stream_rows
    if not rows:
        return []

    # A page can repeat its full header row once per "Bachelor of X"
    # sub-table, and a later occurrence isn't guaranteed to share column
    # positions with an earlier one (confirmed on UJ page 68: a second
    # block inserts a Mathematics Literacy column, shifting every column
    # after it). A single page-wide "best" header, applied to every row,
    # silently applies the WRONG block's columns to the OTHER block's
    # data. Fixed with a sequential sweep instead: each header occurrence
    # replaces the column mapping used for every row until the next one.
    subject_columns: dict[int, str | list[str]] = {}
    redirect: dict[int, int] = {}

    records = []
    for row in rows:
        if _is_header_row(row, profile):
            subject_columns, redirect = _build_header_mapping(row, profile)
            continue
        if not subject_columns:
            continue
        code_col = next((c for c, cell in enumerate(row) if _matching_code(cell, code_pattern)), None)
        if code_col is None:
            continue
        code = _matching_code(row[code_col], code_pattern)

        row_cells: list[tuple[str, Any]] = []
        for col, slugs in subject_columns.items():
            if col >= len(row):
                continue
            extra_cols = [src for src, dst in redirect.items() if dst == col and src < len(row)]
            combined = " ".join(text for text in ([row[col]] + [row[c] for c in extra_cols]) if text)
            cell = interpret_cell(combined, profile)
            slug_list = slugs if isinstance(slugs, list) else [slugs]
            for i_slug, slug in enumerate(slug_list):
                if i_slug == 0 or cell.kind != "level":
                    row_cells.append((slug, cell))
                else:
                    row_cells.append((slug, CellValue(kind="alternative", level=cell.level, raw=cell.raw)))

        tree, excluded = build_subject_tree(row_cells, profile)

        records.append({
            "qualification_code": code,
            "name": _row_name(row, code_col),
            "faculty": None,
            "campus": _row_campus(row, profile),
            "duration_years": None,
            "extended": None,
            "requirements": {
                "nsc": {
                    "score": [{"min_score": _row_aps(row)}] if _row_aps(row) is not None else None,
                    "subjects": tree,
                    "excluded_subjects": sorted(excluded),
                },
            },
            "selection_notes": [],
            "career_text": None,
            "source_page": page_num,
        })
    return records
