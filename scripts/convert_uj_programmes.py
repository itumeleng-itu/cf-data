#!/usr/bin/env python3
"""Turn extracted UJ table rows into seed records.

Reads the output of extract_uj_programmes.py and emits the same record
shape the existing UJ seeds use, so the two can be reconciled directly.

WHAT THIS DOES NOT DO

It does not fill gaps. Where the prospectus prints no duration (the
Science "(Extended)" headings state none), duration_years is null rather
than the four years an extended degree usually runs. Where a cell carries
a note this cannot parse, the note is kept verbatim in selection_notes and
the requirement is left out, never approximated. Every record it cannot
model completely is reported, and the caller decides.

UJ's APS, from page 16 of the prospectus: the sum of the achievement
ratings of SIX subjects, with Life Orientation excluded, on the standard
NSC bands (7 = 80-100% down to 1 = 0-29%). No bonus points, and no
zeroing of low levels -- 0-29% scores 1, not 0. That is already configured
on the institution as aps_best6_excl_lo, so nothing here re-implements it.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DOC = "uj_undergrad_prospectus2027"
DURATION_IN_HEADER = re.compile(r"\(\s*(\d)\s*(½|\.5)?\s*years?\s*\)", re.IGNORECASE)
ACADEMIC_YEAR = 2027

FACULTY_NAMES = {
    "fada": "Art, Design and Architecture",
    "cbe": "Business and Economics",
    "education": "Education",
    "febe": "Engineering and the Built Environment",
    "health": "Health Sciences",
    "humanities": "Humanities",
    "law": "Law",
    "science": "Science",
}

# Column header -> subject slug. The header text varies by faculty
# ("Mathematics Literacy" on some Health pages, "Physical Science **" where
# a footnote applies), so every printed spelling is mapped explicitly
# rather than normalised with a rule that might collide.
COLUMN_SUBJECT = {
    "Mathematics": "mathematics",
    "Mathematics *": "mathematics",
    "Mathematical Literacy": "mathematical_literacy",
    "Mathematics Literacy": "mathematical_literacy",
    "Technical Mathematics": "technical_mathematics",
    "Technical Mathematics **": "technical_mathematics",
    "Physical Science": "physical_sciences",
    "Physical Science **": "physical_sciences",
    "Life Science": "life_sciences",
    "Technical Science": "technical_sciences",
}
CONJUNCTIONS = {"AND/OR", "AND", "OR"}
# A column asking for a second language of any kind, which the engine
# represents with its own node rather than a named language.
COLUMN_ANY_ADDITIONAL = {"Additional Recognised Language", "Additional Language *",
                         "Additional Language"}

# Columns naming a language rather than a subject.
COLUMN_LANGUAGE = {
    "English": "english",
    "English *": "english",
    "Afrikaans": "afrikaans",
    "IsiZulu": "isizulu",
    "Sepedi": "sepedi",
}
# A single column covering two subjects, either of which satisfies it.
COLUMN_EITHER = {
    "Mathematics / Technical Mathematics": ("mathematics", "technical_mathematics"),
    "Mathematics / Technical Maths": ("mathematics", "technical_mathematics"),
    # The BEd tables print one column for both, so the level satisfies
    # either subject -- recording it as Technical Mathematics alone (which
    # a shorter label match did) states a requirement the page does not.
    "Mathematical Literacy / Technical Mathematics":
        ("mathematical_literacy", "technical_mathematics"),
}

# Words the APS cell uses for each subject in its conditional clauses.
APS_SUBJECT_WORDS = [
    (r"tech(?:nical)?\s*maths?|technical mathematics", "technical_mathematics"),
    (r"maths?\s*lit|mathematical literacy|mathematics literacy", "mathematical_literacy"),
    (r"mathematics|maths", "mathematics"),
]

# Exclusions printed OUTSIDE the table, as page notes.
#
# These are real admission rules that no column carries, so a converter
# reading only the table misses them -- which is how 12 Science and Health
# records came out with no excluded subjects where the hand-checked seeds
# correctly had two each.
#
# Each entry quotes the note it comes from and keeps the note's own scope.
# The scopes differ and matter: the Science note covers Degree programmes
# only, and page 95 says the opposite for diplomas.
PAGE_NOTE_EXCLUSIONS = [
    {
        "pages": range(86, 95),  # 86-94; page 95 is diplomas, see below
        "quote": "PLEASE NOTE: Technical Mathematics and Technical Science are not "
                 "accepted for Degree programmes in the Faculty of Science.",
        "exclude": ["technical_mathematics", "technical_sciences"],
        "only_codes": None,
    },
    {
        "pages": [66],
        "quote": "Note: Courses in Diagnostic Radiography, Diagnostic Ultrasound, "
                 "Nuclear Medicine and Radiation Therapy do not accept Technical "
                 "Mathematics and Technical Sciences.",
        "exclude": ["technical_mathematics", "technical_sciences"],
        # The note names four programmes; Biokinetics shares the page and is
        # not one of them.
        "only_codes": {"B9M01Q", "B9M03Q", "B9M02Q", "B9M04Q"},
    },
    {
        "pages": [75],
        "quote": "Technical Mathematics is not accepted for the BA with "
                 "specialisation in Politics, Economics and Technology.",
        "exclude": ["technical_mathematics"],
        "only_codes": {"B7026Q"},
    },
]
# Page 95 states the exception explicitly, so nothing is excluded there:
# "PLEASE NOTE: Technical Mathematics is accepted for the Diploma
# programmes in the Faculty of Science."

LEVEL = re.compile(r"(\d)\s*\(\s*\d{2}\s*%\s*\+?\s*\)")
NOT_ACCEPTED = re.compile(r"not\s+accepted", re.I)
NOT_APPLICABLE = re.compile(r"not\s+applicable", re.I)


def _subject_from_words(text: str) -> list[str]:
    """Which subject(s) an APS clause names, longest spelling first."""
    out: list[str] = []
    low = text.lower()
    for pattern, slug in APS_SUBJECT_WORDS:
        for m in re.finditer(pattern, low):
            if slug not in out:
                out.append(slug)
            low = low[: m.start()] + " " * (m.end() - m.start()) + low[m.end():]
    return out


def parse_aps(cell: str) -> tuple[list[dict], str]:
    """(score entries, unparsed residue).

    Three printed forms:
      "30"                                        -> one unconditional bar
      "25 with Mathematics OR 26 with Maths Lit"  -> one bar per subject
      "24-26 or 27"                               -> a range, not modelled

    A conditional bar becomes one entry per named subject, which is how the
    engine already represents TUT's: the evaluator takes the lowest bar the
    candidate's own subjects qualify them for.
    """
    text = " ".join(cell.split())
    if not text:
        return [], ""

    clauses = re.split(r"\bOR\b|\bor\b", text)
    entries: list[dict] = []
    residue_parts: list[str] = []
    unconditional: int | None = None

    for clause in clauses:
        m = re.search(r"\b(\d{2})\b", clause)
        if not m:
            if clause.strip():
                residue_parts.append(clause.strip())
            continue
        score = int(m.group(1))
        tail = clause[m.end():]
        subjects = _subject_from_words(tail)
        # Canonical order, not the order the longest-first patterns
        # happened to match in, so two readings of the same cell produce
        # the same record.
        rank = {"mathematics": 0, "technical_mathematics": 1, "mathematical_literacy": 2}
        subjects.sort(key=lambda s: rank.get(s, 9))
        if subjects:
            for s in subjects:
                entries.append({"min_score": score, "requires_subject": s})
        elif unconditional is None:
            unconditional = score
        else:
            residue_parts.append(clause.strip())
        leftover = re.sub(r"\bwith\b", " ", tail, flags=re.I)
        for pattern, _slug in APS_SUBJECT_WORDS:
            leftover = re.sub(pattern, " ", leftover, flags=re.I)
        leftover = re.sub(r"[^A-Za-z]+", " ", leftover).strip()
        # "31 with Mathematics ONLY" -- the emphasis says Mathematical
        # Literacy is not accepted, which that column already records as
        # "Not accepted". Nothing is lost by not restating it here.
        leftover = re.sub(r"\bonly\b", " ", leftover, flags=re.I).strip()
        if len(leftover) > 2:
            residue_parts.append(leftover)

    if unconditional is not None and not entries:
        entries = [{"min_score": unconditional}]
    elif unconditional is not None and entries:
        # A bare number alongside conditional bars is a floor that applies
        # whatever the subject; keep it as its own unconditional entry.
        entries.insert(0, {"min_score": unconditional})

    # A range ("24-26 or 27") leaves the second number as a separate entry;
    # flag rather than guess which applies.
    if re.search(r"\d{2}\s*[-–]\s*\d{2}", text):
        residue_parts.append(f"printed as a range: {text}")

    return entries, "; ".join(p for p in residue_parts if p)


def parse_requirement(cell: str) -> tuple[str, int | None, str]:
    """(kind, level, residue) for one subject cell.

    kind is "level" (a minimum), "excluded" (the subject is not accepted),
    "none" (printed as not applicable) or "unparsed".

    Where a cell offers alternatives ("4 (50%+)/ 5 (60%+)**", "5 (60%+) or
    4 (50%+)") the LOWER level is taken, because the higher one is the
    conditional case the footnote qualifies, and admitting on the lower bar
    is what the table's own "or" means.
    """
    # Footnote markers can land inside the phrase ("Not ** applicable"),
    # so they are stripped before the phrase is recognised.
    text = " ".join(cell.replace("*", " ").split())
    if not text or text in {"–", "-"}:
        return "none", None, ""
    if NOT_APPLICABLE.search(text):
        return "none", None, ""
    if NOT_ACCEPTED.search(text):
        return "excluded", None, ""
    levels = [int(m.group(1)) for m in LEVEL.finditer(text)]
    if not levels:
        return "unparsed", None, text
    residue = LEVEL.sub(" ", text)
    residue = re.sub(r"\b(OR|or|AND|and|Home language|Additional Language)\b", " ", residue)
    residue = re.sub(r"[^A-Za-z]+", " ", residue).strip()
    return "level", min(levels), residue if len(residue) > 2 else ""


def language_rule(cell: str, language: str) -> tuple[dict | None, str]:
    """English/Afrikaans columns, which may set two bars by language role.

    "Home language 5 (60%+) OR Additional Language 6 (70%+)" is two bars
    for the same language depending on how it was taken. The engine's
    language rule carries a single minimum, so the lower of the two is
    used -- the bar a candidate can actually meet -- and the full text is
    kept as a note so nothing is lost.
    """
    kind, level, residue = parse_requirement(cell)
    if kind != "level" or level is None:
        return None, residue
    rule = {"kind": "subject", "language": language, "min_level": level}
    note = ""
    # "Home language 5 (60%+) OR Additional Language 6 (70%+)" is two bars
    # for one language: lower if it is the candidate's home language,
    # higher if it is an additional one. Collapsing to the lower of the two
    # admits a First Additional Language candidate at level 5, which the
    # page does not. The engine carries both as min_level/min_level_fal.
    levels = sorted({int(m.group(1)) for m in LEVEL.finditer(cell)})
    # "Home language" plus a second level is enough to recognise the
    # banded form. Requiring the literal word "Additional" too was too
    # strict: on page 55 the isiZulu cell reads "Home language 4 (50%+)
    # OR Language 5 (60%+)", the word having drifted into the neighbouring
    # English cell, and the second bar was silently dropped.
    if re.search(r"home language", cell, re.I) and len(levels) >= 2:
        rule["min_level"] = levels[0]
        rule["min_level_fal"] = levels[-1]
        note = f"{language.title()}: {' '.join(cell.split())}"
    return rule, note


QUALIFICATION_PREFIX = [
    (r"bachelor of engineering technology|beng ?tech", "BEngTech"),
    (r"bachelor of engineering|beng\b", "BEng"),
    (r"bachelor of science in construction", "BSc (Construction)"),
    (r"bachelor of science|bsc\b", "BSc"),
    (r"bachelor of commerce|bcom\b", "BCom"),
    (r"bachelor of health science", "BHSc"),
    (r"bachelor of biokinetics", "B Biokinetics"),
    (r"bachelor of mine surveying", "B Mine Surveying"),
    (r"bachelor of urban and regional planning", "B Urban and Regional Planning"),
    (r"bachelor of arts|^ba\b|\bba degree", "BA"),
    (r"bed degree|^bed\b", "BEd"),
    (r"extended diploma", "Extended Diploma"),
    (r"diploma", "Diploma"),
    (r"higher certificate", "Higher Certificate"),
    (r"bachelor degree|bachelor degrees|b degree|degree programme", "Bachelor"),
]


def title_case(name: str) -> str:
    """UJ prints programme names in capitals; seeds use title case."""
    small = {"and", "of", "in", "with", "the", "for", "or", "to", "a", "an"}
    parts = []
    for i, word in enumerate(name.split()):
        if word.isupper() and len(word) > 3 and word.isalpha():
            w = word.capitalize()
        elif word.isupper() and not word.isalpha():
            w = word  # codes, "R-3", "(CA)"
        else:
            w = word
        if i and w.lower() in small:
            w = w.lower()
        parts.append(w)
    return " ".join(parts)


_GENERIC_BLOCK = re.compile(
    r"^(b|bachelor|bachelors?|ba|bsc|bcom|bed|beng|bengtech|bhsc|diplomas?|"
    r"extended diplomas?|higher certificates?|online|degree)"
    r"( degrees?| programmes?| in)*$", re.I)
_QUALIFICATION_TOKEN = re.compile(
    r"^(b|ba|bsc|bcom|bed|beng|bengtech|bhsc|llb|bcur|boptom|diploma)\b", re.I)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def build_name(row: dict) -> str:
    """The programme's name, from its banner and its table cell.

    A banner is sometimes the programme's own name and sometimes only a
    grouping, and both read as "Bachelor of X": page 68's "Bachelor of
    Nursing (4 years)" heads a single programme, while page 87's "Bachelor
    of Science in Life and Environmental Sciences (3 years)" heads ten.
    Using the banner for both would name ten Science programmes identically;
    ignoring it leaves "Nursing" and "B Optom".

    They are told apart by containment: if the table cell's text appears
    inside the banner, the banner is naming that programme. Otherwise it is
    a grouping, and the name is the qualification abbreviation plus the
    cell's text.
    """
    path = row.get("block_path") or ([row["block"]] if row.get("block") else [])
    body = title_case(row["programme"]).strip()
    specific = ""
    for block in reversed(path):
        candidate = re.sub(r"\([^)]*\)", " ", block)
        candidate = " ".join(candidate.split()).strip(" -–")
        if candidate and not _GENERIC_BLOCK.match(candidate):
            specific = candidate
            break

    core = re.sub(r"^b\s+", "", body, flags=re.I)
    if specific and core and _norm(core) in _norm(specific):
        return specific

    prefix = ""
    blocks = " ".join(path).lower()
    for pattern, label in QUALIFICATION_PREFIX:
        if re.search(pattern, blocks):
            prefix = label
            break

    # The cell may already carry its own qualification ("LLB", "BA (LAW)").
    if _QUALIFICATION_TOKEN.match(body):
        return body
    if not prefix:
        return body
    if prefix == "Bachelor":
        return f"Bachelor of {core}".strip()
    return f"{prefix} {core}".strip()


APS_RANGE = re.compile(r"(\d{2})\s*[-–]\s*(\d{2})\s*or\s*(\d{2})", re.I)


def paired_aps_and_english(aps_cell: str, english_cell: str):
    """The page 76 pairing: English level decides which APS bar applies.

    The four extended BA programmes print "24-26 or 27" against English
    "5 (60%+) or 4 (50%+)", with the note "The APS score in English
    determines the range of the overall APS score" -- English 5 admits at
    24, English 4 needs 27.

    The schema's score threshold carries `min_score` and at most a
    `requires_subject`; there is no way to make a bar conditional on
    another subject's LEVEL, so this rule cannot be recorded exactly.

    Of the two faithful-but-partial options, this takes the pair with the
    LOWER APS and that pair's own English level (24 with English 5). Both
    options can only under-admit, never over-admit -- what must not happen
    is combining the easier APS with the easier English, which would tell
    a learner with English 4 and an APS of 24 that they qualify when the
    table says they do not. The full printed rule is kept in
    selection_notes.
    """
    m = APS_RANGE.search(" ".join(aps_cell.split()))
    if not m:
        return None
    levels = [int(x.group(1)) for x in LEVEL.finditer(english_cell)]
    if len(levels) < 2:
        return None
    low_aps, high_aps = int(m.group(1)), int(m.group(3))
    note = (f"Printed as APS {m.group(1)}-{m.group(2)} or {m.group(3)}, with English "
            f"{max(levels)} or {min(levels)}; the English level determines which APS "
            f"applies. Recorded as the lower APS ({low_aps}) with the English level it "
            f"requires ({max(levels)}). The alternative route, APS {high_aps} with "
            f"English {min(levels)}, is not representable in the score schema.")
    return [{"min_score": low_aps}], max(levels), note


def convert_row(row: dict) -> tuple[dict, list[str]]:
    problems: list[str] = []
    cells = row["cells"]

    paired = paired_aps_and_english(
        cells.get("Minimum APS", ""), cells.get("English", "") or cells.get("English *", "")
    )
    rules: list[dict] = []
    excluded: list[str] = []
    notes: list[str] = []

    score, aps_residue = parse_aps(cells.get("Minimum APS", ""))
    if paired:
        score, english_level, pair_note = paired
        aps_residue = ""
        notes.append(pair_note)
        rules.append({"kind": "subject", "language": "english", "min_level": english_level})
    if not score:
        problems.append("no APS could be parsed")
    if aps_residue:
        problems.append(f"APS cell not fully parsed: {aps_residue}")

    for column, language in COLUMN_LANGUAGE.items():
        if column not in cells:
            continue
        if paired and language == "english":
            continue
        rule, note = language_rule(cells[column], language)
        if rule:
            rules.append(rule)
        if note:
            notes.append(note)

    additional_language: list[dict] = []
    for column in COLUMN_ANY_ADDITIONAL:
        if column not in cells:
            continue
        kind, level, residue = parse_requirement(cells[column])
        if kind == "level" and level is not None:
            additional_language.append({"kind": "any_additional_language", "min_level": level})
        if residue:
            notes.append(f"{column}: {' '.join(cells[column].split())}")

    # Subject columns joined by a printed conjunction.
    paired_rules: list[dict] = []
    order = row.get("column_order") or []
    paired_cols: set[str] = set()
    for i, label in enumerate(order):
        base = label.split("#")[0]
        # "AND" joins requirements that all apply, which is the default.
        #
        # "AND/OR" is treated the same way, deliberately. Page 55 prints
        # "(Maths/Tech Maths OR Mathematical Literacy) AND/OR (Physical
        # Science OR Life Science)" for the BEd Senior Phase subjects.
        # Read literally that is "at least one of the two groups", which
        # would be an `any` of two `any`s -- a shape the bundle format
        # cannot represent. Requiring both groups is the stricter reading,
        # so it can only ever turn a candidate away, never admit one the
        # page would not. The printed wording goes into the notes so the
        # choice is visible and reversible.
        if base not in CONJUNCTIONS or base in ("AND", "AND/OR"):
            if base == "AND/OR":
                notes.append(
                    "Printed as two requirement groups joined by \"AND/OR\"; recorded as "
                    "requiring both, which is the stricter reading."
                )
            continue
        left = order[i - 1] if i else None
        right = order[i + 1] if i + 1 < len(order) else None
        if left in COLUMN_SUBJECT and right in COLUMN_SUBJECT:
            alts = []
            for col in (left, right):
                k, lv, _res = parse_requirement(cells.get(col, ""))
                if k == "level" and lv is not None:
                    alts.append({"kind": "subject", "subject": COLUMN_SUBJECT[col], "min_level": lv})
                elif k == "excluded" and COLUMN_SUBJECT[col] not in excluded:
                    excluded.append(COLUMN_SUBJECT[col])
            paired_cols.update({left, right})
            if len(alts) > 1:
                paired_rules.append({"kind": "any", "rules": alts})
            elif alts:
                paired_rules.append(alts[0])

    maths_group: list[dict] = []
    other_rules: list[dict] = []
    for column, slug in COLUMN_SUBJECT.items():
        if column in paired_cols:
            continue
        if column not in cells:
            continue
        kind, level, residue = parse_requirement(cells[column])
        if residue:
            # The requirement itself parsed; the remainder is note prose
            # printed inside the cell (page 67 runs a long note about
            # AHPCSA registration straight through the subject columns).
            # Kept verbatim rather than dropped, and still reported.
            notes.append(f"{column}: {' '.join(cells[column].split())}")
            problems.append(f"{column} carries note text: {residue}")
        if kind == "excluded":
            if slug not in excluded:
                excluded.append(slug)
        elif kind == "level":
            entry = {"kind": "subject", "subject": slug, "min_level": level}
            if slug in ("mathematics", "mathematical_literacy", "technical_mathematics"):
                maths_group.append(entry)
            else:
                other_rules.append(entry)
        elif kind == "unparsed":
            problems.append(f"{column} unparsed: {cells[column][:60]}")

    for column, (a, b) in COLUMN_EITHER.items():
        if column not in cells:
            continue
        kind, level, residue = parse_requirement(cells[column])
        if kind == "level":
            maths_group.append({"kind": "any", "rules": [
                {"kind": "subject", "subject": a, "min_level": level},
                {"kind": "subject", "subject": b, "min_level": level},
            ]})
        elif kind == "excluded":
            excluded.extend(s for s in (a, b) if s not in excluded)

    # Order matters for the bundle round-trip, which regroups the
    # mutually exclusive maths family and expects it ahead of the other
    # subject groups -- the order the hand-checked seeds already use.
    # Flatten: a combined column contributes an "any" of its two
    # subjects, and nesting that inside the maths-family "any" produces a
    # tree the bundle format cannot reverse. "Either A or B" inside
    # "either of these" is just one list of alternatives.
    flat_maths: list[dict] = []
    for node in maths_group:
        if node.get("kind") == "any":
            flat_maths.extend(node["rules"])
        else:
            flat_maths.append(node)
    seen_subj: set[str] = set()
    maths_group = [n for n in flat_maths
                   if not (n.get("subject") in seen_subj or seen_subj.add(n.get("subject")))]
    # Same canonical order the bundle converter groups them in, so a
    # record built here and one rebuilt from a flat transcription agree.
    _rank = {"mathematics": 0, "technical_mathematics": 1, "mathematical_literacy": 2}
    maths_group.sort(key=lambda n: _rank.get(n.get("subject"), 9))

    if len(maths_group) == 1:
        rules.append(maths_group[0])
    elif maths_group:
        rules.append({"kind": "any", "rules": maths_group})
    rules.extend(paired_rules)
    rules.extend(other_rules)
    # Last, which is where the bundle round-trip puts it.
    rules.extend(additional_language)

    campus = [c for c in re.split(r"[/,]", cells.get("CAMPUS", "")) if c.strip()]
    campus = [c.strip() for c in campus if re.fullmatch(r"[A-Za-z]{3,8}", c.strip())]

    codes = re.findall(r"(?<![A-Z0-9])[A-Z0-9]{6}(?![A-Z0-9])", cells.get("Qualification Code", ""))
    codes = [c for c in codes if any(ch.isdigit() for ch in c)]
    if not codes:
        problems.append("no qualification code")

    # Page notes printed outside the table.
    for note in PAGE_NOTE_EXCLUSIONS:
        if row["page"] not in note["pages"]:
            continue
        if note["only_codes"] and not (set(codes) & note["only_codes"]):
            continue
        for slug in note["exclude"]:
            if slug not in excluded:
                excluded.append(slug)
        if note["quote"] not in notes:
            notes.append(note["quote"])

    blocks = " ".join(row.get("block_path") or [])
    record = {
        "institution_id": "uj",
        "academic_year": ACADEMIC_YEAR,
        "qualification_code": codes[0] if codes else None,
        "name": build_name(row),
        "faculty": FACULTY_NAMES[row["faculty"]],
        "campus": campus,
        "duration_years": row.get("duration_years"),
        "extended": bool(re.search(r"extended", blocks, re.I)),
        "requirements": {
            "nsc": {
                "score": score,
                "subjects": {"kind": "all", "rules": rules},
                "excluded_subjects": excluded,
            }
        },
        "selection_notes": notes,
        "source_doc": SOURCE_DOC,
        "source_page": row["page"],
        "confidence": "verified",
    }
    if len(codes) > 1:
        record["alternate_codes"] = codes[1:]
    return record, problems


def merge_hand_verified(records: list[dict], seed_dir: Path) -> list[str]:
    """Keep exclusions the existing hand-checked seeds carry that the
    prospectus does not state in a form this converter can read.

    Three Health records are affected. The hand-checked seeds exclude
    Mathematical Literacy from Diagnostic Radiography, Nursing and
    Optometry, and exclude the Technical subjects from the latter two. The
    prospectus prints no such rule for them: the page 66 note names four
    other programmes, and these rows simply leave those columns empty.

    The inference behind the hand version is sound -- their APS bars read
    "31 with Mathematics" with no Mathematical Literacy alternative, where
    programmes that do accept it print one. It is still an inference, so
    it is not something to re-derive automatically; but dropping it would
    start telling Mathematical Literacy candidates they qualify for
    Nursing, which is the costlier direction to be wrong in.

    So prior verified judgements are kept, never overwritten, and every
    one is reported.
    """
    import glob
    existing: dict[str, dict] = {}
    for f in glob.glob(str(seed_dir / "*.json")):
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        for p in (data if isinstance(data, list) else data.get("programmes", [])):
            existing[p["qualification_code"]] = p

    kept: list[str] = []
    for rec in records:
        prior = existing.get(rec["qualification_code"])
        if not prior:
            continue
        mine = rec["requirements"]["nsc"]["excluded_subjects"]
        theirs = prior.get("requirements", {}).get("nsc", {}).get("excluded_subjects", [])
        extra = [s for s in theirs if s not in mine]
        if extra:
            mine.extend(extra)
            mine.sort()
            rec["selection_notes"].append(
                "Exclusions carried over from the earlier hand-checked seed and not "
                f"restated in the 2027 prospectus table: {', '.join(extra)}."
            )
            kept.append(f"{rec['qualification_code']} ({rec['name'][:34]}): +{', '.join(extra)}")
    return kept


def _sibling_key(block: str) -> str:
    t = re.sub(r"\((?:extended|\d\s*years?)\)", " ", block, flags=re.I)
    t = re.sub(r"^\s*extended\s+", " ", t, flags=re.I)
    t = re.sub(r"\b(programmes?|degrees?)\b", " ", t, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", t.lower())


def infer_missing_durations(records: list[dict], rows: list[dict]) -> list[str]:
    """Supply a duration the prospectus states elsewhere for the same thing.

    UJ omits the duration from some headings -- the Science and FEBE
    "(Extended)" ones, the BEd Senior Phase ones, the ONLINE PROGRAMMES
    heading -- while printing it for the identical qualification nearby.
    The seed validator requires a duration, and leaving 50 records out of
    the dataset over a missing bracket would be worse than reading what
    the document says a few lines up.

    Nothing is assumed about how long a degree "usually" runs. A value is
    only ever copied from a heading in this same document, in this order:

      1. the same heading without "(Extended)", in the same faculty
      2. the same qualification type in the same faculty
      3. the same qualification type anywhere in the prospectus

    For an extended programme one year is added, which is the relationship
    this prospectus prints wherever it states both forms ("Diplomas (3
    years)" against "Extended Diplomas (4 years)", and twice more).

    Every record says in its notes which heading its duration came from,
    and anything still unresolved is left null and reported.
    """
    exact: dict[tuple[str, str], float] = {}
    by_type: dict[tuple[str, str], float] = {}
    by_type_any: dict[str, float] = {}

    def qual_type(blocks: str) -> str:
        for pattern, label in QUALIFICATION_PREFIX:
            if re.search(pattern, blocks.lower()):
                return label
        return ""

    for row in rows:
        for block in row.get("block_path") or []:
            if re.search(r"extended", block, re.I):
                continue
            m = DURATION_IN_HEADER.search(block)
            if not m:
                continue
            years = float(m.group(1)) + (0.5 if m.group(2) else 0.0)
            exact.setdefault((row["faculty"], _sibling_key(block)), years)
            qt = qual_type(block)
            if qt:
                by_type.setdefault((row["faculty"], qt), years)
                by_type_any.setdefault(qt, years)

    by_name = {
        _norm(r["name"]): r["duration_years"]
        for r in records if r["duration_years"] is not None
    }

    unresolved: list[str] = []
    for rec, row in zip(records, rows):
        if rec["duration_years"] is not None:
            continue
        bump = 1.0 if rec["extended"] else 0.0
        # The ONLINE PROGRAMMES heading names no qualification, but the
        # programmes under it do ("Bachelor of Commerce in Accountancy").
        blocks = " ".join(row.get("block_path") or [])
        qt = qual_type(blocks) or qual_type(rec["name"])
        found = None
        for block in reversed(row.get("block_path") or []):
            if (hit := exact.get((row["faculty"], _sibling_key(block)))) is not None:
                found, why = hit, f'the heading "{block}" without "(Extended)"'
                break
        if found is None and qt and (hit := by_type.get((row["faculty"], qt))) is not None:
            found, why = hit, f"other {qt} headings in {FACULTY_NAMES[row['faculty']]}"
        if found is None and qt and (hit := by_type_any.get(qt)) is not None:
            found, why = hit, f"other {qt} headings in this prospectus"
        if found is None and (hit := by_name.get(_norm(rec["name"]))) is not None:
            # The same programme listed twice -- page 47's online Bachelor
            # of Human Resource Management is page 40's contact programme
            # under a heading that does state the years.
            found, why = hit, "the same programme listed elsewhere in this prospectus"
        if found is None:
            unresolved.append(f"{rec['qualification_code']} {rec['name'][:38]} (p{rec['source_page']})")
            continue
        rec["duration_years"] = found + bump
        rec["selection_notes"].append(
            f"Duration not printed for this programme; taken as {found + bump:g} years from "
            f"{why}" + (" plus one year for the extended form." if bump else ".")
        )
    return unresolved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--merge-seed-dir", type=Path,
                    help="keep exclusions already present in these hand-checked seeds")
    args = ap.parse_args()

    rows = json.loads(args.rows.read_text(encoding="utf-8"))
    records, all_problems = [], {}
    for row in rows:
        rec, problems = convert_row(row)
        records.append(rec)
        if problems:
            all_problems[f"p{row['page']} {rec['qualification_code']} {rec['name'][:40]}"] = problems

    unresolved = infer_missing_durations(records, rows)
    if unresolved:
        print(f"\n{len(unresolved)} record(s) with no duration stated anywhere for their qualification:")
        for u in unresolved:
            print(f"   {u}")

    merged: list[str] = []
    if args.merge_seed_dir:
        merged = merge_hand_verified(records, args.merge_seed_dir)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    if merged:
        print(f"\ncarried {len(merged)} prior hand-checked exclusion set(s):")
        for m in merged:
            print(f"   {m}")

    print(f"{len(records)} records -> {args.out}")
    print(f"faculties: {dict(Counter(r['faculty'] for r in records))}")
    print(f"with conditional APS: {sum(1 for r in records if len(r['requirements']['nsc']['score']) > 1)}")
    print(f"with excluded subjects: {sum(1 for r in records if r['requirements']['nsc']['excluded_subjects'])}")
    print(f"no duration printed: {sum(1 for r in records if r['duration_years'] is None)}")
    print(f"\nrecords with problems: {len(all_problems)}")
    for key, problems in list(all_problems.items())[:25]:
        print(f"  {key}")
        for p in problems:
            print(f"      - {p}")
    if args.report:
        args.report.write_text(json.dumps(all_problems, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nfull report -> {args.report}")


if __name__ == "__main__":
    main()
