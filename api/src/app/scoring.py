"""Calculates a learner's overall "APS" (Admission Point Score) — the
single number most South African universities use as a first filter
before even looking at individual subject requirements.

In plain terms: APS turns a whole matric certificate into one score, by
converting each subject's percentage into a level (1-7) and adding up the
best few. But every university does this slightly differently, so this
file is a small, growable library of scoring recipes — one function per
institution's rule — rather than one hardcoded formula.

APS scoring strategies. APS is not universal — each institution's rule is
a pure function over raw percentages, registered by scoring_strategy
name. Add Stellenbosch etc. by adding one function here and one registry
entry; no refactor of callers required.

APS is institution-wide, not per-programme: excluded_subjects governs
whether a subject can SATISFY a requirement (see evaluator.py), not
whether it counts toward the score. Technical Mathematics still
contributes to a learner's APS even on a programme that won't accept it
in place of Mathematics."""

from collections.abc import Callable

from app.subjects import percentage_to_level

_LIFE_ORIENTATION = "life_orientation"


def _aps_best6_excl_lo(marks: dict[str, int]) -> int:
    """University of Johannesburg's APS formula: convert every subject's
    percentage to a level, ignore Life Orientation entirely (it's
    compulsory but doesn't count towards APS at UJ), then add up the
    SIX highest levels. A learner who took 7+ subjects only benefits
    from their best six."""
    levels = sorted(
        (percentage_to_level(pct) for subject, pct in marks.items() if subject != _LIFE_ORIENTATION),
        reverse=True,
    )
    return sum(levels[:6])


# The registry: maps each institution's scoring_strategy name (stored
# alongside it in the database) to the function that implements it. This
# is how the API looks up "which formula do I use for this university?"
# at request time.
SCORERS: dict[str, Callable[[dict[str, int]], int]] = {
    "aps_best6_excl_lo": _aps_best6_excl_lo,
}
