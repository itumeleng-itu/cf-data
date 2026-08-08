"""Per-field majority vote across three independent extraction candidates.
Pure function -- no PDF I/O, no database. reconcile() decides what the
merged record says and how much to trust each field; the pipeline (not
built this pass) is responsible for turning the result into a
`programmes` row plus its `verification` jsonb column.

Per-field, not per-record, per the explicit design constraint: a record
with every field agreed except campus goes to review for campus only,
never treated as a fully-untrusted record. A method returning None for a
specific field is an ABSTENTION, not a vote against the other two -- it
is excluded from that field's tally entirely rather than counted as a
third, dissenting opinion.
"""

from typing import Any

_LABELS = ("a", "b", "c")


def _get(candidate: dict | None, path: tuple[str, ...]) -> Any:
    if candidate is None:
        return None
    current: Any = candidate
    for part in path:
        if current is None:
            return None
        current = current.get(part)
    return current


def _set_nested(target: dict, path: tuple[str, ...], value: Any) -> None:
    current = target
    for part in path[:-1]:
        current = current.setdefault(part, {})
    current[path[-1]] = value


def _identity_key(value: Any) -> Any:
    return value


def _set_key(value: Any) -> Any:
    return None if value is None else frozenset(value)


def _score_key(value: Any) -> Any:
    if value is None:
        return None
    return frozenset(frozenset(entry.items()) for entry in value)


def _tree_key(node: Any) -> Any:
    """Canonical, order-insensitive key for a requirements.nsc.subjects
    rule tree -- reordering an `any`/`all` node's children must still
    compare equal, since that's not a real disagreement between methods."""
    if node is None:
        return None
    if not isinstance(node, dict):
        return repr(node)
    kind = node.get("kind")
    if kind in ("all", "any"):
        # sort by repr(), not the raw keys: sibling subject/language nodes
        # produce tuples with None in different positions (e.g. a subject
        # node's language slot vs a language node's subject slot), which
        # aren't orderable against each other directly.
        children = tuple(sorted((_tree_key(child) for child in node.get("rules", [])), key=repr))
        return (kind, children)
    if kind == "subject":
        return (kind, node.get("subject"), node.get("language"), node.get("min_level"), node.get("min_level_fal"))
    if kind == "any_additional_language":
        return (kind, node.get("min_level"))
    return repr(node)


# (field_name, path into a candidate dict, canonicalisation for equality)
_FIELDS: list[tuple[str, tuple[str, ...], Any]] = [
    ("qualification_code", ("qualification_code",), _identity_key),
    ("name", ("name",), _identity_key),
    ("faculty", ("faculty",), _identity_key),
    ("campus", ("campus",), _set_key),
    ("duration_years", ("duration_years",), _identity_key),
    ("extended", ("extended",), _identity_key),
    ("requirements.nsc.score", ("requirements", "nsc", "score"), _score_key),
    ("requirements.nsc.subjects", ("requirements", "nsc", "subjects"), _tree_key),
    ("requirements.nsc.excluded_subjects", ("requirements", "nsc", "excluded_subjects"), _set_key),
]


def _reconcile_field(
    path: tuple[str, ...], key_fn: Any, candidates: list[dict | None],
) -> tuple[Any, float, dict[str, Any] | None]:
    raw_values = [_get(candidate, path) for candidate in candidates]
    present = [(label, value) for label, value in zip(_LABELS, raw_values) if value is not None]

    if not present:
        return None, 0.0, None
    if len(present) == 1:
        return present[0][1], 0.5, None

    keyed = [(label, value, key_fn(value)) for label, value in present]
    counts: dict[Any, int] = {}
    for _label, _value, key in keyed:
        counts[key] = counts.get(key, 0) + 1
    best_key, best_count = max(counts.items(), key=lambda item: item[1])

    if best_count == len(keyed):
        merged_value = next(value for _label, value, key in keyed if key == best_key)
        return merged_value, 1.0, None
    if best_count > 1:
        merged_value = next(value for _label, value, key in keyed if key == best_key)
        minority = {label: value for label, value, key in keyed if key != best_key}
        return merged_value, 0.66, minority
    all_candidates = {label: value for label, value, _key in keyed}
    return None, 0.0, all_candidates


def _dedup_preserve_order(items: list[Any]) -> list[Any]:
    return list(dict.fromkeys(items))


def reconcile(a: dict | None, b: dict | None, c: dict | None) -> tuple[dict, dict[str, float]]:
    candidates = [a, b, c]
    merged: dict = {}
    confidence: dict[str, float] = {}
    disagreements: dict[str, dict[str, Any]] = {}

    for field_name, path, key_fn in _FIELDS:
        merged_value, field_confidence, minority = _reconcile_field(path, key_fn, candidates)
        confidence[field_name] = field_confidence
        _set_nested(merged, path, merged_value)
        if minority:
            disagreements[field_name] = minority

    merged["selection_notes"] = _dedup_preserve_order(
        [note for candidate in candidates if candidate is not None for note in (candidate.get("selection_notes") or [])]
    )

    # Never reproduce prospectus marketing prose, regardless of what any
    # method returned -- policy, not something a majority vote can override.
    merged["career_text"] = None

    footnotes = _dedup_preserve_order(
        [
            (fn["marker"], fn["cell_ref"], fn["footnote_text"])
            for candidate in candidates if candidate is not None
            for fn in (candidate.get("unresolved_footnotes") or [])
        ]
    )
    footnotes_expanded = [{"marker": m, "cell_ref": ref, "footnote_text": text} for m, ref, text in footnotes]

    merged["disagreements"] = disagreements
    needs_review = bool(footnotes_expanded) or any(value < 1.0 for value in confidence.values())
    merged["verification"] = {
        "needs_review": needs_review,
        "fields": {name: value for name, value in confidence.items() if value < 1.0},
        "footnotes": footnotes_expanded,
    }

    return merged, confidence
