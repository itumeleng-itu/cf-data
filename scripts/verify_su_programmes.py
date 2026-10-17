#!/usr/bin/env python3
"""Independently verify the Stellenbosch extraction.

WHY THIS FILE EXISTS, AND WHAT IT IS NOT ALLOWED TO DO

The UJ extraction shipped a verifier that recomputed its answer with
the extractor's own qualification-code regex. The regex was wrong, so
the check agreed with the bug and the miss stayed invisible until the
data was loaded. A verifier that shares a feature or an engine with
the thing it verifies is not a verifier.

So nothing here uses DURATION, PROGRAMME-name matching, or the
pdfplumber line reconstruction that the extractor relies on:

  Check 1  TYPOGRAPHY     A different FEATURE. Programme headings are
                          set in Raleway-ExtraBold at 10pt; body text
                          is Raleway-Medium at 8pt. Counting bold
                          blocks cannot be fooled by a duration the
                          extractor's regex does not recognise -- which
                          is the exact fault that hid "LLB (four-year)",
                          a full undergraduate degree, from the first
                          three runs of this pipeline.

  Check 2  POPPLER        A different ENGINE. Every extracted name must
                          appear in pdftotext's rendering of its own
                          page. Catches anything pdfplumber invented or
                          mis-joined across the column gutter.

  Check 3  INTEGRITY      Every offered programme states an aggregate,
                          and no requirement has swallowed prose. This
                          is what fails when a block opener is read as
                          a bullet continuation.

Exit status is non-zero if any check fails, so the conversion can be
gated on it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "sources" / "su_admissions_booklet_2027.pdf"

HEADING_FONT = "Raleway-ExtraBold"
HEADING_SIZE = 10.0
LINE_TOL = 2.0
FIRST_PAGE, LAST_PAGE = 2, 15

# Bold 10pt blocks that are legitimately not programme headings.
#
# Every entry is a banner or a label, and each is listed with the
# reason it is not an offering. This list is the place a reviewer
# should look first if a programme ever goes missing again: adding a
# name here is how a real heading would be silenced, so each one has
# to earn its place.
KNOWN_NON_HEADINGS: dict[str, str] = {
    "Admission and selection":
        "Faculty-wide requirement block (p9, p10, p12, p13), not a programme.",
    "BEng PROGRAMMES":
        "Section banner above the seven BEng entries on p10.",
    "Extended Curriculum Programmes (ECPs)":
        "p4 group banner with no duration; the ECP variants are not "
        "separately admissible offerings.",
    "BSc Extended Curriculum Programmes":
        "First half of the wrapped p15 heading '(ECPs) (4 years)'.",
    "Postgraduate Certificate in Education (PGCE) (1 year) (full time on campus)":
        "Wrapped tail of the p9 PGCE heading. Its trailing parenthetical "
        "is a mode of delivery, not part of the qualification name, so the "
        "words do not appear in the extracted name.",
    "(PGCE) (1 year) (full time on campus)":
        "As above -- the tail line on its own.",
    "BCom (Management Sciences)":
        "Repeated on p7 as the label above that programme's own "
        "'Extended Curriculum Programme (ECP) (4 years)' entry.",
}


def bold_blocks(page) -> list[tuple[float, str]]:
    """(top, text) for each run of heading-weight type on the page.

    Split at the gutter before grouping by height. The booklet sets
    two columns, and headings routinely sit at the same height in
    both -- "BScAgric in Animal Production Systems (4 years)" on the
    left of p3 and "BSc in Forestry (Forestry and Wood Sciences)" on
    the right. Grouping by `top` alone welded them into one block
    that naturally matched no programme.

    The gutter is a measured property of the page (nothing is set
    between x 280 and 300 anywhere in the booklet), not a borrowed
    piece of the extractor's heading logic.
    """
    out: list[tuple[float, str]] = []
    for lo, hi in ((0, 290.0), (290.0, page.width)):
        chars = [
            c
            for c in page.chars
            if lo <= c["x0"] < hi
            and c["fontname"].split("+")[-1] == HEADING_FONT
            and round(c["size"], 1) == HEADING_SIZE
        ]
        chars.sort(key=lambda c: (c["top"], c["x0"]))

        groups: list[list[dict]] = []
        current: list[dict] = []
        for c in chars:
            if current and c["top"] - current[0]["top"] > LINE_TOL:
                groups.append(current)
                current = []
            current.append(c)
        if current:
            groups.append(current)

        for g in groups:
            text = "".join(c["text"] for c in sorted(g, key=lambda c: c["x0"]))
            out.append((g[0]["top"], " ".join(text.split())))
    return sorted(out)


def poppler_pages() -> dict[int, str]:
    """Page text from a different PDF engine entirely."""
    pages: dict[int, str] = {}
    for n in range(FIRST_PAGE, LAST_PAGE + 1):
        out = subprocess.run(
            ["pdftotext", "-f", str(n), "-l", str(n), "-layout", str(PDF), "-"],
            capture_output=True,
            text=True,
            check=True,
        )
        pages[n] = " ".join(out.stdout.split())
    return pages


def normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def check_typography(rows: list[dict]) -> list[str]:
    """Every heading-weight block is an extracted heading or a known banner."""
    failures: list[str] = []
    by_page: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_page[r["page"]].append(r)

    known = {normalise(k) for k in KNOWN_NON_HEADINGS}

    # A heading is printed over two lines often enough that neither
    # half is the whole name: p3 sets "BSc in Forestry (Forestry and
    # Wood Sciences)" above "(BScFor) (4 years)". So a bold block is
    # accounted for when its words are all present in some programme
    # name on that page. Duration words are ignored because they are
    # printed but not kept in the name -- this is string tidying for
    # the comparison, not how headings are found. What finds them is
    # the font, and that is the point of this check.
    free = {"year", "years"} | {str(d) for d in range(1, 10)}

    with pdfplumber.open(PDF) as pdf:
        for n in range(FIRST_PAGE, LAST_PAGE + 1):
            names = [set(normalise(r["name"]).split()) for r in by_page.get(n, [])]
            for _, text in bold_blocks(pdf.pages[n - 1]):
                t = normalise(text)
                if not t or t in known:
                    continue
                words = set(t.split()) - free
                if not words:
                    # Nothing left but a duration, so this is the
                    # tail of a heading whose name is on the line
                    # above -- "(4 years)" under "Bachelor of
                    # Speech-Language and Hearing Therapy" on p12.
                    continue
                if any(words <= nm for nm in names):
                    continue
                failures.append(
                    f"p{n}: heading-weight text {text!r} matches no extracted "
                    f"programme and is not a documented banner"
                )
    return failures


def check_poppler(rows: list[dict]) -> list[str]:
    """Every extracted name is present in a second engine's text."""
    failures: list[str] = []
    pages = poppler_pages()
    for r in rows:
        page = normalise(pages[r["page"]])
        # Headings wrap, and poppler interleaves the columns, so the
        # name may be broken by text from the facing column. Require
        # every word of it to be on the page instead of the whole
        # phrase -- still enough to catch an invented programme.
        missing = [w for w in normalise(r["name"]).split() if w not in page.split()]
        if missing:
            failures.append(
                f"p{r['page']}: {r['name']!r} -- word(s) {missing} absent from "
                f"poppler's text for that page"
            )
    return failures


AGGREGATE = re.compile(
    r"aggregate|National Senior Certificate|\bNSC\b|selection mark", re.I
)

# What a swallowed prose block looks like.
#
# "Career opportunities:" and "Similar programmes:" always carry their
# colon and never occur inside a requirement, so they are flagged
# wherever they appear. "Fields of study" and "Focal areas" cannot be,
# because p3 prints the genuine bullet "See additional requirements
# for each field of study" -- so those two are flagged only when they
# trail a requirement that already stated a percentage, which is the
# signature of a block opener glued onto the end of a bar.
PROSE_LEAK = re.compile(
    r"\b(Career opportunities|Similar programmes?|Postgraduate fields of study)\s*:"
    r"|%.*\b(Fields? of study|Focal areas?)\s*$",
    re.I,
)


# A requirement cannot end on a conjunction; if one does, half of it
# is missing.
DANGLING = re.compile(r"\b(?:or|and)\s*$", re.I)


def check_integrity(rows: list[dict]) -> list[str]:
    failures: list[str] = []
    for r in rows:
        if r["kind"] != "programme":
            continue
        reqs = r["requirements"]
        if not reqs:
            failures.append(f"p{r['page']}: {r['name']!r} has no requirements")
            continue
        if not any(AGGREGATE.search(q["text"]) for q in reqs):
            failures.append(
                f"p{r['page']}: {r['name']!r} states no aggregate or NSC line"
            )
        for q in reqs:
            if q["text"].strip() not in {"AND", "OR"} and DANGLING.search(q["text"]):
                failures.append(
                    f"p{r['page']}: {r['name']!r} requirement ends on a dangling "
                    f"conjunction, so half of it is missing: {q['text'][:70]!r}"
                )
            if PROSE_LEAK.search(q["text"]):
                failures.append(
                    f"p{r['page']}: {r['name']!r} requirement has swallowed a "
                    f"prose block: {q['text'][:70]!r}"
                )
    return failures


def main() -> int:
    rows_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if rows_path is None or not rows_path.exists():
        print("usage: verify_su_programmes.py <su_rows.json>", file=sys.stderr)
        return 2
    rows = json.loads(rows_path.read_text(encoding="utf-8"))

    checks = [
        ("typography (Raleway-ExtraBold 10pt blocks)", check_typography),
        ("poppler (independent PDF engine)", check_poppler),
        ("requirement integrity", check_integrity),
    ]

    total = 0
    for label, fn in checks:
        failures = fn(rows)
        total += len(failures)
        mark = "ok  " if not failures else "FAIL"
        print(f"[{mark}] {label}: {len(failures)} problem(s)")
        for f in failures[:20]:
            print(f"        {f}")

    programmes = [r for r in rows if r["kind"] == "programme"]
    print(
        f"\n{len(rows)} headings, {len(programmes)} offered programmes, "
        f"{len(rows) - len(programmes)} excluded"
    )
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
