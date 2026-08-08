"""Method A: pdfplumber word/character extraction with coordinates. Row
clustering by y-position (top), column clustering by x-position, using
extract/text_repair.py's _group_runs() for any column whose text is
rotated -- never normalise_page_text(), which appends corrected runs to
the baseline rather than replacing them, so a naive consumer would see
rotated headers twice in two different (and differently wrong) orderings.

Two problems confirmed against real UJ 2027 data before writing this,
neither solvable by trusting _group_runs()'s own run/column boundaries
directly:

1. Row alignment: _group_runs() splits a rotated column into "runs" using
   a generic advance-direction gap threshold tuned for presence
   detection, not exact row boundaries. Two consecutive rows with an
   IDENTICAL cell value (e.g. two rows both requiring "5 (60%+)") sit
   close enough along the advance direction that they merge into one run
   spanning both rows. Fix: the qualification-code column's runs never
   merge (codes are never identical between rows), so its runs are used
   as the reliable row anchors -- every other column's runs are flattened
   back into one correctly-ordered character stream and re-split against
   the code column's row bands by nearest geometric row-centre.

2. Column association: a rotated run's perpendicular coordinate
   (text_repair._perp_key) differs enough between a column's HEADER text
   and its DATA cells (different font/baseline) that naive exact or
   rounded-perp matching puts them in different buckets -- confirmed
   directly: "Qualification Code"'s header perp and its data codes' perp
   differ by 3.3 units, and UJ's merged "Mathematics / Technical
   Mathematics" header sits on two further fragments each ~5-37 units
   from the data column they both label. Fix: header runs (identified by
   sitting far along the advance direction, past the last real data row)
   are x0-gap-clustered into header groups first; every data run is then
   assigned to its NEAREST header group by x0 distance, not an exact or
   rounded coordinate match.

Only the rotated_headers=True path is implemented. A non-rotated layout
returns an empty result -- Method B's native pdfplumber table detection
is the intended primary method for those documents, and there is no
non-rotated ground-truth institution yet to validate a second
row/column-clustering implementation against.

3. Multiple header blocks per page: confirmed directly on UJ page 68
   (Faculty of Health Sciences) -- a page can repeat the FULL header row
   once per "Bachelor of X" sub-table, and a later block's columns are
   not guaranteed to be at the same x0 as an earlier block's (page 68's
   first block has 4 subject columns -- English/Mathematics/Physical
   Science/Life Science -- and its second block has 5, with Mathematics
   Literacy inserted, compressing every column after it leftward).
   Clustering all header-range runs into ONE set of columns, as if the
   whole page shared a single layout, silently applies the WRONG block's
   column positions to the OTHER block's rows. Fixed generally, not as
   an institution-specific case: every run matching one of
   profile.layout.header_keywords is a section-boundary marker: they're
   advance-clustered into distinct header-block occurrences, and every
   OTHER run on the page (header or data) is assigned to whichever
   block's advance range it falls into before column association ever
   happens, so each block gets its own independent column mapping.
"""

import re
import sys
from pathlib import Path
from typing import Any

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from text_repair import _advance_key, _group_runs  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import build_subject_tree, interpret_cell, resolve_subject_column  # noqa: E402

_APS_PATTERN = re.compile(r"^\d{2}$")
_HEADER_ADVANCE_MARGIN = 200.0
_HEADER_GROUP_GAP = 15.0


def extract_textlayer(pdf_path: Path, profile: dict, table_pages: list[int]) -> list[dict]:
    layout = profile["layout"]
    if not layout.get("rotated_headers"):
        return []

    code_pattern = re.compile(layout["code_pattern"])
    records: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num in table_pages:
            if not 1 <= page_num <= len(pdf.pages):
                continue
            page = pdf.pages[page_num - 1]
            records.extend(_extract_page(page, page_num, profile, code_pattern))
    return records


def _run_x0(run: list[dict]) -> float:
    return sum(c["x0"] for c in run) / len(run)


def _run_text(run: list[dict]) -> str:
    return "".join(c["text"] for c in run)


def _cluster_by_x0(runs: list[list[dict]], gap: float) -> list[list[list[dict]]]:
    ordered = sorted(runs, key=_run_x0)
    groups: list[list[list[dict]]] = []
    current: list[list[dict]] = []
    prev_x0: float | None = None
    for run in ordered:
        x0 = _run_x0(run)
        if current and prev_x0 is not None and x0 - prev_x0 > gap:
            groups.append(current)
            current = []
        current.append(run)
        prev_x0 = x0
    if current:
        groups.append(current)
    return groups


def _cluster_by_advance(runs: list[list[dict]], gap: float) -> list[list[list[dict]]]:
    ordered = sorted(runs, key=lambda r: _advance_key(r[0]))
    groups: list[list[list[dict]]] = []
    current: list[list[dict]] = []
    prev_advance: float | None = None
    for run in ordered:
        advance = _advance_key(run[0])
        if current and prev_advance is not None and advance - prev_advance > gap:
            groups.append(current)
            current = []
        current.append(run)
        prev_advance = advance
    if current:
        groups.append(current)
    return groups


def _extract_page(page: Any, page_num: int, profile: dict, code_pattern: re.Pattern) -> list[dict]:
    non_upright = [c for c in page.chars if not c.get("upright", True)]
    if not non_upright:
        return []

    all_runs = _group_runs(non_upright)
    if not any(code_pattern.fullmatch(_run_text(run)) for run in all_runs):
        return []

    header_keywords = [k.lower() for k in profile["layout"].get("header_keywords", [])]
    keyword_runs = [
        run for run in all_runs if any(kw in _run_text(run).strip().lower() for kw in header_keywords)
    ]
    if not keyword_runs:
        return []

    # Descending: this rotation's reading order puts an EARLIER section's
    # header block at a HIGHER advance value than a later section's (see
    # module docstring point 1) -- each repeated header marks where the
    # PREVIOUS section's rows end and end an new one begins.
    section_boundaries = sorted(
        (sum(_advance_key(r[0]) for r in g) / len(g) for g in _cluster_by_advance(keyword_runs, _HEADER_ADVANCE_MARGIN)),
        reverse=True,
    )

    def _section_index(advance: float) -> int:
        for i, boundary in enumerate(section_boundaries):
            lower = section_boundaries[i + 1] if i + 1 < len(section_boundaries) else float("-inf")
            if lower < advance <= boundary + 1.0:
                return i
        return len(section_boundaries) - 1

    sections: list[list[list[dict]]] = [[] for _ in section_boundaries]
    for run in all_runs:
        sections[_section_index(_advance_key(run[0]))].append(run)

    upright_page = page.filter(lambda obj: obj.get("object_type") != "char" or obj.get("upright", True))
    upright_words = upright_page.extract_words()

    records = []
    for section_runs in sections:
        records.extend(_extract_section(section_runs, upright_words, page_num, profile, code_pattern))
    return records


def _extract_section(
    all_runs: list[list[dict]], upright_words: list[dict], page_num: int, profile: dict, code_pattern: re.Pattern,
) -> list[dict]:
    code_runs = [run for run in all_runs if code_pattern.fullmatch(_run_text(run))]
    if not code_runs:
        return []

    threshold = max(_advance_key(run[-1]) for run in code_runs) + _HEADER_ADVANCE_MARGIN
    header_runs = [run for run in all_runs if _advance_key(run[0]) > threshold]
    data_runs = [run for run in all_runs if _advance_key(run[0]) <= threshold]

    header_groups = _cluster_by_x0(header_runs, _HEADER_GROUP_GAP)
    group_centres = [sum(_run_x0(r) for r in g) / len(g) for g in header_groups]
    group_text = [" ".join(_run_text(r) for r in sorted(g, key=_run_x0)) for g in header_groups]
    group_resolved = [_resolve_header(t, profile) for t in group_text]

    # A header group that's just an alternative-phrase marker ("OR") never
    # resolves to a subject on its own -- confirmed on real UJ data: the
    # "OR" marker sits in its own x0 cluster, roughly equidistant between
    # Physical Science and Technical Science's headers, so nearest-x0
    # alone would either drop it or misattribute it. Its data belongs
    # with whichever subject column it visually precedes (the alternative
    # it's marking), so it's redirected there rather than resolved.
    alt_phrases = {p.strip().lower() for p in profile["layout"].get("alternative_phrases", [])}
    marker_redirect: dict[int, int] = {}
    for i, text in enumerate(group_text):
        if group_resolved[i] is not None or text.strip().lower() not in alt_phrases:
            continue
        candidates = [j for j in range(len(group_centres)) if group_centres[j] > group_centres[i] and group_resolved[j] is not None]
        if candidates:
            marker_redirect[i] = min(candidates, key=lambda j: group_centres[j])

    # Assign every data run to its nearest header group by x0 distance.
    data_by_group: list[list[list[dict]]] = [[] for _ in header_groups]
    code_group_index: int | None = None
    for run in data_runs:
        x0 = _run_x0(run)
        idx = min(range(len(group_centres)), key=lambda i: abs(group_centres[i] - x0)) if group_centres else None
        if idx is None:
            continue
        idx = marker_redirect.get(idx, idx)
        data_by_group[idx].append(run)
        if code_pattern.fullmatch(_run_text(run)):
            code_group_index = idx

    if code_group_index is None:
        return []

    bands = _row_bands(data_by_group[code_group_index])
    if not bands:
        return []

    code_x0 = min(_run_x0(r) for r in data_by_group[code_group_index])

    subject_columns: dict[int, str | list[str]] = {
        idx: resolved
        for idx, resolved in enumerate(group_resolved)
        if idx != code_group_index and data_by_group[idx] and resolved is not None
    }

    records = []
    for row_index, band in enumerate(bands):
        code = band["code"]

        row_cells: list[tuple[str, Any]] = []
        for idx, slugs in subject_columns.items():
            cell_text = _row_cell_text(data_by_group[idx], row_index, bands)
            cell = interpret_cell(cell_text, profile)
            slug_list = slugs if isinstance(slugs, list) else [slugs]
            for i, slug in enumerate(slug_list):
                if i == 0 or cell.kind != "level":
                    # A header merging two subjects (UJ's "Mathematics /
                    # Technical Mathematics") means both share one cell:
                    # the first is the base requirement, the rest are
                    # alternatives to it -- reusing build_subject_tree's
                    # existing preceding-column pairing, the same
                    # mechanism a row-level "OR" marker uses.
                    row_cells.append((slug, cell))
                else:
                    row_cells.append((slug, type(cell)(kind="alternative", level=cell.level, raw=cell.raw)))

        tree, excluded = build_subject_tree(row_cells, profile)
        name = _row_name(upright_words, band, code_x0)
        campus = _row_campus(upright_words, band, profile)
        aps = _row_aps(upright_words, band)

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


def _row_bands(code_runs: list[list[dict]]) -> list[dict]:
    bands = []
    for run in code_runs:
        bands.append({
            "top": min(c["top"] for c in run),
            "bottom": max(c["bottom"] for c in run),
            "code": _run_text(run),
        })
    bands.sort(key=lambda b: b["top"])
    return bands


def _nearest_row(top: float, bottom: float, bands: list[dict]) -> int:
    centre = (top + bottom) / 2
    return min(
        range(len(bands)),
        key=lambda i: abs(centre - (bands[i]["top"] + bands[i]["bottom"]) / 2),
    )


def _row_cell_text(runs: list[list[dict]], row_index: int, bands: list[dict]) -> str:
    """Row assignment happens per CHARACTER (a run can span multiple rows
    when consecutive rows share an identical value and merge -- see
    module docstring), but ordering/joining happens per RUN: pooling
    matched characters from several distinct runs (e.g. the separate
    "Not" and "accepted" words, or an "OR" marker plus its level cell)
    and sorting them together by advance alone interleaves their
    characters into garbage, since advance alone doesn't encode which
    run a character came from. Each run's own chars stay in their
    already-correct internal order; only whole runs get reordered."""
    parts: list[tuple[float, str]] = []
    for run in runs:
        run_chars = [c for c in run if _nearest_row(c["top"], c["bottom"], bands) == row_index]
        if run_chars:
            mean_advance = sum(_advance_key(c) for c in run_chars) / len(run_chars)
            parts.append((mean_advance, "".join(c["text"] for c in run_chars)))
    parts.sort(key=lambda p: p[0])
    return " ".join(text for _advance, text in parts)


def _resolve_header(header_text: str, profile: dict) -> str | list[str] | None:
    """A header spanning two slash-separated subjects (UJ's own
    'Mathematics / Technical Mathematics' merged column) means both
    subjects share the SAME data cell, and that cell's single level
    applies as an alternative between them -- not a per-row OR marker,
    since the alternative is baked into the header itself here."""
    parts = [p.strip() for p in re.split(r"/", header_text) if p.strip()]
    if len(parts) > 1:
        resolved = [resolve_subject_column(p, profile) for p in parts]
        resolved = [r for r in resolved if r is not None]
        return resolved if len(resolved) > 1 else (resolved[0] if resolved else None)
    return resolve_subject_column(header_text, profile)


def _row_name(upright_words: list[dict], band: dict, code_x0: float) -> str | None:
    words = [
        w for w in upright_words
        if band["top"] - 3 <= w["top"] <= band["bottom"] + 3 and w["x1"] <= code_x0
    ]
    if not words:
        return None
    words.sort(key=lambda w: (w["top"], w["x0"]))
    return " ".join(w["text"] for w in words)


def _row_campus(upright_words: list[dict], band: dict, profile: dict) -> list[str]:
    tokens = set(profile["layout"].get("campus_tokens", []))
    found = [
        w["text"] for w in upright_words
        if band["top"] - 2 <= w["top"] <= band["bottom"] + 2 and w["text"] in tokens
    ]
    return found


def _row_aps(upright_words: list[dict], band: dict) -> int | None:
    candidates = [
        w for w in upright_words
        if band["top"] - 2 <= w["top"] <= band["bottom"] + 2 and _APS_PATTERN.fullmatch(w["text"])
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda w: w["x0"])
    return int(candidates[0]["text"])
