"""
Wits 2027 prospectus — course extraction, pages 40-131.

Built from four failure modes found by measuring against the source:

  1. bulleted curricula      (44 pages)  bullet glyph marks each item
  2. unbulleted curricula    ( 4 pages)  bare AND / OR lines separate items
  3. mixed                   (16 pages)  both styles on one page
  4. no curriculum on page   ( 4 pages)  cross-referenced to other pages

Plus: the bullet glyph sits ~0.9pt ABOVE its text (cluster on top with a
tolerance, never a hard bucket); a rotated faculty banner runs down the outer
edge at x>560; and page footers must be stripped or they glue onto the last
course name.

Deterministic. No model.
"""
import json, re
import pdfplumber

PDF = "/root/.claude/uploads/05d7cf72-f1a4-5c4b-a455-53a8dec2267e/3a52b411-wits-prospectus.pdf"
FIRST, LAST = 40, 131
SPLIT_X, SIDEBAR_X, Y_TOL = 300, 560, 2.5
FOOTER_TOP = 790                      # page number + course-finder URL

YEARS = {"FIRST YEAR", "SECOND YEAR", "THIRD YEAR",
         "FOURTH YEAR", "FIFTH YEAR", "SIXTH YEAR"}

# A stage heading is not always the bare words. The LLB pages head their
# blocks "THIRD YEAR (FIRST YEAR OF REGISTRATION)", because an LLB entered
# after a first degree starts in the third year of study; and because the
# heading is long, it WRAPS, so the parenthesis closes on the next line.
#
# Matching YEARS by equality missed both pages 53 and 54 entirely -- 15 and
# 14 courses read as zero. Worse, it went unnoticed: the completeness check
# derived its expected names with this same stage detection, so a page where
# no stage was found expected nothing and got nothing, and passed. A check
# that shares the parser's blind spot cannot see past it, which is why
# verify.py now asserts non-emptiness against the page's own text.
#
# The suffix must start with "(" -- so a course whose name merely begins
# with an ordinal year is not mistaken for a heading.
YEAR_HEAD = re.compile(
    r"^(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)[\s-]+YEAR\b\s*(\(.*)?$", re.I)
CONNECTOR = re.compile(r"^(AND|OR)[,:]?$", re.I)
# A connector that is not alone on its line but introduces the next item:
# page 119 prints "AND Archaeology I" and "AND/OR Any other Level III
# major" rather than putting the AND on a line of its own. Without this
# the line reads as a continuation and sticks to the item above, giving
# "Calculus AND Any other Level I course".
#
# UPPERCASE only, and never a line ending in a colon. The same shape in
# lower case is wrapped prose or a wrapped name -- "and GIS" (p71), "and
# Scarcity" (p121) -- and a trailing colon marks a header introducing the
# list below it, such as "AND, any three courses from the following:"
# (p62). Splitting on either breaks pages that parse correctly today.
INLINE_CONNECTOR = re.compile(r"^(AND/OR|AND|OR)[,:]?\s+(?P<rest>.+[^:\s])\s*$")
PROSE = re.compile(
    r"(credits?|must be|must have|must complete|is required|^you\b|"
    r"^a student\b|^the school\b|one of the following|at least|a total|"
    r"a minimum|refer to|please note|^note\b|^nb\b|students who|subject to|"
    r"provided that|in addition|choose|select|^plus\b|see page|pages? \d)", re.I)
# A line ending in a colon heads the list below it and is never itself a
# course: "Recommended course:", "Mathematics I (Major):". Without this it
# is absorbed as a continuation and comes out glued to the item above --
# "Any other Level I course Recommended course".
HEADER = re.compile(r":\s*$")
CODE_RE = re.compile(r"^[A-Z]{2,4}\d{2,3}[A-Z]?$")
DEGREE_RE = re.compile(r"^(Bachelor|BCom|BSc|BA\b|BEng|BNurs|BPharm|BDS|BHSci|"
                       r"MBBCh|Master|Diploma|Advanced)", re.I)


# ----------------------------------------------------------------- layout --
ORDINALS = {"FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH"}


def outline_top(words):
    """Y of the first year heading, or None.

    Band detection must look only BELOW it. Several pages set their CAREERS
    list in two bulleted columns high up the right-hand block -- pages 115,
    119 and 124 -- while the course list underneath is a single column.
    Taking bands from the whole block splits a curriculum that was never
    split, which mangled all three."""
    tops = [w["top"] for w in words if w["text"].upper().strip() in ORDINALS]
    return min(tops) if tops else None


def bullet_bands(words):
    """Where bulleted lists start within one outer column.

    Usually one. A few pages set two lists side by side inside the
    right-hand block -- page 62's second year at x=333 and x=449 -- and
    clustering rows across both reads straight through them, giving "Data
    Structures and Electronics I" out of "Data Structures and Algorithms"
    beside "Electronics I": a course in neither list.

    Across all 92 programme pages, adjacent bullet positions within one
    column differ by at most 19pt (indentation jitter, one list) or at
    least 78pt (a second list). Nothing lies between 20 and 77, so
    COLUMN_GAP separates the two without being a tuned guess.
    """
    cut = outline_top(words)
    if cut is None:
        return []
    bands = []
    for x in sorted(w["x0"] for w in words
                    if "ingding" in w["fontname"] and w["top"] >= cut):
        if not bands or x - bands[-1] > COLUMN_GAP:
            bands.append(x)
    return bands


def page_lines(page):
    """(text, bullet, col, top, band) in reading order.

    Rows are clustered WITHIN a bulleted list, never across two that sit
    side by side, so a row carrying one item from each yields two lines.
    """
    out = []
    col = 0
    for lo, hi in ((0, SPLIT_X), (SPLIT_X, page.width)):
        ws = [w for w in page.extract_words(extra_attrs=["fontname"])
              if lo <= w["x0"] < hi and w["x0"] < SIDEBAR_X
              and w["top"] < FOOTER_TOP]
        ws.sort(key=lambda w: (w["top"], w["x0"]))

        # Only the right-hand block. The left column carries the narrative
        # and the CAREERS list, itself often in two bulleted columns, and
        # splitting those gains nothing while breaking the pages where the
        # course list begins at the foot of the left column.
        bands = bullet_bands(ws) if lo >= SPLIT_X else []
        if len(bands) < 2:
            groups = [(col, ws)]
            col += 1
        else:
            edges = [(bands[i] + bands[i + 1]) / 2
                     for i in range(len(bands) - 1)]

            def band_of(word, row_bullets):
                # A word belongs to the list whose bullet is nearest to its
                # LEFT on its own row. That keeps "Signals and Systems I
                # (Electrical)" whole even though "(Electrical)" starts at
                # x=454, inside the neighbouring list's x range -- that
                # list simply has no item on that row. Only when no bullet
                # precedes it does the x position decide, which is the wrap
                # case: "Algorithms" alone continues the item above it.
                left = [b for b in row_bullets if b <= word["x0"] + 1]
                x = max(left) if left else word["x0"]
                for i, edge in enumerate(edges):
                    if x < edge:
                        return i
                return len(edges)

            rows, cur, anchor = [], [], None
            for w in ws:
                if cur and abs(w["top"] - anchor) > Y_TOL:
                    rows.append(cur); cur = []
                if not cur:
                    anchor = w["top"]
                cur.append(w)
            if cur:
                rows.append(cur)

            buckets = {i: [] for i in range(len(bands))}
            for row in rows:
                row_bullets = sorted(w["x0"] for w in row
                                     if "ingding" in w["fontname"])
                for w in row:
                    buckets[band_of(w, row_bullets)].append(w)
            groups = [(col + i, sorted(v, key=lambda w: (w["top"], w["x0"])))
                      for i, v in buckets.items() if v]
            col += len(bands)

        for ci, group in groups:
            cur, anchor = [], None
            for w in group:
                if cur and abs(w["top"] - anchor) > Y_TOL:
                    out.append((cur, ci)); cur = []
                if not cur:
                    anchor = w["top"]
                cur.append(w)
            if cur:
                out.append((cur, ci))

    res = []
    for cluster, ci in out:
        cluster.sort(key=lambda w: w["x0"])
        bullets = [w["x0"] for w in cluster if "ingding" in w["fontname"]]
        res.append({
            "text": " ".join(w["text"] for w in cluster
                             if "ingding" not in w["fontname"]).strip(),
            "bullet": bool(bullets),
            "col": ci,
            "top": min(w["top"] for w in cluster),
            "x": bullets[0] if bullets else min(
                (w["x0"] for w in cluster if "ingding" not in w["fontname"]),
                default=0.0),
        })
    return [l for l in res if l["text"] or l["bullet"]]


def year_of(text):
    """The stage a line heads, or None if it heads no stage.

    Returns the canonical key ("third_year"), so a heading's parenthetical
    qualifier is used to recognise it and then discarded -- the stage is
    the year of STUDY, which is what the curriculum dict is keyed by."""
    m = YEAR_HEAD.match(" ".join(text.split()))
    return f"{m.group(1).lower()}_year" if m else None


def merge_wrapped_headings(lines):
    """Rejoins a stage heading split across two lines.

    "THIRD YEAR (FIRST YEAR OF" / "REGISTRATION)" is one heading. It is
    detectable without guessing: the first line opens a parenthesis it
    never closes, so the heading cannot have ended there."""
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        text = line["text"]
        if (year_of(text)
                and text.count("(") > text.count(")")
                and i + 1 < len(lines)):
            nxt = lines[i + 1]["text"]
            if ")" in nxt and not year_of(nxt):
                out.append({**line, "text": f"{text} {nxt}".strip()})
                i += 2
                continue
        out.append(line)
        i += 1
    return out


def curriculum_region(lines):
    """From the first YEAR heading to CAREERS or end of page."""
    lines = merge_wrapped_headings(lines)
    start = next((i for i, l in enumerate(lines) if year_of(l["text"])), None)
    if start is None:
        return []
    region = []
    for l in lines[start:]:
        upper = l["text"].upper().strip()
        # CAREERS ends the outline. So does HONOURS STUDY (pages 98, 120),
        # a postgraduate aside printed below it -- without this its prose
        # is swept onto the last course, giving "Any other Level III major
        # HONOURS STUDY Follow your BSc undergraduate degree with...".
        if upper.startswith("CAREER") or upper.startswith("HONOURS STUD"):
            break
        region.append(l)
    return region


# -------------------------------------------------------------- curriculum --
# Two bulleted lists set side by side inside the right-hand block, which
# the row clustering reads straight across: page 62's second year gives
# "Data Structures and Electronics I" out of "Data Structures and
# Algorithms" beside "Electronics I", a course in neither list.
#
# Across all 92 programme pages, adjacent bullet positions within one
# column differ by at most 19pt (indentation jitter, one list) or at least
# 78pt (a second list beside the first). Nothing lies between 20 and 77,
# so 40 separates the two cases without being a tuned guess.
COLUMN_GAP = 40
# A wrapped course name sits within 25pt of the line it continues: across
# all 92 pages 779 of 790 continuation gaps are under 25pt and the rest
# form a sparse tail. A larger gap means the text below is a new block --
# a prose paragraph under the course list (pages 104, 128) or the tail of
# a sentence from elsewhere -- not a continuation, and gluing it on gives
# "Any other Level III major HONOURS STUDY Follow your BSc..." .
CONTINUATION_GAP = 35


def split_columns(lines):
    """One year block -> its side-by-side lists, left to right.

    Returns [lines] unchanged when the block holds a single list, which is
    every block on all but a handful of pages.

    Splitting per YEAR BLOCK rather than per page is what makes this safe.
    An earlier attempt partitioned the whole page and emitted each column
    as one run, so the second column's items landed under whichever year
    heading the parser had last seen -- it fixed page 62 and corrupted four
    others. A year block is already bounded by its own heading, so every
    item inside it belongs to that year whichever column it sits in.
    """
    bullet_xs = sorted(l["x"] for l in lines if l["bullet"])
    if not bullet_xs:
        return [lines]
    bands = [bullet_xs[0]]
    for x in bullet_xs[1:]:
        if x - bands[-1] > COLUMN_GAP:
            bands.append(x)
    if len(bands) < 2:
        return [lines]

    # Midpoints, so a heading or a wrapped line sitting slightly left of
    # its own bullets still files under them.
    edges = [(bands[i] + bands[i + 1]) / 2 for i in range(len(bands) - 1)]

    def band_of(line):
        for i, edge in enumerate(edges):
            if line["x"] < edge:
                return i
        return len(edges)

    groups = [[] for _ in bands]
    for line in lines:
        groups[band_of(line)].append(line)
    return [g for g in groups if g]


def parse_curriculum(region):
    """-> ({year: [item]}, notes). Handles bulleted, unbulleted and mixed."""
    # Split into year blocks by VERTICAL POSITION, not by order.
    #
    # The headings sit in the left-hand list, so when a year is set in two
    # lists side by side the right-hand one carries no heading of its own
    # and arrives after every left-hand line. Switching year on each
    # heading as the lines go past therefore files the whole second list
    # under the LAST year on the page: page 62's "Electronics I, Electric
    # Circuits, Mathematics II, Physics II (Electrical), Vacation Work I"
    # are second-year courses that landed at the end of fourth year.
    #
    # A line belongs to the last heading ABOVE it, whichever list it is in.
    heads = sorted(((l["top"], year_of(l["text"])) for l in region
                    if year_of(l["text"])), key=lambda h: h[0])
    blocks = []
    if heads:
        buckets = {y: [] for _, y in heads}
        order = [y for _, y in heads]
        for l in region:
            if year_of(l["text"]):
                continue
            above = [y for top, y in heads if top <= l["top"] + Y_TOL]
            if above:
                buckets[above[-1]].append(l)
        for y in order:
            blocks.append((y, sorted(buckets[y], key=lambda l: (l["col"], l["top"]))))

    curriculum, notes = {}, []
    for year, block_lines in blocks:
        curriculum.setdefault(year, [])
        # Each side-by-side list in this year is parsed on its own, then
        # appended left to right, so the two never interleave.
        for lines in split_columns(block_lines):
            bulleted = any(l["bullet"] for l in lines)
            items, cur, pending_join = [], None, False
            prev_top = None
            after_connector = False

            def flush():
                nonlocal cur
                if cur:
                    name = re.sub(r"\s+", " ", cur).strip(" ,;:")
                    if len(name) > 2:
                        items.append(name)
                cur = None

            for l in lines:
                t = l["text"].strip()
                if not t:
                    continue
                starts_item, after_connector = after_connector, False
                if prev_top is None:
                    prev_top = l["top"]
                this_top = l["top"]
                if CONNECTOR.match(t):
                    # a bare AND/OR separates items; OR makes the pair a choice
                    if cur and t.upper().startswith("OR"):
                        cur += " \x00OR\x00"
                    flush()
                    after_connector = True
                    continue
                if PROSE.search(t) and not l["bullet"]:
                    flush(); notes.append(t); continue
                if HEADER.search(t) and not l["bullet"]:
                    flush(); notes.append(t); continue
                inline = INLINE_CONNECTOR.match(t)
                if inline and not l["bullet"]:
                    if cur and t.upper().startswith("OR"):
                        cur += " \x00OR\x00"
                    flush()
                    cur = inline.group("rest").strip()
                    continue

                if bulleted:
                    if l["bullet"]:
                        flush(); cur = t
                    elif cur is not None and l["top"] - prev_top > CONTINUATION_GAP:
                        # Too far below to be a continuation: a prose block
                        # printed under the course list, not part of it.
                        flush(); notes.append(t)
                    elif cur is not None:
                        cur += " " + t          # wrapped name
                    elif starts_item and not t.endswith(":"):
                        cur = t
                    else:
                        notes.append(t)
                else:
                    # Unbulleted: items are separated by bare AND / OR lines, so
                    # consecutive text lines with no connector between them are
                    # ONE wrapped item ("Molecular and Cell Biology IIC:" +
                    # "Applications (for double-MCB major students)").
                    cur = t if cur is None else cur + " " + t
                prev_top = l["top"]
            flush()
            curriculum[year] += items
    return curriculum, notes


def link_choices(items):
    """'X OR' + 'Y', and inline 'A OR B', become one requirement."""
    out, pending = [], []
    for raw in items:
        raw = raw.replace("\x00OR\x00", " OR ")
        trailing = bool(re.search(r"\sOR$", raw.strip()))
        body = re.sub(r"\s+OR$", "", raw.strip())
        parts = [p.strip(" ,;:") for p in re.split(r"\s+OR\s+", body) if p.strip(" ,;:")]
        pending.extend(parts)
        if trailing:
            continue
        if pending:
            out.append({"options": pending, "choice": True} if len(pending) > 1
                       else {"name": pending[0], "choice": False})
        pending = []
    if pending:
        out.append({"options": pending, "choice": True} if len(pending) > 1
                   else {"name": pending[0], "choice": False})
    for o in out:
        if o["choice"]:
            o["options"] = [re.sub(r"\s+(AND|OR)$", "", x).strip(" ,;:")
                            for x in o["options"]]
        else:
            o["name"] = re.sub(r"\s+(AND|OR)$", "", o["name"]).strip(" ,;:")
    cleaned = []
    for o in out:
        if o["choice"]:
            opts = [x for x in o["options"] if len(x) > 2 and not PROSE.search(x)]
            if not opts:
                continue
            cleaned.append({"options": opts, "choice": True} if len(opts) > 1
                           else {"name": opts[0], "choice": False})
        elif len(o["name"]) > 2 and not PROSE.search(o["name"]):
            cleaned.append(o)
    return cleaned


# ----------------------------------------------------------------- header --
def parse_header(lines):
    left = [l["text"] for l in lines if l["col"] == 0 and l["text"]]
    code = code_line = None
    for l in left:
        for tok in l.split():
            if CODE_RE.match(tok):
                code, code_line = tok, l
                break
        if code:
            break
    name = None
    if code:
        i = left.index(code_line)
        parts = []
        for l in reversed(left[:i]):
            parts.insert(0, l.strip())
            if DEGREE_RE.match(l.strip()) or len(parts) > 3:
                break
        name = " ".join(parts)
    blob = " ".join(left)
    dm = re.search(r"DURATION:?\s*(\d+)\s*YEAR", blob, re.I)
    am = re.search(r"APS\s*(\d{2})\s*\+", blob)
    xref = re.search(r"refer to Pages? ([\d\-– ,and]+)", blob, re.I)
    return {"code": code,
            "name": re.sub(r"\s+", " ", name).strip() if name else None,
            "duration_years": int(dm.group(1)) if dm else None,
            "aps": int(am.group(1)) if am else None,
            "curriculum_elsewhere": xref.group(1).strip() if xref else None}


# ------------------------------------------------------------------- main --
def extract():
    programmes, skipped = [], []
    with pdfplumber.open(PDF) as pdf:
        for pno in range(FIRST, LAST + 1):
            page = pdf.pages[pno - 1]
            lines = page_lines(page)
            hdr = parse_header(lines)
            if not hdr["code"] or hdr["duration_years"] is None:
                skipped.append(pno)
                continue
            cur, notes = parse_curriculum(curriculum_region(lines))
            programmes.append({
                "page": pno, **hdr,
                "curriculum": {y: link_choices(v) for y, v in cur.items()},
                "curriculum_notes": notes,
            })
    return programmes, skipped


if __name__ == "__main__":
    progs, skipped = extract()
    n = sum(len(v) for p in progs for v in p["curriculum"].values())
    json.dump({"source": "Wits Guide for Undergraduate Applicants 2027, pages 40-131",
               "programme_pages": len(progs), "course_requirements": n,
               "programmes": progs},
              open("courses.json", "w"), indent=2, ensure_ascii=False)
    print(f"programme pages     : {len(progs)}")
    print(f"course requirements : {n}")
    print(f"pages skipped       : {len(skipped)}")
