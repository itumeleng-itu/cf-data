"""Unit tests for extract/methods/coordinate_records.py -- one per phase
8.5 step 4 mapping, exercised directly rather than through a real PDF."""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from methods.coordinate_records import NOT_ACCEPTED, to_programme_records  # noqa: E402
from profiles import get_profile  # noqa: E402

_UJ = get_profile("uj")


def _raw(requirements: dict, **overrides) -> dict:
    base = {
        "faculty": "Science", "programme": "Test Programme", "qualification_code": "X0000Q",
        "qualification_type": "Degree", "duration_years": 3, "campus": "APK",
        "minimum_aps": 30, "requirements": requirements, "_page": 90,
        "excluded_subjects_prose": [],
    }
    base.update(overrides)
    return base


def _convert(requirements: dict, **overrides) -> dict:
    records = to_programme_records([_raw(requirements, **overrides)], {}, {}, _UJ)
    assert len(records) == 1
    return records[0]


def _tree_subjects(node: dict) -> set[str]:
    if node.get("kind") in ("all", "any"):
        found: set[str] = set()
        for child in node["rules"]:
            found |= _tree_subjects(child)
        return found
    if node.get("kind") == "subject":
        return {node.get("subject") or node.get("language")}
    return set()


def _find_node(node: dict, predicate) -> dict | None:
    if predicate(node):
        return node
    if node.get("kind") in ("all", "any"):
        for child in node["rules"]:
            found = _find_node(child, predicate)
            if found is not None:
                return found
    return None


# --- score: minimum_aps conversions -------------------------------------

def test_plain_int_aps_becomes_single_score_entry() -> None:
    record = _convert({"english": 5}, minimum_aps=30)
    assert record["requirements"]["nsc"]["score"] == [{"min_score": 30}]


def test_two_key_aps_dict_becomes_two_score_entries_with_requires_subject() -> None:
    record = _convert(
        {"english": 5},
        minimum_aps={"with_mathematics": 25, "with_mathematical_literacy": 26},
    )
    score = record["requirements"]["nsc"]["score"]
    assert {"min_score": 25, "requires_subject": "mathematics"} in score
    assert {"min_score": 26, "requires_subject": "mathematical_literacy"} in score
    assert len(score) == 2


def test_three_key_aps_dict_becomes_three_score_entries_b34hrq_shape() -> None:
    record = _convert(
        {"english": 5},
        minimum_aps={
            "with_mathematics": 26, "with_technical_mathematics": 26, "with_mathematical_literacy": 28,
        },
    )
    score = record["requirements"]["nsc"]["score"]
    assert {"min_score": 26, "requires_subject": "mathematics"} in score
    assert {"min_score": 26, "requires_subject": "technical_mathematics"} in score
    assert {"min_score": 28, "requires_subject": "mathematical_literacy"} in score
    assert len(score) == 3


def test_english_rating_banded_aps_encodes_strictest_value_and_flags() -> None:
    record = _convert(
        {"english": 5},
        minimum_aps={"with_english_rating_5": 24, "with_english_rating_5_upper": 26, "with_english_rating_4": 27},
    )
    assert record["requirements"]["nsc"]["score"] == [{"min_score": 27}]
    assert any("English rating" in n for n in record["selection_notes"])
    assert record["confidence"] == "flagged"


def test_unparsed_aps_text_yields_no_score() -> None:
    record = _convert({"english": 5}, minimum_aps="see faculty office")
    assert record["requirements"]["nsc"]["score"] is None


# --- english: int vs banded ----------------------------------------------

def test_plain_english_int_becomes_single_level_language_node() -> None:
    record = _convert({"english": 5})
    node = _find_node(record["requirements"]["nsc"]["subjects"], lambda n: n.get("language") == "english")
    assert node == {"kind": "subject", "language": "english", "min_level": 5}


def test_banded_english_becomes_home_and_fal_language_node() -> None:
    record = _convert({"english": {"home_language": 5, "first_additional_language": 6}})
    node = _find_node(record["requirements"]["nsc"]["subjects"], lambda n: n.get("language") == "english")
    assert node == {"kind": "subject", "language": "english", "min_level": 5, "min_level_fal": 6}


# --- mathematical_literacy_or_technical_mathematics -> any node ----------

def test_merged_maths_lit_or_tech_maths_column_becomes_any_node() -> None:
    record = _convert({"english": 5, "mathematical_literacy_or_technical_mathematics": 5})
    tree = record["requirements"]["nsc"]["subjects"]
    any_node = _find_node(tree, lambda n: n.get("kind") == "any" and
                           _tree_subjects(n) == {"mathematical_literacy", "technical_mathematics"})
    assert any_node is not None
    for rule in any_node["rules"]:
        assert rule["min_level"] == 5


# --- mutually_exclusive_subjects reuse (shared.py, not reimplemented) ----

def test_mathematics_and_mathematical_literacy_both_present_becomes_any() -> None:
    # B8CD2Q/B34HRQ-style: no visible "/" or "OR" marker in the raw
    # requirements dict, still grouped via profile.layout.mutually_exclusive_subjects.
    record = _convert({"english": 5, "mathematics": 4, "mathematical_literacy": 5})
    tree = record["requirements"]["nsc"]["subjects"]
    any_node = _find_node(tree, lambda n: n.get("kind") == "any" and
                           _tree_subjects(n) == {"mathematics", "mathematical_literacy"})
    assert any_node is not None


def test_negative_control_maths_required_maths_lit_excluded_is_not_any() -> None:
    # B34CAQ/B4C01Q-style negative control: Mathematical Literacy is an
    # EXCLUSION (NOT_ACCEPTED), not a second required alternative -- must
    # never become an `any` node with mathematics.
    record = _convert({"english": 5, "mathematics": 4, "mathematical_literacy": NOT_ACCEPTED})
    tree = record["requirements"]["nsc"]["subjects"]
    any_node = _find_node(tree, lambda n: n.get("kind") == "any" and "mathematics" in _tree_subjects(n))
    assert any_node is None
    assert "mathematical_literacy" in record["requirements"]["nsc"]["excluded_subjects"]
    math_node = _find_node(tree, lambda n: n.get("subject") == "mathematics")
    assert math_node == {"kind": "subject", "subject": "mathematics", "min_level": 4}


# --- additional_language -> any_additional_language node -----------------

def test_additional_language_becomes_any_additional_language_node() -> None:
    record = _convert({"english": 5, "additional_language": 4})
    tree = record["requirements"]["nsc"]["subjects"]
    node = _find_node(tree, lambda n: n.get("kind") == "any_additional_language")
    assert node == {"kind": "any_additional_language", "min_level": 4}


# --- excluded_subjects: NOT_ACCEPTED + page-prose union -------------------

def test_not_accepted_subject_is_excluded_not_dropped() -> None:
    record = _convert({"english": 5, "physical_science": NOT_ACCEPTED})
    assert "physical_sciences" in record["requirements"]["nsc"]["excluded_subjects"]


def test_page_prose_exclusions_are_unioned_in() -> None:
    record = _convert({"english": 5}, excluded_subjects_prose=["technical_sciences"])
    assert "technical_sciences" in record["requirements"]["nsc"]["excluded_subjects"]


# --- requirements.conditions (footnote conditionals) ----------------------

def test_conditions_become_selection_notes_and_flag_confidence() -> None:
    record = _convert({
        "english": 5,
        "conditions": {"physical_science": {"with_chemistry_1A_or_physics_1A_or_1S": 5, "with_geology": 4}},
    })
    assert any("Conditional requirement" in n for n in record["selection_notes"])
    assert record["confidence"] == "flagged"


# --- campus / extended / verification provenance ---------------------------

def test_campus_string_becomes_single_element_list() -> None:
    record = _convert({"english": 5}, campus="APK")
    assert record["campus"] == ["APK"]


def test_missing_campus_becomes_empty_list() -> None:
    record = _convert({"english": 5}, campus=None)
    assert record["campus"] == []


def test_extended_qualification_type_sets_extended_true() -> None:
    record = _convert({"english": 5}, qualification_type="Extended Degree")
    assert record["extended"] is True


def test_non_extended_qualification_type_sets_extended_false() -> None:
    record = _convert({"english": 5}, qualification_type="Degree")
    assert record["extended"] is False


def test_overlay_applied_and_problems_surface_in_verification_block() -> None:
    raw = _raw({"english": 5})
    records = to_programme_records(
        [raw], {"X0000Q": ["no duration resolved from section heading"]},
        {"X0000Q": ["campus", "requirements.english"]}, _UJ,
    )
    record = records[0]
    assert record["verification"]["overlay_applied"] == ["campus", "requirements.english"]
    assert record["verification"]["problems"] == ["no duration resolved from section heading"]
    assert record["confidence"] == "flagged"


def test_clean_record_with_no_problems_or_notes_is_extracted_not_flagged() -> None:
    record = _convert({"english": 5, "mathematics": 6})
    assert record["confidence"] == "extracted"
    assert record["verification"] == {"overlay_applied": [], "problems": []}
