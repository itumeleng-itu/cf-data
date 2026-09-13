"""The semantic half of scripts/validate_data.py -- the checks that fire
on records which are structurally perfect and still wrong.

Every one of these was ported from the retired extraction pipeline, where
it was written against a real failure. They are kept because a human
transcribing a prospectus table by hand makes the same class of mistake a
misaligned column grid does, and because schema validation cannot see any
of them: the D2ACXQ/D2BTEQ APS swap that motivated this suite is two
in-range integers in the right fields.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api" / "src"))

from validate_data import validate  # noqa: E402

_INSTITUTION = {
    "id": "uj", "name": "University of Johannesburg",
    "scoring_strategy": "aps_best6_excl_lo", "scoring_config": {},
}


def _dataset(*programmes: dict) -> dict:
    return {"institutions": [_INSTITUTION], "programmes": list(programmes)}


def _programme(**overrides) -> dict:
    base = {
        "institution_id": "uj",
        "academic_year": 2027,
        "qualification_code": "B00AAQ",
        "name": "Bachelor of Something",
        "faculty": "Science",
        "duration_years": 3,
        "extended": False,
        "requirements": {
            "nsc": {
                "score": [{"min_score": 30}],
                "subjects": {
                    "kind": "all",
                    "rules": [
                        {"kind": "subject", "language": "english", "min_level": 4},
                        {"kind": "subject", "subject": "mathematics", "min_level": 5},
                    ],
                },
                "excluded_subjects": [],
            }
        },
    }
    base.update(overrides)
    return base


def _errors(programme: dict) -> list[str]:
    return validate(_dataset(programme))


def _subjects(*rules: dict) -> dict:
    return {"kind": "all", "rules": list(rules)}


_ENGLISH = {"kind": "subject", "language": "english", "min_level": 4}


# --- a clean record produces nothing -----------------------------------

def test_a_well_formed_record_reports_no_errors() -> None:
    assert _errors(_programme()) == []


# --- duplicate qualification_code within institution + year ------------

def test_duplicate_code_in_the_same_institution_and_year_is_reported() -> None:
    errs = validate(_dataset(_programme(), _programme(name="A different programme")))
    assert any("duplicate code" in e for e in errs)


def test_same_code_in_a_different_year_is_not_a_duplicate() -> None:
    errs = validate(_dataset(_programme(), _programme(academic_year=2026)))
    assert not any("duplicate code" in e for e in errs)


# --- swapped Mathematics / Mathematical Literacy columns ---------------

def test_maths_literacy_below_maths_is_reported_as_swapped_columns() -> None:
    errs = _errors(_programme(requirements={"nsc": {
        "score": [{"min_score": 30}],
        "subjects": _subjects(_ENGLISH, {"kind": "any", "rules": [
            {"kind": "subject", "subject": "mathematics", "min_level": 5},
            {"kind": "subject", "subject": "mathematical_literacy", "min_level": 3},
        ]}),
    }}))
    assert any("columns likely swapped" in e for e in errs)


def test_maths_literacy_above_maths_is_the_normal_case_and_passes() -> None:
    # Maths Literacy is the easier subject, so a HIGHER required level for
    # it than for Mathematics is exactly what a real programme prints.
    errs = _errors(_programme(requirements={"nsc": {
        "score": [{"min_score": 30}],
        "subjects": _subjects(_ENGLISH, {"kind": "any", "rules": [
            {"kind": "subject", "subject": "mathematics", "min_level": 3},
            {"kind": "subject", "subject": "mathematical_literacy", "min_level": 5},
        ]}),
    }}))
    assert errs == []


# --- Physics row-offset transposition ----------------------------------

def test_science_physics_major_below_physical_sciences_5_is_reported() -> None:
    errs = _errors(_programme(
        name="BSc Physics", faculty="Science",
        requirements={"nsc": {
            "score": [{"min_score": 30}],
            "subjects": _subjects(_ENGLISH, {"kind": "subject", "subject": "physical_sciences", "min_level": 4}),
        }},
    ))
    assert any("Physics major" in e for e in errs)


def test_the_physics_check_does_not_repair_the_record() -> None:
    # The whole reason this validator exists in its current form: an
    # earlier version rewrote the level to 5 instead of reporting it,
    # which laundered a transposition into plausible-looking bad data.
    programme = _programme(
        name="BSc Physics", faculty="Science",
        requirements={"nsc": {
            "score": [{"min_score": 30}],
            "subjects": _subjects(_ENGLISH, {"kind": "subject", "subject": "physical_sciences", "min_level": 4}),
        }},
    )
    validate(_dataset(programme))
    node = programme["requirements"]["nsc"]["subjects"]["rules"][1]
    assert node["min_level"] == 4


def test_extended_physics_programme_is_exempt() -> None:
    errs = _errors(_programme(
        name="BSc Physics (Extended)", faculty="Science", extended=True,
        requirements={"nsc": {
            "score": [{"min_score": 30}],
            "subjects": _subjects(_ENGLISH, {"kind": "subject", "subject": "physical_sciences", "min_level": 4}),
        }},
    ))
    assert errs == []


def test_geophysics_style_geology_name_is_exempt() -> None:
    errs = _errors(_programme(
        name="BSc Geology and Geophysics", faculty="Science",
        requirements={"nsc": {
            "score": [{"min_score": 30}],
            "subjects": _subjects(_ENGLISH, {"kind": "subject", "subject": "physical_sciences", "min_level": 4}),
        }},
    ))
    assert errs == []


def test_physics_named_programme_outside_the_science_faculty_is_exempt() -> None:
    errs = _errors(_programme(
        name="BEd Physical Sciences Teaching with Physics", faculty="Education",
        requirements={"nsc": {
            "score": [{"min_score": 30}],
            "subjects": _subjects(_ENGLISH, {"kind": "subject", "subject": "physical_sciences", "min_level": 4}),
        }},
    ))
    assert errs == []


# --- achievement levels outside 1-7 ------------------------------------

def test_level_above_seven_is_reported() -> None:
    errs = _errors(_programme(requirements={"nsc": {
        "score": [{"min_score": 30}],
        "subjects": _subjects(_ENGLISH, {"kind": "subject", "subject": "mathematics", "min_level": 8}),
    }}))
    assert any("out of range 1-7" in e for e in errs)


def test_a_percentage_typed_into_a_level_field_is_reported() -> None:
    # The single likeliest hand-transcription slip: copying 60 out of
    # "5 (60%+)" instead of 5.
    errs = _errors(_programme(requirements={"nsc": {
        "score": [{"min_score": 30}],
        "subjects": _subjects(_ENGLISH, {"kind": "subject", "subject": "mathematics", "min_level": 60}),
    }}))
    assert any("out of range 1-7" in e for e in errs)


def test_level_zero_is_reported() -> None:
    errs = _errors(_programme(requirements={"nsc": {
        "score": [{"min_score": 30}],
        "subjects": _subjects(_ENGLISH, {"kind": "subject", "subject": "mathematics", "min_level": 0}),
    }}))
    assert any("out of range 1-7" in e for e in errs)


# --- APS plausibility ---------------------------------------------------

def test_aps_below_fifteen_is_reported() -> None:
    errs = _errors(_programme(requirements={"nsc": {
        "score": [{"min_score": 12}], "subjects": _subjects(_ENGLISH),
    }}))
    assert any("implausible APS 12" in e for e in errs)


def test_aps_above_forty_five_is_reported() -> None:
    errs = _errors(_programme(requirements={"nsc": {
        "score": [{"min_score": 47}], "subjects": _subjects(_ENGLISH),
    }}))
    assert any("implausible APS 47" in e for e in errs)


def test_both_ends_of_the_plausible_aps_range_are_accepted() -> None:
    for score in (15, 45):
        errs = _errors(_programme(requirements={"nsc": {
            "score": [{"min_score": score}], "subjects": _subjects(_ENGLISH),
        }}))
        assert errs == [], f"APS {score} should be accepted"


def test_every_threshold_is_checked_not_just_the_first() -> None:
    errs = _errors(_programme(requirements={"nsc": {
        "score": [
            {"min_score": 30, "requires_subject": "mathematics"},
            {"min_score": 99, "requires_subject": "mathematical_literacy"},
        ],
        "subjects": _subjects(_ENGLISH),
    }}))
    assert any("implausible APS 99" in e for e in errs)


# --- missing English ----------------------------------------------------

def test_missing_english_requirement_is_reported() -> None:
    errs = _errors(_programme(requirements={"nsc": {
        "score": [{"min_score": 30}],
        "subjects": _subjects({"kind": "subject", "subject": "mathematics", "min_level": 5}),
    }}))
    assert any("no English requirement" in e for e in errs)


def test_english_as_a_specific_hl_subject_node_counts() -> None:
    errs = _errors(_programme(requirements={"nsc": {
        "score": [{"min_score": 30}],
        "subjects": _subjects({"kind": "subject", "subject": "english_hl", "min_level": 5}),
    }}))
    assert not any("English" in e for e in errs)


def test_a_banded_english_node_counts_even_though_it_carries_no_plain_level() -> None:
    errs = _errors(_programme(requirements={"nsc": {
        "score": [{"min_score": 30}],
        "subjects": _subjects(
            {"kind": "subject", "language": "english", "min_level": 5, "min_level_fal": 6}
        ),
    }}))
    assert errs == []


def test_english_nested_inside_an_any_node_counts() -> None:
    errs = _errors(_programme(requirements={"nsc": {
        "score": [{"min_score": 30}],
        "subjects": _subjects({"kind": "any", "rules": [
            _ENGLISH, {"kind": "subject", "language": "afrikaans", "min_level": 4},
        ]}),
    }}))
    assert not any("English" in e for e in errs)


# --- missing duration ---------------------------------------------------

def test_missing_duration_years_is_reported() -> None:
    assert any("no duration_years" in e for e in _errors(_programme(duration_years=None)))


def test_omitted_duration_years_is_reported() -> None:
    programme = _programme()
    del programme["duration_years"]
    assert any("no duration_years" in e for e in _errors(programme))


# --- reporting, never repairing ----------------------------------------

def test_validate_never_mutates_the_dataset_it_is_given() -> None:
    import copy

    programme = _programme(
        name="BSc Physics", faculty="Science", duration_years=None,
        requirements={"nsc": {
            "score": [{"min_score": 99}],
            "subjects": _subjects({"kind": "subject", "subject": "physical_sciences", "min_level": 2}),
        }},
    )
    dataset = _dataset(programme)
    before = copy.deepcopy(dataset)
    errs = validate(dataset)
    assert len(errs) >= 4
    assert dataset == before
