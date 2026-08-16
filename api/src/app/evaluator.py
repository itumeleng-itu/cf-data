"""This is the file that actually decides "does this learner qualify for
this specific programme?" — the heart of the whole app.

In plain terms: every programme in the database stores its subject
requirements as a small tree of rules, e.g. "you need English AND (Maths
OR Maths Literacy) AND Physical Sciences". This file walks that tree
against one learner's marks and reports back either "you qualify" (an
empty list) or a list of specific reasons why not (e.g. "Requires
Mathematics level 5; you have level 4"), so the app can show a learner
exactly what they're missing, not just a plain rejection.

Pure, total evaluation of the recursive requirement tree stored in
programmes.requirements.nsc.subjects. Never raises on malformed input --
an unknown or malformed rule degrades to a Failure instead.

Excluded-subject semantics: `excluded` subjects cannot SATISFY a
requirement and cannot COUNT toward the score, but merely holding one is
never itself a failure -- lookups just treat those keys as absent. A
student with Mathematics 6 and Technical Mathematics 5 qualifies on their
Mathematics; there is no "forbidden subject" failure kind.

Language consumption: when a language subject rule passes, that family is
"consumed" so a sibling any_additional_language rule doesn't also accept
it. This is threaded explicitly via consumed_language, never inferred by
scanning the tree -- inference is fragile and breaks under reordering.
"""

from dataclasses import dataclass

from app.subjects import LANGUAGE_FAMILIES, percentage_to_level


@dataclass(frozen=True, slots=True)
class Failure:
    """One specific reason a learner doesn't meet a requirement — e.g.
    "you needed Mathematics level 5, you have level 4". A programme with
    zero Failures for a given learner means they qualify."""
    kind: str
    message: str
    required: int | None
    actual: int | None
    subject: str | None


# The percentage each achievement level (1-7) starts at, used only to
# build human-readable messages like "level 5 (60%+)" -- the actual
# level comparisons use percentage_to_level() in subjects.py.
MIN_PCT_FOR_LEVEL: dict[int, int] = {1: 0, 2: 30, 3: 40, 4: 50, 5: 60, 6: 70, 7: 80}

# Human-readable names for each language, used when building a message
# like "Requires English as a matric subject".
LANGUAGE_DISPLAY_NAMES: dict[str, str] = {
    "english": "English",
    "afrikaans": "Afrikaans",
    "isizulu": "isiZulu",
    "isixhosa": "isiXhosa",
    "sepedi": "Sepedi",
    "sesotho": "Sesotho",
    "setswana": "Setswana",
    "xitsonga": "Xitsonga",
    "siswati": "siSwati",
    "tshivenda": "Tshivenda",
    "isindebele": "isiNdebele",
}

# Human-readable names for each subject (the database stores the short
# "mathematics" form; the app shows the learner "Mathematics").
SUBJECT_DISPLAY_NAMES: dict[str, str] = {
    "mathematics": "Mathematics",
    "mathematical_literacy": "Mathematical Literacy",
    "technical_mathematics": "Technical Mathematics",
    "physical_sciences": "Physical Sciences",
    "technical_sciences": "Technical Sciences",
    "life_sciences": "Life Sciences",
    "life_orientation": "Life Orientation",
    "accounting": "Accounting",
    "business_studies": "Business Studies",
    "economics": "Economics",
    "geography": "Geography",
    "history": "History",
    "tourism": "Tourism",
    "consumer_studies": "Consumer Studies",
    "visual_arts": "Visual Arts",
    "dramatic_arts": "Dramatic Arts",
    "music": "Music",
    "design": "Design",
    "information_technology": "Information Technology",
    "computer_applications_technology": "Computer Applications Technology",
    "engineering_graphics_and_design": "Engineering Graphics and Design",
    "agricultural_sciences": "Agricultural Sciences",
    "hospitality_studies": "Hospitality Studies",
    "religion_studies": "Religion Studies",
}

_LANGUAGE_SUFFIXES = (("_hl", "Home Language"), ("_fal", "First Additional Language"))


def subject_display_name(key: str) -> str:
    """Turns a database subject code (e.g. "english_hl") into the label a
    learner would recognise (e.g. "English Home Language")."""
    if key in SUBJECT_DISPLAY_NAMES:
        return SUBJECT_DISPLAY_NAMES[key]
    for suffix, label in _LANGUAGE_SUFFIXES:
        if key.endswith(suffix):
            base = key[: -len(suffix)]
            return f"{LANGUAGE_DISPLAY_NAMES.get(base, base.title())} {label}"
    return LANGUAGE_DISPLAY_NAMES.get(key, key.replace("_", " ").title())


def _safe_level(pct: object) -> int | None:
    """Converts a raw percentage to an achievement level, or None if the
    value is missing or not usable -- never raises, since this runs
    against untrusted-shaped data from the database."""
    if pct is None:
        return None
    try:
        return percentage_to_level(pct)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def _valid_level(value: object) -> int | None:
    """Checks that a "required level" value from a programme's rule tree
    is actually a sensible level (a whole number from 1 to 7)."""
    return value if isinstance(value, int) and 1 <= value <= 7 else None


def _lookup(key: str, marks: dict[str, int], excluded: set[str]) -> int | None:
    """Looks up a learner's level in one subject, honouring exclusions:
    if a programme has excluded this subject (see the module docstring),
    it's treated as if the learner never took it at all."""
    if key in excluded:
        return None
    return _safe_level(marks.get(key))


def _malformed(kind: str, message: str) -> list[Failure]:
    """Builds a Failure for a rule that's broken or unrecognised in the
    database, rather than crashing the request -- a malformed rule is
    reported to the learner as "you don't qualify" (safe default) instead
    of taking the whole API down."""
    return [Failure(kind=kind, message=message, required=None, actual=None, subject=None)]


def evaluate(
    rule: dict,
    marks: dict[str, int],
    excluded: set[str],
    consumed_language: str | None = None,
) -> list[Failure]:
    """The main entry point: checks one requirement rule (which may
    contain nested sub-rules) against a learner's marks. Returns an empty
    list if they meet it, or a list of Failures explaining what's
    missing. This function is recursive -- it calls itself for each
    nested rule inside "all"/"any" groups."""
    if not isinstance(rule, dict):
        return _malformed("unknown", f"Malformed rule: expected an object, got {type(rule).__name__}")

    kind = rule.get("kind")
    if kind == "all":
        return _evaluate_all(rule, marks, excluded, consumed_language)
    if kind == "any":
        return _evaluate_any(rule, marks, excluded, consumed_language)
    if kind == "subject":
        return _evaluate_subject(rule, marks, excluded)
    if kind == "any_additional_language":
        return _evaluate_any_additional_language(rule, marks, excluded, consumed_language)
    return _malformed(str(kind), f"Unknown rule kind '{kind}'")


def _is_language_subject_node(child: object) -> bool:
    """True if this rule is asking for a LANGUAGE (like "English") rather
    than a single named subject (like "mathematics") -- languages need
    special handling because a learner picks one of two variants (Home
    Language or First Additional Language), never both."""
    return (
        isinstance(child, dict)
        and child.get("kind") == "subject"
        and "language" in child
        and "subject" not in child
    )


def _evaluate_all(rule: dict, marks: dict, excluded: set[str], consumed_language: str | None) -> list[Failure]:
    """Handles an "ALL of these" requirement group (e.g. English AND
    Mathematics AND Physical Sciences) -- the learner must pass every
    child rule, so every child's failures are collected and returned
    together."""
    failures: list[Failure] = []
    current_consumed = consumed_language
    for child in rule.get("rules") or []:
        if _is_language_subject_node(child):
            child_failures, newly_consumed = _evaluate_language_subject(child, marks, excluded)
            failures.extend(child_failures)
            if newly_consumed is not None:
                current_consumed = newly_consumed
        else:
            failures.extend(evaluate(child, marks, excluded, current_consumed))
    return failures


def _evaluate_any(rule: dict, marks: dict, excluded: set[str], consumed_language: str | None) -> list[Failure]:
    """Handles an "ANY of these" requirement group (e.g. Mathematics OR
    Mathematical Literacy) -- the learner only needs to pass ONE child
    rule. If none pass, reports the failure from whichever branch they
    came CLOSEST to meeting (fewest missing requirements), so the
    feedback is as useful as possible rather than an arbitrary pick."""
    children = rule.get("rules")
    if not children:
        return _malformed("any", "Malformed rule: 'any' node has no branches")
    branches = [evaluate(child, marks, excluded, consumed_language) for child in children]
    if any(not b for b in branches):
        return []
    return min(branches, key=len)


def _evaluate_subject(rule: dict, marks: dict, excluded: set[str]) -> list[Failure]:
    """Checks a single leaf requirement -- either a named subject (e.g.
    "Mathematics level 5") or a language family (e.g. "English level 4")
    -- and routes to the right check for each."""
    has_subject, has_language = "subject" in rule, "language" in rule
    if has_subject == has_language:
        return _malformed("subject", "Malformed rule: set exactly one of subject/language")

    if has_subject:
        min_level = _valid_level(rule.get("min_level"))
        if min_level is None:
            return _malformed("subject", f"Malformed rule: invalid min_level {rule.get('min_level')!r}")
        return _evaluate_subject_key(rule["subject"], min_level, marks, excluded)

    failures, _consumed = _evaluate_language_subject(rule, marks, excluded)
    return failures


def _evaluate_subject_key(
    key: str, min_level: int, marks: dict, excluded: set[str], subject_field: str | None = None,
) -> list[Failure]:
    """The actual pass/fail check for one specific subject: does the
    learner's level meet or beat the required minimum? Builds a clear,
    specific message either way (e.g. "you don't have this subject at
    all" vs "you have it, but at too low a level")."""
    level = _lookup(key, marks, excluded)
    field = subject_field if subject_field is not None else key
    if level is not None and level >= min_level:
        return []
    name = subject_display_name(key)
    if level is None:
        message = f"Requires {name} as a matric subject"
    else:
        threshold = MIN_PCT_FOR_LEVEL[min_level]
        message = f"Requires {name} level {min_level} ({threshold}%+); you have level {level} ({marks.get(key)}%)"
    return [Failure(kind="subject", message=message, required=min_level, actual=level, subject=field)]


def _evaluate_language_subject(rule: dict, marks: dict, excluded: set[str]) -> tuple[list[Failure], str | None]:
    """Checks a language requirement (e.g. "English level 4"). A learner
    only ever takes ONE of Home Language or First Additional Language for
    a given language, so this picks whichever variant the learner
    actually has and checks that one -- if they have both (rare edge
    case) it checks whichever one is closer to passing.
    Returns (failures, family_consumed_if_passed)."""
    language = rule.get("language")
    if language not in LANGUAGE_FAMILIES:
        return _malformed("subject", f"Malformed rule: unknown language family '{language}'"), None

    min_level = _valid_level(rule.get("min_level"))
    if min_level is None:
        return _malformed("subject", f"Malformed rule: invalid min_level {rule.get('min_level')!r}"), None
    min_level_fal = _valid_level(rule.get("min_level_fal", min_level)) or min_level

    hl_key, fal_key = LANGUAGE_FAMILIES[language]
    hl_level = _lookup(hl_key, marks, excluded)
    fal_level = _lookup(fal_key, marks, excluded)

    if hl_level is not None and hl_level >= min_level:
        return [], language
    if fal_level is not None and fal_level >= min_level_fal:
        return [], language

    if fal_level is not None and hl_level is None:
        return _evaluate_subject_key(fal_key, min_level_fal, marks, excluded, subject_field=language), None
    if hl_level is not None and fal_level is None:
        return _evaluate_subject_key(hl_key, min_level, marks, excluded, subject_field=language), None
    if hl_level is not None and fal_level is not None:
        hl_deficit = min_level - hl_level
        fal_deficit = min_level_fal - fal_level
        if hl_deficit <= fal_deficit:
            return _evaluate_subject_key(hl_key, min_level, marks, excluded, subject_field=language), None
        return _evaluate_subject_key(fal_key, min_level_fal, marks, excluded, subject_field=language), None

    display = LANGUAGE_DISPLAY_NAMES.get(language, language)
    return [Failure(
        kind="subject",
        message=f"Requires {display} as a matric subject",
        required=min_level, actual=None, subject=language,
    )], None


def _evaluate_any_additional_language(
    rule: dict, marks: dict, excluded: set[str], consumed_language: str | None,
) -> list[Failure]:
    """Checks a "some SECOND language at level X" requirement (common for
    programmes that want two languages but don't care which). Looks
    across every language the learner took, skipping whichever one
    already satisfied an earlier, separate language requirement
    (consumed_language) so the same language can't count twice."""
    min_level = _valid_level(rule.get("min_level"))
    if min_level is None:
        return _malformed(
            "any_additional_language", f"Malformed rule: invalid min_level {rule.get('min_level')!r}",
        )

    best_level: int | None = None
    for base, (hl_key, fal_key) in LANGUAGE_FAMILIES.items():
        if base == consumed_language:
            continue
        for key in (hl_key, fal_key):
            level = _lookup(key, marks, excluded)
            if level is None:
                continue
            if level >= min_level:
                return []
            if best_level is None or level > best_level:
                best_level = level

    threshold = MIN_PCT_FOR_LEVEL[min_level]
    if best_level is None:
        message = (
            f"Requires an additional language at level {min_level} ({threshold}%+); "
            f"you do not offer a second language"
        )
    else:
        message = (
            f"Requires an additional language at level {min_level} ({threshold}%+); "
            f"your best additional language is level {best_level}"
        )
    return [Failure(
        kind="any_additional_language", message=message, required=min_level, actual=best_level, subject=None,
    )]
