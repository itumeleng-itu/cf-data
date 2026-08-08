"""Score-threshold selection shared between main.py and tests, so
production and test logic can never silently diverge."""


def select_score_threshold(score_entries: list[dict], marks: dict[str, int]) -> int | None:
    """The lowest score threshold whose requires_subject (if any) the
    learner holds. None if no entry applies at all -- e.g. every threshold
    requires either Mathematics or Mathematical Literacy and the learner
    has neither. The caller must treat that as a failure, not fall back to
    an arbitrary threshold."""
    applicable = [
        entry["min_score"] for entry in score_entries
        if entry.get("requires_subject") is None or entry["requires_subject"] in marks
    ]
    return min(applicable) if applicable else None
