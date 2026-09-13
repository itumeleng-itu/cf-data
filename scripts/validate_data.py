"""Structural and semantic validation of an exported/seed programme dataset.

Two layers, both report-only:

STRUCTURAL (walk/validate) -- is the requirement tree well-formed? Unknown
subject slugs, empty all/any nodes, levels outside 1-7, a subject node
that sets both `subject` and `language`.

SEMANTIC (_semantic_errors) -- is the tree well-formed AND still wrong?
These are ported from the retired PDF-extraction pipeline
(extract/methods/coordinate.py's validate()), where they were written
against real transposition and column-swap failures. They matter just as
much for hand-produced JSON, because a human transcribing a prospectus
table makes the same class of mistake a misaligned column grid does: the
hand-built dataset we checked had D2ACXQ and D2BTEQ carrying each other's
APS values, across two revisions. Schema validation passes that happily
-- both are integers, both in range, both in the right field. Only a
semantic check that knows what the numbers MEAN catches it.

Validators REPORT; they never repair. This is carried across verbatim
from the retired module and is not a style preference: an earlier version
of the Physics check silently rewrote physical_science to 5 whenever a
programme name contained "Physics", which laundered a row-offset
transposition into plausible-looking bad data instead of surfacing it. A
wrong record that looks right is worse than a wrong record that fails
loudly.
"""

import json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent / "api" / "src"))
from app.subjects import Subject, LANGUAGE_FAMILIES  # noqa: E402

VALID = {s.value for s in Subject}

# Plausibility bounds, deliberately tighter than seeds/programme.schema.json's
# structural 10-48: an APS of 12 or 47 parses and validates but no real South
# African programme publishes one, so it is far more likely a transcription
# slip than a real threshold.
APS_MIN, APS_MAX = 15, 45


def walk(rule: dict, path: str, errs: list[str]) -> None:
    kind = rule.get("kind")
    if kind in ("all", "any"):
        if not rule.get("rules"):
            errs.append(f"{path}: empty {kind} node")
        for n, r in enumerate(rule.get("rules", [])):
            walk(r, f"{path}.{kind}[{n}]", errs)
    elif kind == "subject":
        has_subj, has_lang = "subject" in rule, "language" in rule
        if has_subj == has_lang:
            errs.append(f"{path}: set exactly one of subject/language")
        if has_subj and rule["subject"] not in VALID:
            errs.append(f"{path}: unknown subject '{rule['subject']}'")
        if has_lang and rule["language"] not in LANGUAGE_FAMILIES:
            errs.append(f"{path}: unknown language family '{rule['language']}'")
        for key in ("min_level", "min_level_fal"):
            if key in rule and not 1 <= rule[key] <= 7:
                errs.append(f"{path}: {key} {rule[key]} out of range 1-7")
    elif kind == "any_additional_language":
        if not 1 <= rule.get("min_level", 0) <= 7:
            errs.append(f"{path}: min_level out of range")
    else:
        errs.append(f"{path}: unknown rule kind '{kind}'")


def collect_levels(rule: dict, out: dict[str, list[int]] | None = None) -> dict[str, list[int]]:
    """Flattens a requirement tree to {slug: [min_level, ...]} for the
    semantic checks, which reason about what a subject's required level
    IS rather than where in the tree it sits. Language-family nodes are
    keyed by their family slug ("english"), subject nodes by their
    Subject value ("mathematics"); a subject appearing in several
    branches contributes several entries."""
    out = {} if out is None else out
    kind = rule.get("kind")
    if kind in ("all", "any"):
        for r in rule.get("rules", []):
            collect_levels(r, out)
    elif kind == "subject":
        slug = rule.get("subject") or rule.get("language")
        level = rule.get("min_level")
        if slug is not None and isinstance(level, int):
            out.setdefault(slug, []).append(level)
    return out


def _mentions_english(rule: dict) -> bool:
    """Presence, not level -- a banded HL/FAL node can carry only
    min_level_fal and so never reaches collect_levels' level map."""
    if rule.get("kind") in ("all", "any"):
        return any(_mentions_english(r) for r in rule.get("rules", []))
    return rule.get("language") == "english" or rule.get("subject") in ("english_hl", "english_fal")


def _semantic_errors(p: dict, tag: str) -> list[str]:
    """Checks a structurally valid record can still fail. Ported from
    extract/methods/coordinate.py's validate(); see the module docstring
    for why each one exists and why none of them repair."""
    errs: list[str] = []
    nsc = p["requirements"]["nsc"]
    levels = collect_levels(nsc["subjects"])
    name = p.get("name") or ""
    low = name.lower()

    # Columns swapped. Mathematical Literacy is the easier subject, so a
    # programme demanding a HIGHER level of it than of Mathematics has
    # read its two adjacent columns in the wrong order.
    maths, maths_lit = levels.get("mathematics"), levels.get("mathematical_literacy")
    if maths and maths_lit and min(maths_lit) < min(maths):
        errs.append(
            f"{tag}: {name!r}: mathematical_literacy={min(maths_lit)} < "
            f"mathematics={min(maths)} (columns likely swapped)"
        )

    # Row-offset transposition. A non-extended Physics major asking for
    # less than level 5 Physical Sciences has almost certainly picked up
    # the neighbouring row's value. Geology is excluded: it sits under the
    # same Physics department heading without the same science bar.
    if p.get("faculty") == "Science" and "physics" in low and "geology" not in low and not p.get("extended"):
        phys = levels.get("physical_sciences")
        if phys and min(phys) < 5:
            errs.append(f"{tag}: {name!r}: Physics major with physical_sciences={min(phys)} (expected >=5)")

    for threshold in nsc.get("score", []):
        score = threshold.get("min_score")
        if isinstance(score, int) and not APS_MIN <= score <= APS_MAX:
            errs.append(f"{tag}: implausible APS {score} (outside {APS_MIN}-{APS_MAX})")

    if not _mentions_english(nsc["subjects"]):
        errs.append(f"{tag}: no English requirement")

    if p.get("duration_years") is None:
        errs.append(f"{tag}: no duration_years")

    return errs


def validate(data: dict) -> list[str]:
    errs: list[str] = []
    if not data.get("programmes"):
        errs.append("no programmes found — refusing to validate an empty dataset")
    inst_ids = {i["id"] for i in data["institutions"]}
    seen: set[tuple] = set()

    for p in data["programmes"]:
        tag = f"{p['institution_id']}/{p['qualification_code']}"
        if p["institution_id"] not in inst_ids:
            errs.append(f"{tag}: unknown institution")
        key = (p["institution_id"], p["academic_year"], p["qualification_code"])
        if key in seen:
            errs.append(f"{tag}: duplicate code for year")
        seen.add(key)

        nsc = p["requirements"].get("nsc")
        if not nsc:
            errs.append(f"{tag}: no nsc requirements")
            continue
        if not nsc.get("score"):
            errs.append(f"{tag}: empty score thresholds")
        for t in nsc.get("score", []):
            rs = t.get("requires_subject")
            if rs and rs not in VALID:
                errs.append(f"{tag}: unknown requires_subject '{rs}'")
        for s in nsc.get("excluded_subjects", []):
            if s not in VALID:
                errs.append(f"{tag}: unknown excluded subject '{s}'")
        walk(nsc["subjects"], tag, errs)
        errs.extend(_semantic_errors(p, tag))

    return errs


def main() -> int:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    errs = validate(data)
    if errs:
        print(f"✗ {len(errs)} errors\n" + "\n".join(f"  {e}" for e in errs))
        return 1
    print(f"✓ {len(data['programmes'])} programmes valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
