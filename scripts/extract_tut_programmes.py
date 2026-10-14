"""Extracts TUT's 2027 admission tables into JSON, one record per
programme, in one pass. Running it twice gives the same file.

THE DOCUMENT
    "First Year Course Information 2027". Despite the title it carries
    ADMISSION REQUIREMENTS, not curricula: compulsory subjects and
    their minimum levels, one or more APS thresholds each conditioned
    on which mathematics the learner offers, duration, campuses,
    closing dates, recommended subjects, further study and careers.
    There is no course outline anywhere in it.

COLUMNS COME FROM GEOMETRY, NOT FROM THE HEADER TABLE
    The header table merges cells -- "COMPULSORY ADMISSION
    REQUIREMENTS" spans the four columns beneath it -- so its boxes do
    not correspond to the data table's columns. Matching labels against
    it mapped `levels` onto whichever column mentioned "MINIMUM" first
    and read page 6's campus column as programme names, emitting four
    programmes called "M Po". So the data table's own columns are used:
    drop ruling slivers, and the remainder are COLUMNS in order. A page
    that does not yield exactly ten is REPORTED, never guessed at.

    Widths are measured from the row with the most real cells, not row
    0: on pages 9 and 16 the first data row is merged into one 785pt
    cell, and measuring it reported the page as a single column and
    silently dropped two faculties.

SUBJECTS PAIR WITH LEVELS BY BASELINE
    See requirements.py. In short: the two columns are not the same
    length, because the source sometimes prints no minimum at all, so
    zipping them shifts every later pairing and invents a level the
    document never printed.
"""
import json
import re
import sys

import pdfplumber

import tut_requirements as reqs

PDF = ("/root/.claude/uploads/05d7cf72-f1a4-5c4b-a455-53a8dec2267e/"
       "f1664967-First-Year-Course_Information_1.pdf")

# The ten data columns, left to right, fixed by the page design.
COLUMNS = ["programme", "campuses", "duration", "closing", "subjects",
           "levels", "aps", "recommended", "further", "careers"]
SLIVER_WIDTH = 8        # narrower than this is a ruling, not a column


def sidebar(page) -> str:
    """Faculty and campus, printed vertically down the left edge.
    pdfplumber emits rotated words in reverse, so the text arrives
    mirrored ("NGISED DNA STRA FO YTLUCAF"); reversing the whole string
    un-mirrors characters and word order together."""
    words = [w["text"] for w in page.extract_words(extra_attrs=["upright"])
             if w.get("upright") is False]
    return " ".join(words)[::-1] if words else ""


def faculty_and_campus(page):
    m = re.search(r"(FACULTY OF [A-Z ,&]+?)\s*\|\s*([A-Za-z ]+?Campus(?:es)?)",
                  sidebar(page))
    if not m:
        return None, None
    faculty = m.group(1).strip().title()
    faculty = re.sub(r"\bOf\b", "of", faculty)
    faculty = re.sub(r"\bAnd\b", "and", faculty)
    faculty = re.sub(r"\bThe\b", "the", faculty)
    faculty = faculty.replace("Ict", "ICT")
    return faculty, m.group(2).strip()


def table_and_columns(page):
    """-> (table, {field: cell_box}, problem)"""
    best = None
    for t in page.find_tables():
        ex = t.extract()
        if len(ex) > 2 and (best is None or len(ex) > len(best.extract())):
            best = t
    if best is None:
        return None, None, None
    ref = max(best.rows, key=lambda r: sum(1 for c in r.cells if c))
    keep = [i for i, c in enumerate(ref.cells)
            if c and (c[2] - c[0]) >= SLIVER_WIDTH]
    if len(keep) != len(COLUMNS):
        return best, None, f"{len(keep)} columns after dropping slivers"
    return best, {name: ref.cells[keep[i]] for i, name in enumerate(COLUMNS)}, None


def row_extents(table):
    """(row, top, bottom) for each row, with every row clipped at the
    next one's top.

    find_tables() reports a row's box from its ruling lines, and where
    a row's cells are merged that box can span everything below it:
    page 9's first programme row is 406pt tall and covers the other
    nine. Reading inside it then collects every name on the page, which
    is how "BEd (Foundation Phase Teaching) BEd (Intermediate Phase
    Teaching) ..." arrived as one programme. Rows cannot overlap, so
    the next row's top is the real bottom."""
    ordered = sorted(table.rows, key=lambda r: r.bbox[1])
    out = []
    for i, row in enumerate(ordered):
        top, bottom = row.bbox[1], row.bbox[3]
        if i + 1 < len(ordered):
            bottom = min(bottom, ordered[i + 1].bbox[1])
        out.append((row, top, bottom))
    return out


def text_in(page, box, top, bottom, words) -> str:
    got = [w for w in words
           if box[0] <= w["x0"] < box[2] and top <= w["top"] < bottom]
    got.sort(key=lambda w: (round(w["top"]), w["x0"]))
    return " ".join(w["text"] for w in got).strip()


APS_ENTRY = re.compile(r"(\d+)\s*(\([^)]*\))?")


def parse_aps(text: str):
    """One or more thresholds, each optionally conditioned on which
    mathematics the learner offers: "22 (with Accounting or Mathematics
    or Technical Mathematics)" then "24 (with Mathematical Literacy)"."""
    out = []
    for score, cond in APS_ENTRY.findall(text or ""):
        condition = cond[1:-1].strip() if cond else None
        if condition:
            condition = re.sub(r"^with\s+", "", condition, flags=re.I)
            condition = re.sub(r"\s+", " ", condition)
        out.append({"min_score": int(score), "condition": condition})
    return out


def scoreable_route(groups) -> bool:
    """True when a route states NSC subject requirements with levels --
    something a school-leaver can be matched against. An experiential
    route (a Senior Certificate plus five years' service, HAZMAT
    certificates) states none, and no formula here can score it."""
    return bool(groups) and any(b.get("min_level") for g in groups for b in g)


def extract():
    programmes, pages_seen, skipped = [], [], []
    with pdfplumber.open(PDF) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            table, cols, problem = table_and_columns(page)
            if table is None:
                continue
            if cols is None:
                skipped.append((pno, problem))
                continue
            faculty, campus = faculty_and_campus(page)
            if faculty is None:
                # Pages 1 and 3 carry tables that are not programme
                # tables (a cover, and the APS explanation chart). The
                # faculty sidebar is what makes a page a faculty page.
                skipped.append((pno, "no faculty sidebar - not a programme table"))
                continue
            words = page.extract_words()
            before = len(programmes)

            for row, top, bottom in row_extents(table):
                if not row.cells or all(c is None for c in row.cells):
                    continue
                if bottom - top < 2:
                    continue
                name = text_in(page, cols["programme"], top, bottom, words)
                aps_text = text_in(page, cols["aps"], top, bottom, words)

                if not name or name.upper().startswith("PROGRAMME"):
                    # A continuation row carries a further APS threshold
                    # for the programme above it.
                    extra = parse_aps(aps_text)
                    if extra and programmes:
                        programmes[-1]["aps"].extend(extra)
                    continue

                # A programme with more than one ROUTE into it prints
                # its name again rather than starting a new programme.
                # Dip (Policing) on page 11 prints two: an experiential
                # one for serving law-enforcement officers (a Senior
                # Certificate, an NQF 5/6 qualification and five years'
                # service, no APS) and an ordinary NSC one (English 3,
                # a mathematics at 3, APS 20). Treated as two records
                # they become two identical cards, one of which can
                # never be matched and tells a school-leaver nothing.
                if programmes and programmes[-1]["name"] == re.sub(r"\s+", " ", name) \
                        and programmes[-1]["page"] == pno:
                    groups, notes, problems = reqs.parse(page, (top, bottom), cols, words)
                    prev = programmes[-1]
                    prev["aps"].extend(parse_aps(aps_text))
                    prev["notes"].extend(notes)
                    prev["routes"] += 1
                    # The scoreable route wins: a route with levelled
                    # subject requirements is one a school-leaver can
                    # actually be matched against, where an
                    # experiential one never matches anybody here.
                    if scoreable_route(groups) and not scoreable_route(prev["requirements"]):
                        prev["requirements"] = groups
                        prev["problems"] = problems
                    else:
                        prev["notes"].extend(
                            opt for g in groups for b in g
                            for opt in (b.get("options") or b.get("all_of") or []))
                    continue

                groups, notes, problems = reqs.parse(page, (top, bottom), cols, words)
                duration = re.findall(
                    r"\d+", text_in(page, cols["duration"], top, bottom, words))

                # A section heading spans the table with nothing in any
                # other column: "TEACHING COURSES", "HEALTH SCIENCES".
                # It is a label for the rows beneath it, not a
                # programme, and counting it inflated the total to 129
                # against the 125 TUT's own dataset held.
                if not duration and not groups and not parse_aps(aps_text):
                    continue
                programmes.append({
                    "page": pno,
                    "faculty": faculty,
                    "campus": campus,
                    "name": re.sub(r"\s+", " ", name),
                    "other_campuses": text_in(page, cols["campuses"], top, bottom, words) or None,
                    "duration_years": int(duration[0]) if duration else None,
                    "closing_date": text_in(page, cols["closing"], top, bottom, words) or None,
                    "requirements": groups,
                    "aps": parse_aps(aps_text),
                    "recommended": text_in(page, cols["recommended"], top, bottom, words) or None,
                    "further_studies": text_in(page, cols["further"], top, bottom, words) or None,
                    "careers": text_in(page, cols["careers"], top, bottom, words) or None,
                    "notes": notes,
                    "problems": problems,
                    "routes": 1,
                })
            pages_seen.append((pno, faculty, len(programmes) - before))

    for p in programmes:
        # Dip (Fire Technology) is admitted on work experience and fire
        # certificates alone, with no APS and no subject levels. Forcing
        # it into a subject tree would invent requirements; the same
        # treatment Wits' NBT-gated programmes get applies here.
        p["scoreable"] = scoreable_route(p["requirements"]) and bool(p["aps"])
        if not p["scoreable"]:
            p["notes"].extend(
                opt for g in p["requirements"] for b in g
                for opt in (b.get("options") or b.get("all_of") or []))
            p["requirements"] = []
            p["problems"] = []
    return programmes, pages_seen, skipped


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    progs, pages, skipped = extract()
    json.dump({"source": "TUT First Year Course Information 2027",
               "programme_count": len(progs), "programmes": progs},
              open("tut_2027.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    print(f"{'pg':>3} {'progs':>6}  faculty")
    for pno, fac, n in pages:
        print(f"{pno:>3} {n:>6}  {fac}")
    if skipped:
        print("\nPages read nothing from:")
        for pno, why in skipped:
            print(f"  p{pno}: {why}")

    flagged = [p for p in progs if p["problems"]]
    print(f"\nprogrammes          : {len(progs)}")
    print(f"faculties           : {len({p['faculty'] for p in progs})}")
    print(f"with an APS         : {sum(1 for p in progs if p['aps'])}")
    print(f"with requirements   : {sum(1 for p in progs if p['requirements'])}")
    print(f"rows with a problem : {len(flagged)}")
    for p in flagged[:15]:
        print(f"   p{p['page']} {p['name'][:44]}")
        for issue in p["problems"]:
            print(f"        {issue}")
