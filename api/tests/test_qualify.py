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


# --- requires_level (TUT-style: alternative electives that CAN coexist) --

def test_requires_level_omitted_means_presence_alone_is_enough() -> None:
    # The UJ shape, unchanged: no requires_level on the entry at all.
    entries = [{"min_score": 25, "requires_subject": "mathematics"}]
    assert select_score_threshold(entries, {"mathematics": 1}) == 25  # 1% -- level 1, still "applies"


def test_requires_level_rejects_a_subject_present_but_below_level() -> None:
    entries = [{"min_score": 22, "requires_subject": "accounting", "requires_level": 3}]
    assert select_score_threshold(entries, {"accounting": 35}) is None  # 35% = level 2, needs 3


def test_requires_level_accepts_a_subject_at_or_above_level() -> None:
    entries = [{"min_score": 22, "requires_subject": "accounting", "requires_level": 3}]
    assert select_score_threshold(entries, {"accounting": 45}) == 22  # 45% = level 3


def test_weak_alternative_no_longer_masks_the_route_a_learner_actually_qualifies_via() -> None:
    # The exact TUT bug this was added for: Accounting present but too weak
    # to satisfy the Accounting route's own bar, Mathematical Literacy
    # present and strong enough for ITS route -- the applicable threshold
    # must be the Mathematical Literacy route's (24), not the Accounting
    # route's lower one (22), which this learner never actually earns.
    entries = [
        {"min_score": 22, "requires_subject": "accounting", "requires_level": 3},
        {"min_score": 24, "requires_subject": "mathematical_literacy", "requires_level": 5},
    ]
    marks = {"accounting": 35, "mathematical_literacy": 65}  # levels 2 and 5
    assert select_score_threshold(entries, marks) == 24
