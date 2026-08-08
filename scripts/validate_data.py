import json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent / "api" / "src"))
from app.subjects import Subject, LANGUAGE_FAMILIES  # noqa: E402

VALID = {s.value for s in Subject}


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
            if not 10 <= t["min_score"] <= 48:
                errs.append(f"{tag}: implausible APS {t['min_score']}")
            rs = t.get("requires_subject")
            if rs and rs not in VALID:
                errs.append(f"{tag}: unknown requires_subject '{rs}'")
        for s in nsc.get("excluded_subjects", []):
            if s not in VALID:
                errs.append(f"{tag}: unknown excluded subject '{s}'")
        walk(nsc["subjects"], tag, errs)

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