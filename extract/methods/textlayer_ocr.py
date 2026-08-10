"""Drop-in replacement for textlayer.py's Method A that reads pre-computed
Unlimited-OCR Markdown from disk instead of running pdfplumber's word/char
extraction live. The OCR model itself is GPU-only (see
scripts/run_unlimited_ocr.py, an offline preprocessing step) -- this
module never imports torch/transformers and never calls the model; it
only reads whatever ocr_cache.py's store_cached_markdown() already wrote.

Cell interpretation and rule-tree construction reuse shared.py's
interpret_cell/build_subject_tree/resolve_subject_column exactly as
textlayer.py does -- turning a cell's text + column subject into a
requirement fragment is identical logic regardless of how the raw text
was obtained.

The Markdown table parser below (_parse_markdown_page) is scaffold logic,
NOT verified against a real Unlimited-OCR sample -- no GPU run has
produced one in this repo yet. It assumes a standard GFM pipe-table with
one header row, one code column (matched via profile.layout.code_pattern
against real cell values, not header text), and correct left-to-right
reading order already resolved by the OCR model (unlike textlayer.py,
which has to reconstruct reading order itself from rotated PDF runs).
Calibrate the column-role heuristics (name/campus/APS column detection
below) against a real cached page before trusting it on production data.
"""

import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_cache import DEFAULT_CACHE_DIR, get_cached_markdown, remove_det  # noqa: E402
from shared import build_subject_tree, interpret_cell, resolve_subject_column  # noqa: E402
from textlayer import extract_textlayer  # noqa: E402

logger = logging.getLogger(__name__)

_APS_PATTERN = re.compile(r"\b(\d{2})\b")
_SEPARATOR_ROW = re.compile(r"^:?-+:?$")


def extract_textlayer_ocr(
    pdf_path: Path,
    profile: dict,
    table_pages: list[int],
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> list[dict]:
    layout = profile["layout"]
    if not layout.get("rotated_headers"):
        return []

    code_pattern = re.compile(layout["code_pattern"])
    records: list[dict] = []
    for page_num in table_pages:
        markdown = get_cached_markdown(pdf_path, page_num, cache_dir)
        if markdown is None:
            logger.warning(
                "OCR cache miss for %s page %d -- falling back to extract_textlayer", pdf_path, page_num,
            )
            records.extend(extract_textlayer(pdf_path, profile, [page_num]))
            continue
        records.extend(_parse_markdown_page(markdown, page_num, profile, code_pattern))
    return records


def _split_markdown_table_rows(markdown: str) -> list[list[str]]:
    rows = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(_SEPARATOR_ROW.fullmatch(c) for c in cells):
            continue  # the |---|---|---| header/body divider row
        rows.append(cells)
    return rows


def _find_code_column(data_rows: list[list[str]], code_pattern: re.Pattern) -> int | None:
    """Identified by CONTENT, not header text -- the header cell's own
    wording ("Qualification Code", "Code", etc.) is not reliable enough to
    match against, but the code pattern itself is exact."""
    if not data_rows:
        return None
    width = max(len(r) for r in data_rows)
    best_idx, best_hits = None, 0
    for idx in range(width):
        hits = sum(1 for r in data_rows if idx < len(r) and code_pattern.fullmatch(r[idx].strip()))
        if hits > best_hits:
            best_idx, best_hits = idx, hits
    return best_idx if best_hits else None


def _classify_header(idx: int, header_text: str, code_col: int, profile: dict) -> tuple[str, str | None]:
    if idx == code_col:
        return "code", None
    resolved = resolve_subject_column(header_text, profile)
    if resolved is not None:
        return "subject", resolved
    lowered = header_text.strip().lower()
    if "aps" in lowered or "score" in lowered:
        return "aps", None
    if "campus" in lowered:
        return "campus", None
    if any(k in lowered for k in ("programme", "qualification", "course", "name")):
        return "name", None
    return "ignored", None


def _parse_markdown_page(markdown: str, page_num: int, profile: dict, code_pattern: re.Pattern) -> list[dict]:
    clean = remove_det(markdown)
    rows = _split_markdown_table_rows(clean)
    if len(rows) < 2:
        return []

    header, *data_rows = rows
    code_col = _find_code_column(data_rows, code_pattern)
    if code_col is None:
        return []

    subject_cols: dict[int, str] = {}
    name_col: int | None = None
    aps_col: int | None = None
    campus_col: int | None = None
    for idx, header_text in enumerate(header):
        role, slug = _classify_header(idx, header_text, code_col, profile)
        if role == "subject":
            subject_cols[idx] = slug
        elif role == "name" and name_col is None:
            name_col = idx
        elif role == "aps" and aps_col is None:
            aps_col = idx
        elif role == "campus" and campus_col is None:
            campus_col = idx

    campus_tokens = set(profile["layout"].get("campus_tokens", []))

    records = []
    for row in data_rows:
        if code_col >= len(row) or not code_pattern.fullmatch(row[code_col].strip()):
            continue
        code = row[code_col].strip()

        row_cells = [
            (slug, interpret_cell(row[idx] if idx < len(row) else "", profile))
            for idx, slug in subject_cols.items()
        ]
        tree, excluded = build_subject_tree(row_cells, profile)

        name = row[name_col].strip() if name_col is not None and name_col < len(row) else None
        campus = (
            [t for t in campus_tokens if t in row[campus_col]]
            if campus_col is not None and campus_col < len(row)
            else []
        )
        aps = None
        if aps_col is not None and aps_col < len(row):
            match = _APS_PATTERN.search(row[aps_col])
            if match:
                aps = int(match.group(1))

        records.append({
            "qualification_code": code,
            "name": name,
            "faculty": None,
            "campus": campus,
            "duration_years": None,
            "extended": None,
            "requirements": {
                "nsc": {
                    "score": [{"min_score": aps}] if aps is not None else None,
                    "subjects": tree,
                    "excluded_subjects": sorted(excluded),
                },
            },
            "selection_notes": [],
            "career_text": None,
            "source_page": page_num,
        })
    return records
