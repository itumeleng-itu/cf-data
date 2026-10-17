"""Regression guards for the Stellenbosch 2027 seed.

These run against the committed seed, not the PDF -- sources/ is
gitignored, so the booklet is not available in CI. Each test below
pins something that was actually wrong at some point while this seed
was being built, because that is the only kind of guard worth having:

  * The four-year LLB was missing entirely. SU prints its duration as
    "LLB (four-year)", the extractor's duration pattern wanted digits,
    and the programme vanished along with its requirements. Nothing
    noticed, because the thing counting programmes used the same
    pattern.

  * BEd (Foundation Phase Education) had no requirements at all. Its
    entry prints none -- the Faculty of Education block above it is
    its admission requirement -- and the inheritance that should have
    supplied it was being reset by a line of body text that matched
    the faculty-banner pattern.

  * Every BEng carried a language rule that read as a flat list of
    alternatives, so "Afrikaans Home Language 50%" alone satisfied
    it. The booklet only allows that in combination with English
    First Additional Language 50%. It parsed cleanly, so no count of
    unparsed lines would ever have shown it.

  * Twenty-one programmes carried fields of study ("Animal Science",
    "Behavioural Economics") as admission requirements, because the
    "Fields of study" heading sits at the bullet-text indent and was
    read as a continuation of the bar above it.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api" / "src"))

SEED = json.loads((ROOT / "seeds" / "su" / "su_2027.json").read_text(encoding="utf-8"))
INSTITUTIONS = json.loads(
    (ROOT / "seeds" / "institutions.json").read_text(encoding="utf-8")
)
BY_CODE = {r["qualification_code"]: r for r in SEED}
BY_NAME = {r["name"]: r for r in SEED}


def _tree(record: dict) -> dict:
    return record["requirements"]["nsc"].get("subjects") or {}


def _walk(node: object):
    if isinstance(node, dict):
        yield node
        for child in node.get("rules") or []:
            yield from _walk(child)


def _names_a_language(node: object) -> bool:
    return any(
        n.get("language") or str(n.get("subject", "")).endswith(("_hl", "_fal"))
        for n in _walk(node)
    )


def test_seed_size_and_institution_registration() -> None:
    assert len(SEED) == 65
    su = next(i for i in INSTITUTIONS if i["id"] == "su")
    # SU publishes a percentage aggregate, not an APS: "an NSC
    # aggregate of at least 65% (excluding Life Orientation)". Summing
    # the best six percentages and dividing by six is that average.
    assert su["scoring_strategy"] == "percentage_sum_div_10"
    assert su["scoring_config"]["divisor"] == 6
    assert su["scoring_config"]["subject_count"] == 6
    assert su["scoring_config"]["exclude_subjects"] == ["life_orientation"]


def test_min_scores_are_percentages_not_aps() -> None:
    """Every bar is a printed percentage, so none can be APS-shaped."""
    for record in SEED:
        for threshold in record["requirements"]["nsc"].get("score") or []:
            assert 40 <= threshold["min_score"] <= 100, record["qualification_code"]


def test_the_four_year_llb_is_present_and_complete() -> None:
    llb = BY_NAME["LLB (four-year)"]
    assert llb["duration_years"] == 4.0
    assert llb["requirements"]["nsc"]["score"] == [{"min_score": 70}]
    subjects = {n.get("subject") for n in _walk(_tree(llb))}
    assert "mathematics" not in subjects, (
        "Mathematics 60% is conditional on taking Economics at university, "
        "so it must be a note rather than an entry bar"
    )
    assert _names_a_language(_tree(llb))
    assert any("NBT" in n for n in llb["selection_notes"])


def test_the_three_year_llb_is_not_offered_to_matriculants() -> None:
    """It needs a prior bachelor's degree, so it is not in the seed."""
    assert "LLB (three-year)" not in BY_NAME


def test_bed_foundation_phase_inherits_the_faculty_requirements() -> None:
    bed = BY_NAME["BEd (Foundation Phase Education)"]
    assert bed["requirements"]["nsc"]["score"] == [{"min_score": 60}]
    tree = _tree(bed)
    # Three mutually exclusive "taught in X" routes, not one flattened
    # list demanding English and Afrikaans and isiXhosa together.
    routes = next(n for n in _walk(tree) if n.get("kind") == "any" and len(n.get("rules") or []) == 3)
    assert all(r["kind"] == "all" for r in routes["rules"])
    heads = {r["rules"][0]["subject"] for r in routes["rules"]}
    assert heads == {"english_hl", "afrikaans_hl", "isixhosa_hl"}


def test_every_beng_carries_the_engineering_faculty_requirements() -> None:
    bengs = [r for r in SEED if r["name"].startswith("BEng")]
    assert len(bengs) == 7
    for record in bengs:
        assert record["requirements"]["nsc"]["score"] == [{"min_score": 70}]
        subjects = {n.get("subject") for n in _walk(_tree(record))}
        assert {"mathematics", "physical_sciences"} <= subjects, record["name"]


def test_the_engineering_language_rule_keeps_its_combination() -> None:
    """Afrikaans alone must not satisfy it.

    The booklet admits Afrikaans Home Language 50% only TOGETHER with
    English First Additional Language 50%. Flattened to a plain list
    of alternatives it admitted Afrikaans on its own.
    """
    tree = _tree(BY_NAME["BEng (Chemical)"])
    group = next(
        n
        for n in _walk(tree)
        if n.get("kind") == "any"
        and any(c.get("subject") == "english_hl" for c in n.get("rules") or [])
    )
    afrikaans_branches = [
        r
        for r in group["rules"]
        if any(c.get("subject") == "afrikaans_hl" for c in _walk(r))
    ]
    assert afrikaans_branches, "the Afrikaans combination went missing"
    for branch in afrikaans_branches:
        assert branch["kind"] == "all", "Afrikaans must be paired, never standalone"
        assert any(c.get("subject") == "english_fal" for c in _walk(branch))


def test_fields_of_study_are_not_admission_requirements() -> None:
    """No programme requires "Animal Science" to get in."""
    leaked = {"Animal Science", "Behavioural Economics", "Operations Research",
              "Statistical Genetics", "Crop Protection and Breeding"}
    for record in SEED:
        for node in _walk(_tree(record)):
            subject = node.get("subject")
            if subject:
                assert subject.replace("_", " ").title() not in leaked


# The programmes whose SOURCE PAGE states no language requirement.
#
# validate_data.py exempts SU from its "no English requirement" check,
# because the Faculty of Medicine and Health Sciences and the Faculty
# of Theology genuinely print none. That exemption is institution-wide,
# so this pins the exact set it is allowed to cover: if a converter
# change drops a language rule from any of the other 56 records, or if
# a future edition adds one to these, this fails.
NO_LANGUAGE_REQUIREMENT = {
    "MBCHB": "p12 Health Sciences prints aggregate + Maths/Physical/Life Sciences only",
    "BACHELOR-NURSING": "p12, as above",
    "BACHELOR-OCCUPATIONAL-THERAPY": "p12, as above",
    "BSC-DIETETICS": "p12, as above",
    "BSC-PHYSIOTHERAPY": "p12, as above",
    "BTH-BACHELOR-THEOLOGY": "p15 prints an aggregate and nothing else",
    "BDIV-BACHELOR-DIVINITY": "p15, as above",
    "DIPLOMA-PRACTICAL-MUSIC": "p5, admitted on audition; scoreable=false",
    "HIGHER-CERTIFICATE-MUSIC": "p5, admitted on audition; scoreable=false",
}


def test_only_the_expected_records_lack_a_language_requirement() -> None:
    actual = {
        code for code, record in BY_CODE.items() if not _names_a_language(_tree(record))
    }
    assert actual == set(NO_LANGUAGE_REQUIREMENT), (
        f"gained={actual - set(NO_LANGUAGE_REQUIREMENT)}, "
        f"lost={set(NO_LANGUAGE_REQUIREMENT) - actual}"
    )


def test_speech_language_therapy_keeps_its_two_of_three_rule() -> None:
    """It prints "at least TWO of the following THREE languages".

    This was routed to a note as inexpressible, leaving a therapy
    degree about language with no language requirement at all. With
    three candidates it is simply the three pairs.
    """
    tree = _tree(BY_NAME["Bachelor of Speech-Language and Hearing Therapy"])
    assert _names_a_language(tree)
    pairs = next(n for n in _walk(tree) if n.get("kind") == "any"
                 and len(n.get("rules") or []) == 3
                 and all(c.get("kind") == "all" for c in n["rules"]))
    assert len(pairs["rules"]) == 3


def test_off_band_bars_are_flagged_and_explained() -> None:
    """75% is not an NSC band floor, so those two records say so."""
    flagged = {r["qualification_code"] for r in SEED if r["confidence"] == "flagged"}
    assert flagged == {"BCOM-MATHEMATICAL-SCIENCES", "BACHELOR-DATA-SCIENCE-BDATSCI"}
    for code in flagged:
        assert any("75%" in n for n in BY_CODE[code]["selection_notes"]), code


def test_interfaculty_data_science_is_one_record() -> None:
    """Printed under four faculties on p3, p6, p8 and p15."""
    bdatsci = BY_NAME["Bachelor of Data Science (BDatSci)"]
    faculties = [f.strip() for f in bdatsci["faculty"].split(";")]
    assert faculties == [
        "Agrisciences",
        "Arts and Social Sciences",
        "Economic and Management Sciences",
        "Science",
    ]
    assert any("Interfaculty programme" in n for n in bdatsci["selection_notes"])


def test_unscoreable_programmes_state_no_invented_bar() -> None:
    for record in SEED:
        if record["scoreable"]:
            continue
        assert not (record["requirements"]["nsc"].get("score") or []), record["name"]


def test_every_record_traces_to_a_page() -> None:
    for record in SEED:
        assert record["source_doc"] == "su_admissions_booklet_2027"
        assert 2 <= record["source_page"] <= 15, record["qualification_code"]
