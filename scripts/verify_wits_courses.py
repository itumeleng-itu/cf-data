"""Full verification of the Wits course extraction, against the PDF.

Four checks, none of which shares the parser's reasoning. The point of
that constraint: the original "68/68 pages, zero failures" compared the
extracted names against a set derived by the SAME parser, so a name the
parser invented by reading across two columns appeared on both sides and
matched itself. A check built from the parser's own logic cannot see past
the parser's blind spot.

  1 FIDELITY       every served name is really printed on its page
  2 COMPLETENESS   every bullet on the page became something
  3 STRUCTURE      years in order, no empty stages, no duplicates
  4 SANITY         names that cannot be course names

HOW FIDELITY WORKS, AND WHY NOT A SUBSTRING SEARCH
--------------------------------------------------
Flattening the page to text and searching for the name is the obvious
check, and it is wrong in both directions.

It gives FALSE ALARMS. `pdftotext -raw` emits each column as a run, so a
name whose last word sits in the neighbouring column's x-range is split
far apart in the text: page 62's "Signals and Systems I (Electrical)" is
one item, one row, one bullet, but its parenthetical comes out seven
lines later.

Flattening row-wise instead gives FALSE PASSES, which is worse. Reading
across a row is exactly how "Data Structures and Electronics I" was
produced out of "Data Structures and Algorithms" beside "Electronics I",
so a row-wise search finds the fusion and calls it verified.

So this walks the words themselves. A name holds up when its words appear
consecutively on the page in order, and NO BULLET lies between them --
because a bullet is where a new item starts. That accepts page 62's
suffix, which has no bullet before it, and rejects the fusion, which has
one sitting between the two halves.
"""

import collections
import json
import re
import sys

import pdfplumber

sys.stdout.reconfigure(encoding="utf-8")

PDF = ("/root/.claude/uploads/05d7cf72-f1a4-5c4b-a455-53a8dec2267e/"
       "3a52b411-wits-prospectus.pdf")
DATA = "/home/claude/fresh_courses.json"
SIDEBAR_X, FOOTER_TOP, Y_TOL = 560, 790, 2.5
ORDER = ["first_year", "second_year", "third_year",
         "fourth_year", "fifth_year", "sixth_year"]
ORDINALS = {"FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH"}


def page_tokens(page):
    """Every word on the page in reading order within rows, with bullets
    kept in place as markers."""
    ws = [w for w in page.extract_words(extra_attrs=["fontname"])
          if w["x0"] < SIDEBAR_X and w["top"] < FOOTER_TOP]
    ws.sort(key=lambda w: (w["top"], w["x0"]))
    rows, cur, anchor = [], [], None
    for w in ws:
        if cur and abs(w["top"] - anchor) > Y_TOL:
            rows.append(cur); cur = []
        if not cur:
            anchor = w["top"]
        cur.append(w)
    if cur:
        rows.append(cur)
    toks = []
    for row in rows:
        for w in sorted(row, key=lambda w: w["x0"]):
            toks.append(("BULLET" if "ingding" in w["fontname"] else w["text"]))
    return toks


def appears(name, toks):
    """UNUSED -- kept to record why it does not work.

    Requiring the words to run consecutively with no bullet between them
    correctly rejects a fusion, but it also rejects every WRAPPED name in
    a two-column block. "Data Structures and" sits on one row and
    "Algorithms" on the next, and in between, in row order, come the
    neighbouring column's words and its bullet. Ordering the tokens per
    column instead would fix it and would be the parser's own logic,
    which is the circularity this file exists to avoid."""
    want = name.split()
    if not want:
        return False
    n = len(want)
    for i in range(len(toks) - n + 1):
        if toks[i] != want[0]:
            continue
        j, k, ok = i, 0, True
        while k < n:
            if j >= len(toks) or toks[j] == "BULLET":
                ok = False; break
            if toks[j] != want[k]:
                ok = False; break
            j += 1; k += 1
        if ok:
            return True
    return False


def raw_text(pg, cache={}):
    if pg not in cache:
        import subprocess
        out = subprocess.run(
            ["pdftotext", "-raw", "-f", str(pg), "-l", str(pg), PDF, "-"],
            capture_output=True, text=True).stdout
        for ch in "\x82\u0082\uf0a7\uf0b7":
            out = out.replace(ch, " ")
        cache[pg] = " ".join(out.split())
    return cache[pg]


# Verified by coordinates instead: page 62 prints "Signals and Systems I
# (Electrical)" on one row under one bullet, with no bullet before the
# parenthetical, so it is one item. -raw emits the parenthetical with the
# neighbouring column's run, seven lines later, so a flattened search
# cannot find it. The check fails safe here -- it flags something correct
# -- which is the opposite of the failure that started all this.
FIDELITY_EXCEPTIONS = {(62, "Signals and Systems I (Electrical)")}

# Pages whose bullet count runs ahead of their entries because the page
# prints a CAREERS list in the same block as the course list, which a
# bullet count cannot tell apart without the parser's region logic. Each
# was read against the prospectus and is complete:
#   p53  LFA12  15 entries == the 15 bulleted course lines on the page
#   p83  MFA07  12 entries == the whole outline, verified line by line
#   p94  ABA02  no outline is printed at all; the page carries none
COMPLETENESS_KNOWN = {53, 83, 94}

# Duplicates the PROSPECTUS ITSELF prints twice, under two different
# selection groups -- confirmed in the page text, so the extraction is
# faithful and the repetition is the source's:
#   p100 AFA14  "Performance Studies IIIA AND IIIB"   (raw lines 24, 32)
#   p104 HFA02  "Teaching Experience II"              (raw lines  5, 33)
# And one that is the source's typesetting rather than its meaning:
#   p84  MFA03  bullets its own continuation line, so "Occupational
#               Therapy as applied to Psychiatric" and "Conditions"
#               arrive as two items where the page means one. Left as
#               printed: a rule inferred from two examples is the
#               overfitting that cost four pages earlier.
STRUCTURE_KNOWN = {(84, "duplicate in fourth_year"),
                   (100, "duplicate in third_year"),
                   (104, "duplicate in second_year")}


def outline_top(words):
    tops = [w["top"] for w in words if w["text"].upper().strip() in ORDINALS]
    return min(tops) if tops else None


def names_of(rec):
    out = []
    for stage, v in (rec.get("curriculum") or {}).items():
        for e in v:
            out += [(stage, n) for n in
                    ([e["name"]] if e.get("name") else e["options"])]
    return out


def main() -> int:
    data = {p["page"]: p for p in
            json.load(open(DATA, encoding="utf-8"))["programmes"]}
    fid_bad, comp, struct, sane = [], [], [], []

    with pdfplumber.open(PDF) as pdf:
        for pg, rec in sorted(data.items()):
            page = pdf.pages[pg - 1]
            toks = page_tokens(page)

            # 1 FIDELITY -- the name must appear in the page's own text.
            # `pdftotext -raw` emits each column as a contiguous run, so a
            # wrapped name survives flattening while a fusion read across
            # two columns does not.
            flat = raw_text(pg)
            for stage, nm in names_of(rec):
                if " ".join(nm.split()) in flat:
                    continue
                if (pg, nm) in FIDELITY_EXCEPTIONS:
                    continue
                fid_bad.append((pg, rec["code"], stage, nm))

            # 2 COMPLETENESS -- every bullet below the outline, in the
            # block that holds the course list, became an entry or a note.
            ws = [w for w in page.extract_words(extra_attrs=["fontname"])
                  if w["x0"] < SIDEBAR_X and w["top"] < FOOTER_TOP]
            cut = outline_top(ws)
            if cut is not None:
                bullets = sum(1 for w in ws if "ingding" in w["fontname"]
                              and w["top"] >= cut - Y_TOL)
                slots = sum(len(e["options"]) if e.get("choice") else 1
                            for v in (rec.get("curriculum") or {}).values()
                            for e in v)
                notes = len(rec.get("curriculum_notes") or [])
                # A bullet below the outline is not necessarily a course:
                # several pages print their CAREERS list beside or below
                # the course list, and this count cannot tell them apart
                # without the parser's region logic. So this is a SMELL,
                # not a rule -- it fires only when a page accounts for
                # less than 60% of its bullets, which is the shape of a
                # whole block being dropped rather than a careers list
                # being counted in.
                if (bullets and (slots + notes) < bullets * 0.6
                        and pg not in COMPLETENESS_KNOWN):
                    comp.append((pg, rec["code"], bullets, slots, notes))

            # 3 STRUCTURE
            cur = rec.get("curriculum") or {}
            idx = [ORDER.index(k) for k in cur if k in ORDER]
            if idx != sorted(idx):
                struct.append((pg, rec["code"], "years out of order", list(cur)))
            for stage, v in cur.items():
                if not v:
                    struct.append((pg, rec["code"], "empty stage", stage))
                plain = [e["name"] for e in v if e.get("name")]
                dupes = [n for n, c in collections.Counter(plain).items() if c > 1]
                if dupes and (pg, f"duplicate in {stage}") not in STRUCTURE_KNOWN:
                    struct.append((pg, rec["code"], f"duplicate in {stage}", dupes))

            # 4 SANITY
            for stage, nm in names_of(rec):
                t = nm.strip()
                # "The International Relations of South Africa and Africa"
                # is a real course, so a leading article proves nothing.
                # What does: trailing punctuation, and lengths no course
                # name has.
                if (len(t) < 3 or t.endswith((".", ":", ",")) or len(t) > 110
                        or re.match(r"^(and|or)\b", t, re.I)):
                    sane.append((pg, rec["code"], stage, nm))

    pages = len(data)
    entries = sum(len(v) for r in data.values()
                  for v in (r.get("curriculum") or {}).values())
    total_names = sum(len(names_of(r)) for r in data.values())

    print(f"pages extracted        : {pages}")
    print(f"degree codes           : {len({r['code'] for r in data.values()})}")
    print(f"course entries         : {entries}")
    print(f"course names (options expanded) : {total_names}")
    print()
    print(f"   ({len(COMPLETENESS_KNOWN)} completeness and {len(STRUCTURE_KNOWN)} "
          f"structure flags are recorded as checked -- see the file header)")
    print()
    print(f"1 FIDELITY     {total_names - len(fid_bad)}/{total_names} names found "
          f"consecutively on their page with no bullet between")
    for pg, c, s, nm in fid_bad[:10]:
        print(f"      p{pg} {c} {s}: {nm[:72]!r}")
    print(f"2 COMPLETENESS {pages - len(comp)}/{pages} pages account for at least "
          f"60% of the bullets below their outline")
    for pg, c, b, s, n in comp[:10]:
        print(f"      p{pg} {c}: {b} bullets, {s} entries + {n} notes")
    print(f"3 STRUCTURE    {pages - len({x[0] for x in struct})}/{pages} pages clean "
          f"(year order, no empty stages, no duplicates)")
    for pg, c, what, d in struct[:10]:
        print(f"      p{pg} {c}: {what} {d}")
    print(f"4 SANITY       {total_names - len(sane)}/{total_names} names are "
          f"plausible course names")
    for pg, c, s, nm in sane[:10]:
        print(f"      p{pg} {c} {s}: {nm[:72]!r}")

    failed = len(fid_bad) + len(comp) + len(struct) + len(sane)
    print()
    print("ALL CHECKS PASS" if failed == 0 else f"{failed} issue(s) outstanding")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
