import pytest

from app.subjects import LANGUAGE_FAMILIES, Subject, percentage_to_level


@pytest.mark.parametrize(
    ("pct", "level"),
    [
        (0, 1), (29, 1),
        (30, 2), (39, 2),
        (40, 3), (49, 3),
        (50, 4), (59, 4),
        (60, 5), (69, 5),
        (70, 6), (79, 6),
        (80, 7), (100, 7),
    ],
)
def test_percentage_to_level_bands(pct: int, level: int) -> None:
    assert percentage_to_level(pct) == level


@pytest.mark.parametrize("pct", [-1, 101, 1000])
def test_percentage_to_level_rejects_out_of_range(pct: int) -> None:
    with pytest.raises(ValueError):
        percentage_to_level(pct)


def test_language_families_keys_are_valid_subjects() -> None:
    valid = {s.value for s in Subject}
    for hl, fal in LANGUAGE_FAMILIES.values():
        assert hl in valid
        assert fal in valid
