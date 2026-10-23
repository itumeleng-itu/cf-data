"""Converts the verified TUT extraction into coursefind-data's seed
schema. Runs only on tut_2027.json, which verify_tut.py has passed.

WHAT MAPS ONTO WHAT

    subject line          -> {"kind": "subject", "subject": slug, "min_level": n}
    a language            -> {"kind": "subject", "language": family, "min_level": n}
    "Additional language" -> {"kind": "any_additional_language", "min_level": n}
    options on one line   -> an "any" node over them, all at that level
    a block of "or" lines -> an "any" node over the lines, EACH at its own
                             level, because TUT holds alternatives to
                             different minimums (Mathematics 3 but
                             Mathematical Literacy 4 on the same row)
    "X and Y"             -> an "all" node, both required
    the whole requirement -> an "all" node over the blocks

CONDITIONAL APS
    TUT prints a threshold per mathematics route:

        22 (with Accounting or Mathematics or Technical Mathematics)
        24 (with Mathematical Literacy)

    The schema's score entry carries ONE requires_subject, so each
    named subject becomes its own entry at that score, and
    select_score_threshold() takes the lowest entry that applies to the
    learner. A learner with Mathematical Literacy alone matches only
    the 24; one with Mathematics matches the 22.

WHAT IS NOT CONVERTED, AND IS RECORDED INSTEAD
    "Two other subjects" and "Any three additional subjects" are
    requirements for a COUNT of unnamed subjects. The requirement tree
    has no way to say that, and inventing specific subjects would be
    worse than saying nothing, so they become selection notes.
"""
import json
import re
import sys

SOURCE_DOC = "tut_first_year_course_information_2027.pdf"

LANGUAGE_FAMILIES = {
    "english": "english", "afrikaans": "afrikaans", "isizulu": "isizulu",
    "isixhosa": "isixhosa", "sepedi": "sepedi", "sesotho": "sesotho",
    "setswana": "setswana", "xitsonga": "xitsonga", "siswati": "siswati",
    "tshivenda": "tshivenda", "isindebele": "isindebele",
}

# TUT's spellings -> the frozen slugs in api/src/app/subjects.py. Every
# singular/plural variant TUT actually prints is listed rather than
# stemmed, so an unrecognised name fails loudly instead of being
# guessed into the nearest match.
SUBJECT_SLUGS = {
    "mathematics": "mathematics",
    "mathematical literacy": "mathematical_literacy",
    "technical mathematics": "technical_mathematics",
    "physical science": "physical_sciences",
    "physical sciences": "physical_sciences",
    "technical science": "technical_sciences",
    "technical sciences": "technical_sciences",
    "life science": "life_sciences",
    "life sciences": "life_sciences",
    "life orientation": "life_orientation",
    "accounting": "accounting",
    "business studies": "business_studies",
    "economics": "economics",
    "geography": "geography",
    "history": "history",
    "tourism": "tourism",
    "consumer studies": "consumer_studies",
    "visual arts": "visual_arts",
    "dramatic arts": "dramatic_arts",
    "music": "music",
    "design": "design",
    "information technology": "information_technology",
    "computer applications technology": "computer_applications_technology",
    "engineering graphics and design": "engineering_graphics_and_design",
    "engineering graphics design": "engineering_graphics_and_design",
    "agricultural science": "agricultural_sciences",
    "agricultural sciences": "agricultural_sciences",
    "agricultural technology": "agricultural_technology",
    "civil technology": "civil_technology",
    "electrical technology": "electrical_technology",
    "mechanical technology": "mechanical_technology",
    "engineering mathematics n3": "engineering_mathematics_n3",
    # The APS cell abbreviates what the subject column spells out: page
    # 10's Dip (Integrated Communication) requires "Engineering
    # Mathematics N3" but conditions its 20 on "Mathematics N3".
    "mathematics n3": "engineering_mathematics_n3",
    "engineering mathematics n4": "engineering_mathematics_n4",
    "engineering science n4": "engineering_science_n4",
    "hospitality studies": "hospitality_studies",
    "religion studies": "religion_studies",
    "catering": "catering",
    "hotel": "hotel",
}

# Phrasings that mean "another language", which name no specific one.
ANY_LANGUAGE = re.compile(
    r"^(additional language|first additional language|second language|"
    r"any other additional language|home language.*|"
    r"any other home language.*|any other official south african language.*)$",
    re.I)


# TUT's campus column, decoded.
#
# The table prints a code per programme ("M Po", "SS E Po") alongside
# a page-level campus banner. Only the banner was being used, and the
# column went into a prose note reading "Also offered at: M Po" --
# which is why Polokwane, Mbombela, eMalahleni and Online appeared
# nowhere in the campus field, and why three programmes whose own
# name says "(Only Mbombela Campus)" were filed under Pretoria.
#
# Codes confirmed against TUT's published campus list: Pretoria,
# Arcadia, Arts, Soshanguve North, Soshanguve South, Ga-Rankuwa,
# eMalahleni, Mbombela and Polokwane.
CAMPUS_CODES = {
    "Pr": "Pretoria Campus",
    "Ar": "Arcadia Campus",
    "SN": "Soshanguve North Campus",
    "SS": "Soshanguve South Campus",
    "G": "Ga-Rankuwa Campus",
    "GR": "Ga-Rankuwa Campus",
    "E": "eMalahleni Campus",
    "M": "Mbombela Campus",
    "Po": "Polokwane Campus",
    "O": "Online",
}

# The page banner names a campus in prose; normalise it to the same
# vocabulary so a programme does not end up with both "Soshanguve
# Campus" and "Soshanguve South Campus".
BANNER_CAMPUSES = {
    "Pretoria Campus": ["Pretoria Campus"],
    "Arts Campus": ["Arts Campus"],
    "GaRankuwa Campus": ["Ga-Rankuwa Campus"],
    "Ga-Rankuwa Campus": ["Ga-Rankuwa Campus"],
    # The banner is generic where the column is specific; the column
    # wins when it says which Soshanguve.
    "Soshanguve Campus": ["Soshanguve Campus"],
    "Arcadia and Pretoria Campuses": ["Arcadia Campus", "Pretoria Campus"],
}


# Codes seen in the column that are not campuses. Reported, never
# guessed: "D" appears once, on Dip (Fire Technology), and the
# prospectus legend is the only thing that can say what it means.
UNRESOLVED_CODES: dict[str, list[str]] = {}


def campuses_for(programme: dict) -> list[str]:
    """Every campus a programme is taught at, banner plus column.

    The column is authoritative where the two disagree: the banner
    describes a page, the column describes the programme.
    """
    banner = programme.get("campus") or ""
    campuses = list(BANNER_CAMPUSES.get(banner, [banner] if banner else []))

    column = (programme.get("other_campuses") or "").strip()
    for token in column.split():
        name = CAMPUS_CODES.get(token)
        if name is None:
            UNRESOLVED_CODES.setdefault(token, []).append(programme.get("name", "?"))
            continue
        if name not in campuses:
            campuses.append(name)

    # The banner says "Soshanguve Campus"; the column says which one.
    # Keeping both would list a programme at a campus and at its own
    # sub-campus.
    if any(c.startswith("Soshanguve ") and c != "Soshanguve Campus" for c in campuses):
        campuses = [c for c in campuses if c != "Soshanguve Campus"]

    # A programme whose own name says it runs at one campus only is
    # not also taught wherever its page banner happens to sit. Three
    # programmes read "(Only Mbombela Campus)" and were filed under
    # Pretoria.
    only = re.search(r"\(Only ([A-Za-z \-]+?) Campus\)", programme.get("name", ""))
    if only:
        return [f"{only.group(1).strip()} Campus"]

    return campuses


def clean(name: str) -> str:
    """TUT's printed form -> a lookup key. The parenthetical after a
    technology subject lists the trades it covers ("Civil Technology
    (Civil Service/Construction/Woodworking)") and is not part of the
    subject's name."""
    s = re.sub(r"\s*\([^)]*\)", "", name).strip().rstrip(".,")
    return re.sub(r"\s+", " ", s).lower()


class Unmapped(Exception):
    pass


def leaf(option: str, level: int) -> dict:
    key = clean(option)
    if key in LANGUAGE_FAMILIES:
        return {"kind": "subject", "language": LANGUAGE_FAMILIES[key],
                "min_level": level}
    if ANY_LANGUAGE.match(key):
        return {"kind": "any_additional_language", "min_level": level}
    if key in SUBJECT_SLUGS:
        return {"kind": "subject", "subject": SUBJECT_SLUGS[key],
                "min_level": level}
    raise Unmapped(option)


def branch_node(b: dict, notes: list) -> dict | None:
    level = b["min_level"]
    if "unnamed_subjects" in b:
        notes.append(f"Also requires: {b['unnamed_subjects']} "
                     f"at level {level}.")
        return None
    if "all_of" in b:
        rules = [leaf(o, level) for o in b["all_of"]]
        return {"kind": "all", "rules": rules} if len(rules) > 1 else rules[0]
    options = b.get("options") or []
    rules = [leaf(o, level) for o in options]
    if not rules:
        return None
    return {"kind": "any", "rules": rules} if len(rules) > 1 else rules[0]


def block_node(group: list, notes: list) -> dict | None:
    """One block of alternatives. Each branch keeps its own level."""
    rules = [n for n in (branch_node(b, notes) for b in group) if n]
    if not rules:
        return None
    return {"kind": "any", "rules": rules} if len(rules) > 1 else rules[0]


def score_entries(aps: list) -> list:
    """A threshold per mathematics route becomes one entry per named
    subject, so the lowest applicable one wins for each learner."""
    out, seen = [], set()
    for entry in aps:
        score, condition = entry["min_score"], entry["condition"]
        if not condition:
            if (score, None) not in seen:
                out.append({"min_score": score})
                seen.add((score, None))
            continue
        # Alternatives are separated by "or", and on page 13's Dip
        # (Multimedia Computing) (Extended) by a slash instead.
        for part in re.split(r"\s+or\s+|\s*/\s*", condition, flags=re.I):
            key = clean(part)
            slug = SUBJECT_SLUGS.get(key)
            if slug is None:
                raise Unmapped(f"APS condition: {part}")
            if (score, slug) not in seen:
                out.append({"min_score": score, "requires_subject": slug})
                seen.add((score, slug))
    return out


def code_for(name: str, used: set) -> str:
    """TUT prints no qualification code in this document, so one is
    derived from the name and marked synthetic in the notes."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48]
    code = f"tut-{base}"
    n = 2
    while code in used:
        code = f"tut-{base}-{n}"
        n += 1
    used.add(code)
    return code


def convert(programmes):
    records, failures = [], []
    used: set = set()
    for p in programmes:
        notes = list(p.get("notes") or [])
        try:
            blocks = [n for n in (block_node(g, notes) for g in p["requirements"]) if n]
            scores = score_entries(p["aps"])
        except Unmapped as e:
            failures.append((p["page"], p["name"], str(e)))
            continue


        if p["closing_date"]:
            notes.append(f"Applications close {p['closing_date']}.")
        if p["recommended"]:
            notes.append(f"Recommended subjects: {p['recommended']}.")
        notes.append("qualification_code is SYNTHETIC - TUT publishes no "
                     "code for this programme in this document.")

        subjects = ({"kind": "all", "rules": blocks} if len(blocks) != 1
                    else blocks[0]) if blocks else {"kind": "all", "rules": []}

        records.append({
            "institution_id": "tut",
            "academic_year": 2027,
            "qualification_code": code_for(p["name"], used),
            "name": p["name"],
            "faculty": p["faculty"],
            "campus": campuses_for(p),
            "duration_years": p["duration_years"],
            "extended": "(Extended)" in p["name"],
            "requirements": {"nsc": {
                "score": scores,
                "subjects": subjects,
                "excluded_subjects": [],
            }},
            "selection_notes": notes,
            "career_text": p["careers"],
            "source_doc": SOURCE_DOC,
            "source_page": p["page"],
            "confidence": "extracted",
            "scoreable": p["scoreable"],
        })
    return records, failures


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.load(open("tut_2027.json", encoding="utf-8"))
    records, failures = convert(data["programmes"])

    json.dump(records, open("tut_2027_seed.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    print(f"converted      : {len(records)} / {len(data['programmes'])}")
    print(f"scoreable      : {sum(1 for r in records if r['scoreable'])}")
    print(f"score entries  : {sum(len(r['requirements']['nsc']['score']) for r in records)}")
    if failures:
        print(f"\nUNMAPPED ({len(failures)}) - nothing is guessed, so these do not convert:")
        for pg, name, what in failures[:20]:
            print(f"   p{pg} {name[:44]}: {what}")
