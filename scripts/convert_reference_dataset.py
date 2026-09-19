"""Converts a `<code>_2027_programmes.json` reference dataset (supplied
directly, not authored through this repo's normal bundle/seeds pipeline)
into the shape api/src/app/data/programmes.json already holds, and merges
it in.

WHY THIS SCRIPT EXISTS, NOT THE NORMAL PIPELINE
-------------------------------------------------
The normal path (docs/BUNDLE_FORMAT.md -> ingest_bundle.py -> Postgres ->
export_data.py) assumes a reachable DATABASE_URL. These sources arrive as
complete, already-structured JSON files sharing one schema (see
universities/2027/qualify.py, their own reference evaluator, for the
authoritative shape) -- not flat per-cell bundles a human transcribed
against seeds/bundle.schema.json. This script transliterates that shared
tree shape into this repo's requirements.nsc.{score,subjects,
excluded_subjects} shape directly.

Started as scripts/convert_tut_reference.py (TUT only); generalised the
moment a second institution (VUT) arrived using the same schema but with
real differences -- an 8-point achievement scale instead of the standard
1-7 one, and a min_percent leaf shape TUT never used. Everything
institution-specific is now DERIVED FROM the source file's own `scoring`
and `global_requirements` blocks wherever possible (see
derive_scoring_config, the global-requirement leaves folded into every
route) rather than hardcoded per institution -- only the subject-name ->
slug table and the small per-institution registry below (source filename,
source_doc label) are hand-maintained, because those genuinely can't be
derived from the data itself.

CONFIDENCE: every converted programme is stamped "extracted", never
"verified" -- nobody has cross-checked this conversion's output against a
cited page of the institution's actual brochure the way
scripts/validate_data.py's semantic checks or a human review normally
would.

KNOWN, DELIBERATE GAPS (see docs/scoring/{institution}.md for the exact
account per institution):
  1. The NSC Bachelor's/Diploma "endorsement" requirement
     (global_requirements.endorsement_by_qualification_type, plus any
     programme's own stricter version) needs "N distinct free-choice
     subjects at level >= X" -- a rule kind evaluator.py does not have.
     Dropped uniformly; every other condition on every route is still
     checked exactly.
  2. @-token leaves used as a route's OWN elective (not the endorsement)
     -- @HOME_LANGUAGE / @FIRST_ADDITIONAL_LANGUAGE / @OTHER_HOME_LANGUAGE
     / @ADDITIONAL_LANGUAGE / @ANY_SUBJECT -- are dropped for the same
     reason. Listed in this script's own report output every time it runs.
  3. nsc_year_min leaves are dropped as always-true for any real 2027
     applicant -- the API collects no NSC-year input to check them
     against regardless.
  4. Bare language-name leaves (e.g. "Sepedi", meaning "any level of this
     language") are encoded as a single min_level applied to BOTH the
     Home Language and First Additional Language variant -- Second
     Additional Language has no slug in the Subject enum at all.
  5. Per-programme closing dates and application-fee/contact metadata are
     not represented in this repo's programme schema; closing dates are
     folded into selection_notes as plain text instead of dropped.

Usage: uv run python scripts/convert_reference_dataset.py <institution_id> [--dry-run]
Example: uv run python scripts/convert_reference_dataset.py vut
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "universities" / "2027"
PROGRAMMES_PATH = ROOT / "api" / "src" / "app" / "data" / "programmes.json"
INSTITUTIONS_SEED_PATH = ROOT / "seeds" / "institutions.json"

# The one thing genuinely not derivable from the source file itself.
REGISTRY: dict[str, dict[str, str]] = {
    "tut": {
        "source_file": "tut_2027_programmes.json",
        "source_doc": "tut_2027_first_year_brochure",
    },
    "vut": {
        "source_file": "vut_2027_programmes.json",
        "source_doc": "vut_2027_undergraduate_minimum_admission_requirements",
    },
}

ACADEMIC_YEAR = 2027

_STANDARD_NSC_BANDS = [
    {"level": 7, "min": 80, "max": 100}, {"level": 6, "min": 70, "max": 79},
    {"level": 5, "min": 60, "max": 69}, {"level": 4, "min": 50, "max": 59},
    {"level": 3, "min": 40, "max": 49}, {"level": 2, "min": 30, "max": 39},
    {"level": 1, "min": 0, "max": 29},
]

# Subject names -> this repo's Subject enum slugs. Shared across every
# institution using this schema -- SA universities largely name subjects
# the same way. Grows as new institutions bring new subjects; never
# renamed, per subjects.py's own "add only" rule.
SUBJECT_SLUGS: dict[str, str] = {
    "Accounting": "accounting",
    "Agricultural Sciences": "agricultural_sciences",
    "Agricultural Technology": "agricultural_technology",
    "Business Studies": "business_studies",
    "Catering": "catering",
    "Civil Technology": "civil_technology",
    "Consumer Studies": "consumer_studies",
    "Economics": "economics",
    "Electrical Technology": "electrical_technology",
    "Engineering Graphics and Design": "engineering_graphics_and_design",
    "Engineering Mathematics N3": "engineering_mathematics_n3",
    "Engineering Mathematics N4": "engineering_mathematics_n4",
    "Engineering Science N4": "engineering_science_n4",
    "Geography": "geography",
    "History": "history",
    "Hospitality Studies": "hospitality_studies",
    "Hotel": "hotel",
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

# Bare language names ("any level of this language") -> the language
# family key evaluator.py's LANGUAGE_FAMILIES uses.
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


def _level_from_bands(pct: int, bands: list[dict]) -> int:
    for band in bands:
        if band["min"] <= pct <= band["max"]:
            return band["level"]
    return 1


def _routes_of(requirements: dict) -> list[dict]:
    return requirements["any"] if "any" in requirements else [requirements]


def _leaf_to_rule(leaf: dict, level_bands: list[dict], report: dict, programme_id: str) -> dict | None:
    """One source leaf -> one evaluator.py rule, or None if this leaf is
    one of the documented, dropped gap cases (see module docstring)."""
    if "subject" not in leaf:
        return None
    names = leaf["subject"]
    if any(n in DROPPED_TOKENS for n in names):
        report["dropped_token_leaves"].append((programme_id, names))
        return None
    if leaf.get("count", 1) > 1:
        report["dropped_count_leaves"].append((programme_id, names, leaf["count"]))
        return None

    min_level = leaf["min_level"] if "min_level" in leaf else _level_from_bands(leaf["min_percent"], level_bands)
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


def _route_primary_subjects(leaf: dict, level_bands: list[dict]) -> list[tuple[str, int]]:
    """The (subject slug, min_level) pairs a route's elective leaf
    represents, for building requires_subject/requires_level score
    entries. Language leaves never gate the score threshold in this
    source (every route's aps_min sits alongside, not keyed to, the
    language leaf), so only non-language SUBJECT_SLUGS names count here."""
    if "subject" not in leaf:
        return []
    min_level = leaf["min_level"] if "min_level" in leaf else _level_from_bands(leaf["min_percent"], level_bands)
    return [(SUBJECT_SLUGS[n], min_level) for n in leaf["subject"] if n in SUBJECT_SLUGS]


def convert_route(route: dict, level_bands: list[dict], report: dict, programme_id: str) -> tuple[list[dict], int | None, list[tuple[str, int]]]:
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
        rule = _leaf_to_rule(leaf, level_bands, report, programme_id)
        if rule is not None:
            rules.append(rule)
            primary_subjects.extend(_route_primary_subjects(leaf, level_bands))
    return rules, aps_min, primary_subjects


def derive_scoring_config(source: dict) -> dict:
    aps_cfg = source["scoring"]["aps"]
    config: dict = {
        "subject_count": aps_cfg["subject_count"],
        "exclude_subjects": ["life_orientation"],
    }
    if aps_cfg.get("zero_below_level"):
        config["zero_below_level"] = aps_cfg["zero_below_level"]
    bands = source["scoring"]["level_bands"]
    if sorted(bands, key=lambda b: b["level"]) != sorted(_STANDARD_NSC_BANDS, key=lambda b: b["level"]):
        config["level_bands"] = bands
    return config


def convert_programme(p: dict, global_rules: list[dict], level_bands: list[dict], institution_id: str, source_doc: str, report: dict) -> dict:
    campus = [c for c in [p.get("main_campus"), *p.get("other_campuses", [])] if c]
    selection_notes = list(p.get("notes", []))
    if p.get("closing_date"):
        selection_notes.append(f"Applications close {p['closing_date']}.")

    base = {
        "institution_id": institution_id,
        "academic_year": ACADEMIC_YEAR,
        "qualification_code": p["id"],
        "name": p["name"],
        "faculty": p.get("faculty"),
        "campus": campus,
        "duration_years": p.get("duration_years"),
        "extended": bool(p.get("is_extended", False)),
        "selection_notes": selection_notes,
        "career_text": p.get("careers") or None,
        "source_doc": source_doc,
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
        rules, aps_min, primary_subjects = convert_route(route, level_bands, report, p["id"])
        rules = [*global_rules, *rules]
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
    parser.add_argument("institution_id", choices=sorted(REGISTRY))
    parser.add_argument("--dry-run", action="store_true", help="Convert and report, write nothing.")
    args = parser.parse_args()

    entry = REGISTRY[args.institution_id]
    source = json.loads((SOURCE_DIR / entry["source_file"]).read_text(encoding="utf-8"))
    level_bands = source["scoring"]["level_bands"]

    report: dict[str, list] = {
        "unscoreable": [], "dropped_token_leaves": [], "dropped_count_leaves": [], "dropped_nsc_year_leaves": [],
    }
    global_rules = []
    for leaf in source["global_requirements"].get("all_programmes", []):
        rule = _leaf_to_rule(leaf, level_bands, report, "<global_requirements.all_programmes>")
        if rule is not None:
            global_rules.append(rule)

    converted = [
        convert_programme(p, global_rules, level_bands, args.institution_id, entry["source_doc"], report)
        for p in source["programmes"]
    ]

    print(f"Converted {len(converted)} {args.institution_id.upper()} programmes.")
    print(f"  global rule(s) applied to every route: {global_rules}")
    print(f"  scoreable=false (not matric_evaluable): {len(report['unscoreable'])} -- {report['unscoreable']}")
    print(f"  routes with a dropped @-token leaf: {len(report['dropped_token_leaves'])}")
    for pid, names in report["dropped_token_leaves"]:
        print(f"    {pid}: {names}")
    print(f"  routes with a dropped count>1 leaf: {len(report['dropped_count_leaves'])}")
    for pid, names, count in report["dropped_count_leaves"]:
        print(f"    {pid}: {names} (count={count})")
    print(f"  dropped nsc_year_min leaves: {len(report['dropped_nsc_year_leaves'])} -- {report['dropped_nsc_year_leaves']}")

    scoring_config = derive_scoring_config(source)
    print(f"  derived scoring_config: {json.dumps(scoring_config)}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    institution_entry = {
        "id": args.institution_id,
        "name": source["institution"]["name"],
        "scoring_strategy": "aps_best6_excl_lo",
        "scoring_config": scoring_config,
    }

    data = json.loads(PROGRAMMES_PATH.read_text(encoding="utf-8"))
    data["institutions"] = [i for i in data["institutions"] if i["id"] != args.institution_id] + [institution_entry]
    data["programmes"] = [p for p in data["programmes"] if p["institution_id"] != args.institution_id] + converted
    PROGRAMMES_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {PROGRAMMES_PATH}")

    seeds = json.loads(INSTITUTIONS_SEED_PATH.read_text(encoding="utf-8"))
    seeds = [i for i in seeds if i["id"] != args.institution_id] + [institution_entry]
    INSTITUTIONS_SEED_PATH.write_text(json.dumps(seeds, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {INSTITUTIONS_SEED_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
