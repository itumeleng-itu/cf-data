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


def test_aps_best6_excl_lo_canonical_fixture() -> None:
    assert SCORERS["aps_best6_excl_lo"](CANONICAL_MARKS) == 41


def test_life_orientation_excluded_even_when_raised() -> None:
    marks = {**CANONICAL_MARKS, "life_orientation": 100}
    assert SCORERS["aps_best6_excl_lo"](marks) == 41


def test_best6_drops_lowest_when_more_than_six_subjects() -> None:
    marks = {**CANONICAL_MARKS, "history": 35}  # 7th non-LO subject, level 2, lowest
    assert SCORERS["aps_best6_excl_lo"](marks) == 41


def test_sums_all_when_fewer_than_six_subjects_no_padding() -> None:
    marks = {"mathematics": 88, "english_hl": 87}
    assert SCORERS["aps_best6_excl_lo"](marks) == 14


def test_empty_marks_returns_zero_without_raising() -> None:
    assert SCORERS["aps_best6_excl_lo"]({}) == 0


def test_registry_contains_aps_best6_excl_lo() -> None:
    assert "aps_best6_excl_lo" in SCORERS
    assert callable(SCORERS["aps_best6_excl_lo"])
