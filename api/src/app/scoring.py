"""Calculates a learner's overall admission score — the single number
most South African universities use as a first filter before even
looking at individual subject requirements.

In plain terms: an admission score turns a whole matric certificate into
one number, usually by converting each subject's percentage into a level
(1-7) and adding up the best few. But every university does this
differently — some sum levels, some sum raw percentages and divide, some
double specific subjects for specific faculties — so this file is a
small, growable library of scoring ALGORITHMS, each one parameterised by
a `scoring_config` dict rather than hardcoded to one institution's rule.

WHY A CONFIG DICT, NOT ONE FUNCTION PER INSTITUTION
----------------------------------------------------
The previous version of this file had exactly that: one function per
institution, "aps_best6_excl_lo" meaning specifically and only UJ's rule.
That doesn't survive a second institution. CPUT's "best six, excluding
Life Orientation" is the SAME shape as UJ's, with different parameters
(raw percentages instead of levels, divided by 10). A faculty inside one
institution can also need a different formula from its own siblings —
UCT's Faculty of Science doubles Mathematics and Physical Sciences within
an otherwise-normal APS; its Commerce faculty doesn't. So scoring
resolves in two layers: SCORERS[strategy] picks the algorithm, and a
config dict (institution default, overridable per programme — see
qualify.py's caller in main.py) supplies that algorithm's parameters.
Three or four algorithms with different config cover most of the 26
public universities; the variation lives in data, not in new functions.

WHY EVERY SCORER MUST HAVE A WORKED EXAMPLE
--------------------------------------------
A wrong REQUIREMENT breaks one programme. A wrong SCORER breaks every
programme at that institution — consistently, invisibly, with nothing
about any individual record looking anomalous, because the arithmetic is
internally consistent even when it's wrong (a systematically-off formula
still produces a plausible-looking APS for every learner it's given). The
requirement-tree validators in scripts/validate_data.py cannot catch this
class of error at all — they check one programme's numbers against
themselves, never a whole institution's formula against the university's
own published arithmetic. The university's own worked example, taken
verbatim from its prospectus, is the only independent check available.
See tests/test_scoring_worked_examples.py, which every scorer here is
required to pass — or, where a prospectus prints no worked example, the
scorer is written from the prose and its status recorded as UNVERIFIED in
docs/scoring/{id}.md instead.

WHY SCORES ARE FLOORED TO int, NEVER LEFT AS A FLOAT
------------------------------------------------------
CPUT's own worked example divides 304 by 10 and prints "30.4" — a
fraction, if taken literally. This module returns int(30) instead, and
that is not a rounding error: admission thresholds themselves
(programme.requirements.nsc.score[].min_score, seeds/programme.schema.json)
are always whole numbers, and for any integer threshold n,
floor(x) >= n if and only if x >= n. Flooring the achieved score can
therefore never flip a qualify/fail outcome versus comparing the exact
fraction — it only avoids threading a float through the rest of the API
(scores dict, margin arithmetic, response schema) for a distinction that
provably never changes an answer.

APS/points are institution- (or programme-) wide, not requirement-wide:
excluded_subjects (requirements.nsc.excluded_subjects) governs whether a
subject can SATISFY a specific requirement (see evaluator.py), never
whether it counts toward the score. A programme that won't accept
Technical Mathematics in place of Mathematics still has Technical
Mathematics contribute to the learner's score if the scoring algorithm's
own exclude_subjects/weights say it should."""

from collections.abc import Callable

from app.subjects import percentage_to_level

_LIFE_ORIENTATION = "life_orientation"


def _aps_best6_excl_lo(marks: dict[str, int], config: dict) -> int:
    """Sum of the N highest achievement LEVELS (percentage converted via
    the standard 1-7 NSC bands), certain subjects never counted at all.

    This is UJ's rule (see UJ 2027 prospectus p.16, "How to determine
    your Admission Point Score") and, unparameterised, the most common
    shape across SA universities generally: convert every subject to a
    level, drop Life Orientation, add the best six.

    Config:
      subject_count     how many of the learner's best subjects count.
                         Default 6.
      exclude_subjects  subject slugs that never contribute, regardless
                         of level. Default ["life_orientation"] -- LO is
                         compulsory on every NSC certificate but no
                         public university counts it toward APS.
    """
    subject_count = config.get("subject_count", 6)
    exclude = set(config.get("exclude_subjects", [_LIFE_ORIENTATION]))
    levels = sorted(
        (percentage_to_level(pct) for subject, pct in marks.items() if subject not in exclude),
        reverse=True,
    )
    return sum(levels[:subject_count])


def _percentage_sum_div_10(marks: dict[str, int], config: dict) -> int:
    """Sum of the N highest RAW PERCENTAGES (not levels), divided by a
    divisor, certain subjects never counted.

    This is CPUT's Method 1, "Best of six subjects" (CPUT 2027 prospectus
    p.3, "CALCULATING THE APS SCORE"): "calculated using the percentage
    score for the 6 highest scoring subjects ... excluding Life
    Orientation ... adding up all the raw scores, and dividing by 10."
    The prospectus's own worked example divides unevenly (304 / 10 =
    30.4); this floors to 30 via integer division -- see the module
    docstring for why that never changes a qualify/fail outcome.

    Config:
      subject_count     how many of the learner's best subjects count.
                         Default 6.
      divisor           what the summed percentages are divided by.
                         Default 10.
      exclude_subjects  subject slugs that never contribute. Default
                         ["life_orientation"].
    """
    subject_count = config.get("subject_count", 6)
    divisor = config.get("divisor", 10)
    exclude = set(config.get("exclude_subjects", [_LIFE_ORIENTATION]))
    percentages = sorted(
        (pct for subject, pct in marks.items() if subject not in exclude),
        reverse=True,
    )
    return sum(percentages[:subject_count]) // divisor


def _weighted_levels(marks: dict[str, int], config: dict) -> int:
    """Sum of the N highest WEIGHTED levels: each subject's level
    (percentage converted via the standard 1-7 bands) is multiplied by a
    per-subject weight before the best N are added up.

    Modelled on the UCT/Wits "faculty points" shape described in
    docs/scoring/uct.md and wits.md -- e.g. UCT's Faculty of Science
    "doubles the scores achieved for Mathematics and Physical Sciences"
    within an otherwise-standard APS. NOT registered against either
    institution yet and has no worked-example test: both docs were a
    read-only investigation, explicitly not a verified scoring config
    (see their own headers), and encoding one now would be inventing a
    formula rather than transcribing one. See
    docs/scoring/weighted_levels.md for the UNVERIFIED record this
    module docstring requires. Register a scoring_strategy that uses this
    once a human has read a real worked example and can write a test for
    it, per tests/test_scoring_worked_examples.py.

    To EXCLUDE a subject entirely, give it weight 0 -- it will only ever
    contribute 0 regardless of level, and (having no positive weighted
    value to compete on) is automatically pushed out of the top N by any
    subject with a positive weight. This is deliberately the same
    mechanism as weighting, not a separate exclude_subjects config key:
    "counts for nothing" and "is excluded" are the same outcome here.

    Config:
      weights          {subject_slug: multiplier}. Default {}.
      default_weight   multiplier for any subject not named in `weights`.
                        Default 1.
      subject_count    how many of the learner's best WEIGHTED subjects
                        count. Default 6.
    """
    weights: dict[str, int] = config.get("weights", {})
    default_weight = config.get("default_weight", 1)
    subject_count = config.get("subject_count", 6)
    weighted = sorted(
        (percentage_to_level(pct) * weights.get(subject, default_weight) for subject, pct in marks.items()),
        reverse=True,
    )
    return sum(weighted[:subject_count])


# The registry: maps each institution's (or programme override's)
# scoring_strategy name to the algorithm that implements it. Every
# function here takes (marks, resolved_config) and returns an int score
# -- see the module docstring for why the config is a separate argument
# and why the return type is always int, never a float.
SCORERS: dict[str, Callable[[dict[str, int], dict], int]] = {
    "aps_best6_excl_lo": _aps_best6_excl_lo,
    "percentage_sum_div_10": _percentage_sum_div_10,
    "weighted_levels": _weighted_levels,
}
