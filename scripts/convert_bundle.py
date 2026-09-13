"""Converts a hand-typed FLAT bundle into the seed schema's REQUIREMENT TREES.

WHY THIS MODULE EXISTS
----------------------
A person reading a prospectus table transcribes what the table looks
like: one row, one column per subject, one number per cell.

    {"english": 4, "mathematics": 5, "mathematical_literacy": "not_accepted"}

The API evaluates a recursive rule tree instead, because "Mathematics OR
Mathematical Literacy" and "Mathematics, and Mathematical Literacy is
forbidden" are different shapes, not different values:

    {"nsc": {"score": [...], "subjects": {"kind": "all", "rules": [...]},
             "excluded_subjects": ["mathematical_literacy"]}}

Asking an operator to hand-author trees would mean hand-authoring that
distinction several hundred times. This module derives it instead. See
docs/BUNDLE_FORMAT.md for the input format and a worked example.

"NOT ACCEPTED" IS NOT ABSENCE
-----------------------------
The single most important rule in this file. In the flat shape:

    "mathematical_literacy": "not_accepted"   -> excluded_subjects entry
    "mathematical_literacy": null             -> nothing at all
    (key omitted entirely)                    -> nothing at all

These are OPPOSITE in the target schema and identical to the eye. Both
cases are real and both are in the current dataset: B34CAQ's Mathematical
Literacy is "Not accepted" -- a learner offering it is actively barred --
while B2I02Q's Physical Science is "Not applicable", which bars nobody.
The retired PDF extractor could not tell them apart from the printed page
(several UJ tables render both as a dash) and had to restore the
distinction from a hand-verified overlay. A human transcriber CAN tell
them apart, by reading the sentence under the table -- so the flat format
demands they say which, and this module trusts that answer literally.

MUTUALLY EXCLUSIVE SUBJECTS
---------------------------
Mathematics / Mathematical Literacy / Technical Mathematics is one
national NSC subject-choice group: no South African university requires
two of them, because a learner picks between them in matric and can never
hold two. So two REQUIRED members in the same row always mean `any`, even
when the source table prints no "OR" marker at all (confirmed on B8CD2Q
and the three-way B34HRQ).

_group_mutually_exclusive and build_subject_tree below are ported
unchanged from the retired extract/methods/shared.py rather than
rewritten, together with their tests -- including the two negative
controls that make the rule safe. B34CAQ (Mathematics 5 required,
Mathematical Literacy and Technical Mathematics both "Not accepted") and
B4C01Q (Mathematics 4 required, Mathematical Literacy "Not accepted")
must NOT become `any` nodes. They don't, structurally: an excluded
subject short-circuits into the excluded set and never becomes a node, so
it can never be a second group member for grouping to find. Shared group
membership alone never triggers an `any` -- only two or more group
members that each carry a real level.

The flat-key -> tree mapping and the score conversion are likewise ported
from the retired extract/methods/coordinate_records.py, which was tested
against the full 180-record UJ run.
"""

import argparse
import json
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api" / "src"))

from app.subjects import LANGUAGE_FAMILIES, Subject  # noqa: E402
from validate_data import validate  # noqa: E402

_SUBJECTS = {s.value for s in Subject}

# The literal flat-format value meaning "a learner offering this subject
# is barred". Anything else falsy (null, omitted) means absence.
NOT_ACCEPTED = "not_accepted"

# National NSC subject-choice groups. Not institution-specific: a learner
# picks between these in matric and can never hold two, so two required
# members in one row is always an `any`. Physical Sciences / Technical
# Sciences is deliberately NOT here -- those two CAN be held together,
# and a programme accepting either says so with an explicit
# `physical_sciences_or_technical_sciences` compound key.
MUTUALLY_EXCLUSIVE_SUBJECTS: list[list[str]] = [
    ["mathematics", "mathematical_literacy", "technical_mathematics"],
]

# Prospectus spellings that don't match a Subject enum value directly --
# the enum is plural ("physical_sciences"), most prospectus columns are
# singular ("Physical Science"). Accepting both means a transcriber never
# has to remember which way round it goes.
_SUBJECT_ALIASES: dict[str, str] = {
    "physical_science": "physical_sciences",
    "technical_science": "technical_sciences",
    "life_science": "life_sciences",
    "maths": "mathematics",
    "maths_literacy": "mathematical_literacy",
    "technical_maths": "technical_mathematics",
}

# minimum_aps variant key -> the subject that variant is conditional on.
_SCORE_SUBJECT_MAP = {
    "with_mathematics": "mathematics",
    "with_technical_mathematics": "technical_mathematics",
    "with_mathematical_literacy": "mathematical_literacy",
}

_COMPOUND_SEPARATOR = "_or_"


class BundleError(Exception):
    """A bundle that cannot be converted at all -- an unknown subject key,
    a malformed value. Raised rather than guessed: the whole point of the
    flat format is that the human already knows the answer."""


@dataclass(frozen=True, slots=True)
class CellValue:
    """Ported from extract/methods/shared.py. kind is one of 'level',
    'not_accepted', 'alternative'. 'alternative' pairs the cell with
    whichever cell immediately precedes it into an `any` node."""

    kind: str
    level: int | None = None


def _subject_node(slug: str, level: int) -> dict:
    if slug in LANGUAGE_FAMILIES:
        return {"kind": "subject", "language": slug, "min_level": level}
    return {"kind": "subject", "subject": slug, "min_level": level}


def _group_mutually_exclusive(nodes: list[dict]) -> list[dict]:
    """Ported unchanged from extract/methods/shared.py (which read the
    groups from a per-institution layout profile; they are a national
    convention, so they are a constant here instead).

    When 2+ PLAIN subject nodes from the same group are present -- each
    already carrying its own level from a real level value, not an
    exclusion -- they combine into ONE flat `any` node. A group member
    that was excluded never reaches this function as a node at all, so
    "required X, excluded Y" from the same group is structurally
    unaffected: that is what makes the B34CAQ/B4C01Q negative controls
    hold. Three members merge into one three-way `any`, not two nested
    pairwise ones -- a nested shape doesn't compare equal to the flat one
    even though it means the same thing.

    The one deliberate change from the original: the merged `any` node
    takes the position of the FIRST group member it replaced, where the
    original returned all merged nodes ahead of everything else. Hoisting
    was harmless when the caller was a PDF column scan, but here it would
    reorder the rules of every existing hand-verified seed record (moving
    the maths `any` in front of English) for no gain."""
    result = list(nodes)
    for group in MUTUALLY_EXCLUSIVE_SUBJECTS:
        group_set = set(group)
        matched = [n for n in result if n.get("kind") == "subject" and n.get("subject") in group_set]
        if len(matched) < 2:
            continue
        at = result.index(matched[0])
        for node in matched:
            result.remove(node)
        result.insert(at, {"kind": "any", "rules": matched})
    return result


def build_subject_tree(row: list[tuple[str, CellValue]]) -> tuple[dict, set[str]]:
    """Ported unchanged from extract/methods/shared.py. row is the ordered
    (slug, CellValue) pairs for one programme, in the order the flat
    record lists them. Order matters: an 'alternative' cell pairs with
    whichever cell immediately precedes it. Returns (rule_tree,
    excluded_subjects)."""
    excluded: set[str] = set()
    nodes: list[dict] = []

    for slug, cell in row:
        if cell.kind == "not_accepted":
            excluded.add(slug)
        elif cell.kind == "level":
            nodes.append(_subject_node(slug, cell.level))
        elif cell.kind == "alternative":
            alt_node = _subject_node(slug, cell.level)
            if nodes:
                preceding = nodes.pop()
                nodes.append({"kind": "any", "rules": [preceding, alt_node]})
            else:
                nodes.append(alt_node)

    return {"kind": "all", "rules": _group_mutually_exclusive(nodes)}, excluded


def _resolve_slug(key: str) -> str:
    """Flat requirement key -> canonical Subject value or language family.
    A closed vocabulary: an unrecognised key raises rather than being
    dropped, because silently ignoring a column the transcriber typed
    loses a real requirement."""
    slug = _SUBJECT_ALIASES.get(key, key)
    if slug in _SUBJECTS or slug in LANGUAGE_FAMILIES:
        return slug
    raise BundleError(f"unknown subject key '{key}'")


def _split_compound(key: str) -> list[str] | None:
    """'physical_sciences_or_technical_sciences' -> both slugs. Returns
    None for a plain key. No Subject value contains '_or_', so splitting
    on it is unambiguous."""
    if _COMPOUND_SEPARATOR not in key:
        return None
    return [_resolve_slug(part) for part in key.split(_COMPOUND_SEPARATOR)]


def _in_one_group(slugs: list[str]) -> bool:
    return any(set(slugs) <= set(group) for group in MUTUALLY_EXCLUSIVE_SUBJECTS)


def _level(value: Any, key: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 7:
        raise BundleError(f"{key}: expected an achievement level 1-7 or {NOT_ACCEPTED!r}, got {value!r}")
    return value


def build_requirements(flat: dict, extra_excluded: list[str] | None = None) -> tuple[dict, list[str]]:
    """Flat requirements dict -> (subjects_tree, sorted excluded_subjects).

    Cells feed through build_subject_tree in the order the flat record
    lists them, so a compound key's two members stay adjacent and pair
    correctly. Two node shapes bypass it because CellValue cannot express
    them: a banded Home/First-Additional-Language requirement (two levels
    in one cell) and "any recognised additional language"."""
    bridge: list[tuple[str, CellValue]] = []
    banded: list[dict] = []
    additional_language: list[dict] = []
    excluded: set[str] = set(extra_excluded or [])

    for key, value in flat.items():
        if value is None:
            continue

        if key == "additional_language":
            if value != NOT_ACCEPTED:
                additional_language.append(
                    {"kind": "any_additional_language", "min_level": _level(value, key)}
                )
            continue

        compound = _split_compound(key)
        if compound is not None:
            if value == NOT_ACCEPTED:
                excluded.update(compound)
                continue
            level = _level(value, key)
            if _in_one_group(compound):
                # Both members are already in one mutual-exclusion group,
                # so feed them as plain levels and let grouping flatten
                # them. Chaining as level+alternative instead would NEST
                # an `any` inside an `any` whenever a third group member
                # appears elsewhere in the same record (B5BFPQ's shape).
                bridge.extend((slug, CellValue(kind="level", level=level)) for slug in compound)
            else:
                # No configured group (physical/technical sciences): pair
                # them explicitly via the alternative-cell chain.
                bridge.append((compound[0], CellValue(kind="level", level=level)))
                bridge.extend(
                    (slug, CellValue(kind="alternative", level=level)) for slug in compound[1:]
                )
            continue

        slug = _resolve_slug(key)

        if value == NOT_ACCEPTED:
            excluded.add(slug)
            continue

        if isinstance(value, dict):
            if slug not in LANGUAGE_FAMILIES:
                raise BundleError(f"{key}: only a language family can carry a home/additional band")
            banded.append({
                "kind": "subject", "language": slug,
                "min_level": _level(value["home_language"], key),
                "min_level_fal": _level(value["first_additional_language"], key),
            })
            continue

        bridge.append((slug, CellValue(kind="level", level=_level(value, key))))

    tree, tree_excluded = build_subject_tree(bridge)
    # any_additional_language goes LAST unconditionally. evaluate() threads
    # "which language family already satisfied a rule" left to right
    # through an `all` node, so a named language rule must be evaluated
    # before the any-additional rule or the same language counts twice.
    tree["rules"] = banded + tree["rules"] + additional_language
    return tree, sorted(excluded | tree_excluded)


def build_score(minimum_aps: Any) -> tuple[list[dict], list[str]]:
    """Flat minimum_aps -> (score thresholds, notes). Ported from the
    retired coordinate_records._convert_score."""
    if isinstance(minimum_aps, int) and not isinstance(minimum_aps, bool):
        return [{"min_score": minimum_aps}], []

    if isinstance(minimum_aps, dict):
        if "with_english_rating_5" in minimum_aps:
            # The APS depends on the ENGLISH RATING achieved, not on
            # holding a subject, and the schema has no requires_subject
            # equivalent for that. Encode the strictest printed value
            # unconditionally: under-qualifying a few learners is safer
            # than over-promising, and the raw shape goes to a note so a
            # reviewer can see what was collapsed.
            value = max(v for v in minimum_aps.values() if isinstance(v, int))
            note = f"APS depends on English rating (source: {minimum_aps!r}); encoded strictest value {value}."
            return [{"min_score": value}], [note]

        unknown = set(minimum_aps) - set(_SCORE_SUBJECT_MAP)
        if unknown:
            raise BundleError(f"minimum_aps: unknown variant key(s) {sorted(unknown)}")
        return (
            [{"min_score": v, "requires_subject": _SCORE_SUBJECT_MAP[k]} for k, v in minimum_aps.items()],
            [],
        )

    raise BundleError(f"minimum_aps: expected an integer or a variant object, got {minimum_aps!r}")


def convert_record(flat: dict, institution_id: str, academic_year: int, source: dict) -> dict:
    """One flat programme record -> one seed programme record."""
    code = flat.get("qualification_code")
    if not code:
        raise BundleError("record is missing qualification_code")

    tree, excluded = build_requirements(flat.get("requirements") or {}, flat.get("excluded_subjects"))
    score, notes = build_score(flat.get("minimum_aps"))
    notes = list(flat.get("selection_notes") or []) + notes

    qualification_type = flat.get("qualification_type") or ""
    return {
        "institution_id": institution_id,
        "academic_year": academic_year,
        "qualification_code": code,
        "name": flat["name"],
        "faculty": flat.get("faculty"),
        "campus": flat.get("campus") or [],
        "duration_years": flat.get("duration_years"),
        "extended": bool(flat.get("extended", "extended" in qualification_type.lower())),
        "requirements": {"nsc": {"score": score, "subjects": tree, "excluded_subjects": excluded}},
        "selection_notes": notes,
        "career_text": flat.get("career_text"),
        "source_doc": source.get("document"),
        "source_page": flat.get("source_page"),
        "confidence": flat.get("confidence", "extracted"),
        "scoring_override": flat.get("scoring_override"),
        "scoring_strategy_override": flat.get("scoring_strategy_override"),
        "scoreable": flat.get("scoreable", True),
    }


def convert_bundle(bundle: dict) -> tuple[dict, list[dict]]:
    """Returns (institution block, seed programme records)."""
    institution = bundle["institution"]
    year = bundle["academic_year"]
    source = bundle.get("source") or {}
    records = []
    for flat in bundle["programmes"]:
        try:
            records.append(convert_record(flat, institution["id"], year, source))
        except BundleError as exc:
            raise BundleError(f"{flat.get('qualification_code', '?')}: {exc}") from exc
    return institution, records


def _read_bundles(path: Path) -> list[tuple[str, dict]]:
    """A bundle is one JSON file per institution-year; several are
    normally shipped zipped together."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.endswith(".json")]
            return [(n, json.loads(zf.read(n).decode("utf-8"))) for n in sorted(names)]
    return [(path.name, json.loads(path.read_text(encoding="utf-8")))]


def _merge_institutions(new: list[dict], seeds_dir: Path) -> None:
    """Upserts each bundle's institution block into the seeds directory's
    institutions.json, leaving institutions the bundles didn't mention
    alone. Writes into seeds_dir, never unconditionally into the repo's
    own seeds/ -- a --dry-run or a --out pointing at a scratch directory
    must not touch tracked data."""
    path = seeds_dir / "institutions.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    by_id = {i["id"]: i for i in existing}
    for institution in new:
        by_id[institution["id"]] = institution
    path.write_text(
        json.dumps([by_id[k] for k in sorted(by_id)], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("bundle", type=Path, help="a bundle .json, or a .zip of them")
    ap.add_argument("--out", type=Path, default=ROOT / "seeds", help="seeds directory to write into")
    ap.add_argument("--dry-run", action="store_true", help="convert and validate, write nothing")
    args = ap.parse_args()

    institutions: list[dict] = []
    all_records: list[dict] = []
    written: list[Path] = []

    for name, bundle in _read_bundles(args.bundle):
        try:
            institution, records = convert_bundle(bundle)
        except (BundleError, KeyError) as exc:
            print(f"✗ {name}: {exc}")
            return 1
        institutions.append(institution)
        all_records.extend(records)
        out_file = args.out / institution["id"] / f"{institution['id']}_{bundle['academic_year']}.json"
        if not args.dry_run:
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(
                json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        written.append(out_file)
        print(f"  {name}: {len(records)} programmes → {out_file}")

    errs = validate({"institutions": institutions, "programmes": all_records})
    if errs:
        print(f"✗ {len(errs)} validation errors\n" + "\n".join(f"  {e}" for e in errs))
        return 1

    if not args.dry_run:
        _merge_institutions(institutions, args.out)
    print(f"✓ {len(all_records)} programmes across {len(written)} file(s), 0 validation errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
