"""The reverse of convert_bundle.py: tree-shaped programme records ->
flat bundle files.

Two reasons this exists:

1. TEMPLATE GENERATION. Transcribing a new institution is easier with a
   real, already-encoded example open next to the blank prospectus --
   export an institution close to the one you're about to type, and see
   the shape rather than inventing it from docs/BUNDLE_FORMAT.md alone.

2. THE ROUND-TRIP GATE. seeds/ holds 29 hand-verified UJ programme trees.
   Running them through export_bundle.py and straight back through
   convert_bundle.py must reproduce those exact trees --
   tests/test_export_bundle.py is built on exactly that. If a real,
   hand-verified record can't survive the round trip, the flat format is
   missing something the tree format can express, and that is a design
   bug in the FORMAT, not a bug in one record.

WHY THIS IS THE HARDER DIRECTION
----------------------------------
convert_bundle.py's forward mapping is not one-to-one: several different
flat inputs collapse to the same tree (a plain requires_subject entry
that happens to equal min_score vs. one that doesn't; "Not applicable"
and an omitted key both mean nothing at all -- see docs/BUNDLE_FORMAT.md
(a)). Reversing a many-to-one mapping means picking ONE flat shape among
several that would forward-convert to the same tree, and there is no way
to recover information the tree never carried in the first place.

Concretely, this module:

  - Reconstructs a mutually-exclusive `any` node (Mathematics et al) back
    into plain per-subject keys, which convert_bundle.py's own
    auto-grouping will re-merge -- confirmed against the mutually
    exclusive subject groups convert_bundle.py itself declares, not a
    second copy of that list.
  - Reconstructs any OTHER `any` node as one `any_of` block. Only ONE
    such block survives per programme, because the flat format only has
    room for one (see convert_bundle.py's module docstring) -- a tree
    with two independent manual `any` groups cannot be exported and
    raises ExportError rather than silently dropping one.
  - Reconstructs excluded_subjects as `"not_accepted"` values -- the
    correct, sufficient choice: forward-conversion treats a `not_accepted`
    key exactly the same regardless of whether it came from a
    requirements-dict entry or a top-level excluded_subjects list (see
    build_requirements), so which one export_bundle.py picks cannot
    affect the reconverted tree.
  - Refuses (ExportError) any score shape this module cannot reverse
    unambiguously -- notably the English-rating-banded minimum_aps shape
    (build_score's "with_english_rating_5" branch), which is intentionally
    LOSSY going forward (it collapses several printed numbers to the one
    strictest value plus a note) and therefore has no single correct flat
    shape to reconstruct. No seed record uses this shape today.

A record this module cannot reverse is reported and skipped, never
guessed at -- exporting is a convenience tool and a test harness, not
something anything downstream depends on for correctness.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from convert_bundle import MUTUALLY_EXCLUSIVE_SUBJECTS, _SCORE_SUBJECT_MAP, NOT_ACCEPTED  # noqa: E402
from seed_loader import load  # noqa: E402

_REVERSE_SCORE_MAP = {v: k for k, v in _SCORE_SUBJECT_MAP.items()}


class ExportError(Exception):
    """A record's tree shape cannot be reversed unambiguously into the
    flat format. Reported and skipped, never guessed at."""


def _unflatten_subject_node(node: dict, flat: dict) -> None:
    if "language" in node:
        if "min_level_fal" in node:
            flat[node["language"]] = {
                "home_language": node["min_level"],
                "first_additional_language": node["min_level_fal"],
            }
        else:
            flat[node["language"]] = node["min_level"]
        return
    flat[node["subject"]] = node["min_level"]


def _is_auto_group(subjects: set[str]) -> bool:
    return any(subjects <= set(group) for group in MUTUALLY_EXCLUSIVE_SUBJECTS)


def _unflatten_any_node(node: dict, flat: dict) -> None:
    children = node.get("rules", [])
    if not all(c.get("kind") == "subject" and "subject" in c for c in children):
        raise ExportError(f"any node with a non-plain-subject child can't be reversed: {node!r}")

    subjects = {c["subject"] for c in children}
    if _is_auto_group(subjects):
        # convert_bundle.py's own auto-grouping will re-merge these --
        # writing them as plain keys is not a workaround, it's the
        # correct flat shape (see docs/BUNDLE_FORMAT.md (b)).
        for child in children:
            flat[child["subject"]] = child["min_level"]
        return

    if "any_of" in flat:
        raise ExportError("more than one manual `any` group in one record -- any_of supports only one")
    flat["any_of"] = [{c["subject"]: c["min_level"]} for c in children]


def unflatten_requirements(nsc: dict) -> dict:
    """Tree-shaped requirements.nsc -> a flat requirements dict that
    convert_bundle.build_requirements() will convert back to the same
    tree. Raises ExportError for any shape it can't reverse."""
    tree = nsc["subjects"]
    if tree.get("kind") != "all":
        raise ExportError(f"top-level subjects node must be 'all', got {tree.get('kind')!r}")

    flat: dict[str, Any] = {}
    for node in tree.get("rules", []):
        kind = node.get("kind")
        if kind == "subject":
            _unflatten_subject_node(node, flat)
        elif kind == "any":
            _unflatten_any_node(node, flat)
        elif kind == "any_additional_language":
            flat["additional_language"] = node["min_level"]
        else:
            raise ExportError(f"unrecognised or unsupported rule kind: {kind!r}")

    for slug in nsc.get("excluded_subjects") or []:
        if slug in flat and flat[slug] != NOT_ACCEPTED:
            raise ExportError(f"{slug!r} is both a required subject and excluded -- contradictory tree")
        flat[slug] = NOT_ACCEPTED

    return flat


def unflatten_score(score: list[dict]) -> Any:
    """score thresholds -> a minimum_aps value build_score() will convert
    back to the same thresholds. Raises ExportError for the
    English-rating-banded shape, which build_score() cannot reverse
    (see the module docstring)."""
    if not score:
        raise ExportError("empty score list")
    if len(score) == 1 and "requires_subject" not in score[0]:
        return score[0]["min_score"]

    variants: dict[str, int] = {}
    for entry in score:
        subject = entry.get("requires_subject")
        if subject not in _REVERSE_SCORE_MAP:
            raise ExportError(f"score entry can't be reversed: {entry!r}")
        variants[_REVERSE_SCORE_MAP[subject]] = entry["min_score"]
    return variants


def unflatten_programme(programme: dict) -> dict:
    """One seed-shaped programme record -> one flat bundle record."""
    nsc = programme["requirements"]["nsc"]
    flat: dict[str, Any] = {
        "qualification_code": programme["qualification_code"],
        "programme": programme["name"],
        "duration_years": programme.get("duration_years"),
        "minimum_aps": unflatten_score(nsc["score"]),
        "requirements": unflatten_requirements(nsc),
    }
    if programme.get("faculty") is not None:
        flat["faculty"] = programme["faculty"]
    if programme.get("campus"):
        flat["campus"] = programme["campus"]
    if programme.get("source_page") is not None:
        flat["source_page"] = programme["source_page"]
    if programme.get("extended"):
        flat["extended"] = True
    if programme.get("career_text") is not None:
        flat["career_text"] = programme["career_text"]
    if programme.get("selection_notes"):
        flat["selection_notes"] = programme["selection_notes"]
    if programme.get("scoring_override"):
        flat["scoring_override"] = programme["scoring_override"]
    if programme.get("scoring_strategy_override"):
        flat["scoring_strategy_override"] = programme["scoring_strategy_override"]
    if not programme.get("scoreable", True):
        flat["scoreable"] = False
    # confidence is deliberately never written -- see docs/BUNDLE_FORMAT.md
    # "Confidence is never yours to set": a bundle produced by this tool
    # is meant to be re-ingested, not to smuggle a review status back in.
    return flat


def export_institution(institution: dict, programmes: list[dict]) -> tuple[dict, list[str]]:
    """Returns (bundle, skipped_codes). A record whose tree this module
    cannot reverse is skipped and named, never silently dropped."""
    source_docs = {p.get("source_doc") for p in programmes if p.get("source_doc")}
    source = {"document": next(iter(source_docs))} if len(source_docs) == 1 else {}

    flat_programmes = []
    skipped = []
    for p in sorted(programmes, key=lambda p: p["qualification_code"]):
        try:
            flat_programmes.append(unflatten_programme(p))
        except ExportError as exc:
            skipped.append(f"{p['qualification_code']}: {exc}")

    years = {p["academic_year"] for p in programmes}
    bundle = {
        "institution": {
            "id": institution["id"],
            "name": institution["name"],
            "scoring_strategy": institution["scoring_strategy"],
            "scoring_config": institution.get("scoring_config") or {},
        },
        "academic_year": next(iter(years)) if len(years) == 1 else sorted(years)[0],
        "source": source,
        "programmes": flat_programmes,
    }
    return bundle, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--institution", default=None, help="restrict to this institution_id (default: all in seeds/)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "bundle_exports", help="output directory")
    args = ap.parse_args()

    data = load()
    institutions = {i["id"]: i for i in data["institutions"]}
    by_institution: dict[str, list[dict]] = {}
    for p in data["programmes"]:
        by_institution.setdefault(p["institution_id"], []).append(p)

    ids = [args.institution] if args.institution else sorted(by_institution)
    args.out.mkdir(parents=True, exist_ok=True)

    total_written = 0
    for institution_id in ids:
        if institution_id not in institutions:
            print(f"✗ no institution {institution_id!r} in seeds/institutions.json")
            return 1
        programmes = by_institution.get(institution_id, [])
        if not programmes:
            print(f"  {institution_id}: 0 seed programmes, nothing to export")
            continue

        bundle, skipped = export_institution(institutions[institution_id], programmes)
        out_file = args.out / f"{institution_id}_{bundle['academic_year']}.json"
        out_file.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        total_written += len(bundle["programmes"])
        print(f"  {institution_id}: {len(bundle['programmes'])}/{len(programmes)} programmes → {out_file}")
        for s in skipped:
            print(f"    skipped: {s}")

    print(f"✓ {total_written} programmes exported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
