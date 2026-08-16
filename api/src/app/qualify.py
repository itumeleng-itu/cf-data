"""Works out the minimum APS score a specific programme actually requires
for THIS learner.

Why this needs its own logic: a programme's required APS isn't always a
single fixed number. Some programmes publish two (or more) different
minimums depending on which subject the learner took — for example "APS
26 with Mathematics, or APS 28 with Mathematical Literacy". This file
picks the right one to compare the learner against.

Score-threshold selection shared between main.py and tests, so
production and test logic can never silently diverge."""


def select_score_threshold(score_entries: list[dict], marks: dict[str, int]) -> int | None:
    """Given a programme's list of possible APS thresholds and a
    learner's subject marks, returns the LOWEST threshold that actually
    applies to this learner (easiest to reach). Returns None if none of
    the published thresholds apply at all -- e.g. every threshold requires
    either Mathematics or Mathematical Literacy and the learner took
    neither. The caller must treat that as a failure, not fall back to
    an arbitrary threshold."""
    applicable = [
        entry["min_score"] for entry in score_entries
        if entry.get("requires_subject") is None or entry["requires_subject"] in marks
    ]
    return min(applicable) if applicable else None
