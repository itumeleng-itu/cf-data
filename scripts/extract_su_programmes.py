#!/usr/bin/env python3
"""Extract programmes from the Stellenbosch 2027 admissions booklet.

WHY THIS ONE IS DIFFERENT

UJ, TUT and Wits publish tables. Stellenbosch publishes a two-column
prose booklet: a programme is a heading ending in "(3 years)", followed
by a short bulleted list of requirements, then optional "Fields of
study", "Focal areas", "Similar programmes" and "Career opportunities"
blocks that are prose, not requirements.

So there is no table geometry to read -- no header row, no cell
rectangles. What there is instead is a gutter and an indent, and both
turn out to be reliable:

  * Words cluster at x 20-280 and 300-560 with nothing between, and
    `pdftotext -layout` interleaves the two columns, so the first job
    is to split them and read each one down the page.

  * A bullet's text begins 2.8pt to the right of the paragraph margin
    (left column: marker 28.3, text 39.7, prose 36.9; right column:
    14.7 / 26.1 / 23.2). So a wrapped bullet can be told from the
    paragraph that follows it by x0 alone, which is what CONT_MIN_INDENT
    below is for. The previous version guessed from capitalisation and
    the presence of "%", and glued whole career-prospects paragraphs
    onto the end of requirements.

WHAT SU ASKS FOR, AND HOW IT MAPS

Stellenbosch does not use an APS. It asks for "an NSC aggregate of at
least 60% (excluding Life Orientation)" -- an average percentage, which
is the existing percentage_sum_div_10 scorer with divisor 6, and
min_score holds 55, 63 or 65 as plain integers.

Subject bars are percentages too, and every one in this booklet except
a single "Mathematics 75%" on page 7 (BCom Mathematical Sciences) falls
exactly on an NSC band boundary (40, 50, 60, 70, 80), so converting
them to levels is lossless. That exception is handled in the converter,
not here.

WHAT THIS FILE DELIBERATELY DOES NOT DO

It does not drop anything it cannot classify. Every heading the
booklet prints becomes a row, tagged with a `kind`; the converter
decides what becomes an offering. A page that silently loses a
programme is the failure mode this pipeline exists to prevent, so the
reconciliation test counts rows per page against this extraction and
the verifier counts headings with a different engine entirely.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = ROOT / "sources" / "su_admissions_booklet_2027.pdf"

# Programme content runs from page 2 to page 15; page 1 is the cover and
# page 16 the back matter.
FIRST_PAGE, LAST_PAGE = 2, 15

# The gutter. Measured, not guessed: word x0 values cluster at 20-280
# and 300-560 across every content page, with nothing in between.
COLUMN_SPLIT = 290.0

# Vertical tolerance for "same visual line".
#
# This replaces `round(top / 3)` bucketing, which split 8 lines across
# the booklet -- and every one of the 8 was a requirement bullet
# carrying a percentage, because the percentage is set in a slightly
# different font and lands 0.032pt lower than the words around it:
#
#     p5  tops [574.474, 574.506]  "- An NSC aggregate of at least 60% ..."
#     p5  tops [583.474, 583.506]  "- Home Language 50%"
#     p7  tops [697.474, 697.506]  "- Mathematics 70%"
#
# A fixed bucket boundary falling between 574.474 and 574.506 tore the
# percentage off its requirement. Clustering by distance cannot.
LINE_TOP_TOL = 2.0

# How far right of a bullet's own marker a line must start to count as
# that bullet's continuation. Wraps land at either +11.4 (the text
# margin) or +18.0 (the hanging indent used by the p12 and p15 lists),
# while a paragraph that ends the list returns to the marker column.
CONT_MIN_INDENT = 5.0

# A duration suffix is what marks a heading: "(3 years)", "(4 years)",
# "(1 year)", "(3½ years)".
#
# A heading may carry further parentheticals after the duration --
# "Postgraduate Certificate in Education (PGCE) (1 year) (full time on
# campus)" on p9. Anchoring strictly to end-of-line lost that entry
# entirely: it was never a heading, so it never appeared in the output
# and never appeared in the count that was supposed to notice.
# Durations are not always digits. The Faculty of Law prints "LLB
# (four-year)" and "LLB (three-year)", and Theology prints "Extended
# Curriculum Programme (+1 year)". A digits-only pattern silently lost
# all three -- and the four-year LLB is a full undergraduate
# qualification with its own NSC requirements, so its bullets were
# read with no programme open and discarded without trace. That is the
# exact failure this pipeline exists to catch, and it was invisible
# because the thing counting headings used this same regex.
WORD_YEARS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}

DURATION = re.compile(
    r"\(\s*\+?\s*(?:(?P<digits>\d)\s*(?P<half>½|\.5)?|(?P<word>"
    + "|".join(WORD_YEARS)
    + r"))[-\s]*years?\s*\)(?:\s*\([^)]*\))*\s*$",
    re.I,
)

# Headings whose name wraps onto the heading line's predecessor. The
# duration line then carries only a parenthetical or nothing at all:
#
#     "BAgric in Agricultural Production and Management:" / "Elsenburg (3 years)"
#     "BSc in Forestry (Forestry and Wood Sciences)"      / "(BScFor) (4 years)"
#     "BA in Political, Philosophical and Economic Studies" / "(PPE) (3 years)"
#     "BEng (Electrical and Electronic)"                  / "(Data Engineering) (4 years)"
#     "Bachelor of Speech-Language and Hearing Therapy"   / "(4 years)"
#     "BSc Extended Curriculum Programmes"                / "(ECPs) (4 years)"
#
# A qualification name always begins with a letter, so a remainder that
# is empty or opens a bracket is a continuation, not a name.
WRAPPED_REMAINDER = re.compile(r"^\s*(\(.*)?$")

# A line that begins a qualification name. Used only to decide whether
# the PREVIOUS line is really a heading's first half, so it needs to be
# permissive rather than exact.
NAME_START = re.compile(
    r"^(B[A-Za-z]|LLB|M[A-Z]|Bachelor\b|Diploma\b|Advanced Diploma\b"
    r"|Higher Certificate\b|Postgraduate Certificate\b)"
)

# The faculty banner, set in caps on a line of its own.
#
# Case-sensitive on purpose. With re.I this also matched the body line
# "Faculty of Education yearbook on the website www.su.ac.za." at the
# foot of p9, which reset the faculty-wide requirement block to empty
# before the programmes above it had inherited from it -- so BEd
# (Foundation Phase Education), whose entry prints no requirements of
# its own, came out with none at all.
FACULTY_HEAD = re.compile(r"^FACULTY OF(\s|$)")

# The faculty-wide requirement block. On the Education (p9) and
# Engineering (p10) pages the requirements are printed ONCE under this
# heading and apply to every programme on the page; the programme
# entries beneath carry only prose.
#
# The previous version listed "Admission" and "Selection" in
# PROSE_BLOCK as terminators, so this heading ENDED requirement capture
# at exactly the point it should have started it. That is why six BEng
# programmes and BEd (Foundation Phase) came out with none.
ADMISSION_HEAD = re.compile(r"^\s*Admission and selection\s*$", re.I)

# Blocks that follow a programme's requirements and are prose about the
# programme, not conditions on entry. Reaching one ends the list.
#
# "Admission" and "Selection" are absent on purpose -- see above. The
# one in-programme use, "Selection requirements are available at
# www.maties.com..." (p5 Drama), is excluded by the indent test
# instead: it sits at the paragraph margin, not the bullet indent.
PROSE_BLOCK = re.compile(
    r"^\s*(Fields? of study|Focal areas?|Similar programmes?"
    r"|Career opportunities|Postgraduate fields of study"
    r"|Note|Please note)\b",
    re.I,
)

BULLET_MARKERS = {"-", "•", "·", "–", "—"}

# "See BA (Law) under the Faculty of Law, page 11."
# "For admission requirements, see under the Faculty of Law on page 11."
CROSS_REF = re.compile(r"\bsee\b.{0,60}?\bpage\s+\d+", re.I | re.S)

# Group headings, not programmes. Each introduces the extended-curriculum
# variants of the programmes around it rather than naming one offering.
ECP_GROUP = re.compile(r"extended curriculum programmes?\b", re.I)

# Entry needs a prior qualification, so these are not school-leaver
# offerings whatever their duration says.
POSTGRADUATE = re.compile(r"^(Postgraduate Certificate|Advanced Diploma)\b", re.I)

# Some say so in the body rather than the name. "LLB (three-year)" is
# printed in the same style as the four-year LLB beside it and carries
# a three-year duration, but its entry reads "This degree is only
# available as a second bachelor's degree ... Selection is based on
# the prior bachelor's degree". Offering it to a matriculant would be
# wrong in the one direction that matters: telling someone they
# qualify when they cannot apply at all.
PRIOR_QUALIFICATION = re.compile(
    r"second bachelor|prior bachelor|prior degree|another qualification"
    r"|Entry requirement:\s*a degree|must have a Diploma",
    re.I,
)


@dataclass
class Line:
    top: float
    x0: float
    text: str


# Words that stay lowercase inside a title.
_SMALL = {"and", "of", "the", "in", "for", "on", "to"}


def title_case(text: str) -> str:
    """Title-case a caps banner without mangling the small words."""
    words = text.lower().split()
    return " ".join(
        w.capitalize() if i == 0 or w not in _SMALL else w
        for i, w in enumerate(words)
    )


@dataclass
class Requirement:
    """One bullet, with where it came from and what introduced it.

    `source` separates the faculty-wide block from the programme's own
    list, because a programme can carry both: BEd (Intermediate Phase
    Education) prints no admission bars of its own at all -- the
    Education block on p9 IS its admission requirement -- and its own
    bullets are the teaching modules you may choose once admitted.

    `intro` is the colon-terminated line in force when the bullet was
    read, which is the booklet's own label for the list. It is what
    tells "If you take Mathematics as a university subject, then
    also:" / "- Mathematics 70%" (a conditional entry bar, BMus p5)
    apart from "...you may choose two additional teaching subjects
    from the following teaching modules...:" / "- Life Skills" (not an
    entry bar at all). Both are colon-introduced bullet lists sitting
    in the same position; nothing in their shape distinguishes them,
    so the label has to be carried through to the converter rather
    than guessed at here.
    """

    text: str
    source: str = "own"
    intro: str | None = None


@dataclass
class Programme:
    page: int
    faculty: str
    section: str
    name: str
    duration_years: float
    kind: str = "programme"
    bulleted: bool = False
    requirements: list[Requirement] = field(default_factory=list)
    inherited_requirements: bool = False
    notes: list[str] = field(default_factory=list)
    extended: bool = False


def column_lines(page, lo: float, hi: float) -> list[Line]:
    """Lines of one column, in reading order, with their geometry.

    Lines are rebuilt from words rather than taken from `extract_text`,
    because the two columns interleave otherwise: poppler's layout mode
    puts the Open Day blurb and the Agrisciences requirements on the
    same output line.
    """
    words = [w for w in page.extract_words() if lo <= w["x0"] < hi]
    words.sort(key=lambda w: w["top"])

    groups: list[list[dict]] = []
    current: list[dict] = []
    for w in words:
        if current and w["top"] - current[0]["top"] > LINE_TOP_TOL:
            groups.append(current)
            current = []
        current.append(w)
    if current:
        groups.append(current)

    out: list[Line] = []
    for g in groups:
        g = sorted(g, key=lambda w: w["x0"])
        out.append(
            Line(top=g[0]["top"], x0=g[0]["x0"], text=" ".join(w["text"] for w in g))
        )
    return out


def page_lines(page) -> list[Line]:
    """Both columns, left one first, as a single reading order."""
    return column_lines(page, 0, COLUMN_SPLIT) + column_lines(
        page, COLUMN_SPLIT, page.width
    )


def split_bullet(line: Line) -> tuple[str, float] | None:
    """(text, x0 of the MARKER) if the line is a bullet, else None.

    The marker's own x0 is what identifies continuations, via a
    minimum indent rather than an exact match. An earlier version
    returned the x0 of the bullet's text, computed by adding a
    per-glyph width, and required a continuation to land on it
    exactly. Two indent styles defeat that: most bullets wrap to the
    text margin (marker 28.3, text and wraps at 39.7), but the
    Science ECP block on p15 and the numbered categories on p12 hang
    their wraps at 46.3 -- 7.6pt further right than their own text.
    Exact matching dropped those continuations, truncating the
    requirement mid-sentence.

    A minimum indent covers both. It is safe only because the named
    block openers are tested first: "Field of study" sits at 39.7 and
    would otherwise read as a continuation of the bullet above it.
    """
    parts = line.text.split(maxsplit=1)
    if not parts or parts[0] not in BULLET_MARKERS:
        return None
    return (parts[1] if len(parts) > 1 else ""), line.x0


def is_heading(line: Line, previous: Line | None) -> tuple[str, float, bool] | None:
    """(name, years, bulleted) if this line ends a heading, else None.

    `bulleted` is kept because a heading printed as a list item is a
    pointer to the real entry elsewhere in the booklet, not an entry:
    p6 prints "- BCom (Law) (3 years)" and "- BAccLLB (5 years)" under
    "For admission requirements, see under the Faculty of Law on page
    11", and both are set out in full on p11.
    """
    m = DURATION.search(line.text)
    if not m:
        return None

    if m.group("word"):
        years = float(WORD_YEARS[m.group("word").lower()])
    else:
        years = float(m.group("digits")) + (0.5 if m.group("half") else 0.0)
    remainder = line.text[: m.start()].strip()

    # A word-form duration is part of the printed name, not a suffix
    # to strip: "LLB (four-year)" and "LLB (three-year)" are two
    # different qualifications and both reduce to "LLB" without it.
    if m.group("word"):
        return " ".join(line.text.split()), years, False

    bulleted = False
    stripped = remainder.split(maxsplit=1)
    if stripped and stripped[0] in BULLET_MARKERS:
        bulleted = True
        remainder = stripped[1] if len(stripped) > 1 else ""

    # A heading wraps when the duration line carries no name of its
    # own -- "(BScFor) (4 years)" -- or when the line above it ends in
    # a colon, which is how p2 sets "BAgric in Agricultural Production
    # and Management:" / "Elsenburg (3 years)". The colon case has a
    # perfectly ordinary word as its remainder, so testing only for an
    # empty-or-bracketed remainder named that programme "Elsenburg".
    colon_wrap = previous is not None and previous.text.rstrip().endswith(":")
    if WRAPPED_REMAINDER.match(remainder) or colon_wrap:
        if previous is None or not NAME_START.match(previous.text):
            return None
        head = previous.text.rstrip(":").strip()
        if not remainder:
            name = head
        else:
            name = f"{head}: {remainder}" if colon_wrap else f"{head} {remainder}"
    else:
        name = remainder

    return " ".join(name.split()), years, bulleted


def classify(prog: "Programme") -> str:
    if ECP_GROUP.search(prog.name):
        return "ecp_group"
    if POSTGRADUATE.match(prog.name):
        return "postgraduate"
    body = " ".join(prog.notes) + " " + " ".join(r.text for r in prog.requirements)
    if PRIOR_QUALIFICATION.search(body):
        return "postgraduate"
    if prog.bulleted:
        return "cross_reference"
    if prog.notes and CROSS_REF.search(" ".join(prog.notes)):
        return "cross_reference"
    return "programme"


def extract(pdf_path: Path) -> list[Programme]:
    """One pass over the booklet in reading order.

    Single pass rather than "find the faculty block, then find the
    programmes", because the faculty block is not reliably at the top
    of its page. Page 9 carries the last two Commerce programmes, then
    the Education banner, then Education's shared requirements, then
    the two BEd programmes. A per-page pass that stops at the first
    heading never reaches that block, and BEd (Foundation Phase) --
    whose entry prints no requirements of its own at all -- comes out
    empty. Reading position is what scopes it: a block applies to the
    headings that follow it, until the next faculty banner.
    """
    programmes: list[Programme] = []
    faculty = ""
    section = ""

    # The faculty-wide requirement list currently in force.
    faculty_reqs: list[str] = []
    in_faculty_block = False

    current: Programme | None = None
    in_requirements = False
    bullet_x0: float | None = None
    intro: str | None = None
    paragraph: list[str] = []
    after_bullet = False

    with pdfplumber.open(pdf_path) as pdf:
        for n in range(FIRST_PAGE, LAST_PAGE + 1):
            lines = page_lines(pdf.pages[n - 1])

            for i, line in enumerate(lines):
                prev = lines[i - 1] if i else None
                text = line.text.strip()
                if not text:
                    continue

                # ── Faculty banner: resets everything scoped to it ────
                if FACULTY_HEAD.match(text):
                    # The banner is set in caps over two lines, and the
                    # break falls wherever it fits: "FACULTY OF" /
                    # "AGRISCIENCES", but also "FACULTY OF ARTS AND" /
                    # "SOCIAL SCIENCES" and "FACULTY OF MEDICINE" /
                    # "AND HEALTH SCIENCES". Reading only the line
                    # after the banner gave faculties called "Arts And"
                    # and "Economic And".
                    parts = [text[len("FACULTY OF"):].strip()]
                    for nxt in lines[i + 1: i + 3]:
                        t2 = nxt.text.strip()
                        if not t2 or not t2.isupper():
                            break
                        parts.append(t2)
                    faculty = " ".join(p for p in parts if p)
                    section = ""
                    faculty_reqs = []
                    in_faculty_block = False
                    current = None
                    in_requirements = False
                    continue

                # ── Heading ───────────────────────────────────────────
                head = is_heading(line, prev)
                if head:
                    name, years, bulleted = head
                    in_faculty_block = False
                    current = Programme(
                        page=n,
                        faculty=title_case(faculty),
                        section=section,
                        name=name,
                        duration_years=years,
                        bulleted=bulleted,
                    )
                    programmes.append(current)
                    in_requirements = True
                    bullet_x0 = None
                    intro = None
                    paragraph = []
                    after_bullet = False
                    continue

                # ── Faculty-wide requirement block ───────────────────
                if ADMISSION_HEAD.match(text):
                    in_faculty_block = True
                    faculty_reqs = []
                    bullet_x0 = None
                    continue

                if in_faculty_block:
                    b = split_bullet(line)
                    if b is not None:
                        faculty_reqs.append(b[0])
                        bullet_x0 = b[1]
                    elif (
                        faculty_reqs
                        and bullet_x0 is not None
                        and line.x0 - bullet_x0 > CONT_MIN_INDENT
                    ):
                        faculty_reqs[-1] += " " + text
                    elif re.fullmatch(r"(AND|OR)", text, re.I) or text.endswith(":"):
                        # Structural connectors in the Education block:
                        # "AND", "OR", "Learners who were taught in
                        # English:". Dropping these would flatten three
                        # mutually exclusive language routes into one
                        # list that no applicant could satisfy.
                        faculty_reqs.append(text)
                        bullet_x0 = None
                    else:
                        in_faculty_block = False
                        bullet_x0 = None
                    continue

                # ── Section banner ───────────────────────────────────
                # An all-caps line that is not a heading groups the
                # programmes beneath it ("UNDERGRADUATE DIPLOMA
                # PROGRAMME", "INTERDISCIPLINARY PROGRAMMES",
                # "DEGREE PROGRAMMES FOR PROFESSIONAL REGISTRATION").
                if text.isupper() and len(text) > 8 and not DURATION.search(text):
                    section = text.title()
                    continue

                if current is None:
                    continue

                # ── Requirements ─────────────────────────────────────
                b = split_bullet(line)
                if b is not None:
                    if in_requirements:
                        current.requirements.append(
                            Requirement(text=b[0], source="own", intro=intro)
                        )
                        bullet_x0 = b[1]
                    after_bullet = True
                    continue

                # A named block opener ends the requirement list, and is
                # tested BEFORE the continuation rule because it is not
                # set at the paragraph margin.
                #
                # "Field of study" sits at x0 39.7 -- the bullet-text
                # margin, 2.8pt right of the 36.9 paragraph margin --
                # so the indent test called it a wrapped bullet, glued
                # it onto "- Physical Sciences (Physics and Chemistry)
                # 50%", and left the list open so that every field of
                # study beneath it was captured as an admission
                # requirement. 21 of the 67 programmes were carrying
                # "Animal Science", "Behavioural Economics" or
                # "Operations Research" as entry conditions.
                if PROSE_BLOCK.match(text):
                    in_requirements = False
                    bullet_x0 = None
                    continue

                if (
                    in_requirements
                    and current.requirements
                    and bullet_x0 is not None
                    and line.x0 - bullet_x0 > CONT_MIN_INDENT
                ):
                    # A wrapped bullet. Decided by indent, not by
                    # capitalisation: "60%" and "Language) 50%" are
                    # continuations, and "Career opportunities: ..." at
                    # the paragraph margin is not.
                    #
                    # Unless it ends in a colon, in which case it is
                    # not a continuation at all but the label for the
                    # bullets below. BMus and BA in Music (p5) print
                    # "If you take Mathematics as a university
                    # subject, then also:" at the bullet margin,
                    # between the audition requirement and
                    # "- Mathematics 70%". Glued onto the audition
                    # bullet, the condition vanishes and the 70%
                    # Mathematics bar reads as mandatory -- which
                    # would refuse every music applicant who does not
                    # take Mathematics at all.
                    if text.endswith(":"):
                        # The condition usually wraps, so its opening
                        # has already been glued onto the requirement
                        # above it -- "First Additional Language 40%
                        # If you take Organisational Informatics as a
                        # university subject," on p4. Take it back:
                        # left there it corrupts a real language bar
                        # and leaves the label as a bare "then also:".
                        tail = ""
                        if current.requirements:
                            prior = current.requirements[-1]
                            m = re.search(r"(?:^|(?<=\s))(?:If|When|Should)\s.*$", prior.text)
                            if m and "%" not in prior.text[m.start():]:
                                tail = prior.text[m.start():].strip()
                                prior.text = prior.text[: m.start()].strip()
                        intro = f"{tail} {text}".strip()
                        bullet_x0 = None
                        after_bullet = False
                        paragraph = [intro]
                        continue
                    current.requirements[-1].text += " " + text
                    after_bullet = True
                    continue

                bullet_x0 = None

                # Prose between the heading and the bullets is a note on
                # the programme, not a requirement: "This is an
                # interfaculty programme.", "125 places in the
                # programme.", the BCom (International Business)
                # selection paragraph.
                if in_requirements:
                    if after_bullet:
                        paragraph = []
                        after_bullet = False
                    paragraph.append(text)
                    current.notes.append(text)
                    # A colon-terminated paragraph labels the bullets
                    # that follow it; anything else clears the label.
                    # The whole paragraph is kept, not just its last
                    # line: the label that matters is "...you may
                    # choose two additional teaching subjects from the
                    # following teaching modules...", and its final
                    # wrapped line alone is just "teaching modules):".
                    intro = " ".join(paragraph) if text.endswith(":") else None

            # A faculty's shared block reaches the programmes printed
            # after it, including any on later pages of that faculty.
            #
            # Additive, not a fallback. A programme having its own
            # bullets does not mean the faculty block stops applying to
            # it -- BEd (Intermediate Phase Education) must meet the
            # Education requirements AND choose two teaching modules,
            # and treating the block as "use only when the programme
            # printed nothing" dropped the admission requirements for
            # the one programme on that page that printed both.
            for p in programmes:
                if not faculty_reqs or p.page != n or p.faculty != title_case(faculty):
                    continue
                if any(r.source == "faculty" for r in p.requirements):
                    continue
                p.requirements = [
                    Requirement(text=t, source="faculty") for t in faculty_reqs
                ] + p.requirements
                p.inherited_requirements = True

    for p in programmes:
        _mend_split_bullets(p)
        p.kind = classify(p)
        p.extended = bool(ECP_GROUP.search(p.name))

    return programmes


# A requirement that ends on a bare conjunction has been cut in half.
DANGLING = re.compile(r"\b(?:or|and|OR|AND)\s*$")


def _mend_split_bullets(prog: Programme) -> None:
    """Rejoin a requirement the booklet itself broke across two bullets.

    p11 sets BCom (Law)'s language rule as two list items:

        -  English or Afrikaans Home Language 60% OR Afrikaans or
        -  English First Additional Language 70%

    Both carry a real hyphen at x0 304.72, so this is the booklet's
    own typesetting slip, not a misread -- BA (Law) and BAccLLB print
    the identical rule unbroken on the same page. Left as it is, the
    engine would demand BOTH halves of an OR and refuse every
    applicant who satisfies the rule as written.

    Only a trailing conjunction triggers this, and the structural
    "AND"/"OR" connectors of the Education block are whole items
    rather than sentence tails, so they are left alone.
    """
    merged: list[Requirement] = []
    for req in prog.requirements:
        if (
            merged
            and merged[-1].source == req.source
            and merged[-1].text.strip() not in {"AND", "OR"}
            and DANGLING.search(merged[-1].text)
        ):
            merged[-1].text = f"{merged[-1].text.rstrip()} {req.text}"
            continue
        merged.append(req)
    prog.requirements = merged


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    progs = extract(args.pdf)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps([asdict(p) for p in progs], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    per_page: dict[int, int] = {}
    kinds: dict[str, int] = {}
    for p in progs:
        per_page[p.page] = per_page.get(p.page, 0) + 1
        kinds[p.kind] = kinds.get(p.kind, 0) + 1

    print(f"{len(progs)} headings -> {args.out}")
    print("  pages:", ", ".join(f"p{k}={v}" for k, v in sorted(per_page.items())))
    print("  kinds:", ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    inherited = [p for p in progs if p.inherited_requirements]
    print(f"  inherited faculty requirements: {len(inherited)}")
    noreq = [p for p in progs if not p.requirements and p.kind == "programme"]
    print(f"  programmes with no requirements: {len(noreq)}")
    for p in noreq:
        print(f"     p{p.page} {p.name[:68]!r}")


if __name__ == "__main__":
    main()
