#!/usr/bin/env python3
"""Extract programme rows from the UJ 2027 undergraduate prospectus.

WHY THIS IS GEOMETRY AND NOT TEXT

UJ prints each faculty's offering as one wide table whose column headers and
most of whose cell values are rotated 90 degrees -- qualification codes,
subject levels, campus codes and the conditional APS strings all run
vertically up the page. `pdftotext -layout` flattens that into something
unusable: on page 32 it shows two programmes where there are four, and it
renders "B8BA3Q" as "Q3AB8B".

Rotated runs come back from pdfplumber reversed, so a cell is rebuilt by
sorting its characters by descending `top` (rotated text reads bottom to
top). Space glyphs are real in this document, so joining the characters in
that order reproduces the cell verbatim with no word-splitting heuristics.

Columns are not fixed. Every faculty prints a different set -- FADA carries
Technical Mathematics, Health carries Life Science, Humanities pages 78-79
carry Subject 1-4 and no qualification code at all -- so columns are read
off each page's own header rather than from a template.

ROW ANCHORING

A programme name wraps over several lines ("BA" / "(COMMUNICATION" /
"DESIGN)"), so left-column lines cannot delimit rows. What marks a real row
is a value in the Qualification Code column, or, on the pages that have no
such column, in Minimum APS. Rows are anchored there and the left column is
then read within each row's vertical band.

This script only reads the table. It makes no admission-rule decisions --
conversion to requirement trees is convert_uj_programmes.py's job, and
verification is done against a different engine in verify_uj_programmes.py.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = ROOT / "sources" / "uj_undergrad_prospectus2027.pdf"

# Faculty sections, by printed page == PDF page (verified against the
# contents page, which prints "11" on PDF page 11).
FACULTIES: list[tuple[str, str, int, int]] = [
    ("fada", "Faculty of Art, Design and Architecture", 30, 37),
    ("cbe", "College of Business and Economics", 38, 51),
    ("education", "Faculty of Education", 52, 57),
    ("febe", "Faculty of Engineering and the Built Environment", 58, 63),
    ("health", "Faculty of Health Sciences", 64, 71),
    ("humanities", "Faculty of Humanities", 72, 79),
    ("law", "Faculty of Law", 80, 83),
    ("science", "Faculty of Science", 84, 97),
]

# Canonical column labels, longest first so "Technical Mathematics **" is
# matched before "Mathematics".
COLUMN_LABELS = [
    # Longest first: "Mathematical Literacy / Technical Mathematics" must
    # win over "Technical Mathematics", or the Education tables record a
    # Technical Mathematics requirement where the page offers a choice.
    "Mathematical Literacy / Technical Mathematics",
    "Additional Recognised Language",
    "Mathematics / Technical Mathematics",
    "Mathematics / Technical Maths",
    "Technical Mathematics **",
    "Technical Mathematics",
    "Mathematical Literacy",
    "Mathematics Literacy",
    "Qualification Code",
    "Physical Science **",
    "Technical Science",
    "Physical Science",
    "Minimum APS",
    "Life Science",
    "Mathematics *",
    "Mathematics",
    "PROGRAMME",
    "English *",
    "Additional Recognised Language",
    "Additional Language *",
    "Additional Language",
    "Afrikaans",
    "IsiZulu",
    "Sepedi",
    "English",
    "Subject 1",
    "Subject 2",
    "Subject 3",
    "Subject 4",
    "CAREER",
    "CAMPUS",
    # Conjunction markers. UJ prints these as their own narrow columns
    # between two subject columns to say how the pair combines -- page 60
    # sets "Physical Science | OR | Technical Science". Without them the
    # pair reads as two separate requirements, and a technical-stream
    # candidate is told they need Physical Sciences they were never
    # offered. Listed last so a longer label always wins the match.
    "AND/OR",
    "AND",
    "OR",
]
CONJUNCTIONS = {"AND/OR", "AND", "OR"}

# Lines that head a block rather than name a programme. They carry the
# duration that the rows beneath them inherit.
BLOCK_HEADER = re.compile(
    r"^(DEGREE|DIPLOMA|EXTENDED|HIGHER CERTIFICATE|CERTIFICATE)\b.*PROGRAMMES?\s*$"
    r"|^(Bachelor|BA|BCom|BSc|BEd|BEng|BHSc|LLB|Diploma|Higher Certificate|Advanced Diploma|"
    r"Extended|National Diploma)\b[^a-z]*\(\s*\d\s*(?:½|\.5)?\s*years?\s*\)\s*$",
    re.IGNORECASE,
)
DURATION_IN_HEADER = re.compile(r"\(\s*(\d)\s*(½|\.5)?\s*years?\s*\)", re.IGNORECASE)

X_BUCKET = 4.0
ROW_TOL = 4.0

# UJ qualification codes: six uppercase alphanumerics carrying at least one
# digit.
#
# This shape was derived by listing every token in the Qualification Code
# column of all eight faculties, NOT inferred from a sample. The first
# attempt guessed `[A-Z]\d[A-Z0-9]{3}Q` from a handful of FADA codes, and
# that pattern silently excludes real codes: DI1401 (Diploma in Business
# Information Technology, page 44), B34ACC, B34HRC, B9ENV1. Worse, the
# verifier used the same pattern, so the miss was invisible to the check --
# both engines agreed because both were asked the wrong question. Hence
# also the name/code parity check in verify_uj_programmes.py, which does
# not depend on this pattern at all.
#
# Six-character all-caps words in the column that are NOT codes (DEGREE,
# SCHOOL) carry no digits, so the digit requirement separates them cleanly.
# One digit, not two: B5BITQ, D6OPMQ and D2ACXQ each carry exactly one, and
# requiring two emptied the Education faculty entirely.
_CODE_TOKEN = re.compile(r"(?<![A-Z0-9])[A-Z0-9]{6}(?![A-Z0-9])")


def find_codes(text: str) -> list[str]:
    return [t for t in _CODE_TOKEN.findall(text) if any(ch.isdigit() for ch in t)]


class _QualCode:
    """Regex-shaped adapter so call sites read the same as before."""

    @staticmethod
    def findall(text: str) -> list[str]:
        return find_codes(text)

    @staticmethod
    def search(text: str):
        return bool(find_codes(text))

    @staticmethod
    def fullmatch(text: str):
        codes = find_codes(text)
        return bool(codes) and codes[0] == text.strip()


QUAL_CODE = _QualCode()
# An APS cell is a bare number, or a conditional pair ("25 with Mathematics
# OR 26 with Mathematical Literacy").
APS_VALUE = re.compile(r"^\s*\d{1,2}\b")


@dataclass
class Cell:
    column: str
    text: str
    top: float
    rotated: bool


@dataclass
class Row:
    page: int
    faculty: str
    block: str | None
    duration_years: float | None
    programme: str
    cells: dict[str, str] = field(default_factory=dict)
    block_path: list[str] = field(default_factory=list)
    column_order: list[str] = field(default_factory=list)
    block_carried: bool = False


def _bucket(x: float) -> int:
    return int(round(x / X_BUCKET))


def rotated_text(chars: list) -> str:
    """Rebuild the printed string from a group of rotated characters.

    A rotated cell can run to several lines, and each line is a separate
    vertical column of glyphs: "Not applicable" is printed as "Not " at
    x0=248.6 and "applicable" at x0=258.2. Sorting every character in the
    cell by `top` alone interleaves the two and yields "applicaNblote",
    which is how this was first got wrong.

    So: group characters into lines by x0, read the lines left to right,
    and read each line's characters bottom to top. Space glyphs are real in
    this PDF, so nothing has to be re-inserted between words.
    """
    if not chars:
        return ""
    lines: dict[int, list] = {}
    for c in chars:
        lines.setdefault(int(round(c["x0"] / 2.0)), []).append(c)
    parts = []
    for key in sorted(lines):
        run = sorted(lines[key], key=lambda c: -c["top"])
        parts.append("".join(c["text"] for c in run))
    return " ".join(p.strip() for p in parts if p.strip())


def rotated_runs(page) -> list[tuple[float, float, float, str]]:
    """(x_centre, top_min, top_max, text) for each vertical run of rotated text."""
    rot = [c for c in page.chars if not c.get("upright")]
    out: list[tuple[float, float, float, str]] = []
    rot.sort(key=lambda c: _bucket(c["x0"]))
    for _, grp in itertools.groupby(rot, key=lambda c: _bucket(c["x0"])):
        chars = list(grp)
        if not chars:
            continue
        xc = sum(c["x0"] for c in chars) / len(chars)
        tops = [c["top"] for c in chars]
        out.append((xc, min(tops), max(tops), rotated_text(chars)))
    return out


def header_bands(page) -> list[tuple[float, float]]:
    """(label_top, baseline) for every table header on the page, in order.

    Both ends are measured, not assumed. A table's rows run from its own
    baseline down to where the NEXT table's labels begin, and label blocks
    differ in height from page to page; subtracting a fixed 140pt cut page
    54's first table in half and lost two BEd programmes.

    A page can carry more than one table. Page 47 prints the extended
    diploma table and then, under its own fresh header, the ONLINE
    PROGRAMMES table; pages 54-55, 66, 68-69 and 90 do the same. Both
    headers sit at the same x, so scanning a column top-to-bottom merges
    them into one run and the second table's rows are swallowed into the
    first table's last row -- which is how B34ACC and B34HRC ended up
    concatenated inside one qualification-code cell.

    Headers are therefore found by splitting each column vertically as well
    as horizontally: a gap of more than 30pt inside a column separates two
    pieces of printing, and any piece spelling PROGRAMME starts a table.
    """
    rot = [c for c in page.chars if not c.get("upright")]
    rot.sort(key=lambda c: (_bucket(c["x0"]), -c["top"]))
    found: list[tuple[float, float]] = []

    def take(run: list) -> None:
        if run and "PROGRAMME" in rotated_text(run):
            found.append((min(x["top"] for x in run), max(x["top"] for x in run)))

    for _, grp in itertools.groupby(rot, key=lambda c: _bucket(c["x0"])):
        chars = sorted(grp, key=lambda c: c["top"])
        run: list = []
        for c in chars:
            if run and c["top"] - run[-1]["top"] > 30:
                take(run)
                run = []
            run.append(c)
        take(run)
    return sorted(found, key=lambda b: b[1])


def page_columns(page, baseline: float | None = None) -> dict[str, float]:
    """Column label -> x centre, read off one table's own header.

    Headers cannot be found by scanning whole columns. A column's run holds
    its values and its label in one string (reading bottom to top puts the
    label last), and a two-line label is split across x positions with its
    own values sitting between them -- page 86 prints "Qualification" at
    x=146.8, the codes at x=151.3 and "Code" at x=156.4. Matching whole runs
    therefore missed "Qualification Code" on that page and dropped every
    Science row that depended on it.

    So the header is read from its own band. PROGRAMME is present on every
    table page and is label-only, so its vertical extent defines where
    labels live; within that band, nearby x clusters are merged before
    matching, which reunites a split label without ever joining two real
    columns (the narrowest genuine gap in this document is 20pt).
    """
    rot = [c for c in page.chars if not c.get("upright")]
    if not rot:
        return {}

    # The band runs UPWARDS from the header baseline, not down from
    # PROGRAMME's own top. Labels are bottom-aligned, so a long one starts
    # higher than a short one: on page 87 PROGRAMME begins at top 96 while
    # "Qualification Code" begins at 78.6. A band anchored on PROGRAMME's
    # top clipped the longer labels mid-word, so they matched nothing and
    # the whole Science faculty collapsed from 95 rows to 6.
    if baseline is None:
        bands = header_bands(page)
        if not bands:
            return {}
        baseline = bands[0][1]
    band = (baseline - 130, baseline + 8)

    head = [c for c in rot if band[0] <= c["top"] <= band[1]]
    head.sort(key=lambda c: c["x0"])

    clusters: list[list] = []
    for c in head:
        if clusters and c["x0"] - clusters[-1][-1]["x0"] <= 14:
            clusters[-1].append(c)
        else:
            clusters.append([c])

    cols: dict[str, float] = {}
    for cl in clusters:
        text = rotated_text(cl)
        xc = sum(c["x0"] for c in cl) / len(cl)
        for label in COLUMN_LABELS:
            # Containment, not endswith: a header may carry a qualifier
            # after the label -- Science pages 87-94 print "PROGRAMME
            # (Major subject combination***)", which clusters into one
            # string and ended with ")", so those eight pages were gated
            # out entirely. COLUMN_LABELS is ordered longest-first, so
            # "Physical Science **" still wins over "Physical Science" and
            # "Mathematics / Technical Mathematics" over "Mathematics".
            if label in text:
                if label in CONJUNCTIONS:
                    # A conjunction can legitimately appear several times
                    # in one header -- page 55 prints "Maths/Tech Maths |
                    # OR | Mathematical Literacy | AND/OR | Physical
                    # Science | OR | Life Science". Collapsing them onto
                    # one key dropped the second OR, so Physical Science
                    # and Life Science were required together instead of
                    # either one.
                    n = sum(1 for k in cols if k.split("#")[0] == label)
                    cols[f"{label}#{n}"] = xc
                else:
                    # Nearest-wins: a label appears twice where a spread
                    # puts two tables side by side (pages 54-55, 69).
                    cols.setdefault(label, xc)
                break
    return cols



def column_bounds(cols: dict[str, float], page=None, baseline: float | None = None
                  ) -> dict[str, tuple[float, float]]:
    """Each column's x-range, taken from the cell rectangles the table draws.

    Earlier versions guessed: first a fixed tolerance around the header
    centre, which was too narrow and truncated the conditional APS strings,
    then the midpoint between neighbouring headers, which was too wide
    beside the CAREER column and pulled career prose into Technical
    Mathematics ("Not accepted Architectural shaping construction the most
    in the erection...").

    Neither guess was necessary. The header row is drawn as one rectangle
    per column, so the true edges are in the file; a label belongs to the
    rectangle its centre falls inside. Midpoints remain only as a fallback
    for a table that draws no header cells.
    """
    if page is not None and baseline is not None:
        cells = sorted(
            (r for r in page.rects
             if r["top"] < baseline < r["top"] + r["height"]
             and r["height"] > 30 and r["width"] < 480),
            key=lambda r: r["x0"],
        )
        if cells:
            out: dict[str, tuple[float, float]] = {}
            for label, x in cols.items():
                for r in cells:
                    if r["x0"] <= x < r["x1"]:
                        out[label] = (r["x0"], r["x1"])
                        break
            if len(out) == len(cols):
                return out

    ordered = sorted(cols.items(), key=lambda kv: kv[1])
    out = {}
    for i, (label, x) in enumerate(ordered):
        lo = (ordered[i - 1][1] + x) / 2 if i else x - 30
        hi = (ordered[i + 1][1] + x) / 2 if i + 1 < len(ordered) else x + 30
        out[label] = (lo, hi)
    return out


def split_runs_into_cells(page, cols: dict[str, float], bounds=None) -> list[Cell]:
    """Every cell on the page, whichever way its text is set.

    Orientation is not a property of the table, it is a property of the
    faculty. FADA rotates its values; Humanities (pages 74-76) prints the
    identical columns upright, so a whole row reads as one horizontal line
    -- "SOCIAL WORK B7025Q 31 5 Social Worker ... APK". Anchoring rows on
    rotated text alone found nothing there and silently dropped the entire
    faculty. Even within one page the two mix: a plain numeric APS is set
    upright where a conditional one is rotated.

    So both orientations are assigned to columns the same way, by x
    proximity, and a row is anchored on whatever its anchor column holds.
    """
    if not cols:
        return []
    cells: list[Cell] = []
    bounds = bounds or column_bounds(cols)

    def column_for(x0: float) -> str | None:
        for label, (lo, hi) in bounds.items():
            if lo <= x0 < hi:
                return label
        return None

    # ── rotated ──────────────────────────────────────────────────────────
    by_col: dict[str, list] = {}
    for c in page.chars:
        if c.get("upright"):
            continue
        label = column_for(c["x0"])
        if label:
            by_col.setdefault(label, []).append(c)

    for label, chars in by_col.items():
        chars.sort(key=lambda c: -c["top"])
        run: list = []
        for c in chars:
            if run and abs(run[-1]["top"] - c["top"]) > 14:
                cells.append(_mk_cell(label, run, rotated=True))
                run = []
            run.append(c)
        if run:
            cells.append(_mk_cell(label, run, rotated=True))

    # ── upright ──────────────────────────────────────────────────────────
    up_by_col: dict[str, list] = {}
    for w in upright_words(page):
        label = column_for(w["x0"])
        if label and label not in ("PROGRAMME", "CAREER"):
            up_by_col.setdefault(label, []).append(w)

    for label, words in up_by_col.items():
        words.sort(key=lambda w: w["top"])
        run = []
        for w in words:
            if run and abs(run[-1]["top"] - w["top"]) > 6:
                cells.append(_mk_upright_cell(label, run))
                run = []
            run.append(w)
        if run:
            cells.append(_mk_upright_cell(label, run))

    # Drop each column's own header cell.
    return [c for c in cells if c.text.strip() not in COLUMN_LABELS]


def _mk_cell(label: str, chars: list, rotated: bool) -> Cell:
    return Cell(label, rotated_text(chars).strip(), min(c["top"] for c in chars), rotated)


def _mk_upright_cell(label: str, words: list) -> Cell:
    text = " ".join(w["text"] for w in sorted(words, key=lambda w: (w["top"], w["x0"])))
    return Cell(label, text.strip(), min(w["top"] for w in words), False)


def upright_words(page) -> list[dict]:
    """Upright words only.

    page.extract_words() returns rotated words too, with their glyphs in
    reverse ("EMMARGORP" for PROGRAMME). Letting those through put mirrored
    header text into programme names.
    """
    words = page.extract_words(
        use_text_flow=False, keep_blank_chars=False, extra_attrs=["upright"]
    )
    return [w for w in words if w.get("upright", True)]


def cells_in_band(page, cols: dict[str, float], top: float, bottom: float, bounds=None,
                  skip: list | None = None) -> dict[str, str]:
    """Every column's text within one row's vertical band.

    Characters are assigned to the band first and to a column second, rather
    than a column's content being cut into cells by vertical gaps. Gap
    splitting looked reasonable and was wrong: a conditional APS is set as
    two tall rotated lines ("24 with Maths/Tech Maths OR" / "26 with
    Mathematical Literacy"), and consecutive rows' strings run into one
    another with no gap to split on. The whole column collapsed into a
    single cell belonging to the first row, leaving 14 programmes across six
    pages with no APS at all.
    """
    bounds = bounds or column_bounds(cols)

    def column_for(x0: float) -> str | None:
        for label, (lo, hi) in bounds.items():
            if lo <= x0 < hi:
                return label
        return None

    def blocked(x: float, y: float) -> bool:
        # A banner row can overlap a data row's band; its words are not
        # cell values. Without this, "Bachelor of ... (3 years)" leaked in
        # and subject cells read "5 (60%+) (3" / "5 (60%+) years)".
        return any(r["x0"] <= x < r["x1"] and r["top"] - 2 <= y < r["top"] + r["height"]
                   for r in (skip or []))

    rot: dict[str, list] = {}
    for c in page.chars:
        if c.get("upright") or not (top <= c["top"] < bottom) or blocked(c["x0"], c["top"]):
            continue
        label = column_for(c["x0"])
        if label:
            rot.setdefault(label, []).append(c)

    out = {label: rotated_text(chars) for label, chars in rot.items()}

    up: dict[str, list] = {}
    for w in upright_words(page):
        if not (top <= w["top"] < bottom) or blocked(w["x0"], w["top"]):
            continue
        label = column_for(w["x0"])
        if label and label not in ("PROGRAMME", "CAREER"):
            up.setdefault(label, []).append(w)
    for label, words in up.items():
        text = " ".join(
            w["text"] for w in sorted(words, key=lambda w: (round(w["top"] / 3), w["x0"]))
        )
        out[label] = (out.get(label, "") + " " + text).strip() if out.get(label) else text

    return {
        k: v for k, v in ((k, _dehyphenate(v)) for k, v in out.items())
        if v and v not in COLUMN_LABELS
    }


def _dehyphenate(text: str) -> str:
    """Rejoin words the typesetter split across rotated lines.

    Rotated cells are narrow, so UJ hyphenates inside them: "Not applica-
    ble", "Mathe- matics", "Li- teracy". Reassembling the lines preserves
    the hyphen and the space, and a requirement cell reading "Not applica-
    ble" matches nothing.
    """
    return re.sub(r"(\w)-\s+(\w)", r"\1\2", text.replace("\xa0", " ")).replace("  ", " ").strip()



def _banner_rects(page, cols: dict[str, float], baseline: float, region_end: float) -> list:
    others = [x for l, x in cols.items() if l != "PROGRAMME"]
    if not others:
        return []
    prog_right = min(others) - 10
    # Banners AND in-table notes. Both span past the programme column and
    # neither is cell content: the notes are what left "4 (50%+) does
    # accupuncturist Allied the master for Homeopathy" in a Mathematics
    # requirement. Only the coloured ones are headings (block_bands
    # filters on fill); the white ones are notes, excluded but not titled.
    return [
        r for r in page.rects
        if r["x0"] < 60 and r["x1"] > prog_right + 30
        and 8 < r["height"] < 40
        and baseline < r["top"] < region_end
    ]


def block_bands(page, cols: dict[str, float], baseline: float, region_end: float
                ) -> list[tuple[float, str]]:
    """(top, text) for each banner row inside this table.

    Banners carry the qualification type and duration that the rows beneath
    inherit -- "Bachelor of Engineering (BEng) Degree (4 years)", "Diplomas
    (3 years)", "Bachelor of Science in Physical Sciences". Matching them by
    wording failed: 119 of 179 rows came back with no block at all, because
    the Science banners are plain title case with no "(N years)" and no
    "PROGRAMMES".

    They are recognised by shape instead. A banner's leftmost rectangle
    spans past the programme column -- across the whole table on page 60,
    as far as the career column on page 90 -- where an ordinary row's stops
    at the column edge.
    """
    others = [x for l, x in cols.items() if l != "PROGRAMME"]
    if not others:
        return []
    prog_right = min(others) - 10
    bands = [
        r for r in page.rects
        if r["x0"] < 60 and r["x1"] > prog_right + 30
        and 8 < r["height"] < 32
        and baseline < r["top"] < region_end
        and _is_banner_fill(r)
    ]
    out = []
    words = upright_words(page)
    for r in sorted(bands, key=lambda r: r["top"]):
        inside = [
            w for w in words
            if r["top"] - 2 <= w["top"] < r["top"] + r["height"] and r["x0"] <= w["x0"] < r["x1"]
        ]
        # Line by line, then left to right. Sorting on x alone interleaves a
        # banner that spans two columns: the BEd headings came out as
        # "BEd - LANGUAGE Degree in EDUCATION Senior Phase and ...".
        inside.sort(key=lambda w: (round(w["top"] / 3), w["x0"]))
        text = " ".join(w["text"] for w in inside).strip()
        if text:
            out.append((r["top"], text))
    return out


# Banners are filled orange or grey; an in-table note is filled white. The
# fill is what separates them -- matching on wording let the Emergency
# Medical Care note on page 66 become a qualification heading.
_BANNER_FILLS = ((0.91, 0.353, 0.047), (0.838, 0.835, 0.846))


def _is_banner_fill(rect) -> bool:
    ns = rect.get("non_stroking_color")
    if not ns or not rect.get("fill"):
        return False
    try:
        rgb = tuple(round(float(v), 3) for v in ns)
    except (TypeError, ValueError):
        return False
    return any(all(abs(a - b) < 0.02 for a, b in zip(rgb, f)) for f in _BANNER_FILLS if len(rgb) == 3)

def extract_page(page, page_no: int, faculty: str) -> list[Row]:
    """Every table on the page, each read within its own vertical region."""
    bands = header_bands(page)
    rows: list[Row] = []
    for i, (_label_top, baseline) in enumerate(bands):
        # Rows stop where the next table's LABELS start, measured from that
        # header rather than guessed as a fixed offset.
        region_end = bands[i + 1][0] - 6 if i + 1 < len(bands) else page.height
        rows.extend(extract_table(page, page_no, faculty, baseline, region_end))
    return rows


def extract_table(page, page_no: int, faculty: str, baseline: float, region_end: float) -> list[Row]:
    cols = page_columns(page, baseline)
    if "PROGRAMME" not in cols:
        return []

    # Clamp the table at the bottom edge it actually draws.
    #
    # The last row otherwise runs to the next header or the page foot and
    # swallows whatever sits below the table -- footnotes, the running
    # footer -- which is how "FINANCE" became "FINANCE UJ Accountancy
    # outstanding 2027 UNDERGRADUATE PROSPECTUS". The row COUNT still comes
    # from the anchors, so this does not borrow the verifier's row test; it
    # only stops text bleeding in past the last rule.
    others_x = [x for l, x in cols.items() if l != "PROGRAMME"]
    if others_x:
        right = min(others_x)
        boxes = [
            r for r in page.rects
            if r["x0"] < 60 and r["height"] > 8
            and abs(r["x1"] - (right - 10)) < 45
            and baseline <= r["top"] < region_end
        ]
        if boxes:
            region_end = min(region_end, max(r["top"] + r["height"] for r in boxes) + 2)

    bounds = column_bounds(cols, page, baseline)
    banners = block_bands(page, cols, baseline, region_end)
    banner_rects = _banner_rects(page, cols, baseline, region_end)
    cells = [
        c for c in split_runs_into_cells(page, cols, bounds)
        if baseline + 8 <= c.top < region_end
    ]

    # A row is anchored on a value that LOOKS like what the anchor column
    # holds, not merely on something landing at that x. The faculty intro
    # pages carry the table header but no table, and their body prose sits
    # under the column positions -- unshaped anchoring turned page 30's
    # blurb about "the hashtag generation" into 37 programmes.
    anchor_col = "Qualification Code" if "Qualification Code" in cols else "Minimum APS"
    shape = QUAL_CODE if anchor_col == "Qualification Code" else APS_VALUE
    anchors = sorted(
        {round(c.top, 1) for c in cells if c.column == anchor_col and shape.search(c.text)}
    )
    if not anchors:
        return []

    # The programme name is set to the LEFT of the PROGRAMME header, not
    # under it, so the name region runs from the page edge to just before
    # the first real data column.
    others = [x for l, x in cols.items() if l != "PROGRAMME"]
    name_limit = (min(others) - 20) if others else page.width
    # Lines built from the NAME COLUMN'S words only.
    #
    # Grouping upright words into full page-width lines first and then
    # keeping those that START left of the name column keeps the whole
    # line, career prose and all: "ACCOUNTING 28 Financial Manager,
    # Accountant," came out as a programme name, and 104 of 179 names were
    # contaminated that way. The x filter has to be applied per word,
    # before words are joined.
    lines = [
        l for l in left_region_lines(page, name_limit)
        if baseline + 8 <= l[1] < region_end
    ]

    # Exact row edges, from the rectangles the table draws.
    #
    # Anchor-to-anchor bands are approximate: a cell's text can start a few
    # points above its row's qualification code, so on page 54 a single
    # "Not applicable" split across the boundary and arrived as "Not" in
    # one row and "applicable" in the next -- neither of which means
    # anything. Row IDENTITY and COUNT still come from the anchors, so the
    # verifier's rectangle count remains an independent check; only the
    # edges are taken from the drawing.
    row_boxes = sorted(
        (r for r in page.rects
         if r["x0"] < 60 and r["height"] > 8
         and others and abs(r["x1"] - (min(others) - 10)) < 45
         and baseline + 8 <= r["top"] < region_end),
        key=lambda r: r["top"],
    ) if (others := [x for l, x in cols.items() if l != "PROGRAMME"]) else []

    def band_for(top: float, fallback_end: float) -> tuple[float, float]:
        for r in row_boxes:
            if r["top"] - ROW_TOL - 6 <= top < r["top"] + r["height"]:
                return r["top"] - 2, r["top"] + r["height"] - 1
        return top - ROW_TOL, fallback_end - ROW_TOL

    rows: list[Row] = []
    for i, top in enumerate(anchors):
        nxt = anchors[i + 1] if i + 1 < len(anchors) else region_end
        row = Row(page=page_no, faculty=faculty, block=None, duration_years=None, programme="")
        lo, hi = band_for(top, nxt)
        row.cells = cells_in_band(page, cols, lo, hi, bounds, banner_rects)
        name_parts = [
            text
            for _x0, ltop, text in lines
            if lo <= ltop < hi and not BLOCK_HEADER.match(text)
        ]
        row.programme = clean_name(" ".join(name_parts))
        row.column_order = [l for l, _ in sorted(cols.items(), key=lambda kv: kv[1])]
        rows.append(row)

    _apply_blocks(rows, banners, anchors)
    _fill_merged_cells(page, cols, bounds, rows, anchors, baseline, region_end)
    return rows


def _fill_merged_cells(page, cols, bounds, rows, anchors, baseline, region_end) -> None:
    """Give a vertically merged cell's value to every row it spans.

    Where consecutive rows share a requirement, UJ draws ONE tall cell
    across them: on page 54 the three BEd Commerce subjects share a single
    English cell reading "Home language 5 (60%+) OR Additional Language
    6 (70%+)". Assigning text to the row band it starts in gave that
    requirement to Accounting alone and left Business Management and
    Economics with no English requirement at all -- which the seed
    validator caught, and which would have admitted candidates the page
    does not.

    The drawing says what is merged: a cell rectangle taller than one row
    belongs to every row it covers. Only empty cells are filled, so a row
    with its own value always keeps it.
    """
    if not rows:
        return
    words = upright_words(page)
    for label, (lo, hi) in bounds.items():
        if label in ("PROGRAMME", "CAREER"):
            continue
        tall = [
            r for r in page.rects
            if lo - 2 <= r["x0"] < hi and abs(r["x1"] - hi) < 6
            and baseline + 8 <= r["top"] < region_end
            and r["height"] > 1.6 * min(
                (a2 - a1) for a1, a2 in zip(anchors, list(anchors[1:]) + [region_end])
            )
        ]
        for rect in tall:
            inside_rot = [
                c for c in page.chars
                if not c.get("upright")
                and lo <= c["x0"] < hi
                and rect["top"] <= c["top"] < rect["top"] + rect["height"]
            ]
            inside_up = [
                w for w in words
                if lo <= w["x0"] < hi
                and rect["top"] <= w["top"] < rect["top"] + rect["height"]
            ]
            text = (rotated_text(inside_rot) + " " + " ".join(
                w["text"] for w in sorted(inside_up, key=lambda w: (round(w["top"] / 3), w["x0"]))
            )).strip()
            text = _dehyphenate(text)
            if not text or text in COLUMN_LABELS:
                continue
            for row, top in zip(rows, anchors):
                if rect["top"] - 4 <= top < rect["top"] + rect["height"]:
                    # Overwrite, don't just fill blanks. The rows under a
                    # merged cell each catch a FRAGMENT of its text -- page
                    # 54 split one English requirement into "Home language
                    # 5 (60%+)", "OR Additional Language" and "6 (70%+)" --
                    # so none of them is empty and none of them is right.
                    # The rectangle proves the three belong to one cell.
                    row.cells[label] = text


def left_region_lines(page, limit: float) -> list[tuple[float, float, str]]:
    """Lines assembled only from upright words left of `limit`."""
    words = sorted(
        (w for w in upright_words(page) if w["x0"] < limit),
        key=lambda w: (round(w["top"] / 3), w["x0"]),
    )
    out = []
    for _, grp in itertools.groupby(words, key=lambda w: round(w["top"] / 3)):
        g = sorted(grp, key=lambda w: w["x0"])
        out.append((g[0]["x0"], g[0]["top"], " ".join(w["text"] for w in g)))
    return out


def upright_lines(page) -> list[tuple[float, float, str]]:
    """(x0, top, text) for each line of upright text, left to right."""
    words = sorted(upright_words(page), key=lambda w: (round(w["top"] / 3), w["x0"]))
    out = []
    for _, grp in itertools.groupby(words, key=lambda w: round(w["top"] / 3)):
        g = sorted(grp, key=lambda w: w["x0"])
        out.append((g[0]["x0"], g[0]["top"], " ".join(w["text"] for w in g)))
    return out


_SENTENCE_WORD = re.compile(r"^[A-Z][a-z]")
# "the"/"a" are deliberately absent: they almost never appear inside a UJ
# programme name but routinely begin the note that follows one ("The UJ
# actuarial science degree subjects A111...").
_NAME_CONNECTORS = {"with", "specialisation", "specialising", "in", "and",
                    "of", "for", "or", "to"}


def clean_name(text: str) -> str:
    """Trim an in-cell footnote off the end of a programme name.

    Some programme cells carry a note under the name, inside the same drawn
    box: "CHIROPRACTIC Applicants are required letters of recommendation",
    "ACTUARIAL SCIENCE The UJ actuarial science degree subjects A111...".
    The box boundary cannot separate them because the note is genuinely
    inside it.

    Names are set in capitals, with lowercase connectors ("BA with
    specialisation in STRATEGIC COMMUNICATION"); notes read as ordinary
    sentences. So the name ends at the first sentence-case word that is not
    inside brackets -- brackets being where real names do use sentence case
    ("(Artificial Intelligence)").
    """
    out: list[str] = []
    depth = 0
    for tok in text.split():
        # Whether this token is bracketed is decided by the depth BEFORE
        # it. Applying its closing paren first made "Intelligence)" look
        # unbracketed, so it tripped the sentence-case rule and truncated
        # "... specialising in AI (Artificial Intelligence)".
        inside = depth > 0
        depth = max(depth + tok.count("(") - tok.count(")"), 0)
        if inside:
            out.append(tok)
            continue
        # A footnote marker ends the name when something follows it. A
        # trailing marker is part of the printed name ("MARKETING **").
        if depth <= 0 and out and set(tok) == {"*"}:
            break
        if depth <= 0 and tok.startswith("*") and len(tok) > 2:
            break
        if depth <= 0 and _SENTENCE_WORD.match(tok) and tok.lower().strip(":,.") not in _NAME_CONNECTORS:
            break
        out.append(tok)
    return " ".join(out).strip(" ,;:-").strip()


def _apply_blocks(rows: list[Row], headers: list[tuple[float, str]], anchors) -> None:
    """Attach the banners above each row, and the duration they state.

    Both the nearest banner and the section banner above it are kept:
    "EXTENDED DEGREE PROGRAMMES" sits above "Bachelor of Engineering
    Technology (3 years)", and dropping the outer one loses the fact that
    the programme is extended.
    """
    for row, top in zip(rows, anchors):
        above = [h for h in headers if h[0] <= top + ROW_TOL]
        if not above:
            continue
        above.sort(key=lambda h: h[0])
        row.block = above[-1][1]
        row.block_path = [t for _, t in above]
        for _, txt in reversed(above):
            m = DURATION_IN_HEADER.search(txt)
            if m:
                row.duration_years = float(m.group(1)) + (0.5 if m.group(2) else 0.0)
                break


def extract(pdf_path: Path) -> list[Row]:
    """All faculty tables, with banners carried across page breaks.

    A banner is printed once and governs every row under it until the next
    one, including the rows that continue onto the following page -- the
    FADA "BA Degree (3 years)" heading is on page 32 and its last three
    programmes are on page 33. Reading each page in isolation left 25 rows
    with no qualification type and no duration. Carry-over is reset at each
    faculty boundary, so a heading never leaks into a faculty it was not
    printed in.
    """
    rows: list[Row] = []
    with pdfplumber.open(pdf_path) as pdf:
        for slug, _name, first, last in FACULTIES:
            carried_block: str | None = None
            carried_path: list[str] = []
            carried_duration: float | None = None
            for n in range(first, last + 1):
                for row in extract_page(pdf.pages[n - 1], n, slug):
                    if row.block is None:
                        row.block = carried_block
                        row.block_path = list(carried_path)
                        row.duration_years = carried_duration
                        row.block_carried = carried_block is not None
                    else:
                        carried_block = row.block
                        carried_path = list(row.block_path)
                        carried_duration = row.duration_years
                    rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    rows = extract(args.pdf)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps([asdict(r) for r in rows], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    per_fac: dict[str, int] = {}
    per_page: dict[int, int] = {}
    for r in rows:
        per_fac[r.faculty] = per_fac.get(r.faculty, 0) + 1
        per_page[r.page] = per_page.get(r.page, 0) + 1
    print(f"{len(rows)} rows -> {args.out}")
    for slug, _n, _f, _l in FACULTIES:
        print(f"  {slug:<11} {per_fac.get(slug, 0):>3}")
    print("  pages:", ", ".join(f"p{p}={c}" for p, c in sorted(per_page.items())))


if __name__ == "__main__":
    main()
