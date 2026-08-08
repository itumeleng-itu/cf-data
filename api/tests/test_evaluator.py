import pytest

from app.evaluator import MIN_PCT_FOR_LEVEL, evaluate, subject_display_name
from app.subjects import percentage_to_level


# --- subject, exact key -----------------------------------------------------

def test_subject_exact_key_pass() -> None:
    rule = {"kind": "subject", "subject": "mathematics", "min_level": 7}
    assert evaluate(rule, {"mathematics": 88}, set()) == []


def test_subject_exact_key_fail_message_format() -> None:
    rule = {"kind": "subject", "subject": "mathematics", "min_level": 5}
    failures = evaluate(rule, {"mathematics": 52}, set())
    assert len(failures) == 1
    f = failures[0]
    assert f.message == "Requires Mathematics level 5 (60%+); you have level 4 (52%)"
    assert f.kind == "subject"
    assert f.required == 5
    assert f.actual == 4
    assert f.subject == "mathematics"


def test_subject_exact_key_absent() -> None:
    rule = {"kind": "subject", "subject": "mathematics", "min_level": 5}
    failures = evaluate(rule, {}, set())
    assert len(failures) == 1
    assert failures[0].actual is None
    assert failures[0].message == "Requires Mathematics as a matric subject"
    assert failures[0].subject == "mathematics"


# --- excluded-subject semantics: absence, never a special failure kind ------

def test_excluded_subject_treated_as_absent_not_a_special_failure() -> None:
    rule = {"kind": "subject", "subject": "mathematics", "min_level": 5}
    failures = evaluate(rule, {"mathematics": 90}, {"mathematics"})
    assert len(failures) == 1
    assert failures[0].actual is None
    assert failures[0].message == "Requires Mathematics as a matric subject"
    assert failures[0].kind == "subject"  # no "forbidden subject" kind exists


def test_excluded_subject_does_not_block_a_different_valid_subject() -> None:
    rule = {"kind": "subject", "subject": "mathematics", "min_level": 6}
    marks = {"mathematics": 75, "technical_mathematics": 80}
    assert evaluate(rule, marks, {"technical_mathematics"}) == []


# --- subject, language key ---------------------------------------------------

def test_language_hl_level_sufficient_passes() -> None:
    rule = {"kind": "subject", "language": "english", "min_level": 5}
    assert evaluate(rule, {"english_hl": 87}, set()) == []


def test_language_fal_level_sufficient_passes() -> None:
    rule = {"kind": "subject", "language": "english", "min_level": 5, "min_level_fal": 6}
    assert evaluate(rule, {"english_fal": 75}, set()) == []


def test_language_fal_72_passes_65_fails() -> None:
    rule = {"kind": "subject", "language": "english", "min_level": 5, "min_level_fal": 6}
    assert evaluate(rule, {"english_fal": 72}, set()) == []
    failures = evaluate(rule, {"english_fal": 65}, set())
    assert len(failures) == 1
    assert failures[0].required == 6


def test_language_fal_only_present_reports_fal_threshold() -> None:
    rule = {"kind": "subject", "language": "english", "min_level": 5, "min_level_fal": 6}
    failures = evaluate(rule, {"english_fal": 55}, set())
    assert len(failures) == 1
    assert failures[0].required == 6
    assert failures[0].actual == 4


def test_language_hl_only_present_reports_hl_threshold() -> None:
    rule = {"kind": "subject", "language": "english", "min_level": 5, "min_level_fal": 6}
    failures = evaluate(rule, {"english_hl": 45}, set())
    assert len(failures) == 1
    assert failures[0].required == 5
    assert failures[0].actual == 3


def test_language_both_insufficient_reports_smaller_deficit() -> None:
    rule = {"kind": "subject", "language": "afrikaans", "min_level": 6, "min_level_fal": 6}
    marks = {"afrikaans_hl": 65, "afrikaans_fal": 55}
    failures = evaluate(rule, marks, set())
    assert len(failures) == 1
    assert failures[0].required == 6
    assert failures[0].actual == 5


def test_language_tie_prefers_hl() -> None:
    rule = {"kind": "subject", "language": "afrikaans", "min_level": 6, "min_level_fal": 5}
    marks = {"afrikaans_hl": 55, "afrikaans_fal": 45}
    failures = evaluate(rule, marks, set())
    assert failures[0].required == 6


def test_language_absent_names_language() -> None:
    rule = {"kind": "subject", "language": "isizulu", "min_level": 4}
    failures = evaluate(rule, {"english_hl": 87, "mathematics": 88}, set())
    assert len(failures) == 1
    assert failures[0].actual is None
    assert failures[0].message == "Requires isiZulu as a matric subject"
    assert failures[0].subject == "isizulu"


# --- any_additional_language: explicit consumed_language, never inferred ----

def test_any_additional_language_passes_via_non_consumed_language() -> None:
    rule = {"kind": "any_additional_language", "min_level": 4}
    marks = {"english_hl": 87, "afrikaans_fal": 85}
    assert evaluate(rule, marks, set(), consumed_language="english") == []


def test_any_additional_language_excludes_only_the_explicitly_consumed_family() -> None:
    rule = {"kind": "any_additional_language", "min_level": 4}
    marks = {"english_hl": 87}  # the only language present is the consumed one
    failures = evaluate(rule, marks, set(), consumed_language="english")
    assert len(failures) == 1


def test_any_additional_language_none_consumed_checks_all_families() -> None:
    rule = {"kind": "any_additional_language", "min_level": 4}
    marks = {"english_hl": 87}
    assert evaluate(rule, marks, set(), consumed_language=None) == []


def test_any_additional_language_reports_best_candidate_level() -> None:
    rule = {"kind": "any_additional_language", "min_level": 6}
    marks = {"english_hl": 87, "afrikaans_fal": 55}
    failures = evaluate(rule, marks, set(), consumed_language="english")
    assert len(failures) == 1
    assert failures[0].actual == 4


def test_any_additional_language_generic_when_none_offered() -> None:
    failures = evaluate(
        {"kind": "any_additional_language", "min_level": 4},
        {"english_hl": 87}, set(), consumed_language="english",
    )
    assert len(failures) == 1
    assert failures[0].actual is None


# --- all / any, with explicit consumed_language threading -------------------

def test_all_concatenates_failures_from_all_children() -> None:
    rule = {"kind": "all", "rules": [
        {"kind": "subject", "subject": "mathematics", "min_level": 7},
        {"kind": "subject", "subject": "geography", "min_level": 7},
    ]}
    failures = evaluate(rule, {"mathematics": 50, "geography": 50}, set())
    assert len(failures) == 2


def test_all_threads_consumed_language_to_any_additional_language() -> None:
    rule = {"kind": "all", "rules": [
        {"kind": "subject", "language": "english", "min_level": 5},
        {"kind": "any_additional_language", "min_level": 4},
    ]}
    # Only english offered -- if 'all' correctly marks it consumed after the
    # first rule passes, the second rule must fail (nothing else offered).
    failures = evaluate(rule, {"english_hl": 87}, set())
    assert len(failures) == 1
    assert failures[0].kind == "any_additional_language"


def test_all_does_not_thread_consumption_when_language_rule_fails() -> None:
    rule = {"kind": "all", "rules": [
        {"kind": "subject", "language": "english", "min_level": 5},
        {"kind": "any_additional_language", "min_level": 4},
    ]}
    # english_hl too low to pass -- nothing is consumed, so both rules fail
    # independently (any_additional_language even considers english itself,
    # since it was never actually consumed).
    failures = evaluate(rule, {"english_hl": 40}, set())
    assert len(failures) == 2


def test_two_sequential_language_subject_nodes_evaluate_independently() -> None:
    # A two-language programme: English then isiZulu, both explicit
    # "subject"+"language" nodes (neither is any_additional_language).
    # English passing and "consuming" its family must not affect isiZulu's
    # own independent check.
    rule = {"kind": "all", "rules": [
        {"kind": "subject", "language": "english", "min_level": 5, "min_level_fal": 6},
        {"kind": "subject", "language": "isizulu", "min_level": 4, "min_level_fal": 5},
    ]}
    assert evaluate(rule, {"english_hl": 87, "isizulu_hl": 75}, set()) == []

    failures = evaluate(rule, {"english_hl": 87}, set())
    assert len(failures) == 1
    assert failures[0].subject == "isizulu"


def test_any_passes_if_any_child_passes() -> None:
    rule = {"kind": "any", "rules": [
        {"kind": "subject", "subject": "mathematics", "min_level": 7},
        {"kind": "subject", "subject": "mathematical_literacy", "min_level": 4},
    ]}
    assert evaluate(rule, {"mathematical_literacy": 90}, set()) == []


def test_any_returns_closest_failing_branch() -> None:
    rule = {"kind": "any", "rules": [
        {"kind": "subject", "subject": "mathematics", "min_level": 7},
        {"kind": "all", "rules": [
            {"kind": "subject", "subject": "geography", "min_level": 7},
            {"kind": "subject", "subject": "history", "min_level": 7},
        ]},
    ]}
    failures = evaluate(rule, {}, set())
    assert len(failures) == 1
    assert failures[0].required == 7


def test_two_sibling_any_nodes_in_one_all_evaluate_independently() -> None:
    # FEBE's BEngTech pattern: one 'any' for maths (Maths OR Technical
    # Maths), a separate sibling 'any' for science (Physical OR Technical
    # Sciences). Each must evaluate on its own -- a learner failing both
    # gets exactly one failure per 'any', not a merged/confused result.
    rule = {"kind": "all", "rules": [
        {"kind": "any", "rules": [
            {"kind": "subject", "subject": "mathematics", "min_level": 5},
            {"kind": "subject", "subject": "technical_mathematics", "min_level": 5},
        ]},
        {"kind": "any", "rules": [
            {"kind": "subject", "subject": "physical_sciences", "min_level": 5},
            {"kind": "subject", "subject": "technical_sciences", "min_level": 5},
        ]},
    ]}

    # Passes via the technical variant on both sides.
    assert evaluate(rule, {"technical_mathematics": 75, "technical_sciences": 75}, set()) == []

    # Fails both -- exactly one failure per 'any', not a merged four.
    failures = evaluate(rule, {}, set())
    assert len(failures) == 2
    kinds_by_subject = {f.subject for f in failures}
    assert kinds_by_subject == {"mathematics", "physical_sciences"}


def test_any_with_empty_rules_returns_failure_not_raise() -> None:
    failures = evaluate({"kind": "any", "rules": []}, {}, set())
    assert len(failures) == 1
    assert failures[0].kind == "any"


def test_any_with_missing_rules_key_returns_failure_not_raise() -> None:
    failures = evaluate({"kind": "any"}, {}, set())
    assert len(failures) == 1


# --- totality: never raises ---------------------------------------------------

def test_unknown_kind_returns_failure_not_raise() -> None:
    failures = evaluate({"kind": "bogus"}, {}, set())
    assert len(failures) == 1
    assert "bogus" in failures[0].message


def test_subject_both_subject_and_language_set_is_malformed() -> None:
    rule = {"kind": "subject", "subject": "mathematics", "language": "english", "min_level": 5}
    failures = evaluate(rule, {}, set())
    assert len(failures) == 1


def test_subject_neither_subject_nor_language_set_is_malformed() -> None:
    failures = evaluate({"kind": "subject", "min_level": 5}, {}, set())
    assert len(failures) == 1


def test_subject_missing_min_level_is_malformed() -> None:
    failures = evaluate({"kind": "subject", "subject": "mathematics"}, {}, set())
    assert len(failures) == 1


def test_any_additional_language_missing_min_level_is_malformed() -> None:
    failures = evaluate({"kind": "any_additional_language"}, {}, set())
    assert len(failures) == 1


def test_out_of_range_mark_value_does_not_raise() -> None:
    rule = {"kind": "subject", "subject": "mathematics", "min_level": 5}
    failures = evaluate(rule, {"mathematics": 150}, set())
    assert len(failures) == 1
    assert failures[0].actual is None


def test_non_dict_rule_does_not_raise() -> None:
    failures = evaluate(None, {}, set())  # type: ignore[arg-type]  # exercising totality against malformed input
    assert len(failures) == 1


# --- helper tables --------------------------------------------------------------

@pytest.mark.parametrize("level", [2, 3, 4, 5, 6, 7])
def test_min_pct_for_level_roundtrips_against_percentage_to_level(level: int) -> None:
    pct = MIN_PCT_FOR_LEVEL[level]
    assert percentage_to_level(pct) == level
    assert percentage_to_level(pct - 1) == level - 1


def test_subject_display_name_examples() -> None:
    assert subject_display_name("mathematics") == "Mathematics"
    assert subject_display_name("siswati_hl") == "siSwati Home Language"
    assert subject_display_name("isizulu_fal") == "isiZulu First Additional Language"
    assert subject_display_name("engineering_graphics_and_design") == "Engineering Graphics and Design"
