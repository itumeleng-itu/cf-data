"""Column/cell interpretation shared by Method A (textlayer.py) and Method
B (geometric.py). The two methods differ in how they find rows and
columns on a page -- word clustering vs pdfplumber's table detection --
but once a cell's raw text and its column's subject are known, turning
that into a requirement-tree fragment is identical logic, so it lives
here once rather than twice.

interpret_cell()'s four-way split (level / not_accepted / alternative /
empty) is what lets build_subject_tree() produce OPPOSITE structures for
the same subject from the same function: a not_accepted cell becomes an
excluded_subjects entry, an alternative cell becomes a sibling inside an
`any` node with the preceding column. Technical Mathematics/Technical
Science being excluded in one UJ programme and an accepted alternative in
another is not a special case anywhere in this module -- it falls out of
which phrase matched in that row's cell.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api" / "src"))
from app.subjects import LANGUAGE_FAMILIES, Subject  # noqa: E402

_LEVEL_PATTERN = re.compile(r"\b([1-7])\b")

# Singular/plural and phrasing variants seen in real prospectus headers
# that don't match a Subject enum value's underscore-to-space form
# directly (e.g. the enum is plural "physical_sciences" but UJ's own
# column header reads "Physical Science", singular).
_MANUAL_HEADER_ALIASES: dict[str, str] = {
    "physical science": "physical_sciences",
    "physical sciences": "physical_sciences",
    "technical science": "technical_sciences",
    "technical sciences": "technical_sciences",
    "life science": "life_sciences",
    "life sciences": "life_sciences",
    "mathematics literacy": "mathematical_literacy",
    "mathematical literacy": "mathematical_literacy",
}


@dataclass(frozen=True, slots=True)
class CellValue:
    """kind is one of 'level', 'not_accepted', 'alternative', 'empty'.
    level is set for 'level'/'alternative'; raw keeps the original cell
    text for footnote-marker detection downstream."""

    kind: str
    level: int | None = None
    raw: str = ""


def _phrase_words_present(phrase: str, lowered_text: str) -> bool:
    """All of the phrase's words appear in lowered_text, regardless of
    order -- rotated-text reconstruction (textlayer.py) orders separate
    words by their geometric advance position, which doesn't always
    match true reading order (a real UJ cell reconstructs as "accepted
    Not", not "Not accepted"). A multi-word phrase should still match."""
    return all(re.search(rf"\b{re.escape(word)}\b", lowered_text) for word in phrase.lower().split())


def _normalise_header(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def resolve_subject_column(header_text: str, profile: dict) -> str | None:
    """Maps a column header to a Subject slug or a language-family name
    (e.g. 'english'). Returns None rather than guessing when the header
    isn't recognised -- an unmapped column is dropped, not misattributed."""
    normalised = _normalise_header(header_text)
    if normalised in LANGUAGE_FAMILIES:
        return normalised
    if normalised in _MANUAL_HEADER_ALIASES:
        return _MANUAL_HEADER_ALIASES[normalised]
    for member in Subject:
        if member.value.replace("_", " ") == normalised:
            return member.value
    return None


def interpret_cell(text: str, profile: dict) -> CellValue:
    stripped = text.strip()
    if not stripped:
        return CellValue(kind="empty", raw=text)

    layout = profile["layout"]
    lowered = stripped.lower()

    if any(_phrase_words_present(phrase, lowered) for phrase in layout.get("not_accepted_phrases", [])):
        return CellValue(kind="not_accepted", raw=stripped)

    level_match = _LEVEL_PATTERN.search(stripped)
    level = int(level_match.group(1)) if level_match else None

    is_alternative = any(
        re.search(rf"\b{re.escape(phrase)}\b", stripped) for phrase in layout.get("alternative_phrases", [])
    )
    if is_alternative and level is not None:
        return CellValue(kind="alternative", level=level, raw=stripped)
    if level is not None:
        return CellValue(kind="level", level=level, raw=stripped)
    return CellValue(kind="empty", raw=stripped)


def _subject_node(slug: str, level: int) -> dict:
    if slug in LANGUAGE_FAMILIES:
        return {"kind": "subject", "language": slug, "min_level": level}
    return {"kind": "subject", "subject": slug, "min_level": level}


def build_subject_tree(row: list[tuple[str, CellValue]]) -> tuple[dict, set[str]]:
    """row is the ordered (subject_slug, CellValue) pairs for one
    programme's requirement row, left to right as they appear in the
    table. Order matters: an 'alternative' cell pairs with whichever
    column immediately precedes it, matching the real layout (UJ's
    Technical Science OR-column sits directly after Physical Science).
    Returns (rule_tree, excluded_subjects)."""
    excluded: set[str] = set()
    nodes: list[dict] = []

    for slug, cell in row:
        if cell.kind == "not_accepted":
            excluded.add(slug)
        elif cell.kind == "level":
            nodes.append(_subject_node(slug, cell.level))
        elif cell.kind == "alternative":
            alt_node = _subject_node(slug, cell.level)
            if nodes:
                preceding = nodes.pop()
                nodes.append({"kind": "any", "rules": [preceding, alt_node]})
            else:
                nodes.append(alt_node)
        # cell.kind == "empty": not required, contributes nothing

    return {"kind": "all", "rules": nodes}, excluded
