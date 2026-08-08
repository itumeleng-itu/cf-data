from app.qualify import select_score_threshold


def test_unconditional_threshold_applies_directly() -> None:
    assert select_score_threshold([{"min_score": 40}], {}) == 40


def test_lowest_applicable_threshold_wins() -> None:
    entries = [
        {"min_score": 25, "requires_subject": "mathematics"},
        {"min_score": 26, "requires_subject": "mathematical_literacy"},
    ]
    assert select_score_threshold(entries, {"mathematics": 90}) == 25
    assert select_score_threshold(entries, {"mathematical_literacy": 90}) == 26


def test_both_subjects_present_picks_lowest() -> None:
    entries = [
        {"min_score": 25, "requires_subject": "mathematics"},
        {"min_score": 26, "requires_subject": "mathematical_literacy"},
    ]
    assert select_score_threshold(entries, {"mathematics": 90, "mathematical_literacy": 90}) == 25


def test_returns_none_when_no_entry_applies() -> None:
    entries = [
        {"min_score": 25, "requires_subject": "mathematics"},
        {"min_score": 26, "requires_subject": "mathematical_literacy"},
    ]
    assert select_score_threshold(entries, {"geography": 90}) is None
