"""Unit tests for extract/methods/coordinate.py -- Method D's raw-stage
parsing (parse_rating/parse_english/parse_aps), overlay application, and
report-only validation. Integration (extract_raw_rows/extract_coordinate
against a real PDF) is covered separately in
tests/test_methods_coordinate_integration.py, guarded by pytest.mark.slow
per this repo's convention (see tests/test_methods_geometric.py).
"""

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from methods.coordinate import (  # noqa: E402
    NOT_ACCEPTED,
    apply_overlay,
    faculty_for_page,
    parse_aps,
    parse_english,
    parse_rating,
    validate,
)
from profiles import get_profile  # noqa: E402

_UJ = get_profile("uj")


# --- parse_rating: the phase 8.5 schema-gap fix -----------------------

def test_not_accepted_returns_sentinel_not_none() -> None:
    # B34CAQ-style: a real exclusion, must be distinguishable from absence.
    assert parse_rating("Not accepted", _UJ) is NOT_ACCEPTED


def test_not_applicable_returns_none_not_sentinel() -> None:
    # B2I02Q-style: absent/not-applicable, must NOT become an exclusion.
    assert parse_rating("Not applicable", _UJ) is None


def test_empty_and_dash_return_none() -> None:
    assert parse_rating("", _UJ) is None
    assert parse_rating("-", _UJ) is None
    assert parse_rating("–", _UJ) is None


def test_percentage_banded_rating_parses_to_level() -> None:
    assert parse_rating("5 (60%+)", _UJ) == 5


def test_bare_digit_rating_parses_to_level() -> None:
    assert parse_rating("6", _UJ) == 6


def test_out_of_nsc_range_digit_does_not_parse() -> None:
    assert parse_rating("9", _UJ) is None


# --- parse_english ------------------------------------------------------

def test_plain_english_rating_delegates_to_parse_rating() -> None:
    assert parse_english("5 (60%+)", _UJ) == 5


def test_banded_english_rating_returns_home_and_fal() -> None:
    text = "Home language 5 (60%+) OR\nAdditional Language 6 (70%+)"
    assert parse_english(text, _UJ) == {"home_language": 5, "first_additional_language": 6}


def test_english_not_accepted_still_returns_sentinel() -> None:
    assert parse_english("Not accepted", _UJ) is NOT_ACCEPTED


# --- parse_aps ------------------------------------------------------------

def test_plain_two_digit_aps() -> None:
    assert parse_aps("30") == 30


def test_combined_maths_tech_maths_and_maths_lit_variants() -> None:
    text = "26 with Maths/Tech Maths OR 28 with Mathematical Literacy"
    assert parse_aps(text) == {
        "with_mathematics": 26, "with_technical_mathematics": 26, "with_mathematical_literacy": 28,
    }


def test_three_way_conditional_aps_shape() -> None:
    # Spec step 4's illustrative three-entry example -- three SEPARATE
    # "N with X" clauses, distinct from the combined "Maths/Tech Maths"
    # shared-value form covered above.
    text = "26 with Mathematics OR 26 with Tech Maths OR 28 with Mathematical Literacy"
    assert parse_aps(text) == {
        "with_mathematics": 26, "with_technical_mathematics": 26, "with_mathematical_literacy": 28,
    }


def test_maths_lit_only_variant() -> None:
    assert parse_aps("28 with Mathematical Literacy") == {"with_mathematical_literacy": 28}


def test_soft_hyphenated_line_break_is_rejoined() -> None:
    assert parse_aps("27 with Mathe-\nmatics") == {"with_mathematics": 27}


def test_aps_label_prefix_is_stripped() -> None:
    assert parse_aps("APS 27") == 27


def test_english_rating_banded_aps_humanities_shape() -> None:
    assert parse_aps("24-26 or 27") == {
        "with_english_rating_5": 24, "with_english_rating_5_upper": 26, "with_english_rating_4": 27,
    }


def test_unparseable_text_is_left_in_place() -> None:
    assert parse_aps("see faculty office") == "see faculty office"


def test_empty_aps_is_none() -> None:
    assert parse_aps("") is None


# --- faculty_for_page -----------------------------------------------------

def test_faculty_for_page_uses_profile_ranges() -> None:
    assert faculty_for_page(90, _UJ) == "Science"  # 84-96 in registry.json
    assert faculty_for_page(80, _UJ) == "Law"       # 80-83
    assert faculty_for_page(0, _UJ) == ""            # front matter, no range covers it


# --- apply_overlay ----------------------------------------------------

def _raw_record(**overrides) -> dict:
    base = {
        "faculty": "Science", "programme": "Test Programme", "qualification_code": "X0000Q",
        "qualification_type": "Degree", "duration_years": 3, "campus": "APK",
        "minimum_aps": 30, "requirements": {"english": 5, "mathematics": 6}, "_page": 1,
        "excluded_subjects_prose": [],
    }
    base.update(overrides)
    return base


def test_overlay_unknown_code_is_a_no_op() -> None:
    record = _raw_record()
    original = copy.deepcopy(record)
    patched, applied = apply_overlay(record, {})
    assert patched == original
    assert applied == []


def test_overlay_shallow_merges_requirements_one_level_deep() -> None:
    record = _raw_record()
    overlay = {"X0000Q": {"source": "test", "note": "test", "patch": {"requirements": {"english": 4}}}}
    patched, applied = apply_overlay(record, overlay)
    # mathematics (untouched by the patch) must survive the merge.
    assert patched["requirements"] == {"english": 4, "mathematics": 6}
    assert applied == ["requirements.english"]


def test_overlay_replaces_non_requirements_keys_outright() -> None:
    record = _raw_record()
    overlay = {"X0000Q": {"source": "test", "note": "test", "patch": {"campus": "SWC"}}}
    patched, applied = apply_overlay(record, overlay)
    assert patched["campus"] == "SWC"
    assert applied == ["campus"]


# --- validate: report-only, never mutates ------------------------------

def test_validate_flags_duplicate_code() -> None:
    records = [_raw_record(qualification_code="X0000Q"), _raw_record(qualification_code="X0000Q", programme="Other")]
    problems = validate(records)
    assert any("duplicate code" in p for p in problems["X0000Q"])


def test_validate_flags_physics_major_under_level_5() -> None:
    record = _raw_record(
        faculty="Science", programme="BSc Physics", qualification_type="Degree",
        requirements={"english": 5, "physical_science": 4},
    )
    problems = validate([record])
    assert any("Physics major" in p for p in problems["X0000Q"])


def test_validate_does_not_flag_extended_physics_under_5() -> None:
    record = _raw_record(
        faculty="Science", programme="BSc Physics (Extended)", qualification_type="Extended Degree",
        requirements={"english": 5, "physical_science": 4},
    )
    assert validate([record]) == {}


def test_validate_does_not_flag_geology_under_5() -> None:
    record = _raw_record(
        faculty="Science", programme="BSc Geology and Physics", qualification_type="Degree",
        requirements={"english": 5, "physical_science": 4},
    )
    assert validate([record]) == {}


def test_validate_flags_maths_lit_below_maths_as_likely_swap() -> None:
    record = _raw_record(requirements={"english": 5, "mathematics": 6, "mathematical_literacy": 3})
    problems = validate([record])
    assert any("columns likely swapped" in p for p in problems["X0000Q"])


def test_validate_flags_rating_outside_nsc_range() -> None:
    record = _raw_record(requirements={"english": 5, "mathematics": 9})
    problems = validate([record])
    assert any("outside NSC range" in p for p in problems["X0000Q"])


def test_validate_flags_unparsed_aps_text() -> None:
    record = _raw_record(minimum_aps="see faculty office")
    problems = validate([record])
    assert any("unparsed APS" in p for p in problems["X0000Q"])


def test_validate_flags_implausible_aps() -> None:
    record = _raw_record(minimum_aps=90)
    problems = validate([record])
    assert any("implausible APS" in p for p in problems["X0000Q"])


def test_validate_flags_missing_english() -> None:
    record = _raw_record(requirements={"mathematics": 6})
    problems = validate([record])
    assert any("no English requirement" in p for p in problems["X0000Q"])


def test_validate_flags_missing_duration() -> None:
    record = _raw_record(duration_years=None)
    problems = validate([record])
    assert any("no duration resolved" in p for p in problems["X0000Q"])


def test_validate_clean_record_has_no_problems() -> None:
    record = _raw_record(requirements={"english": 5, "mathematics": 6})
    assert validate([record]) == {}


def test_validate_never_mutates_input() -> None:
    record = _raw_record(minimum_aps=90, requirements={"mathematics": 9})
    original = copy.deepcopy(record)
    validate([record])
    assert record == original
