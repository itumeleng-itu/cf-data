"""
UJ 2027 Undergraduate Prospectus  ->  structured JSON.

STATUS: A STANDALONE TOOL, NOT PART OF THE PIPELINE
---------------------------------------------------
This file is UJ-specific and nothing else in the repo imports it. The
data pipeline is hand-produced JSON bundles (docs/BUNDLE_FORMAT.md ->
scripts/convert_bundle.py -> seeds/ -> Postgres); the generic multi-method
PDF extraction pipeline this script was the reference implementation for
was removed, and this is the one piece of it that was kept.

It is kept because it WORKS on exactly one document: run against the UJ
2027 prospectus it produces 180 programmes, 180 unique codes and 0
validation problems in seconds, and it independently found six errors in
the hand-built dataset. That makes it a free cross-check on hand-typed
UJ JSON -- transcribe a page, run this, compare. It does NOT generalise:
every page range, column convention and code pattern below is a literal
fact about this one PDF, and pointing it at any other prospectus
produces confident garbage rather than an error.

Its output is its OWN flat shape, close to but not identical with the
bundle format -- most importantly it cannot distinguish "Not accepted"
from absent (see parse_rating), which the bundle format requires and a
human reader can supply. Treat its output as a second opinion on the
numbers, never as a bundle to load directly.

WHY THE PREVIOUS SCRIPT RETURNED ZERO ROWS
------------------------------------------
1. Rotated text. Every table header and most numeric cells in this PDF are
   rendered at 90 degrees. pdfplumber emits rotated glyphs in visual order, so
   "B8BA3Q" arrives as "Q3AB8B" and "English" as "hsilgnE". `CODE_PATTERN` was
   matched against the raw token and therefore never matched anything.
2. The header guard tested for the substrings "code" / "aps" / "programme" -
   which are also reversed ("edoC", "SPA", "EMMARGORP"), so every table was
   skipped before parsing began.
3. `extract_tables()` with default settings returned the header box only and
   dropped the body. Explicit `vertical/horizontal_strategy="lines"` with
   snap/join tolerances is needed to absorb the double-stroked ~0.5pt borders.
4. Even with the right strategy, `table.extract()` interleaves the words of
   multi-line rotated cells: "25 with Mathematics OR / 26 with Mathematical
   Literacy" degrades to "Literacy OR Mathematics Mathematical with with 25 26".
   No string reversal recovers that - the line grouping itself is wrong, so the
   cell must be rebuilt from glyph coordinates (see `cell_text`).
5. `duration_years` was guessed from the title. "BEng" is 4 years, "BEngTech" is
   3, and neither states it; the real source is the section heading above the
   row ("Bachelor Degree (3 years)").
6. `campus` took `clean_row[-1]`, which on a rotated row is "BPA", not "APB".
7. `validate_science_invariants` silently REWROTE physical_science to 5 whenever
   a name contained "Physics". That laundered a row-offset transposition into
   plausible-looking bad data. Validators here return findings and never mutate.

PIPELINE
--------
  extract_raw_rows  geometry only - ruling-line tables, coordinate-based cell
                    reconstruction, section-heading context. No domain rules.
  apply_overlay     hand-verified facts the grid cannot carry: footnote
                    conditionals, OR-selections, split-campus rows, and the
                    handful of cells where the printed grid is column-shifted.
                    Every entry is provenance-tagged with its page.
  validate          invariants that report loudly and repair nothing.

Usage:  python uj_extract.py uj.pdf out.json [golden.json]
Requires: pdfplumber >= 0.11
"""

from __future__ import annotations

import json
import re
import sys
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

# ==========================================================================
# Constants
# ==========================================================================

# The prospectus draws full ruling grids, so "lines" beats "text" everywhere.
# Tolerances absorb the paired borders (e.g. v-edges at x=120.3 AND x=120.9).
TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 4,
    "join_tolerance": 4,
    "intersection_tolerance": 6,
}

# UJ codes: B/D + faculty digit + 3 alnum + Q (C/P for online variants).
# B9ENV1 and DI1401 are legacy shapes that break the pattern and need naming.
CODE_PATTERN = re.compile(r"^(?:[BD][0-9I][A-Z0-9]{3}[QCP]|B9ENV1|DI1401)$")

DURATION_PATTERN = re.compile(r"\((\d)\s*years?\)", re.I)

# Later in each faculty the same codes reappear in NC(V) / NASCA / SC(a)
# admission tables, which use a different criteria model entirely (percentages
# across "fundamental" and "vocational" components rather than APS ratings).
# Those are alternate entry ROUTES, not extra programmes; parsing them yielded
# 27 duplicate codes that silently shadowed the real rows.
ALTERNATE_ROUTE_HEADER = re.compile(r"fundamental|vocational|group\s*a", re.I)

# Faculty page ranges, 0-indexed as pdfplumber sees them (the printed folio is
# one lower because of the unnumbered cover).
FACULTY_RANGES: List[Tuple[int, int, str]] = [
    (29, 37, "Faculty of Art, Design and Architecture"),
    (38, 51, "College of Business and Economics"),
    (52, 57, "Faculty of Education"),
    (58, 63, "Faculty of Engineering and the Built Environment"),
    (64, 71, "Faculty of Health Sciences"),
    (72, 79, "Faculty of Humanities"),
    (80, 83, "Faculty of Law"),
    (84, 96, "Faculty of Science"),
]

# Header fragment -> requirement key. Order matters: first match wins, so the
# specific patterns must precede the generic "math" rule.
# A table is a column LEGEND only if its first cell is the "PROGRAMME" label.
# Without this guard, a data table's APS cell ("25 with Mathematical Literacy")
# is mistaken for a Maths Lit header and clobbers the real legend, wiping the
# English column for whole faculties.
LEGEND_FIRST_CELL = re.compile(r"^programme", re.I)

HEADER_MAP: List[Tuple[re.Pattern, str]] = [
    # "Mathematics / Technical Mathematics" is ONE column accepting either
    # subject; it must not be captured by the technical-only rule below.
    # "Mathematical Literacy / Technical Mathematics" is ONE alternative column
    # in the Education tables - either subject satisfies it at the stated rating.
    (re.compile(r"literacy\s*/\s*technical", re.I),
     "mathematical_literacy_or_technical_mathematics"),
    (re.compile(r"math\w*\s*/\s*tech", re.I), "mathematics"),
    # Language-specialisation columns in the BEd Language Education table.
    (re.compile(r"afrikaans", re.I), "afrikaans"),
    (re.compile(r"isizulu", re.I), "isizulu"),
    (re.compile(r"sepedi", re.I), "sepedi"),
    (re.compile(r"technical\s*math", re.I), "technical_mathematics"),
    (re.compile(r"technical\s*science", re.I), "technical_science"),
    (re.compile(r"math\w*\s*literacy", re.I), "mathematical_literacy"),
    (re.compile(r"physical\s*science", re.I), "physical_science"),
    (re.compile(r"life\s*science", re.I), "life_sciences"),
    (re.compile(r"additional\s*(recognised\s*)?language", re.I), "additional_language"),
    (re.compile(r"geography", re.I), "geography"),
    (re.compile(r"math", re.I), "mathematics"),
    (re.compile(r"english", re.I), "english"),
]

NOT_ACCEPTED = re.compile(r"not\s*(accepted|applicable)", re.I)

# Columns whose cells state a Home Language and a First Additional Language
# threshold rather than one number.
BANDED_SUBJECTS = {"english", "afrikaans", "isizulu", "sepedi", "additional_language"}


# ==========================================================================
# Stage 1a - text orientation
# ==========================================================================

def cell_text(page, bbox: Optional[Tuple[float, float, float, float]]) -> str:
    """
    Read one table cell, reconstructing 90-degree-rotated text correctly.

    This is the fix that makes the script work at all. Rather than trusting
    `table.extract()`, we go back to glyph coordinates:

      * pdfplumber tags each word with `upright`. If most words in the cell are
        rotated, the cell is treated as rotated.
      * For bottom-to-top text one visual LINE shares an x0, and reading order
        within that line runs from LARGER top to SMALLER top. Lines themselves
        run left-to-right by x0.
      * Each word's characters are still emitted in reverse, so we flip them.

    Bucketing x0 and top by 3pt absorbs sub-point baseline jitter.
    """
    if bbox is None:
        return ""
    x0, top, x1, bottom = bbox
    # Inset half a point so the ruling lines are not sampled as glyphs.
    crop = page.crop((x0 + 0.5, top + 0.5, x1 - 0.5, bottom - 0.5), strict=False)
    words = crop.extract_words(extra_attrs=["upright"], use_text_flow=False)
    if not words:
        return ""

    rotated = [w for w in words if not w["upright"]]
    if len(rotated) <= len(words) / 2:
        ordered = sorted(words, key=lambda w: (round(w["top"] / 3), w["x0"]))
        return " ".join(w["text"] for w in ordered)

    lines: Dict[int, List[dict]] = {}
    for w in rotated:
        lines.setdefault(round(w["x0"] / 3), []).append(w)
    return "\n".join(
        " ".join(w["text"][::-1] for w in sorted(lines[k], key=lambda w: -w["top"]))
        for k in sorted(lines)
    )


def flat(text: str) -> str:
    """Collapse newlines and runs of whitespace into single spaces."""
    return " ".join((text or "").split())


# ==========================================================================
# Stage 1b - value parsing
# ==========================================================================

def parse_rating(value: str) -> Optional[int]:
    """
    '5 (60%+)' -> 5;  'Not accepted' -> None;  '–' -> None;  '' -> None.

    "Not accepted" and "absent" collapse to None. They differ in meaning
    (forbidden vs not-applicable) but the prospectus renders both the same way
    in several tables, so distinguishing them here would be invention; the
    OVERLAY restores the distinction where it is actually stated.
    """
    text = flat(value)
    if not text or NOT_ACCEPTED.search(text) or text in {"-", "–", "—"}:
        return None
    m = re.search(r"\b([1-7])\s*\(\s*\d{1,3}\s*%", text)   # "5 (60%+)"
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"([1-7])", text)                      # bare "5"
    return int(m.group(1)) if m else None


def parse_english(value: str) -> Any:
    """
    English cells come in two shapes.

      "5 (60%+)"                                    -> 5
      "Home language 5 (60%+) OR
       Additional Language 6 (70%+)"                -> {"home_language": 5,
                                                        "first_additional_language": 6}

    The banded form appears throughout the Faculty of Education, where the
    threshold depends on whether English is taken as Home Language or as a
    First Additional Language. Flattening it to a single number would make every
    BEd programme unscorable for FAL candidates.
    """
    text = flat(value)
    home = re.search(r"Home\s*language\s*([1-7])", text, re.I)
    additional = re.search(r"Additional\s*Language\s*([1-7])", text, re.I)
    if home and additional:
        return {
            "home_language": int(home.group(1)),
            "first_additional_language": int(additional.group(1)),
        }
    return parse_rating(value)


def parse_aps(value: str) -> Any:
    """
    Normalise the APS cell into an int or a variant dict.

      "30"                                            -> 30
      "26 with Maths/Tech Maths OR 28 with Maths Lit" -> {"with_mathematics": 26,
                                                          "with_technical_mathematics": 26,
                                                          "with_mathematical_literacy": 28}
      "28 with Mathematical Literacy"                 -> {"with_mathematical_literacy": 28}

    The combined "Maths/Tech Maths" form shares ONE number across two keys.
    Separate per-subject regexes miss it, because "Tech Maths" in that phrasing
    has no leading digit of its own.
    """
    text = flat(value)
    if not text:
        return None
    # Soft-hyphenation across a rotated line break: "27 with Mathe- matics".
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    # Some cells are prefixed with the literal label, e.g. "APS 27".
    text = re.sub(r"^APS\s+", "", text, flags=re.I)

    if re.fullmatch(r"\d{2}", text):
        return int(text)

    # Humanities extended degrees (p.76) key the APS off the ENGLISH rating
    # rather than off a maths subject: "24-26 or 27" paired with "5 (60%+) or
    # 4 (50%+)" means 24-26 if English is 5, else 27 if English is 4.
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
    # Leave unparsed text in place so validate() surfaces it instead of guessing.
    return text


def merge_header_rows(page, table) -> Dict[int, str]:
    """
    Build column index -> requirement key.

    Several tables split the header across two physical rows: on the FADA pages
    the "English *" label sits in a second row beneath an empty cell, so a
    single-row read loses English for the whole faculty. We concatenate the
    first two rows per column before matching.
    """
    rows = table.rows[:2]
    texts: Dict[int, str] = {}
    for row in rows:
        for idx, cell in enumerate(row.cells):
            texts[idx] = (texts.get(idx, "") + " " + flat(cell_text(page, cell))).strip()

    mapping: Dict[int, str] = {}
    for idx, text in texts.items():
        if not text:
            continue
        for pattern, key in HEADER_MAP:
            if pattern.search(text):
                mapping.setdefault(idx, key)
                break
    return mapping


def faculty_for_page(page_index: int) -> str:
    for lo, hi, name in FACULTY_RANGES:
        if lo <= page_index <= hi:
            return name
    return ""


# ==========================================================================
# Stage 1c - extraction
# ==========================================================================

def extract_raw_rows(pdf_path: str) -> List[Dict[str, Any]]:
    """
    One dict per programme row. Pure geometry; no corrections, no overlay.

    State that must persist ACROSS table objects:
      * headers    - the column legend is emitted as its own standalone table,
                     separate from the data table beneath it, and is often
                     printed once for a run of pages. Re-reading it per table
                     would leave every data table header-less.
      * duration /
        qual_type  - carried by section headings ("Bachelor Degree (3 years)")
                     which frequently sit on the previous page when a table
                     spans a spread.
    All three reset when the faculty changes, since column semantics differ
    between faculties.
    """
    rows: List[Dict[str, Any]] = []
    seen: set = set()

    headers: Dict[int, str] = {}
    duration: Optional[int] = None
    qual_type: Optional[str] = None
    current_faculty: Optional[str] = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            faculty = faculty_for_page(page_index)
            if not faculty:
                continue  # front matter, campus life, bursaries, back matter

            if faculty != current_faculty:
                headers, duration, qual_type = {}, None, None
                current_faculty = faculty

            for table in page.find_tables(TABLE_SETTINGS):
                header_blob = " ".join(
                    flat(cell_text(page, c)) for c in table.rows[0].cells
                )
                if ALTERNATE_ROUTE_HEADER.search(header_blob):
                    continue  # NC(V) / NASCA / SC(a) alternate-route table

                # A legend table updates the column map and contributes no rows.
                first_cell = flat(cell_text(page, table.rows[0].cells[0]))
                if LEGEND_FIRST_CELL.match(first_cell):
                    found = merge_header_rows(page, table)
                    if found:
                        headers = found
                    # NOTE: do NOT skip the table here. Some pages print the
                    # legend and the data rows inside a single table object;
                    # header rows are harmless because they carry no code.

                # Vertically merged cells: the Education Commerce table prints
                # the English band once and lets it span the rows beneath. An
                # empty requirement cell there means "same as above", not
                # "no requirement", so we carry the last value forward.
                carried: Dict[int, str] = {}

                for row in table.rows:
                    cells = [cell_text(page, c) for c in row.cells]
                    populated = [c for c in cells if c]

                    # A section heading fills exactly one cell and carries the
                    # duration and qualification type for the rows beneath it.
                    if len(populated) == 1 and cells[0]:
                        heading = flat(cells[0])
                        m = DURATION_PATTERN.search(heading)
                        if m:
                            duration = int(m.group(1))
                        low = heading.lower()
                        # Science prints "... (Extended)" with no year count.
                        # Extended programmes are always one year longer than
                        # their mainstream equivalent.
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

                    # A row may legitimately carry TWO codes - Public Management
                    # is printed once as "B34PKQ / B34PSQ" for its two campuses.
                    codes: List[str] = []
                    code_col = -1
                    for idx, cell in enumerate(cells):
                        found = [t for t in re.split(r"[\s/]+", cell) if CODE_PATTERN.match(t)]
                        if found:
                            codes, code_col = found, idx
                            break
                    if not codes:
                        continue

                    for idx in headers:
                        if idx < len(cells):
                            if cells[idx]:
                                carried[idx] = cells[idx]
                            elif idx in carried:
                                cells[idx] = carried[idx]

                    title = flat(cells[1] if code_col == 0 else cells[0])
                    aps_cell = cells[code_col + 1] if code_col + 1 < len(cells) else ""
                    requirements = {
                        # Language columns use the Home / First Additional
                        # banding, every other column is a single rating.
                        key: (parse_english(cells[idx])
                              if key in BANDED_SUBJECTS else parse_rating(cells[idx]))
                        for idx, key in sorted(headers.items())
                        if idx < len(cells)
                    }

                    for code in codes:
                        if code in seen:
                            continue
                        seen.add(code)
                        rows.append(
                            {
                                "faculty": faculty,
                                "programme": title,
                                "qualification_code": code,
                                "qualification_type": qual_type
                                or ("Diploma" if code.startswith("D") else "Degree"),
                                "duration_years": duration,
                                "campus": flat(cells[-1]) or None,
                                "minimum_aps": parse_aps(aps_cell),
                                "requirements": requirements,
                                "_page": page_index,  # provenance; stripped on export
                            }
                        )

    return rows


# ==========================================================================
# Stage 2 - overlay
# ==========================================================================
#
# Facts the table GEOMETRY cannot carry, each tagged with the printed page it
# was verified against so a future prospectus can be re-checked cheaply.
#
#   (a) footnote conditionals - the "*" / "**" markers under the Science tables
#       that make a minimum depend on which first-year module you enrol in
#   (b) split-campus rows - one printed row, two codes, two campuses
#   (c) corrections - cells where the printed grid is column-shifted or bleeds
#       a value from the facing page
#
# CRITICAL: the same "*" marker means DIFFERENT things in different Science
# tables. Conflating them is the easiest error to make in this document.
#   Life & Environmental Sciences (pp.87-88): Maths 6 if Maths 1A, 5 if Maths 1C
#   Physical Sciences            (pp.90-91): Maths 5 if Maths 1A, 4 if Maths 1C

LIFE_ENV_MATHS = {"with_mathematics_1A": 6, "with_mathematics_1C": 5}
LIFE_ENV_PHYSCI = {
    "with_chemistry_1A_or_physics_1A_or_S1": 5,
    "with_chemistry_1C_or_physics_G1_L1_or_biology_or_geology": 4,
}
GEOLOGY_PHYSCI = {"with_chemistry_1A_or_physics_1A_or_1S": 5, "with_geology": 4}


def _cond(**blocks: Dict[str, int]) -> Dict[str, Any]:
    """Shorthand for a `requirements.conditions` patch."""
    return {"requirements": {"conditions": dict(blocks)}}


OVERLAY: Dict[str, Dict[str, Any]] = {
    # ---- (c) corrections -------------------------------------------------
    "B34HRQ": {
        "source": "p.40",
        "note": "English and Maths Lit were printed in adjacent columns and read "
                "in reverse order.",
        "patch": {"requirements": {"english": 4, "mathematical_literacy": 5}},
    },
    "B34I7Q": {
        "source": "p.40",
        "note": "Column-shifted row: Tech Maths is Not accepted, Maths Lit is 5, "
                "and the APS cell carries both variants.",
        "patch": {
            "minimum_aps": {"with_mathematics": 26, "with_mathematical_literacy": 28},
            "requirements": {
                "english": 4,
                "mathematics": 4,
                "mathematical_literacy": 5,
                "technical_mathematics": None,
            },
        },
    },
    "D9S01Q": {
        "source": "p.70",
        "note": "English is 3 (40%+), not 4.",
        "patch": {"requirements": {"english": 3}},
    },
    "B2P82Q": {
        "source": "p.91",
        "note": "APS 31 like every other Physical Sciences row; 33 bleeds in from "
                "the Mathematical Sciences table on the facing page.",
        "patch": {"minimum_aps": 31},
    },
    "B34IMQ": {
        "source": "p.42",
        "note": "Only the Maths Lit variant is printed; a Maths variant must NOT "
                "be inferred from the pattern of neighbouring rows.",
        "patch": {"minimum_aps": {"with_mathematical_literacy": 28}},
    },
    # ---- (b) split-campus row -------------------------------------------
    "B34PKQ": {"source": "p.41", "patch": {"campus": "APK"}},
    "B34PSQ": {"source": "p.41", "patch": {"campus": "SWC"}},
    # ---- (a) Life & Environmental Sciences footnotes ---------------------
    **{
        code: {"source": "pp.87-88",
               "patch": _cond(mathematics=LIFE_ENV_MATHS,
                              physical_science=LIFE_ENV_PHYSCI)}
        for code in ("B2L10Q", "B2L12Q", "B2L13Q", "B2L16Q", "B2L18Q", "B2L26Q")
    },
    **{
        code: {"source": "pp.87-88",
               "patch": _cond(physical_science=LIFE_ENV_PHYSCI)}
        for code in ("B2L11Q", "B2L14Q", "B2L15Q", "B2L24Q", "B2L25Q")
    },
    "B2L17Q": {"source": "p.87", "patch": _cond(mathematics=LIFE_ENV_MATHS)},
    # ---- (a) Physical Sciences footnotes ---------------------------------
    **{
        code: {
            "source": "pp.90-91",
            "note": "Mathematics stays at the printed 6 (70%+); the '*' footnote "
                    "does not override an explicitly printed column value. Only "
                    "Physical Science is conditional here.",
            "patch": _cond(physical_science=GEOLOGY_PHYSCI),
        }
        for code in ("B2P81Q", "B2P82Q", "B2P83Q")
    },
}


def apply_overlay(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Shallow-merge an OVERLAY patch. `requirements` merges one level deep so a
    patch can adjust a single subject without restating the block; every other
    key is replaced outright.
    """
    entry = OVERLAY.get(record["qualification_code"])
    if not entry:
        return record
    for key, value in entry["patch"].items():
        if key == "requirements" and isinstance(value, dict):
            record["requirements"].update(value)
        else:
            record[key] = value
    return record


# ==========================================================================
# Stage 3 - validation
# ==========================================================================

def validate(records: List[Dict[str, Any]]) -> List[str]:
    """
    Return a list of problems. Deliberately returns rather than mutates: the
    original invariant check rewrote physical_science to 5, which turns a
    detectable transposition into undetectable bad data.
    """
    problems: List[str] = []

    seen: Dict[str, str] = {}
    for r in records:
        code = r["qualification_code"]
        if code in seen:
            problems.append(f"duplicate code {code}: {seen[code]!r} vs {r['programme']!r}")
        seen[code] = r["programme"]

    for r in records:
        code, name, reqs = r["qualification_code"], r["programme"], r["requirements"]
        low = name.lower()

        # Semantic invariant catching row-offset transposition in Science: a
        # Physics major needs Physical Science 5, a Geology major accepts 4.
        # When those swap, the names and the numbers disagree - which is exactly
        # how B2P77Q..B2P83Q were mislabelled in an earlier hand-built dataset.
        if r["faculty"] == "Faculty of Science":
            ps = reqs.get("physical_science")
            extended = r["qualification_type"].startswith("Extended")
            if (not extended and "physics" in low and "geology" not in low
                    and isinstance(ps, int) and ps < 5):
                problems.append(f"{code} {name!r}: Physics major with physical_science={ps} (expected >=5)")

        # Maths Lit sits one band above Maths in essentially every UJ table.
        # An inversion means the two columns were read in the wrong order.
        m, ml = reqs.get("mathematics"), reqs.get("mathematical_literacy")
        if isinstance(m, int) and isinstance(ml, int) and ml < m:
            problems.append(f"{code} {name!r}: maths_lit={ml} < maths={m} (columns likely swapped)")

        for key, value in reqs.items():
            if isinstance(value, int) and not 1 <= value <= 7:
                problems.append(f"{code}: {key}={value} outside NSC range 1-7")

        aps = r["minimum_aps"]
        if isinstance(aps, str):
            problems.append(f"{code}: unparsed APS cell {aps!r}")
        elif isinstance(aps, int) and not 15 <= aps <= 45:
            problems.append(f"{code}: implausible APS {aps}")

        if reqs.get("english") is None:  # dict form is fine; None is not
            problems.append(f"{code}: no English requirement captured")

        if r["duration_years"] is None:
            problems.append(f"{code}: no duration resolved from section heading")

    return problems


# ==========================================================================
# Export
# ==========================================================================

EXPORT_ORDER = [
    "faculty", "programme", "qualification_code", "qualification_type",
    "duration_years", "campus", "minimum_aps", "requirements",
]


def to_export(record: Dict[str, Any]) -> "OrderedDict[str, Any]":
    """Stable key order; internal provenance fields (leading _) are dropped."""
    return OrderedDict((k, record[k]) for k in EXPORT_ORDER if k in record)


def main(pdf_path: str, out_path: str, golden_path: Optional[str] = None) -> int:
    records = [apply_overlay(r) for r in extract_raw_rows(pdf_path)]
    records.sort(key=lambda r: (r["_page"], r["qualification_code"]))

    problems = validate(records)
    for p in problems:
        print(f"  VALIDATION: {p}", file=sys.stderr)

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump([to_export(r) for r in records], fh, indent=2, ensure_ascii=False)

    print(f"Extracted {len(records)} programmes -> {out_path}")
    print(f"Validation problems: {len(problems)}")

    # Regression gate against a hand-verified fixture, if supplied.
    if golden_path:
        with open(golden_path, encoding="utf-8") as fh:
            golden = {g["qualification_code"] for g in json.load(fh)}
        got = {r["qualification_code"] for r in records}
        missing, extra = sorted(golden - got), sorted(got - golden)
        print(f"vs fixture: missing={len(missing)} extra={len(extra)}")
        if missing:
            print("  missing:", ", ".join(missing))
        if extra:
            print("  extra:", ", ".join(extra))

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(
        main(
            pdf_path=sys.argv[1] if len(sys.argv) > 1 else "uj.pdf",
            out_path=sys.argv[2] if len(sys.argv) > 2 else "uj_undergraduate_courses.json",
            golden_path=sys.argv[3] if len(sys.argv) > 3 else None,
        )
    )
