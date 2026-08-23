"""Method D: coordinate-based table extraction. Ported from the verified
reference implementation (universities/uj_extract.py, phase 8.5's
"paste this block first" architecture note) -- that script found 180
programmes / 180 unique codes / 0 validation problems on the real UJ 2027
prospectus and independently corrected six errors in the hand-built seed
dataset. This module keeps its extraction LOGIC unchanged and moves every
institution-specific literal into the profile, so the same code runs
against any institution that carries the right profile.layout knobs
(table_settings, header_map, legend_first_cell, alternate_route_header)
and top-level faculty_ranges -- see extract/institutions/registry.json's
"uj" entry for the ported values and extract/profiles.py for their
validation.

Pipeline:
  extract_raw_rows   geometry + section-heading state only, via
                     coordinate_cells.cell_text -- no domain rules, no
                     document-specific literals. x-COORDINATE driven
                     throughout, not list-index driven (see
                     merge_header_rows' docstring for why that
                     distinction is load-bearing, not stylistic).
  apply_overlay      an OPT-IN mechanism for a reviewed, one-off
                     exception -- NOT applied by default (see
                     extract_coordinate's docstring). The PDF is the
                     master copy: what extract_raw_rows reads from it is
                     trusted as-is, not second-guessed against a
                     hardcoded correction table tied to one prospectus
                     edition's specific codes.
  validate           invariants that report loudly and repair nothing --
                     see the reference script's own module docstring
                     point 7 for why silent repair is the thing this
                     phase must not reintroduce.
extract_coordinate() then converts the validated raw rows into the
project's Programme shape (extract/methods/coordinate_records.py) before
returning. Nothing in this pipeline hardcodes a qualification code or a
requirement value -- every institution- and document-specific literal
lives in the profile (extract/institutions/registry.json), so the same
code runs unmodified against a future UJ prospectus update; only the
profile's faculty_ranges (page numbers) need re-verifying per edition,
the one cost phase 8.5's own design doc flagged as unavoidable for a
page-based approach.

KNOWN GAP, reported rather than hidden (see registry.json's uj quirks):
profile.layout.code_pattern is reused UNCHANGED from Methods A/B rather
than widened to the reference script's own stricter CODE_PATTERN, so the
two legacy code shapes it special-cased (B9ENV1, DI1401) are not
recognised here -- DI1401 in particular fails the shared pattern outright
(its second character isn't a digit). Full-document sanity should read
~179, not ~180, for this reason.
"""

import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from footnotes import find_footnotes_for_code  # noqa: E402
from text_repair import page_prose_text  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coordinate_cells import cell_text  # noqa: E402
from coordinate_records import NOT_ACCEPTED, to_programme_records  # noqa: E402
from shared import scan_page_exclusions  # noqa: E402

_OVERLAY_PATH = Path(__file__).resolve().parent.parent / "institutions" / "uj_overlay.json"

DURATION_PATTERN = re.compile(r"\((\d)\s*years?\)", re.I)

# Raw-key vocabulary for cells stating a Home Language / First Additional
# Language band rather than one number -- matches this profile's own
# header_map key vocabulary (see registry.json), not a generic mechanism.
BANDED_SUBJECTS = {"english", "afrikaans", "isizulu", "sepedi", "additional_language"}


def flat(text: str) -> str:
    """Collapse newlines and runs of whitespace into single spaces."""
    return " ".join((text or "").split())


def _phrase_words_present(phrase: str, lowered_text: str) -> bool:
    return all(re.search(rf"\b{re.escape(word)}\b", lowered_text) for word in phrase.lower().split())


_NO_MATCH = object()


def _classify_not_accepted(lowered_text: str, phrases: list[str]) -> Any:
    """_NO_MATCH if no configured not_accepted_phrases entry matches.
    Otherwise NOT_ACCEPTED for a phrase literally about ACCEPTANCE ('Not
    accepted'), or None for any other configured phrase ('Not
    applicable' -- absent, not excluded). An unrecognised configured
    phrase (an institution whose not_accepted_phrases carries neither
    word) defaults to absent rather than an invented exclusion --
    silently under-rejecting is the safer failure mode than wrongly
    excluding a subject a learner actually holds."""
    matched = [p for p in phrases if _phrase_words_present(p, lowered_text)]
    if not matched:
        return _NO_MATCH
    if any("accept" in p.lower() for p in matched):
        return NOT_ACCEPTED
    return None


def parse_rating(value: str, profile: dict) -> Any:
    """'5 (60%+)' -> 5; 'Not accepted' -> NOT_ACCEPTED; 'Not applicable'/
    '-'/'' -> None."""
    text = flat(value)
    if not text or text in {"-", "–", "—"}:
        return None
    classification = _classify_not_accepted(text.lower(), profile["layout"].get("not_accepted_phrases", []))
    if classification is not _NO_MATCH:
        return classification
    m = re.search(r"\b([1-7])\s*\(\s*\d{1,3}\s*%", text)  # "5 (60%+)"
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"([1-7])", text)  # bare "5"
    return int(m.group(1)) if m else None


def parse_english(value: str, profile: dict) -> Any:
    """
      "5 (60%+)"                                    -> 5
      "Home language 5 (60%+) OR
       Additional Language 6 (70%+)"                -> {"home_language": 5,
                                                        "first_additional_language": 6}
    """
    text = flat(value)
    home = re.search(r"Home\s*language\s*([1-7])", text, re.I)
    additional = re.search(r"Additional\s*Language\s*([1-7])", text, re.I)
    if home and additional:
        return {
            "home_language": int(home.group(1)),
            "first_additional_language": int(additional.group(1)),
        }
    return parse_rating(value, profile)


def parse_aps(value: str) -> Any:
    """
      "30"                                            -> 30
      "26 with Maths/Tech Maths OR 28 with Maths Lit" -> {"with_mathematics": 26,
                                                          "with_technical_mathematics": 26,
                                                          "with_mathematical_literacy": 28}
      "28 with Mathematical Literacy"                 -> {"with_mathematical_literacy": 28}
    """
    text = flat(value)
    if not text:
        return None
    # Soft-hyphenation across a rotated line break: "27 with Mathe- matics".
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    text = re.sub(r"^APS\s+", "", text, flags=re.I)

    if re.fullmatch(r"\d{2}", text):
        return int(text)

    # Humanities extended degrees key the APS off the ENGLISH rating rather
    # than a maths subject: "24-26 or 27" paired with "5 (60%+) or 4 (50%+)"
    # means 24-26 if English is 5, else 27 if English is 4. No
    # requires_subject equivalent exists in this schema for this shape --
    # coordinate_records.py encodes the strictest value and flags for review.
    banded = re.fullmatch(r"(\d{2})\s*-\s*(\d{2})\s*or\s*(\d{2})", text, re.I)
    if banded:
        return {
            "with_english_rating_5": int(banded.group(1)),
            "with_english_rating_5_upper": int(banded.group(2)),
            "with_english_rating_4": int(banded.group(3)),
        }

    aps: "OrderedDict[str, int]" = OrderedDict()
    combo = re.search(r"(\d{2})\s*with\s*Maths?\s*/\s*Tech\w*\s*Maths", text, re.I)
    if combo:
        aps["with_mathematics"] = int(combo.group(1))
        aps["with_technical_mathematics"] = int(combo.group(1))
    else:
        plain = re.search(r"(\d{2})\s*with\s*(?:Maths|Mathematics)\b(?!\s*Lit)", text, re.I)
        if plain:
            aps["with_mathematics"] = int(plain.group(1))
        tech = re.search(r"(\d{2})\s*with\s*Tech\w*\s*Maths", text, re.I)
        if tech:
            aps["with_technical_mathematics"] = int(tech.group(1))

    lit = re.search(r"(\d{2})\s*with\s*(?:Maths\s*Lit|Mathematical\s*Literacy)", text, re.I)
    if lit:
        aps["with_mathematical_literacy"] = int(lit.group(1))

    if aps:
        return dict(aps)
    return text  # left in place so validate() surfaces it instead of guessing


def _resolve_header_key(text: str, profile: dict) -> str | None:
    """First match wins -- profile.layout.header_map is ORDERED so a
    specific pattern (e.g. 'Technical Mathematics') can precede the
    generic 'math' rule it would otherwise be swallowed by."""
    for entry in profile["layout"].get("header_map", []):
        if re.search(entry["pattern"], text):
            return entry["key"]
    return None


def _cell_x_center(bbox: tuple[float, float, float, float] | None) -> float | None:
    return None if bbox is None else (bbox[0] + bbox[2]) / 2


def merge_header_rows(page: Any, table: Any, profile: dict) -> tuple[dict[str, float], set[str]]:
    """Some tables split the header across two physical rows -- concatenate
    the first two rows per column before matching, or a single-row read
    loses whichever label sits in the second row alone.

    Returns (raw_key -> x-CENTER of its header cell, {raw_key that is an
    alternative to whichever key precedes it}) -- keyed by POSITION, not
    list index. This matters: confirmed directly that 38 of UJ 2027's 40
    table pages have at least one data row whose row.cells contains a
    None bbox (a broken/merged ruling-line gap pdfplumber can't resolve
    into a real cell for that row) -- every cell AFTER that gap then sits
    at a different LIST INDEX than the header's own cells, even though
    its geometric column hasn't moved at all (real case, p.67 row 8: the
    header's 'Life Science' cell is list-index 8, but that row's actual
    Life Science cell -- same x-range, 279.8-302.5 -- is list-index 9,
    because index 8 in THAT row is a None gap). Extraction driven by
    list-index alignment silently reads every column after a gap one
    column too late. x-coordinate matching sidesteps this by never
    assuming a data row's Nth cell means the header's Nth cell at all --
    the same principle underlying this whole method (see coordinate_cells).

    Also detects a standalone "OR" header cell (UJ page 60: 'Physical
    Science', 'OR', 'Technical Science' as three separate header columns)
    -- the same alternative-marker convention Methods A/B already handle
    (see geometric.py's _marker_redirect / textlayer.py's marker_redirect),
    now ported here: the NEXT resolved column after a marker cell (by
    x-position) is returned as an "alternative" key, so the row-conversion
    stage (coordinate_records.py) pairs it with the PRECEDING column into
    an `any` node instead of two independently-required plain subjects.
    """
    rows = table.rows[:2]
    texts: dict[int, str] = {}
    x_centers: dict[int, float] = {}
    for row in rows:
        for idx, cell in enumerate(row.cells):
            texts[idx] = (texts.get(idx, "") + " " + flat(cell_text(page, cell))).strip()
            x = _cell_x_center(cell)
            if x is not None and idx not in x_centers:
                x_centers[idx] = x

    alt_phrases = {p.strip().lower() for p in profile["layout"].get("alternative_phrases", [])}
    marker_cols = {idx for idx, text in texts.items() if text.strip().lower() in alt_phrases}

    col_to_key: dict[int, str] = {}
    for idx, text in texts.items():
        if not text or idx in marker_cols:
            continue
        key = _resolve_header_key(text, profile)
        if key is not None:
            col_to_key[idx] = key

    header_x: dict[str, float] = {
        key: x_centers[idx] for idx, key in col_to_key.items() if idx in x_centers
    }

    alternative_keys: set[str] = set()
    for marker_idx in marker_cols:
        later = [c for c in col_to_key if c > marker_idx]
        if later:
            alternative_keys.add(col_to_key[min(later)])
    return header_x, alternative_keys


def faculty_for_page(page_index: int, profile: dict) -> str:
    for lo, hi, name in profile.get("faculty_ranges", []):
        if lo <= page_index <= hi:
            return name
    return ""


def extract_raw_rows(pdf_path: Path, profile: dict, table_pages: list[int]) -> list[dict]:
    """One dict per programme row, geometry + section-heading state only
    -- no overlay, no validation. Walks every page covered by
    profile.faculty_ranges (needed for cross-page header/duration/
    qualification-type state -- see module docstring), but only EMITS
    rows found on a page inside table_pages (an empty/falsy table_pages
    disables this filter, emitting from every faculty-covered page).

    State that must persist ACROSS table objects and pages, resetting
    only on faculty change:
      * headers            column legend is often its own standalone
                           table, printed once for a run of pages.
      * duration/qual_type  carried by section headings ("Bachelor Degree
                           (3 years)"), which frequently sit on the
                           previous page when a table spans a spread.
    """
    layout = profile["layout"]
    table_settings = layout.get("table_settings")
    if not table_settings:
        return []  # institution not configured for Method D

    code_pattern = re.compile(layout["code_pattern"])
    legend_first_cell = re.compile(layout["legend_first_cell"]) if "legend_first_cell" in layout else None
    alternate_route_header = re.compile(layout["alternate_route_header"]) if "alternate_route_header" in layout else None
    page_filter = set(table_pages) if table_pages else None

    rows: list[dict] = []
    seen: set[str] = set()

    headers: dict[str, float] = {}  # raw_key -> x-center of its header cell
    alt_keys: set[str] = set()
    duration: int | None = None
    qual_type: str | None = None
    current_faculty: str | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            faculty = faculty_for_page(page_index, profile)
            if not faculty:
                continue  # front matter, campus life, bursaries, back matter

            if faculty != current_faculty:
                headers, alt_keys, duration, qual_type = {}, set(), None, None
                current_faculty = faculty

            page_number = page_index + 1  # 1-indexed, matching table_pages/source_page convention
            page_exclusions = scan_page_exclusions(page_prose_text(page), profile)

            for table in page.find_tables(table_settings):
                if not table.rows or not table.rows[0].cells:
                    continue
                header_blob = " ".join(flat(cell_text(page, c)) for c in table.rows[0].cells)
                if alternate_route_header is not None and alternate_route_header.search(header_blob):
                    continue  # NC(V) / NASCA / SC(a) alternate-route table

                first_cell = flat(cell_text(page, table.rows[0].cells[0]))
                if legend_first_cell is not None and legend_first_cell.match(first_cell):
                    found, found_alt_keys = merge_header_rows(page, table, profile)
                    if found:
                        headers, alt_keys = found, found_alt_keys
                    # NOTE: do NOT skip the table -- some pages print the
                    # legend and the data rows inside a single table object.

                carried: dict[str, str] = {}

                for row in table.rows:
                    cells = [cell_text(page, c) for c in row.cells]
                    populated = [c for c in cells if c]

                    # Position-based cell lookup for this row -- see
                    # merge_header_rows' docstring: a data row's Nth cell
                    # is NOT reliably the header's Nth cell (a None-bbox
                    # gap earlier in the row shifts every later cell's
                    # LIST index without moving its geometric column).
                    # Every read of this row's own cell content for a
                    # known header key goes through nearest-x lookup
                    # instead of `cells[idx]`, confirmed necessary on 38 of
                    # UJ 2027's 40 table pages.
                    cell_positions = [
                        (x, txt) for x, txt in
                        ((_cell_x_center(bbox), txt) for bbox, txt in zip(row.cells, cells))
                        if x is not None
                    ]

                    def _cell_at(x_center: float) -> str:
                        if not cell_positions:
                            return ""
                        return min(cell_positions, key=lambda p: abs(p[0] - x_center))[1]

                    # A single-letter-per-cell 'O'/'R' row (e.g. UJ p.67,
                    # between Life Science and Technical Science) is NOT a
                    # semantic alternative marker to act on -- it turned
                    # out to be a symptom of the SAME None-bbox list-index
                    # misalignment merge_header_rows' docstring explains
                    # (verified: once cell reads became x-position-based
                    # instead of list-index-based, both columns already
                    # read correctly with no special-casing at all; an
                    # earlier attempt that treated this row as a real
                    # alternative marker actively made a real case
                    # -B9E01Q- WRONG by pairing Life Science with whichever
                    # OTHER column happened to precede it once its own
                    # value was already correct). This row still has no
                    # code and 2+ populated cells, so it falls through to
                    # "not a heading, not a data row" below and is
                    # harmlessly skipped without any special detection.
                    if len(populated) == 1 and cells[0]:
                        heading = flat(cells[0])
                        m = DURATION_PATTERN.search(heading)
                        if m:
                            duration = int(m.group(1))
                        low = heading.lower()
                        if "extended" in low and not m:
                            duration = 4
                        if "online" in low:
                            qual_type = "Online Degree"
                        elif "extended" in low and "diploma" in low:
                            qual_type = "Extended Diploma"
                        elif "extended" in low:
                            qual_type = "Extended Degree"
                        elif "diploma" in low:
                            qual_type = "Diploma"
                        elif "degree" in low or "bachelor" in low:
                            qual_type = "Degree"
                        continue

                    codes: list[str] = []
                    code_col = -1
                    for idx, cell in enumerate(cells):
                        found_codes = [t for t in re.split(r"[\s/]+", cell) if code_pattern.fullmatch(t)]
                        if found_codes:
                            codes, code_col = found_codes, idx
                            break
                    if not codes:
                        continue

                    # Vertical merge carrying, keyed by raw KEY (not column
                    # index, for the same reason cell reads are x-based
                    # now): an empty requirement means "same as above",
                    # not "no requirement" -- carry the last real value
                    # forward within this table.
                    raw_by_key = {key: _cell_at(x) for key, x in headers.items()}
                    for key, text in raw_by_key.items():
                        if text:
                            carried[key] = text
                        elif key in carried:
                            raw_by_key[key] = carried[key]

                    title = flat(cells[1] if code_col == 0 else cells[0])
                    aps_cell = cells[code_col + 1] if code_col + 1 < len(cells) else ""
                    requirements = {
                        key: (parse_english(text, profile) if key in BANDED_SUBJECTS else parse_rating(text, profile))
                        for key, text in raw_by_key.items()
                    }

                    # A row may print TWO codes for two campuses in one
                    # cell ("B34PKQ / B34PSQ") -- generically, not
                    # hardcoded per code: if the campus cell ALSO splits
                    # into exactly as many tokens as there are codes, pair
                    # them positionally (code[i] <-> campus_token[i]);
                    # otherwise every code gets the whole printed string,
                    # same as a single-code row.
                    campus_raw = flat(cells[-1])
                    campus_tokens = [t for t in re.split(r"[\s/]+", campus_raw) if t] if campus_raw else []
                    campus_by_code = (
                        dict(zip(codes, campus_tokens)) if len(campus_tokens) == len(codes) else {}
                    )

                    for code in codes:
                        if code in seen:
                            continue
                        if page_filter is not None and page_number not in page_filter:
                            continue
                        seen.add(code)
                        # Footnote markers ('*'/'**' on a cell, e.g. a
                        # module-dependent Physical Science threshold) are
                        # a genuinely un-tabulated fact -- not a column
                        # value at all, so no amount of cell-reading finds
                        # it. Read DYNAMICALLY off this code's own row and
                        # whatever legend text precedes it in the document
                        # (extract/footnotes.py, already generic and
                        # institution-agnostic) instead of a hardcoded
                        # per-code lookup table: works for any prospectus
                        # edition without a single code literal in this
                        # file.
                        footnotes = (
                            find_footnotes_for_code(pdf, page_number, code, profile)
                            if layout.get("footnote_markers") else []
                        )
                        rows.append({
                            "faculty": faculty,
                            "programme": title,
                            "qualification_code": code,
                            "qualification_type": qual_type
                            or ("Diploma" if code.startswith("D") else "Degree"),
                            "duration_years": duration,
                            "campus": campus_by_code.get(code, campus_raw or None),
                            "minimum_aps": parse_aps(aps_cell),
                            "requirements": requirements,
                            "alternative_keys": sorted(alt_keys),
                            "excluded_subjects_prose": page_exclusions,
                            "unresolved_footnotes": footnotes,
                            "_page": page_number,
                        })
    return rows


# ==========================================================================
# Stage 2 - overlay
# ==========================================================================

def _load_overlay() -> dict[str, dict]:
    return json.loads(_OVERLAY_PATH.read_text(encoding="utf-8"))


def apply_overlay(record: dict, overlay: dict[str, dict]) -> tuple[dict, list[str]]:
    """Shallow-merge an overlay patch onto the raw record. `requirements`
    merges one level deep so a patch can adjust a single subject without
    restating the block; every other key is replaced outright. Returns
    (record, overlay_applied) -- the field names patched, for the
    output record's own provenance (see coordinate_records.py)."""
    entry = overlay.get(record["qualification_code"])
    if not entry:
        return record, []
    applied: list[str] = []
    for key, value in entry["patch"].items():
        if key == "requirements" and isinstance(value, dict):
            record["requirements"].update(value)
            applied.extend(f"requirements.{k}" for k in value)
        else:
            record[key] = value
            applied.append(key)
    return record, applied


# ==========================================================================
# Stage 3 - validation (report-only; see module docstring point 7)
# ==========================================================================

def validate(records: list[dict]) -> dict[str, list[str]]:
    """Returns {qualification_code: [problem, ...]}. Deliberately returns
    rather than mutates: an earlier version of this check rewrote
    physical_science to 5 whenever a programme name contained "Physics",
    which laundered a row-offset transposition into plausible-looking bad
    data instead of surfacing it."""
    problems: dict[str, list[str]] = {}

    def _add(code: str, message: str) -> None:
        problems.setdefault(code, []).append(message)

    seen: dict[str, str] = {}
    for r in records:
        code = r["qualification_code"]
        if code in seen:
            _add(code, f"duplicate code {code}: {seen[code]!r} vs {r['programme']!r}")
        seen[code] = r["programme"]

    for r in records:
        code, name, reqs = r["qualification_code"], r["programme"], r["requirements"]
        low = name.lower()

        if r["faculty"] == "Science":
            ps = reqs.get("physical_science")
            extended = (r["qualification_type"] or "").startswith("Extended")
            if (not extended and "physics" in low and "geology" not in low
                    and isinstance(ps, int) and ps < 5):
                _add(code, f"{name!r}: Physics major with physical_science={ps} (expected >=5)")

        m, ml = reqs.get("mathematics"), reqs.get("mathematical_literacy")
        if isinstance(m, int) and isinstance(ml, int) and ml < m:
            _add(code, f"{name!r}: maths_lit={ml} < maths={m} (columns likely swapped)")

        for key, value in reqs.items():
            if isinstance(value, int) and not 1 <= value <= 7:
                _add(code, f"{key}={value} outside NSC range 1-7")

        aps = r["minimum_aps"]
        if isinstance(aps, str):
            _add(code, f"unparsed APS cell {aps!r}")
        elif isinstance(aps, int) and not 15 <= aps <= 45:
            _add(code, f"implausible APS {aps}")

        if reqs.get("english") is None:  # dict form is fine; None is not
            _add(code, "no English requirement captured")

        if r["duration_years"] is None:
            _add(code, "no duration resolved from section heading")

    return problems


# ==========================================================================
# Contract entry point
# ==========================================================================

def extract_coordinate(
    pdf_path: Path, profile: dict, table_pages: list[int], overlay: dict[str, dict] | None = None,
) -> tuple[list[dict], dict]:
    """Contract-compatible with Methods A/B's positional arguments
    (pdf_path, profile, table_pages); unlike their bare list[dict]
    return, this returns (records, stats) per phase 8.5's explicit
    contract for Method D.

    overlay defaults to EMPTY -- deliberately NOT
    extract/institutions/uj_overlay.json's contents, even though that
    file still exists and _load_overlay() can still read it. A hardcoded
    per-qualification-code correction table is tied to one prospectus
    edition's specific codes and page layout; it cannot be dynamic across
    a future UJ prospectus update the way the rest of this method is
    (profile-driven, x-coordinate-based, no document-specific literals in
    code). Worse, it can be actively WRONG once the extraction bug it was
    written to patch around gets fixed properly: confirmed directly on
    B34IMQ (source p.42) -- the overlay's own note claims "only the Maths
    Lit variant is printed," but the real cell reads "26 with Maths/Tech
    Maths OR 28 with Mathematical Literacy", both variants, in full. That
    correction would have DELETED real, correctly-extracted data.
    Similarly B34HRQ and D9S01Q's corrections turned out to be masking
    the SAME x-coordinate list-index bug already fixed in extract_raw_rows
    -- pure extraction reads them correctly with no help at all. See
    extract/institutions/registry.json's uj quirks for the full audit.
    Pass an explicit overlay dict only for a genuinely one-off, reviewed
    exception -- never load the JSON file automatically."""
    if overlay is None:
        overlay = {}

    raw_rows = extract_raw_rows(pdf_path, profile, table_pages)

    overlaid: list[dict] = []
    overlay_applied: dict[str, list[str]] = {}
    for row in raw_rows:
        row, applied = apply_overlay(row, overlay)
        overlaid.append(row)
        if applied:
            overlay_applied[row["qualification_code"]] = applied

    problems = validate(overlaid)
    records = to_programme_records(overlaid, problems, overlay_applied, profile)

    stats = {
        "raw_rows": len(raw_rows),
        "unique_codes": len({r["qualification_code"] for r in overlaid}),
        "validation_problems": sum(len(v) for v in problems.values()),
        "overlay_applied_count": len(overlay_applied),
    }
    return records, stats
