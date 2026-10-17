#!/usr/bin/env python3
"""Turn the extracted Stellenbosch rows into seed records.

WHAT MAKES SU DIFFERENT FROM THE OTHER THREE

Stellenbosch does not use an APS. Every bar in the booklet is a
percentage: "An NSC aggregate of at least 65% (excluding Life
Orientation)", "Mathematics 70%". The aggregate maps onto the existing
percentage_sum_div_10 scorer with divisor 6, and min_score holds the
printed percentage unchanged.

Subject bars become NSC levels. That is lossless for 128 of the 129
bars in the booklet, because they sit exactly on band boundaries --
40, 50, 60, 70 and 80 are the floors of levels 3, 4, 5, 6 and 7. The
single exception is handled at OFF_BAND_BARS below.

HOW THIS FILE TREATS WHAT IT CANNOT PARSE

It never guesses a bar. A requirement it does not recognise becomes a
selection_note and marks the record `needs_review`, so the failure
mode is a programme that under-promises and carries the printed text,
never one that silently invents an entry condition. Dropping a
requirement on the floor is the one outcome that is not allowed, and
the counts printed at the end exist to make it visible if it happens.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INSTITUTION = "su"
ACADEMIC_YEAR = 2027
SOURCE_DOC = "su_admissions_booklet_2027"

# NSC bands, as (floor, level). A printed percentage converts
# losslessly only when it equals a floor exactly.
NSC_BANDS = [(90, 8), (80, 7), (70, 6), (60, 5), (50, 4), (40, 3), (30, 2), (0, 1)]
BAND_FLOOR = {floor: level for floor, level in NSC_BANDS}

LANGUAGES = [
    "english", "afrikaans", "isizulu", "isixhosa", "sepedi", "sesotho",
    "setswana", "xitsonga", "siswati", "tshivenda", "isindebele",
]

SUBJECT_WORDS: list[tuple[str, str]] = [
    # Longest first: "Mathematical Literacy" must win over "Mathematics",
    # and "Technical Mathematics" over both.
    (r"technical mathematics", "technical_mathematics"),
    (r"mathematical literacy", "mathematical_literacy"),
    (r"mathematics", "mathematics"),
    (r"physical sciences(?:\s*\(physics and chemistry\))?", "physical_sciences"),
    (r"life sciences", "life_sciences"),
    (r"agricultural sciences", "agricultural_sciences"),
    (r"business studies", "business_studies"),
    (r"accounting", "accounting"),
    (r"economics", "economics"),
    (r"geography", "geography"),
    (r"history", "history"),
    (r"information technology", "information_technology"),
    (r"visual arts", "visual_arts"),
    (r"dramatic arts", "dramatic_arts"),
    (r"music", "music"),
]

# OFF-BAND BARS
#
# Most printed bars sit on a band floor and convert exactly. Some do
# not, and the booklet has more than one:
#
#   BCom (Mathematical Sciences), p7   Mathematics 75%
#   Bachelor of Data Science, p3/6/8/15
#       Afrikaans First Additional Language 75% OR English First
#       Additional Language 75%
#   BCom (Actuarial Science), p8       English FAL 75% (conditional,
#                                      already a note)
#
# Each maps to the band it falls INSIDE -- 75% is within level 6
# (70-79%) -- and the record carries the printed bar in
# selection_notes and is flagged.
#
# Mapping down rather than up is a deliberate choice about which error
# to prefer. Level 7 can never over-admit, but it hides the programme
# from every applicant between 75% and 79%, who are exactly the people
# the bar is written for, and a learner who never sees a programme
# cannot apply to it. Level 6 shows it to a slightly wider group, each
# of whom is shown the real requirement on the record.
#
# This is applied as a rule rather than a list of known cases so that
# a bar SU introduces in a later edition is handled the same way
# instead of silently falling through as unparseable.
OFF_BAND_NOTE = (
    "The booklet requires {subject} {pct}%. This tool matches on NSC "
    "levels, and {pct}% falls inside level {level} ({floor}-{ceiling}%), "
    "so a level {level} mark is matched here - check your actual "
    "percentage against the {pct}% Stellenbosch requires."
)

def _s(subject: str, level: int) -> dict:
    return {"kind": "subject", "subject": subject, "min_level": level}


# TWO REQUIREMENTS BUILT BY HAND
#
# Both nest an AND inside an OR, and both are printed once and shared.
# A general parser for them would be a parser fitted to two sentences:
# it would be more code than the rules themselves, exercised by
# nothing else in the booklet, and the first thing to break on the
# 2028 edition. The UJ p76 pairing was handled the same way.
#
# Writing them out is also the only way to get them RIGHT. Fed to the
# ordinary alternatives parser, the Engineering rule flattens into a
# plain list of language bars, and "Afrikaans Home Language 50%" on
# its own then satisfies it -- which the booklet does not allow, and
# which no count of unparsed lines would have revealed, because it
# parsed.
HAND_BUILT: dict[str, tuple[dict, list[str]]] = {
    # Engineering, p10. Shared by all seven BEng programmes.
    "English Home Language 50%, with no Afrikaans requirement, OR English "
    "First Additional Language 60%, with no Afrikaans requirement, OR English "
    "First Additional Language 50% with Afrikaans Home Language 50% OR English "
    "First Additional Language 50% with Afrikaans Second Additional Language 60%": (
        {
            "kind": "any",
            "rules": [
                _s("english_hl", 4),
                _s("english_fal", 5),
                {"kind": "all", "rules": [_s("english_fal", 4), _s("afrikaans_hl", 4)]},
            ],
        },
        [
            "The Faculty also admits English First Additional Language 50% "
            "together with Afrikaans Second Additional Language 60%. The NSC "
            "subject list this tool matches on has no Second Additional "
            "Language, so that combination is not matched here - if it "
            "describes you, apply anyway.",
        ],
    ),
    # Bachelor of Speech-Language and Hearing Therapy, p12.
    #
    # "At least TWO of the following THREE" has no rule kind, but with
    # three candidates it is just the three pairs written out. The
    # third language is "a third South African language", i.e. any
    # language that is not English or Afrikaans, so that pair becomes
    # an `any` over the nine remaining families.
    #
    # It was previously routed to a note as inexpressible, which left
    # a therapy degree whose whole point is language with no language
    # requirement at all.
    "At least TWO of the following THREE languages (Home Language or First "
    "Additional Language) 60%: English AND/ OR Afrikaans AND/OR a third South "
    "African language.": (
        {
            "kind": "any",
            "rules": [
                {
                    "kind": "all",
                    "rules": [
                        {"kind": "subject", "language": "english", "min_level": 5},
                        {"kind": "subject", "language": "afrikaans", "min_level": 5},
                    ],
                },
                {
                    "kind": "all",
                    "rules": [
                        {"kind": "subject", "language": "english", "min_level": 5},
                        {
                            "kind": "any",
                            "rules": [
                                {"kind": "subject", "language": b, "min_level": 5}
                                for b in LANGUAGES
                                if b not in ("english", "afrikaans")
                            ],
                        },
                    ],
                },
                {
                    "kind": "all",
                    "rules": [
                        {"kind": "subject", "language": "afrikaans", "min_level": 5},
                        {
                            "kind": "any",
                            "rules": [
                                {"kind": "subject", "language": b, "min_level": 5}
                                for b in LANGUAGES
                                if b not in ("english", "afrikaans")
                            ],
                        },
                    ],
                },
            ],
        },
        [
            "At least two of English, Afrikaans and a third South African "
            "language at 60% (Home Language or First Additional Language).",
        ],
    ),
    # Diploma in Sustainable Development, p6.
    "Mathematics 50% OR Mathematical Literacy 60% OR Mathematics 40% or "
    "Mathematical Literacy 50% AND 60% for Business Studies or Economics or "
    "Accounting": (
        {
            "kind": "any",
            "rules": [
                _s("mathematics", 4),
                _s("mathematical_literacy", 5),
                {
                    "kind": "all",
                    "rules": [
                        {
                            "kind": "any",
                            "rules": [_s("mathematics", 3), _s("mathematical_literacy", 4)],
                        },
                        {
                            "kind": "any",
                            "rules": [
                                _s("business_studies", 5),
                                _s("economics", 5),
                                _s("accounting", 5),
                            ],
                        },
                    ],
                },
            ],
        },
        [],
    ),
}


# Requirements that are conditions on the applicant but not subject
# bars the engine can test. Each becomes a selection_note verbatim.
NOTE_PATTERNS = [
    r"^Write the NBTs",
    r"^Applicants are also subject to selection",
    r"^Candidates must be available",
    r"^In the main instrument",
    r"^Hand in a prescribed portfolio",
    r"^See additional requirements",
    r"^You will be selected based on",
    r"^You must have a",
    r"^Entry requirement:",
    r"^For the PGCE teaching modules",
    r"^This is a selection programme",
    r"^An interview with the Dean",
    r"^Applicants from the designated",
    r"^A National Senior Certificate with at least \d+% in each",
    r"^If the Home Language",
    r"^A limited number",
]

# A bare NSC with no numeric bar at all (Higher Certificate in Music).
BARE_NSC = re.compile(r"^A National Senior Certificate\.?$", re.I)

AGGREGATE = re.compile(
    r"(?:aggregate|NSC|National Senior Certificate).*?at least\s*(\d{2})\s*%"
    r"|at least\s*(\d{2})\s*%.*?(?:aggregate|for the NSC)",
    re.I | re.S,
)

PCT = re.compile(r"(\d{2})\s*%")


# Off-band conversions made while parsing the record in hand. The
# parser functions are small and are called from several places, so
# rather than thread a result object through all of them they record
# here and build_record drains it.
_OFF_BAND: list[tuple[int, int]] = []


def level_for(pct: int) -> int | None:
    """NSC level for a printed percentage.

    Exact when the percentage is a band floor. Otherwise the band it
    falls inside, recorded in _OFF_BAND so the record can carry a note
    saying what was actually printed.
    """
    if pct in BAND_FLOOR:
        return BAND_FLOOR[pct]
    for floor, level in NSC_BANDS:
        if pct >= floor:
            _OFF_BAND.append((pct, level))
            return level
    return None


def band_range(level: int) -> tuple[int, int]:
    floors = [f for f, lv in NSC_BANDS if lv == level]
    floor = floors[0]
    higher = [f for f, lv in NSC_BANDS if f > floor]
    return floor, (min(higher) - 1 if higher else 100)


def slug(name: str) -> str:
    """A stable, URL-safe code.

    Stellenbosch prints no qualification codes -- UJ's "B8BA3Q" has no
    counterpart here -- but the API addresses a programme by code, so
    one has to be derived. It comes from the printed name so that it
    stays stable across editions as long as the name does.
    """
    s = re.sub(r"[^A-Za-z0-9]+", " ", name).upper().split()
    drop = {"IN", "OF", "AND", "THE"}
    kept = [w for w in s if w not in drop] or s
    return "-".join(kept)[:48].rstrip("-")


# ─── Language parsing ────────────────────────────────────────────────


def _lang_rule(base: str, variant: str | None, level: int) -> dict:
    if variant == "hl":
        return {"kind": "subject", "subject": f"{base}_hl", "min_level": level}
    if variant == "fal":
        return {"kind": "subject", "subject": f"{base}_fal", "min_level": level}
    return {"kind": "subject", "language": base, "min_level": level}


def _any_variant(variant: str, level: int) -> dict:
    """"Home Language 50%" with no language named.

    The booklet means "whatever your home language is, at 50%". There
    is no rule kind for that, and `any_additional_language` is not it
    -- that one spans both variants of every language and is meant for
    the SECOND language, so using it here would let one subject
    satisfy both the Home Language and the First Additional Language
    line at once. An explicit `any` over the eleven keys of the right
    variant cannot: the HL and FAL key sets are disjoint.
    """
    return {
        "kind": "any",
        "rules": [
            {"kind": "subject", "subject": f"{b}_{variant}", "min_level": level}
            for b in LANGUAGES
        ],
    }


NAMED_LANG = re.compile(
    r"\b(" + "|".join(LANGUAGES) + r")\s+"
    r"(home language|first additional language)\s*(\d{2})\s*%",
    re.I,
)

# "English OR Afrikaans (Home Language or First Additional Language) 50%"
PAIRED_LANG = re.compile(
    r"^\s*(?P<a>" + "|".join(LANGUAGES) + r")\s+OR\s+(?P<b>" + "|".join(LANGUAGES) + r")\s*"
    r"\(home language or first additional language\)\s*(?P<pct>\d{2})\s*%\s*$",
    re.I,
)

# "English or Afrikaans Home Language 60% OR Afrikaans or English First
#  Additional Language 70%"
SHARED_LANG = re.compile(
    r"(?P<a>" + "|".join(LANGUAGES) + r")\s+or\s+(?P<b>" + "|".join(LANGUAGES) + r")\s+"
    r"(?P<variant>home language|first additional language)\s*(?P<pct>\d{2})\s*%",
    re.I,
)

GENERIC_LANG = re.compile(
    r"^\s*(home language|first additional language)\s*(\d{2})\s*%\s*$", re.I
)


def parse_language(text: str) -> dict | None:
    """A language requirement as a rule tree, or None if not one."""
    g = GENERIC_LANG.match(text)
    if g:
        variant = "hl" if g.group(1).lower().startswith("home") else "fal"
        level = level_for(int(g.group(2)))
        return _any_variant(variant, level) if level else None

    p = PAIRED_LANG.match(text)
    if p:
        level = level_for(int(p.group("pct")))
        if not level:
            return None
        # Either language, either variant, at the same bar.
        return {
            "kind": "any",
            "rules": [
                _lang_rule(p.group("a").lower(), None, level),
                _lang_rule(p.group("b").lower(), None, level),
            ],
        }

    # "English or Afrikaans Home Language 60% OR Afrikaans or English
    # First Additional Language 70%" -- two languages sharing one
    # variant and one bar, twice over.
    #
    # This is tried before the single-language form because the
    # single-language pattern also matches INSIDE it: "Afrikaans Home
    # Language 60%" and "English First Additional Language 70%" are
    # both there as substrings. Letting that win produced
    # ANY[afrikaans_hl, english_fal] and quietly lost the other two
    # branches, refusing an English Home Language 60% applicant whom
    # BA (Law), BCom (Law) and BAccLLB all admit.
    #
    # The guard is coverage: the shared reading is used only when its
    # matches account for every percentage printed in the line, so a
    # partial match cannot displace a better one.
    shared = list(SHARED_LANG.finditer(text))
    if shared and len(shared) == len(PCT.findall(text)):
        branches = []
        for m in shared:
            level = level_for(int(m.group("pct")))
            if not level:
                return None
            variant = "hl" if m.group("variant").lower().startswith("home") else "fal"
            branches.append(_lang_rule(m.group("a").lower(), variant, level))
            branches.append(_lang_rule(m.group("b").lower(), variant, level))
        return {"kind": "any", "rules": branches}

    named = list(NAMED_LANG.finditer(text))
    if named:
        branches = []
        for m in named:
            level = level_for(int(m.group(3)))
            if not level:
                return None
            variant = "hl" if m.group(2).lower().startswith("home") else "fal"
            branches.append(_lang_rule(m.group(1).lower(), variant, level))
        if len(branches) == 1:
            return branches[0]
        return {"kind": "any", "rules": branches}

    return None


# ─── Subject parsing ─────────────────────────────────────────────────


def _subject_key(fragment: str) -> str | None:
    frag = fragment.lower()
    for pattern, key in SUBJECT_WORDS:
        if re.search(rf"\b{pattern}", frag):
            return key
    return None


def _split_outside_brackets(text: str, pattern: str) -> list[str]:
    """Split on `pattern`, ignoring matches inside parentheses.

    "Physical Sciences (Physics and Chemistry) 50%" names ONE subject.
    Splitting on " and " without regard to the brackets produced
    "Physical Sciences (Physics" and "Chemistry) 50%", neither of
    which names a subject, so the requirement failed to parse and
    seven Agrisciences programmes lost their Physical Sciences bar.
    """
    depth = 0
    spans: list[str] = []
    start = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            m = re.match(pattern, text[i:], re.I)
            if m and m.end():
                spans.append(text[start:i])
                i += m.end()
                start = i
                continue
        i += 1
    spans.append(text[start:])
    return [s for s in spans if s.strip()]


def _parse_conjunct(fragment: str) -> dict | None:
    """One AND-joined piece, e.g. "Mathematics 60% and Accounting 70%"."""
    parts = _split_outside_brackets(fragment, r"\s+and\s+")
    rules = []
    for part in parts:
        pcts = PCT.findall(part)
        key = _subject_key(part)
        if not key or len(pcts) != 1:
            return None
        level = level_for(int(pcts[0]))
        if not level:
            return None
        rules.append({"kind": "subject", "subject": key, "min_level": level})
    if not rules:
        return None
    return rules[0] if len(rules) == 1 else {"kind": "all", "rules": rules}


def parse_subject(text: str) -> dict | None:
    """A subject requirement as a rule tree, or None if not one."""
    if PCT.search(text) is None:
        return None

    # "Life Sciences or Physical Sciences 50%" -- one percentage shared
    # between two subjects, as opposed to "Physical Sciences 50% OR Life
    # Sciences 60%" where each carries its own. Reading the first form
    # as a single subject would silently drop an alternative and refuse
    # applicants the booklet admits.
    shared = re.match(
        r"^\s*(?P<a>[A-Za-z ]+?)\s+or\s+(?P<b>[A-Za-z ]+?)\s*(?P<pct>\d{2})\s*%\s*$",
        text,
        re.I,
    )
    if shared and len(PCT.findall(text)) == 1:
        ka, kb = _subject_key(shared.group("a")), _subject_key(shared.group("b"))
        level = level_for(int(shared.group("pct")))
        if ka and kb and level:
            return {
                "kind": "any",
                "rules": [
                    {"kind": "subject", "subject": ka, "min_level": level},
                    {"kind": "subject", "subject": kb, "min_level": level},
                ],
            }

    branches = []
    for fragment in _split_outside_brackets(text, r"\s+OR\s+|;\s*OR\s+"):
        rule = _parse_conjunct(fragment)
        if rule is None:
            return None
        branches.append(rule)
    if not branches:
        return None
    return branches[0] if len(branches) == 1 else {"kind": "any", "rules": branches}


# ─── Education's three language routes ───────────────────────────────


TAUGHT_IN = re.compile(r"^Learners who were taught in (\w+):$", re.I)


def education_routes(reqs: list[dict]) -> tuple[list[dict], list[dict]] | None:
    """Rebuild the p9 Education block's "taught in X" alternatives.

    The block prints three mutually exclusive routes joined by OR, each
    a pair of language bars:

        Learners who were taught in English:
          - English Home Language 60%
          - Afrikaans OR isiXhosa (Home Language or First Additional) 50%
        OR
        Learners who were taught in Afrikaans:  ...

    Flattened into one list these become an impossible requirement --
    English AND Afrikaans AND isiXhosa all at once. Returns
    (rules_before_the_routes, the_route_group).
    """
    idx = next(
        (i for i, q in enumerate(reqs) if TAUGHT_IN.match(q["text"].strip())), None
    )
    if idx is None:
        return None

    head = reqs[:idx]
    # Drop the bare "AND" that introduces the routes.
    head = [q for q in head if q["text"].strip().upper() != "AND"]

    routes: list[list[dict]] = []
    current: list[dict] | None = None
    for q in reqs[idx:]:
        t = q["text"].strip()
        if TAUGHT_IN.match(t):
            current = []
            routes.append(current)
            continue
        if t.upper() in {"AND", "OR"}:
            continue
        if current is not None:
            current.append(q)

    branches = []
    for route in routes:
        rules = [parse_language(q["text"]) for q in route]
        if any(r is None for r in rules):
            return None
        branches.append({"kind": "all", "rules": rules})
    if len(branches) < 2:
        return None
    return head, [{"kind": "any", "rules": branches}]


# ─── Record construction ─────────────────────────────────────────────


def is_note(text: str) -> bool:
    return any(re.search(p, text, re.I) for p in NOTE_PATTERNS)


def build_record(row: dict, pages: list[int], faculties: list[str]) -> dict:
    notes: list[str] = []
    unparsed: list[str] = []
    off_band: list[tuple[str, int, int]] = []
    rules: list[dict] = []
    min_score: int | None = None

    reqs = list(row["requirements"])

    # Teaching modules and other labelled sub-lists are not entry bars.
    # The booklet's own label is what says so, carried through by the
    # extractor as `intro`.
    for q in reqs:
        if q.get("intro") and re.search(r"teaching (subjects|modules)", q["intro"], re.I):
            notes.append(f"Teaching module choice: {q['text']}")
    reqs = [
        q
        for q in reqs
        if not (q.get("intro") and re.search(r"teaching (subjects|modules)", q["intro"], re.I))
    ]

    routes = education_routes(reqs)
    if routes is not None:
        head, route_rules = routes
        reqs = head
        rules.extend(route_rules)

    for q in reqs:
        text = q["text"].strip()
        if not text or text.upper() in {"AND", "OR"}:
            continue

        if BARE_NSC.match(text):
            continue

        # Consulted before the note patterns: a rule written out by
        # hand is an explicit decision that this text IS expressible,
        # and must not be pre-empted by a pattern that says it is not.
        normalised = " ".join(text.split())
        if normalised in HAND_BUILT:
            rule, extra = HAND_BUILT[normalised]
            rules.append(rule)
            notes.extend(extra)
            continue

        if is_note(text):
            notes.append(text)
            continue

        m = AGGREGATE.search(text)
        if m and re.search(r"aggregate|for the NSC|NSC or|NSC,", text, re.I):
            value = int(m.group(1) or m.group(2))
            min_score = value if min_score is None else max(min_score, value)
            continue

        # A conditional bar ("If you take Economics as a university
        # subject, then also: Mathematics 60%") is not an entry
        # condition -- it binds only once the applicant chooses that
        # university subject, which they have not done yet.
        if q.get("intro") and re.match(r"^\s*(If|When|Should)\b", q["intro"], re.I):
            notes.append(f"{q['intro'].rstrip(':')}: {text}")
            continue

        # "Mathematics 60% or 70% (depending on ...) **" -- the booklet
        # itself defers to a later choice, so take the bar that always
        # applies and record the rest.
        if re.search(r"\*\*|depending on your choice|if you choose", text, re.I):
            pcts = [int(p) for p in PCT.findall(text)]
            key = _subject_key(text)
            if key and pcts:
                level = level_for(min(pcts))
                if level:
                    rules.append({"kind": "subject", "subject": key, "min_level": level})
                    notes.append(text)
                    continue

        _OFF_BAND.clear()
        rule = parse_language(text) or parse_subject(text)
        if rule is not None:
            rules.append(rule)
            for pct, level in dict.fromkeys(_OFF_BAND):
                floor, ceiling = band_range(level)
                notes.append(
                    OFF_BAND_NOTE.format(
                        subject=_subject_key(text) or "that subject",
                        pct=pct,
                        level=level,
                        floor=floor,
                        ceiling=ceiling,
                    )
                )
                off_band.append((text, pct, level))
            _OFF_BAND.clear()
            continue
        _OFF_BAND.clear()

        unparsed.append(text)
        notes.append(text)

    requirements: dict = {"nsc": {}}
    if min_score is not None:
        requirements["nsc"]["score"] = [{"min_score": min_score}]
    if min_score is not None or rules:
        # An empty "all" is the honest encoding of "the booklet states
        # no subject conditions" -- it evaluates to no failures, which
        # is exactly right. BTh and BDiv (p15) print an aggregate and
        # nothing else, and the evaluator reads this key directly.
        requirements["nsc"]["subjects"] = {"kind": "all", "rules": rules}

    return {
        "institution_id": INSTITUTION,
        "academic_year": ACADEMIC_YEAR,
        "qualification_code": slug(row["name"]),
        "name": row["name"],
        "faculty": "; ".join(faculties) if faculties else None,
        "campus": ["Stellenbosch"],
        "duration_years": row["duration_years"],
        "extended": row["extended"],
        "requirements": requirements,
        "selection_notes": notes,
        "career_text": None,
        "source_doc": SOURCE_DOC,
        "source_page": pages[0],
        "confidence": "flagged" if (unparsed or off_band) else "verified",
        "scoreable": min_score is not None,
    }, unparsed, off_band


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "seeds" / "su" / "su_2027.json")
    args = ap.parse_args()

    rows = [
        r
        for r in json.loads(args.rows.read_text(encoding="utf-8"))
        if r["kind"] == "programme"
    ]

    # One interfaculty programme can be printed under several
    # faculties. Bachelor of Data Science appears on p3, p6, p8 and
    # p15 with identical requirements; it is one offering.
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["name"], []).append(r)

    records = []
    unparsed_total: list[tuple[str, str]] = []
    off_band_total: list[tuple[str, str, int, int]] = []
    for name, group in grouped.items():
        pages = [g["page"] for g in group]
        faculties = sorted({g["faculty"] for g in group if g["faculty"]})
        record, unparsed, off_band = build_record(group[0], pages, faculties)
        off_band_total.extend((name, t, p_, l) for t, p_, l in off_band)
        if len(group) > 1:
            record["selection_notes"].append(
                "Interfaculty programme, listed under "
                + ", ".join(faculties)
                + f" (booklet pages {', '.join(str(p) for p in pages)})."
            )
        records.append(record)
        unparsed_total.extend((name, u) for u in unparsed)

    records.sort(key=lambda r: r["qualification_code"])

    codes = [r["qualification_code"] for r in records]
    dupes = {c for c in codes if codes.count(c) > 1}
    if dupes:
        raise SystemExit(f"duplicate qualification codes: {sorted(dupes)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    scoreable = sum(1 for r in records if r["scoreable"])
    review = [r for r in records if r["confidence"] == "flagged"]
    print(f"{len(records)} records -> {args.out}")
    print(f"  scoreable (aggregate parsed): {scoreable}")
    print(f"  flagged for review: {len(review)}")
    print(f"  off-band bars mapped to the band they fall in: {len(off_band_total)}")
    for name, text, pct, level in off_band_total:
        print(f"     {name[:30]:32} {pct}% -> level {level}   {text[:52]}")
    print(f"  unparsed requirement lines: {len(unparsed_total)}")
    for name, text in unparsed_total:
        print(f"     {name[:34]:36} {text[:76]}")


if __name__ == "__main__":
    main()
