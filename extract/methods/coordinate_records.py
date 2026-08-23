"""Converts Method D's raw, overlaid row shape (extract/methods/
coordinate.py's extract_raw_rows/apply_overlay output) into the
project's Programme shape -- the same requirements.nsc.{score,subjects,
excluded_subjects} contract Methods A and B emit. The reference script
(universities/uj_extract.py) exports its OWN flat shape; this module is
the phase-8.5-mandated translation layer, never a drop-in of that shape.

Subject-tree assembly reuses extract/methods/shared.py's CellValue /
build_subject_tree wherever possible (mutually-exclusive-subject
grouping and alternative/OR-cell pairing are ALREADY implemented and
tested there -- see shared.py's own docstring -- so this module bridges
into that machinery instead of reimplementing it) and only builds a node
directly for the two shapes shared.py's CellValue model can't express at
all: a Home/First-Additional-Language band (two levels in one cell) and
an "any recognised additional language" column.
"""

from pathlib import Path
from typing import Any
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import CellValue, build_subject_tree  # noqa: E402


class _NotAccepted:
    """Sentinel distinguishing 'Not accepted' (the subject is excluded)
    from None ('Not applicable' / absent -- nothing at all). Defined here
    (not in coordinate.py) so both modules can import it without a
    circular dependency -- coordinate.py's parse_rating() produces it,
    this module consumes it. See coordinate.py's module docstring for
    the schema-gap rationale (B34CAQ vs B2I02Q)."""

    def __repr__(self) -> str:
        return "NOT_ACCEPTED"


NOT_ACCEPTED = _NotAccepted()

# raw header_map key -> canonical Subject enum value (see
# extract/institutions/registry.json's uj.layout.header_map). Plural
# forms (technical_sciences, physical_sciences) match the Subject enum
# even though the reference script's own raw keys are singular/mixed.
_SUBJECT_RAW_KEYS = {
    "mathematics": "mathematics",
    "mathematical_literacy": "mathematical_literacy",
    "technical_mathematics": "technical_mathematics",
    "technical_science": "technical_sciences",
    "life_sciences": "life_sciences",
    "physical_science": "physical_sciences",
    "geography": "geography",
}

# raw header_map key -> language-family slug (shared.py's LANGUAGE_FAMILIES).
_LANGUAGE_RAW_KEYS = {
    "english": "english",
    "afrikaans": "afrikaans",
    "isizulu": "isizulu",
    "sepedi": "sepedi",
}

_SCORE_SUBJECT_MAP = {
    "with_mathematics": "mathematics",
    "with_technical_mathematics": "technical_mathematics",
    "with_mathematical_literacy": "mathematical_literacy",
}


def _build_subjects_and_exclusions(
    requirements: dict, alternative_keys: set[str], profile: dict,
) -> tuple[dict, set[str]]:
    """Returns (subjects_tree, excluded_subjects). Bridges plain-level and
    alternative-marked cells through shared.build_subject_tree (reusing
    its mutual-exclusion grouping and alternative-cell pairing verbatim);
    banded-language and any-additional-language cells build their own
    node directly, since shared.py's CellValue has no shape for either.

    alternative_keys are raw keys whose HEADER carried a standalone "OR"
    marker column immediately before it (e.g. UJ page 60's 'Physical
    Science' / 'OR' / 'Technical Science' three separate header columns
    -- see coordinate.py's merge_header_rows) -- such a key's cell is fed
    through as CellValue(kind="alternative") instead of "level", so
    shared.build_subject_tree pairs it with whichever key immediately
    precedes it into an `any` node, the same convention Methods A/B use
    for this exact marker."""
    extra_nodes: list[dict] = []
    excluded: set[str] = set()
    bridge_cells: list[tuple[str, CellValue]] = []

    for key, value in requirements.items():
        if value is None:
            continue

        if key == "additional_language":
            if value is NOT_ACCEPTED:
                continue  # no specific slug to exclude
            if isinstance(value, int):
                extra_nodes.append({"kind": "any_additional_language", "min_level": value})
            continue

        if key in _LANGUAGE_RAW_KEYS:
            slug = _LANGUAGE_RAW_KEYS[key]
            if value is NOT_ACCEPTED:
                excluded.add(slug)
            elif isinstance(value, dict):
                extra_nodes.append({
                    "kind": "subject", "language": slug,
                    "min_level": value["home_language"],
                    "min_level_fal": value["first_additional_language"],
                })
            elif isinstance(value, int):
                bridge_cells.append((slug, CellValue(kind="level", level=value)))
            continue

        if key in ("mathematical_literacy_or_technical_mathematics", "mathematics_or_technical_mathematics"):
            # ONE cell/level shared by two subjects, either satisfying it.
            # NOTE: profile.layout.header_map maps UJ's "Mathematics /
            # Technical Mathematics" column to
            # "mathematics_or_technical_mathematics", NOT the reference
            # script's own bare "mathematics" key -- the reference script
            # never converts to a subject tree at all, so its choice of a
            # single collapsed key was adequate for its own scope but would
            # silently drop the alternative here (confirmed against real
            # data: B6CS0Q/B6CV3Q, phase 8.5's own named hard case).
            #
            # Both members feed in as plain "level" cells, NOT
            # CellValue(kind="alternative") -- both are already members of
            # profile.layout.mutually_exclusive_subjects for UJ (mathematics/
            # mathematical_literacy/technical_mathematics is one national-
            # convention group), so shared.build_subject_tree's own
            # _group_mutually_exclusive flattens them into ONE `any` node
            # regardless of how many group members end up present in this
            # row (2 or 3) -- the same mechanism that already produces
            # B34HRQ's flat three-way `any` from three independent plain
            # columns. Chaining them as level+alternative instead would
            # NEST ("any" wrapping an "any") when a plain "Mathematics"
            # column is ALSO present elsewhere in the same row (confirmed
            # on real Education-faculty data, B5BFPQ: 'Mathematics', 'OR',
            # 'Mathematical Literacy / Technical Mathematics' as three
            # separate header columns) -- a nested shape doesn't compare
            # equal to the flat one at all, even though it is the same
            # every-other-subject-excluded shape group-merging already
            # gets right elsewhere.
            base = "mathematical_literacy" if key.startswith("mathematical_literacy") else "mathematics"
            if value is NOT_ACCEPTED:
                excluded.add(base)
                excluded.add("technical_mathematics")
            elif isinstance(value, int):
                bridge_cells.append((base, CellValue(kind="level", level=value)))
                bridge_cells.append(("technical_mathematics", CellValue(kind="level", level=value)))
            continue

        if key in _SUBJECT_RAW_KEYS:
            slug = _SUBJECT_RAW_KEYS[key]
            if value is NOT_ACCEPTED:
                excluded.add(slug)
            elif isinstance(value, int):
                # Group-membership takes priority over an OR-marker
                # redirect: a subject already covered by
                # mutually_exclusive_subjects is fed in as "level" so
                # _group_mutually_exclusive's flat merge handles it (see
                # the note above) -- "alternative" stays reserved for
                # pairs with NO configured group at all (UJ has none for
                # physical_sciences/technical_sciences, so that pair still
                # goes through the CellValue chain-pairing path).
                in_group = any(slug in group for group in profile["layout"].get("mutually_exclusive_subjects", []))
                kind = "alternative" if (key in alternative_keys and not in_group) else "level"
                bridge_cells.append((slug, CellValue(kind=kind, level=value)))
            continue
        # unrecognised raw key: header_map is a closed vocabulary controlled
        # by the profile; nothing to do for a key outside it.

    tree, tree_excluded = build_subject_tree(bridge_cells, profile)
    tree["rules"] = tree["rules"] + extra_nodes
    excluded |= tree_excluded
    return tree, excluded


def _convert_score(minimum_aps: Any) -> tuple[list[dict] | None, str | None]:
    """Returns (score, note). note is a selection_notes-worthy string only
    for a shape this schema can't express natively -- never silently
    dropped."""
    if minimum_aps is None or isinstance(minimum_aps, str):
        return None, None  # str = unparsed text; validate() already flags it
    if isinstance(minimum_aps, int):
        return [{"min_score": minimum_aps}], None
    if isinstance(minimum_aps, dict):
        if "with_english_rating_5" in minimum_aps:
            # Humanities extended-degree shape: APS depends on the ENGLISH
            # RATING achieved, not on holding a subject -- no
            # requires_subject equivalent exists in this schema. Encode the
            # strictest (highest) printed value unconditionally, per phase
            # 8.5 step 4's policy: under-qualifying a few learners is safer
            # than over-promising.
            value = max(minimum_aps.values())
            note = f"APS depends on English rating (source: {minimum_aps!r}); encoded strictest value {value}."
            return [{"min_score": value}], note
        entries = [
            {"min_score": v, "requires_subject": _SCORE_SUBJECT_MAP[k]}
            for k, v in minimum_aps.items() if k in _SCORE_SUBJECT_MAP
        ]
        return (entries or None), None
    return None, None


def _condition_notes(requirements: dict) -> list[str]:
    """requirements.conditions (footnote conditionals ported from the
    overlay's _cond patches) can't be expressed in the rule tree --
    render each as a selection_notes string so a reviewer sees the raw
    conditional the tree itself only encodes the stricter branch of."""
    conditions = requirements.get("conditions")
    if not conditions:
        return []
    return [f"Conditional requirement (see source page): {subject}={variants!r}"
            for subject, variants in conditions.items()]


def to_programme_records(
    raw_records: list[dict], problems: dict[str, list[str]],
    overlay_applied: dict[str, list[str]], profile: dict,
) -> list[dict]:
    """Converts every raw (overlaid, validated) row into the project's
    Programme shape. Each mapping is exercised individually by
    tests/test_coordinate_records.py."""
    out: list[dict] = []
    for raw in raw_records:
        code = raw["qualification_code"]
        alt_keys = set(raw.get("alternative_keys") or [])
        tree, excluded = _build_subjects_and_exclusions(raw["requirements"], alt_keys, profile)
        excluded |= set(raw.get("excluded_subjects_prose") or [])

        score, score_note = _convert_score(raw["minimum_aps"])
        notes = _condition_notes(raw["requirements"])
        if score_note:
            notes.append(score_note)

        footnotes = raw.get("unresolved_footnotes") or []
        notes.extend(
            f"Footnote {fn['marker']} on {fn['cell_ref']}: {fn['footnote_text']}" for fn in footnotes
        )

        record_problems = problems.get(code, [])
        qual_type = raw.get("qualification_type") or ""

        out.append({
            "qualification_code": code,
            "name": raw["programme"],
            "faculty": raw["faculty"],
            "campus": [raw["campus"]] if raw.get("campus") else [],
            "duration_years": raw["duration_years"],
            "extended": "extended" in qual_type.lower(),
            "requirements": {
                "nsc": {
                    "score": score,
                    "subjects": tree,
                    "excluded_subjects": sorted(excluded),
                },
            },
            "selection_notes": notes,
            "career_text": None,
            "source_page": raw["_page"],
            "confidence": "flagged" if (record_problems or notes) else "extracted",
            "unresolved_footnotes": footnotes,
            "verification": {
                "overlay_applied": overlay_applied.get(code, []),
                "problems": record_problems,
            },
        })
    return out
