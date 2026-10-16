#!/usr/bin/env python3
"""Verify the UJ extraction against evidence the extractor never consults.

A check that shares the extractor's reasoning cannot see the extractor's
blind spot. That is not hypothetical here: the first version of this script
counted qualification codes with the same regex the extractor used, so when
that regex turned out to be wrong -- it excluded DI1401, a real diploma code
on page 44 -- both sides agreed and the row was lost silently. Agreement
between two things asking the same wrong question is worth nothing.

So the row count comes from somewhere else entirely:

  1. DRAWN GEOMETRY. UJ draws these tables with real rectangles. The
     left-hand column's boxes are counted directly, which involves no text,
     no regex and no notion of what a qualification code looks like. This
     is the primary check, and it is what caught page 54 holding eight rows
     where six were extracted.

  2. A DIFFERENT PDF ENGINE. Codes are counted again from poppler's
     `pdftotext -layout` output, a separate implementation. poppler renders
     the rotated cells mirrored ("Q3AB8B"), so both spellings are accepted.

  3. COMPLETENESS of each row: a name, and an APS.

Checks 1 and 2 disagree with each other by design. Where a page's drawn rows
and its codes differ, that is reported rather than reconciled, because the
difference is usually a real feature of the page.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pdfplumber  # noqa: E402

from extract_uj_programmes import (  # noqa: E402
    FACULTIES, find_codes, header_bands, page_columns,
)

DEFAULT_PDF = ROOT / "sources" / "uj_undergrad_prospectus2027.pdf"
CODE_TOKEN_ANY = re.compile(r"(?<![A-Z0-9])[A-Z0-9]{6}(?![A-Z0-9])")

# Codes that appear in the prospectus but are deliberately not programmes in
# the seed. Each needs a reason, and the reason has to be a fact about the
# document rather than a convenience.
KNOWN_NON_PROGRAMMES = {
    "S3M01Q": "Short Learning Programme (Retail Management), named only in a "
              "footnote on page 45 as an alternative access route; not an "
              "undergraduate qualification.",
    "MKT010": "Short Learning Programme module (Introduction to Retail "
              "Management), named only in the same page 45 footnote.",
    "B34INQ": "BCom Industrial Psychology. Appears ONLY in the NC(V) admission "
              "table on page 49 -- UJ publishes no NSC row for it anywhere in "
              "this prospectus, so there are no NSC requirements to record. "
              "Admitting it would mean inventing them.",
    "B34HRP": "A second Human Resource Management code appearing only in the "
              "NC(V) table on page 49 (the NSC tables carry B34HRQ on page 40 "
              "and B34HRC on page 47). No NSC row is published for it.",
    "B34ACP": "BCom (Accounting) as listed only in the NASCA table on page 51; "
              "the NSC tables carry B34ACC. No NSC row is published for it.",
}


def codes_on_page(text: str) -> set[str]:
    """Code-shaped tokens poppler emits for a page, as printed.

    These are NOT canonicalised. poppler renders rotated cells mirrored, and
    a mirrored code is itself code-shaped -- "B8BA3Q" comes out "Q3AB8B" and
    both pass the shape test. Choosing a canonical orientation here would be
    a guess, and guessing it wrong reported 188 phantom missing codes. So
    both spellings are kept and `covers()` compares in either direction.
    """
    return {t for t in CODE_TOKEN_ANY.findall(text) if find_codes(t) == [t]}


def covers(tokens: set[str], code: str) -> bool:
    """Whether poppler saw this code, written forwards or mirrored."""
    return code in tokens or code[::-1] in tokens


def drawn_rows(page) -> int | None:
    """Data rows the page actually draws, from vector rectangles alone.

    The leftmost column's boxes are the programme cells. The first is the
    header cell (it is markedly taller and starts at the table top), and
    block-header bands span the full table width rather than this column.
    """
    bands = header_bands(page)
    if not bands:
        return None
    cols = page_columns(page, bands[0][1])
    if "PROGRAMME" not in cols:
        return None
    others = [x for l, x in cols.items() if l != "PROGRAMME"]
    if not others:
        return None
    right = min(others)
    boxes = [
        r for r in page.rects
        if r["x0"] < 60 and r["height"] > 8 and abs(r["x1"] - (right - 10)) < 45
    ]
    if not boxes:
        return None
    # One header cell per table, not one per page: page 47 prints two
    # tables and so draws two header boxes.
    return len(boxes) - len(bands)


def poppler_pages(pdf: Path) -> list[str]:
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    return out.split("\f")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--manifest", type=Path)
    args = ap.parse_args()

    rows = json.loads(args.rows.read_text(encoding="utf-8"))
    pages_text = poppler_pages(args.pdf)
    in_range = {n for _s, _n, f, l in FACULTIES for n in range(f, l + 1)}

    by_page: dict[int, list] = defaultdict(list)
    seen: Counter[str] = Counter()
    extracted_codes: dict[int, set[str]] = defaultdict(set)
    for r in rows:
        by_page[r["page"]].append(r)
        for c in find_codes(r["cells"].get("Qualification Code", "")):
            seen[c] += 1
            extracted_codes[r["page"]].add(c)

    failures: list[str] = []
    notes: list[str] = []

    # 1 ── drawn geometry
    with pdfplumber.open(args.pdf) as pdf:
        for n in sorted(in_range):
            drawn = drawn_rows(pdf.pages[n - 1])
            if drawn is None:
                if by_page.get(n):
                    failures.append(f"p{n}: {len(by_page[n])} rows extracted from a page that draws no table")
                continue
            got = len(by_page.get(n, []))
            if drawn != got:
                failures.append(f"p{n}: page draws {drawn} data rows, extraction produced {got}")

    # 2 ── a different engine
    poppler_all: set[str] = set()
    for n, text in enumerate(pages_text, start=1):
        poppler_all |= codes_on_page(text)
    ours = set(seen)
    excluded = set(KNOWN_NON_PROGRAMMES)
    # A poppler token is accounted for if it, or its mirror, was extracted
    # or is a documented exclusion.
    unaccounted = {
        t for t in poppler_all
        if not any(covers({t}, c) for c in ours | excluded)
    }
    if unaccounted:
        shown = sorted(unaccounted)[:20]
        failures.append(
            f"{len(unaccounted)} code-shaped token(s) poppler sees that nothing accounts for: {shown}"
        )
    invented = {c for c in ours if not covers(poppler_all, c)}
    if invented:
        failures.append(f"{len(invented)} code(s) extracted that poppler never sees: {sorted(invented)}")
    for code, why in KNOWN_NON_PROGRAMMES.items():
        if code in ours:
            failures.append(f"{code} is recorded as not-a-programme but was extracted anyway")
        elif covers(poppler_all, code):
            notes.append(f"excluded {code}: {why}")

    for n in sorted(in_range):
        here = codes_on_page(pages_text[n - 1])
        stray = {c for c in extracted_codes.get(n, set()) if not covers(here, c)}
        if stray:
            failures.append(f"p{n}: code(s) attributed to this page that poppler does not see here: {sorted(stray)}")

    # 3 ── completeness
    dupes = {c: k for c, k in seen.items() if k > 1}
    if dupes:
        failures.append(f"code(s) extracted more than once: {dupes}")
    nameless = [(r["page"], r["cells"].get("Qualification Code", "?")) for r in rows if not r["programme"].strip()]
    apsless = [(r["page"], r["cells"].get("Qualification Code", "?")) for r in rows if not r["cells"].get("Minimum APS", "").strip()]
    if nameless:
        failures.append(f"{len(nameless)} row(s) with no programme name: {nameless[:12]}")
    if apsless:
        failures.append(f"{len(apsless)} row(s) with no Minimum APS: {apsless[:12]}")

    print(f"rows extracted       : {len(rows)}")
    print(f"distinct codes       : {len(seen)}")
    print(f"codes poppler sees   : {len(poppler_all)}")
    print(f"documented exclusions: {len(KNOWN_NON_PROGRAMMES)}")
    for note in notes:
        print(f"   - {note}")
    print()

    if failures:
        print(f"FAIL  ({len(failures)} check(s))")
        for f in failures:
            print("  -", f)
        return 1

    print("PASS  drawn rows, poppler codes and extraction all agree; every row named and scored")
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps({str(n): sorted(extracted_codes.get(n, set())) for n in sorted(in_range)}, indent=2),
            encoding="utf-8",
        )
        print(f"manifest -> {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
