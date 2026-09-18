"""One-off converter: universities/2027/tut_2027_programmes.json (a
self-contained reference dataset+evaluator supplied directly, not authored
through this repo's normal bundle/seeds pipeline) -> the same shape
api/src/app/data/programmes.json already holds.

WHY THIS SCRIPT EXISTS, NOT THE NORMAL PIPELINE
-------------------------------------------------
The normal path (docs/BUNDLE_FORMAT.md -> ingest_bundle.py -> Postgres ->
export_data.py) assumes a reachable DATABASE_URL. This source arrived as a
complete, already-structured JSON file with its own (different) schema and
its own reference evaluator (universities/2027/qualify.py) -- not a flat
per-cell bundle a human transcribed against seeds/bundle.schema.json. This
script transliterates that source's tree shape into this repo's
requirements.nsc.{score,subjects,excluded_subjects} shape directly, and
merges the result into api/src/app/data/programmes.json and
seeds/institutions.json in one step, since there is no Postgres round trip
to go through here.

CONFIDENCE: every converted programme is stamped "extracted", never
"verified" -- nobody has cross-checked this conversion's output against a
cited page of TUT's actual brochure the way scripts/validate_data.py's
semantic checks or a human review normally would. Treat it exactly like
any other extracted-not-verified data: usable, but not yet the standard
the rest of this repo holds UJ to.

KNOWN, DELIBERATE GAPS (see docs/scoring/tut.md for the full account):
  1. The NSC Bachelor's/Diploma "endorsement" requirement (source's
     global_requirements.endorsement_by_qualification_type, plus three
     programmes' own stricter versions) needs "N distinct free-choice
     subjects at level >= X" -- a rule kind evaluator.py does not have.
     Dropped uniformly; every other condition on every route is still
     checked exactly.
  2. @-token leaves used as a route's OWN elective (not the endorsement)
     -- @HOME_LANGUAGE / @FIRST_ADDITIONAL_LANGUAGE / @OTHER_HOME_LANGUAGE
     / @ADDITIONAL_LANGUAGE / @ANY_SUBJECT -- are dropped for the same
     reason. Affects 7 programmes; listed in this script's own report
     output every time it runs.
  3. nsc_year_min leaves (2 programmes, both requiring NSC year >= 2008)
     are dropped as always-true for any real 2027 applicant -- the API
     collects no NSC-year input to check them against regardless.
  4. Bare language-name leaves (e.g. "Sepedi", meaning "any level of this
     language") are encoded as a single min_level applied to BOTH the
     Home Language and First Additional Language variant -- correct for
     every such leaf actually used here (checked: none need a Second
     Additional Language variant, which the Subject enum has no slug for
     at all).
  5. Per-programme closing dates and application-fee/contact metadata are
     not represented in this repo's programme schema; closing dates are
     folded into selection_notes as plain text instead of dropped.

Usage: uv run python scripts/convert_tut_reference.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "universities" / "2027" / "tut_2027_programmes.json"
PROGRAMMES_PATH = ROOT / "api" / "src" / "app" / "data" / "programmes.json"
INSTITUTIONS_SEED_PATH = ROOT / "seeds" / "institutions.json"

INSTITUTION_ID = "tut"
ACADEMIC_YEAR = 2027
GLOBAL_ENGLISH_MIN_LEVEL = 3  # global_requirements.all_programmes

# Concrete (non-language) subject names -> this repo's Subject enum slugs.
SUBJECT_SLUGS: dict[str, str] = {
    "Accounting": "accounting",
    "Agricultural Sciences": "agricultural_sciences",
    "Agricultural Technology": "agricultural_technology",
    "Business Studies": "business_studies",
    "Civil Technology": "civil_technology",
    "Consumer Studies": "consumer_studies",
    "Economics": "economics",
    "Electrical Technology": "electrical_technology",
    "Engineering Graphics and Design": "engineering_graphics_and_design",
    "Engineering Mathematics N3": "engineering_mathematics_n3",
    "Geography": "geography",
    "History": "history",
    "Hospitality Studies": "hospitality_studies",
    "Information Technology": "information_technology",
    "Life Sciences": "life_sciences",
    "Mathematical Literacy": "mathematical_literacy",
    "Mathematics": "mathematics",
    "Mechanical Technology": "mechanical_technology",
    "Physical Sciences": "physical_sciences",
    "Technical Mathematics": "technical_mathematics",
    "Technical Sciences": "technical_sciences",
    "Tourism": "tourism",
}

# Bare language names ("any level of this language") -> the language family
# key evaluator.py's LANGUAGE_FAMILIES uses. English is handled separately
# (it gets the same treatment, but every route already names it).
LANGUAGE_NAMES: dict[str, str] = {
    "Afrikaans": "afrikaans",
    "Sepedi": "sepedi",
    "Setswana": "setswana",
    "Tshivenda": "tshivenda",
    "Xitsonga": "xitsonga",
    "isiZulu": "isizulu",
}

DROPPED_TOKENS = {
    "@ANY_SUBJECT",
    "@HOME_LANGUAGE",
    "@OTHER_HOME_LANGUAGE",
    "@FIRST_ADDITIONAL_LANGUAGE",
    "@ADDITIONAL_LANGUAGE",
}


def _routes_of(requirements: dict) -> list[dict]:
    """A programme's requirements are either one implicit route (a bare
    "all" node) or an explicit list of "any" routes -- normalise to a
    list either way."""
    return requirements["any"] if "any" in requirements else [requirements]


def _leaf_to_rule(leaf: dict, report: dict, programme_id: str) -> dict | None:
    """One source leaf -> one evaluator.py rule, or None if this leaf is
    one of the documented, dropped gap cases (see module docstring)."""
    if "subject" not in leaf:
        # aps_min / nsc_year_min leaves are handled by the caller, not here.
        return None
    names = leaf["subject"]
    if any(n in DROPPED_TOKENS for n in names):
        report["dropped_token_leaves"].append((programme_id, names))
        return None
    if leaf.get("count", 1) > 1:
        report["dropped_count_leaves"].append((programme_id, names, leaf["count"]))
        return None

    min_level = leaf["min_level"]
    alternatives = []
    for name in names:
        if name == "English":
            alternatives.append({"kind": "subject", "language": "english", "min_level": min_level})
        elif name in LANGUAGE_NAMES:
            alternatives.append({
                "kind": "subject", "language": LANGUAGE_NAMES[name],
                "min_level": min_level, "min_level_fal": min_level,
            })
        elif name in SUBJECT_SLUGS:
            alternatives.append({"kind": "subject", "subject": SUBJECT_SLUGS[name], "min_level": min_level})
        else:
            raise ValueError(f"{programme_id}: unknown subject name {name!r} -- add it to SUBJECT_SLUGS/LANGUAGE_NAMES")

    if len(alternatives) == 1:
        return alternatives[0]
    return {"kind": "any", "rules": alternatives}


def _route_primary_subjects(leaf: dict) -> list[tuple[str, int]]:
    """The (subject slug, min_level) pairs a route's elective leaf
    represents, for building requires_subject/requires_level score
    entries -- e.g. [("mathematics", 3), ("technical_mathematics", 3)]
    for a "Mathematics / Technical Mathematics" route at level 3. The
    level travels WITH the subject deliberately: qualify.py's
    select_score_threshold must reject a route as "applicable" when the
    subject is present but below the level this specific route actually
    needs (see that module's docstring for the TUT case this closes).
    English and language leaves never gate the score threshold in this
    source (every route's aps_min sits alongside, not keyed to, the
    language leaf), so only non-language SUBJECT_SLUGS names count here."""
    if "subject" not in leaf:
        return []
    return [(SUBJECT_SLUGS[n], leaf["min_level"]) for n in leaf["subject"] if n in SUBJECT_SLUGS]


def convert_route(route: dict, report: dict, programme_id: str) -> tuple[list[dict], int | None, list[tuple[str, int]]]:
    """One route ("all" of leaves, possibly labelled) -> (subject rules
    for this route excluding aps_min/nsc_year_min, this route's aps_min,
    the (subject, min_level) pairs this route's score threshold should
    key on)."""
    leaves = route["all"] if "all" in route else [route]
    rules: list[dict] = []
    aps_min: int | None = None
    primary_subjects: list[tuple[str, int]] = []
    for leaf in leaves:
        if "aps_min" in leaf:
            aps_min = leaf["aps_min"]
            continue
        if "nsc_year_min" in leaf:
            report["dropped_nsc_year_leaves"].append(programme_id)
            continue
        rule = _leaf_to_rule(leaf, report, programme_id)
        if rule is not None:
            rules.append(rule)
            primary_subjects.extend(_route_primary_subjects(leaf))
    return rules, aps_min, primary_subjects


def convert_programme(p: dict, report: dict) -> dict:
    campus = [p["main_campus"], *p.get("other_campuses", [])]
    selection_notes = list(p.get("notes", []))
    if p.get("closing_date"):
        selection_notes.append(f"Applications close {p['closing_date']}.")

    base = {
        "institution_id": INSTITUTION_ID,
        "academic_year": ACADEMIC_YEAR,
        "qualification_code": p["id"],
        "name": p["name"],
        "faculty": p.get("faculty"),
        "campus": campus,
        "duration_years": p.get("duration_years"),
        "extended": bool(p.get("is_extended", False)),
        "selection_notes": selection_notes,
        "career_text": p.get("careers") or None,
        "source_doc": "tut_2027_first_year_brochure",
        "source_page": None,
        "confidence": "extracted",
        "scoring_override": None,
        "scoring_strategy_override": None,
    }

    if not p.get("matric_evaluable", True):
        report["unscoreable"].append(p["id"])
        return {
            **base,
            "scoreable": False,
            "requirements": {"nsc": {"score": [], "subjects": {"kind": "all", "rules": []}, "excluded_subjects": []}},
        }

    routes = _routes_of(p["requirements"])
    score_entries: list[dict] = []
    subject_any_branches: list[dict] = []
    for route in routes:
        rules, aps_min, primary_subjects = convert_route(route, report, p["id"])
        # Every route always requires the global English floor, in
        # addition to whatever else it lists -- see module docstring.
        rules = [{"kind": "subject", "language": "english", "min_level": GLOBAL_ENGLISH_MIN_LEVEL}, *rules]
        branch = rules[0] if len(rules) == 1 else {"kind": "all", "rules": rules}
        subject_any_branches.append(branch)

        if aps_min is None:
            continue
        if primary_subjects:
            for subj, min_level in primary_subjects:
                score_entries.append({"min_score": aps_min, "requires_subject": subj, "requires_level": min_level})
        else:
            score_entries.append({"min_score": aps_min})

    subjects_tree = subject_any_branches[0] if len(subject_any_branches) == 1 else {
        "kind": "any", "rules": subject_any_branches,
    }

    return {
        **base,
        "scoreable": True,
        "requirements": {
            "nsc": {"score": score_entries, "subjects": subjects_tree, "excluded_subjects": []},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Convert and report, write nothing.")
    args = parser.parse_args()

    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    report: dict[str, list] = {
        "unscoreable": [], "dropped_token_leaves": [], "dropped_count_leaves": [], "dropped_nsc_year_leaves": [],
    }

    converted = [convert_programme(p, report) for p in source["programmes"]]

    print(f"Converted {len(converted)} TUT programmes.")
    print(f"  scoreable=false (not matric_evaluable): {len(report['unscoreable'])} -- {report['unscoreable']}")
    print(f"  routes with a dropped @-token leaf: {len(report['dropped_token_leaves'])}")
    for pid, names in report["dropped_token_leaves"]:
        print(f"    {pid}: {names}")
    print(f"  routes with a dropped count>1 leaf: {len(report['dropped_count_leaves'])}")
    for pid, names, count in report["dropped_count_leaves"]:
        print(f"    {pid}: {names} (count={count})")
    print(f"  dropped nsc_year_min leaves: {len(report['dropped_nsc_year_leaves'])} -- {report['dropped_nsc_year_leaves']}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    data = json.loads(PROGRAMMES_PATH.read_text(encoding="utf-8"))
    data["institutions"] = [i for i in data["institutions"] if i["id"] != INSTITUTION_ID] + [{
        "id": INSTITUTION_ID,
        "name": source["institution"]["name"],
        "scoring_strategy": "aps_best6_excl_lo",
        "scoring_config": {"subject_count": 6, "exclude_subjects": ["life_orientation"], "zero_below_level": 2},
    }]
    data["programmes"] = [p for p in data["programmes"] if p["institution_id"] != INSTITUTION_ID] + converted
    PROGRAMMES_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {PROGRAMMES_PATH}")

    seeds = json.loads(INSTITUTIONS_SEED_PATH.read_text(encoding="utf-8"))
    seeds = [i for i in seeds if i["id"] != INSTITUTION_ID] + [{
        "id": INSTITUTION_ID,
        "name": source["institution"]["name"],
        "scoring_strategy": "aps_best6_excl_lo",
        "scoring_config": {"subject_count": 6, "exclude_subjects": ["life_orientation"], "zero_below_level": 2},
    }]
    INSTITUTIONS_SEED_PATH.write_text(json.dumps(seeds, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {INSTITUTIONS_SEED_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
