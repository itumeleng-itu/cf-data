"""Works out the minimum APS score a specific programme actually requires
for THIS learner.

Why this needs its own logic: a programme's required APS isn't always a
single fixed number. Some programmes publish two (or more) different
minimums depending on which subject the learner took — for example "APS
26 with Mathematics, or APS 28 with Mathematical Literacy". This file
picks the right one to compare the learner against.

Score-threshold selection shared between main.py and tests, so
production and test logic can never silently diverge."""

from app.subjects import percentage_to_level


def select_score_threshold(score_entries: list[dict], marks: dict[str, int]) -> int | None:
    """Given a programme's list of possible APS thresholds and a
    learner's subject marks, returns the LOWEST threshold that actually
    applies to this learner (easiest to reach). Returns None if none of
    the published thresholds apply at all -- e.g. every threshold requires
    either Mathematics or Mathematical Literacy and the learner took
    neither. The caller must treat that as a failure, not fall back to
    an arbitrary threshold.

    An entry's `requires_subject` alone only means "this subject appears
    on the learner's certificate at all" -- for institutions where a
    programme's alternative electives can genuinely coexist on one real
    transcript (e.g. TUT's "Accounting, or Mathematics/Technical
    Mathematics, or Mathematical Literacy" routes -- unlike UJ's
    Mathematics/Mathematical Literacy pairs, which never coexist on a
    real NSC certificate), that alone isn't enough: a learner can hold a
    weak Accounting mark (present, but below the Accounting route's own
    minimum) *and* a strong Mathematical Literacy mark, and this function
    must not let the weak subject's lower threshold apply just because
    the subject is present. An entry's optional `requires_level` closes
    that gap -- when set, the subject must ALSO be at or above that
    level for the entry to be applicable, not merely present. Omitted
    (the UJ case) means "presence alone is enough," exactly the previous
    behaviour -- fully backward compatible."""
    applicable = []
    for entry in score_entries:
        subject = entry.get("requires_subject")
        if subject is None:
            applicable.append(entry["min_score"])
            continue
        if subject not in marks:
            continue
        min_level = entry.get("requires_level")
        if min_level is not None and percentage_to_level(marks[subject]) < min_level:
            continue
        applicable.append(entry["min_score"])
    return min(applicable) if applicable else None
