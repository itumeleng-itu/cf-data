"""Per-institution APS scoring strategies. APS is not universal — each
institution's rule is a pure function over raw percentages, registered by
scoring_strategy name. Add Stellenbosch etc. by adding one function here
and one registry entry; no refactor of callers required.

APS is institution-wide, not per-programme: excluded_subjects governs
whether a subject can SATISFY a requirement (see evaluator.py), not
whether it counts toward the score. Technical Mathematics still
contributes to a learner's APS even on a programme that won't accept it
in place of Mathematics."""

from collections.abc import Callable

from app.subjects import percentage_to_level

_LIFE_ORIENTATION = "life_orientation"


def _aps_best6_excl_lo(marks: dict[str, int]) -> int:
    levels = sorted(
        (percentage_to_level(pct) for subject, pct in marks.items() if subject != _LIFE_ORIENTATION),
        reverse=True,
    )
    return sum(levels[:6])


SCORERS: dict[str, Callable[[dict[str, int]], int]] = {
    "aps_best6_excl_lo": _aps_best6_excl_lo,
}
