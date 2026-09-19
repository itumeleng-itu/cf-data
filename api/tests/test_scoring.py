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


def test_zero_below_level_zeroes_a_weak_subject_but_still_occupies_a_slot() -> None:
    # TUT-style: "LO and any subject at level 1 are not counted" -- a
    # level-1 subject contributes 0, but doesn't get DROPPED in favour of
    # some other subject the way excluding it outright would. With exactly
    # six subjects offered, the weak one has no competition to lose to --
    # it still occupies a slot, worth 0 instead of its real level.
    marks = {
        "mathematics": 88,          # level 7
        "english_hl": 87,           # level 7
        "geography": 92,            # level 7
        "life_sciences": 87,        # level 7
        "physical_sciences": 73,    # level 6
        "history": 25,              # level 1 -- below zero_below_level=2
    }
    without_floor = SCORERS["aps_best6_excl_lo"](marks, {"subject_count": 6})
    with_floor = SCORERS["aps_best6_excl_lo"](marks, {"subject_count": 6, "zero_below_level": 2})
    assert without_floor == 7 + 7 + 7 + 7 + 6 + 1  # history counts as its real level 1
    assert with_floor == 7 + 7 + 7 + 7 + 6 + 0  # history's slot -> 0, not dropped for a 7th subject


def test_zero_below_level_does_not_change_ranking_when_a_stronger_subject_is_available() -> None:
    # A level-1 subject that WOULD lose its slot on raw merit anyway (a 7th
    # subject beats it outright) behaves identically with or without the
    # floor -- zeroing only matters when the weak subject actually makes
    # the cut.
    marks = {
        "mathematics": 88, "english_hl": 87, "geography": 92, "life_sciences": 87,
        "physical_sciences": 73, "accounting": 65,  # level 5 -- beats history either way
        "history": 25,  # level 1
    }
    without_floor = SCORERS["aps_best6_excl_lo"](marks, {"subject_count": 6})
    with_floor = SCORERS["aps_best6_excl_lo"](marks, {"subject_count": 6, "zero_below_level": 2})
    assert without_floor == with_floor == 7 + 7 + 7 + 7 + 6 + 5


def test_zero_below_level_default_is_none_so_every_level_counts_as_itself() -> None:
    marks = {"history": 25}  # level 1
    assert SCORERS["aps_best6_excl_lo"](marks, {"subject_count": 1}) == 1


# --- level_bands (VUT-style 8-point scale) -------------------------------

_VUT_BANDS = [
    {"level": 8, "min": 90, "max": 100}, {"level": 7, "min": 80, "max": 89},
    {"level": 6, "min": 70, "max": 79}, {"level": 5, "min": 60, "max": 69},
    {"level": 4, "min": 50, "max": 59}, {"level": 3, "min": 40, "max": 49},
    {"level": 2, "min": 30, "max": 39}, {"level": 1, "min": 0, "max": 29},
]


def test_level_bands_splits_the_top_standard_band_into_two() -> None:
    # 85% is level 7 on BOTH scales (standard NSC caps at 7 for 80-100%
    # entirely; VUT's own scale narrows level 7 to just 80-89%).
    assert SCORERS["aps_best6_excl_lo"]({"mathematics": 85}, {"subject_count": 1, "level_bands": _VUT_BANDS}) == 7
    # 95% is level 8 on VUT's scale specifically -- the standard scale has
    # no level 8 at all and would cap this at 7, undercounting VUT's real APS.
    assert SCORERS["aps_best6_excl_lo"]({"mathematics": 95}, {"subject_count": 1, "level_bands": _VUT_BANDS}) == 8


def test_level_bands_default_is_none_so_the_standard_1_to_7_scale_applies() -> None:
    assert SCORERS["aps_best6_excl_lo"]({"mathematics": 95}, {"subject_count": 1}) == 7


def test_level_bands_below_every_band_falls_back_to_level_one() -> None:
    sparse_bands = [{"level": 5, "min": 50, "max": 100}]  # no band covers 0-49
    assert SCORERS["aps_best6_excl_lo"]({"mathematics": 20}, {"subject_count": 1, "level_bands": sparse_bands}) == 1


def test_level_bands_and_zero_below_level_compose() -> None:
    marks = {"mathematics": 95, "history": 20}  # levels 8 and 1 on VUT's scale
    result = SCORERS["aps_best6_excl_lo"](
        marks, {"subject_count": 2, "level_bands": _VUT_BANDS, "zero_below_level": 2},
    )
    assert result == 8 + 0  # history's level 1 zeroed, mathematics' level 8 untouched


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


# --- custom_points_with_bonus (Wits/SPU-style, unregistered) -------------

# A small, made-up points table for testing -- NOT Wits' or SPU's real
# config (neither is verified yet, see docs/scoring/wits.md, spu.md).
_TEST_POINTS_TABLE = [[90, 8], [80, 7], [70, 6], [60, 5], [50, 4], [40, 3], [30, 2], [0, 1]]
_TEST_LO_TABLE = [[90, 4], [80, 3], [70, 2], [60, 1], [0, 0]]


def test_custom_points_with_bonus_uses_the_configured_table_not_nsc_levels() -> None:
    marks = {"geography": 92}  # would be level 7 on the standard scale
    result = SCORERS["custom_points_with_bonus"](
        marks, {"points_table": _TEST_POINTS_TABLE, "subject_count": 1},
    )
    assert result == 8  # the config's own top band, not 7


def test_custom_points_with_bonus_life_orientation_uses_its_own_table() -> None:
    marks = {"life_orientation": 92}
    result = SCORERS["custom_points_with_bonus"](
        marks,
        {
            "points_table": _TEST_POINTS_TABLE,
            "life_orientation_points_table": _TEST_LO_TABLE,
            "subject_count": 1,
        },
    )
    assert result == 4  # LO's own capped table, not the 8-point ordinary one


def test_custom_points_with_bonus_life_orientation_is_included_not_excluded() -> None:
    # Unlike aps_best6_excl_lo, LO competes for a place rather than being
    # dropped outright -- with only one subject offered, it must count.
    marks = {"life_orientation": 50}
    result = SCORERS["custom_points_with_bonus"](
        marks,
        {
            "points_table": _TEST_POINTS_TABLE,
            "life_orientation_points_table": _TEST_LO_TABLE,
            "subject_count": 1,
        },
    )
    assert result == 0  # LO's own table: below 60% -> 0, but it still counted


def test_custom_points_with_bonus_named_subject_bonus_stacks_on_base_points() -> None:
    marks = {"mathematics": 65}  # base points_table: 60-69 -> 5
    result = SCORERS["custom_points_with_bonus"](
        marks,
        {"points_table": _TEST_POINTS_TABLE, "bonus": {"mathematics": [[60, 2], [40, 1]]}, "subject_count": 1},
    )
    assert result == 5 + 2


def test_custom_points_with_bonus_home_language_bonus_applies_to_whichever_hl_subject_is_offered() -> None:
    marks = {"isizulu_hl": 65}  # base: 5, +2 home-language bonus
    result = SCORERS["custom_points_with_bonus"](
        marks,
        {"points_table": _TEST_POINTS_TABLE, "bonus_for_home_language": [[60, 2], [40, 1]], "subject_count": 1},
    )
    assert result == 5 + 2


def test_custom_points_with_bonus_home_language_bonus_never_applies_to_fal() -> None:
    marks = {"isizulu_fal": 65}  # not "_hl" -- no bonus
    result = SCORERS["custom_points_with_bonus"](
        marks,
        {"points_table": _TEST_POINTS_TABLE, "bonus_for_home_language": [[60, 2], [40, 1]], "subject_count": 1},
    )
    assert result == 5


def test_custom_points_with_bonus_subject_count_defaults_to_seven() -> None:
    marks = {f"subject{i}": 65 for i in range(9)}  # 9 subjects, each worth 5
    result = SCORERS["custom_points_with_bonus"](marks, {"points_table": _TEST_POINTS_TABLE})
    assert result == 5 * 7  # best 7 of 9, not all 9 and not just 6


def test_registry_contains_custom_points_with_bonus() -> None:
    assert "custom_points_with_bonus" in SCORERS
