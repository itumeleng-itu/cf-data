from app.scoring import SCORERS

CANONICAL_MARKS = {
    "english_hl": 87,
    "afrikaans_fal": 85,
    "mathematics": 88,
    "life_orientation": 88,
    "geography": 92,
    "life_sciences": 87,
    "physical_sciences": 73,
}


# --- aps_best6_excl_lo ---------------------------------------------------

def test_aps_best6_excl_lo_canonical_fixture_with_default_config() -> None:
    assert SCORERS["aps_best6_excl_lo"](CANONICAL_MARKS, {}) == 41


def test_life_orientation_excluded_even_when_raised() -> None:
    marks = {**CANONICAL_MARKS, "life_orientation": 100}
    assert SCORERS["aps_best6_excl_lo"](marks, {}) == 41


def test_best6_drops_lowest_when_more_than_six_subjects() -> None:
    marks = {**CANONICAL_MARKS, "history": 35}  # 7th non-LO subject, level 2, lowest
    assert SCORERS["aps_best6_excl_lo"](marks, {}) == 41


def test_sums_all_when_fewer_than_six_subjects_no_padding() -> None:
    marks = {"mathematics": 88, "english_hl": 87}
    assert SCORERS["aps_best6_excl_lo"](marks, {}) == 14


def test_empty_marks_returns_zero_without_raising() -> None:
    assert SCORERS["aps_best6_excl_lo"]({}, {}) == 0


def test_subject_count_is_config_driven() -> None:
    marks = {**CANONICAL_MARKS, "history": 35}
    assert SCORERS["aps_best6_excl_lo"](marks, {"subject_count": 7}) == 43


def test_exclude_subjects_is_config_driven_not_hardcoded_to_life_orientation() -> None:
    # 3 subjects, life_orientation is the WEAKEST (level 3) -- if it were
    # still hardcoded as the exclusion, it would drop out on its own merit
    # and both configs would agree. Excluding history (level 7) instead
    # must force a materially different, lower total.
    marks = {"mathematics": 88, "life_orientation": 45, "history": 82}
    excl_lo_by_default = SCORERS["aps_best6_excl_lo"](marks, {})
    excl_history_instead = SCORERS["aps_best6_excl_lo"](marks, {"exclude_subjects": ["history"]})
    assert excl_lo_by_default == 7 + 7  # mathematics + history, LO dropped
    assert excl_history_instead == 7 + 3  # mathematics + life_orientation, history dropped
    assert excl_lo_by_default != excl_history_instead


def test_empty_exclude_subjects_config_counts_life_orientation_too() -> None:
    marks = {"mathematics": 88, "life_orientation": 88}
    assert SCORERS["aps_best6_excl_lo"](marks, {"exclude_subjects": []}) == 14


def test_registry_contains_aps_best6_excl_lo() -> None:
    assert "aps_best6_excl_lo" in SCORERS
    assert callable(SCORERS["aps_best6_excl_lo"])


# --- percentage_sum_div_10 (CPUT-style) ----------------------------------

def test_percentage_sum_div_10_sums_raw_percentages_not_levels() -> None:
    marks = {"english_hl": 60, "mathematics": 60, "accounting": 60,
             "geography": 60, "history": 60, "business_studies": 60}
    # 6 * 60 = 360 / 10 = 36 -- if this used levels instead (level 5 each),
    # it would be 30, so this pins that raw percentages are used.
    assert SCORERS["percentage_sum_div_10"](marks, {}) == 36


def test_percentage_sum_div_10_excludes_life_orientation_by_default() -> None:
    marks = {"english_hl": 60, "mathematics": 60, "accounting": 60,
             "geography": 60, "history": 60, "business_studies": 60, "life_orientation": 100}
    assert SCORERS["percentage_sum_div_10"](marks, {}) == 36


def test_percentage_sum_div_10_takes_only_the_best_n() -> None:
    marks = {"english_hl": 60, "mathematics": 60, "accounting": 60,
             "geography": 60, "history": 60, "business_studies": 60, "tourism": 10}
    assert SCORERS["percentage_sum_div_10"](marks, {}) == 36


def test_percentage_sum_div_10_divisor_is_config_driven() -> None:
    marks = {"english_hl": 60, "mathematics": 60, "accounting": 60,
             "geography": 60, "history": 60, "business_studies": 60}
    assert SCORERS["percentage_sum_div_10"](marks, {"divisor": 5}) == 72


def test_percentage_sum_div_10_floors_uneven_division() -> None:
    marks = {"english_hl": 57, "mathematics": 55, "accounting": 50,
             "business_studies": 54, "geography": 43, "history": 45}
    assert sum(marks.values()) == 304
    assert SCORERS["percentage_sum_div_10"](marks, {}) == 30  # not 30.4, not 31


def test_registry_contains_percentage_sum_div_10() -> None:
    assert "percentage_sum_div_10" in SCORERS


# --- weighted_levels (UCT/Wits-style, unregistered) ----------------------

def test_weighted_levels_applies_multiplier_to_named_subjects() -> None:
    marks = {"mathematics": 70, "physical_sciences": 70, "english_hl": 70}  # each level 6
    result = SCORERS["weighted_levels"](
        marks, {"weights": {"mathematics": 2, "physical_sciences": 2}, "subject_count": 3},
    )
    assert result == 6 * 2 + 6 * 2 + 6 * 1  # maths and physics doubled, english at default weight


def test_weighted_levels_default_weight_is_config_driven() -> None:
    marks = {"mathematics": 70, "english_hl": 70}  # each level 6
    result = SCORERS["weighted_levels"](marks, {"default_weight": 3, "subject_count": 2})
    assert result == 6 * 3 + 6 * 3


def test_weighted_levels_weight_zero_excludes_a_subject() -> None:
    marks = {"life_orientation": 100, "mathematics": 60, "english_hl": 60}  # levels 7, 5, 5
    result = SCORERS["weighted_levels"](
        marks, {"weights": {"life_orientation": 0}, "subject_count": 2},
    )
    # Life Orientation's weighted value is 0, so it loses to both level-5
    # subjects for the top 2 slots despite having the highest raw level.
    assert result == 5 + 5


def test_weighted_levels_unweighted_subjects_use_default_weight_of_one() -> None:
    marks = {"mathematics": 60}  # level 5
    assert SCORERS["weighted_levels"](marks, {"subject_count": 1}) == 5


def test_registry_contains_weighted_levels() -> None:
    assert "weighted_levels" in SCORERS
