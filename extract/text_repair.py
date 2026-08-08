"""Repairs pdfplumber's character-order assembly for rotated text.

Several UJ 2027 pages (and CPUT's) render qualification codes, score
thresholds, and the accept/reject marker in a rotated (90-degree) text
run -- column headers and, on some pages, data cells that share the same
rotation. pdfplumber correctly identifies these via char["upright"] and
even correctly clusters the glyphs into words, but assembles them in the
wrong direction: it sorts by ascending on-page position assuming a
top-to-bottom read, when the character matrix (char["matrix"], the
(a, b, c, d, e, f) text-to-user-space transform) shows the true glyph
advance direction runs the other way. The result: 'B8BA3Q' extracts as
'Q3AB8B', '(60%+)' as ')+%06(', and -- the one that actually changes a
decision downstream -- 'Not accepted' as 'detpecca toN'. If Method A in
8.4 fails to match "Not accepted" because it reads backwards, a
programme that should exclude Technical Maths silently accepts it
instead.

normalise_page_text() re-derives the correct order directly from each
character's matrix rather than trusting pdfplumber's own assumption:
- Group non-upright characters by rotation signature and by the
  coordinate perpendicular to their advance direction (same column).
- Within each group, split into runs wherever the gap along the advance
  direction is too large to be the same phrase (a different table row
  reusing the same rotated column, not a word break -- calibrated
  against real UJ 2027 data: intra-phrase gaps topped out around 42
  advance-key units; the next row down in the same column was 500+).
- Sort each run by the advance-direction projection to get the correct
  character sequence, including any real space characters already
  present in page.chars (this document renders them explicitly; no
  whitespace needs to be synthesized).

An earlier version of this function tried to guess pdfplumber's own
(wrong) assembly for each run as a plain reversal of the correct text,
then find-and-replace it in page.extract_text()'s output. That broke on
real data in two ways, both confirmed on page 38 rather than assumed:
(1) pdfplumber's own line-breaking for a multi-word rotated run doesn't
correspond to a single space-joined string reversed as one unit -- e.g.
'Qualification Code' and 'Minimum APS' come out interleaved across
different `\n`-separated lines in pdfplumber's raw output, in a shape no
single reversal predicts; (2) a ligature glyph ('fi' as one character
entry in page.chars) breaks a plain Python string reversal, which flips
its internal letter order too, while pdfplumber's own wrong assembly
(which reverses the SEQUENCE of character entries, not each entry's own
text) does not. Rather than chase every such quirk, normalise_page_text
now APPENDS each run's correctly-ordered text instead of patching
pdfplumber's output in place. Downstream signal extraction (code_matches,
keyword_hits, etc.) only needs the correct text to be PRESENT somewhere
in the page's text, not positioned exactly where pdfplumber's original
(possibly still-reversed) text was -- so appending is both simpler and
strictly more robust than guessing a replacement target.

looks_reversed() is a separate, lightweight heuristic for spot-checking
a single already-extracted token or phrase without touching a PDF at
all -- useful for tests and ad-hoc QA of extraction output.
"""

import re
from typing import Any

_ROTATION_ROUND = 2
_PERP_ROUND = 1

# Advance-key units (see _advance_key). Calibrated against real UJ 2027
# data: the largest intra-phrase gap observed (between "Not" and
# "accepted", including the real space character between them) was ~42;
# the gap between one table row's marker cell and the next row's, sharing
# the same rotated column, was 500+. 100 sits with wide margin between the
# two, so runs split only at genuine cell/row boundaries.
_RUN_GAP_THRESHOLD = 100.0

_PERCENT_CELL_PATTERN = re.compile(r"^\)\+?%\d{2}\($")
_KNOWN_REVERSED_PHRASES = {"detpecca", "ton", "detpecca ton"}


def _advance_key(char: dict) -> float:
    a, b, _c, _d, e, f = char["matrix"]
    return a * e + b * f


def _perp_key(char: dict) -> float:
    a, b, _c, _d, e, f = char["matrix"]
    return round(-b * e + a * f, _PERP_ROUND)


def _rotation_signature(char: dict) -> tuple[float, float, float, float]:
    a, b, c, d, _e, _f = char["matrix"]
    return (round(a, _ROTATION_ROUND), round(b, _ROTATION_ROUND), round(c, _ROTATION_ROUND), round(d, _ROTATION_ROUND))


def _group_runs(chars: list[dict]) -> list[list[dict]]:
    """Groups non-upright chars into ordered runs: same rotation, same
    column (perpendicular coordinate), contiguous along the advance
    direction. Returns each run's chars pre-sorted into correct reading
    order."""
    keyed = sorted(
        ((_rotation_signature(c), _perp_key(c), _advance_key(c), c) for c in chars),
        key=lambda t: (t[0], t[1], t[2]),
    )

    runs: list[list[dict]] = []
    current: list[dict] = []
    prev_group_key: tuple | None = None
    prev_advance: float | None = None
    for rot, perp, advance, char in keyed:
        group_key = (rot, perp)
        starts_new_run = group_key != prev_group_key or (
            prev_advance is not None and advance - prev_advance > _RUN_GAP_THRESHOLD
        )
        if starts_new_run and current:
            runs.append(current)
            current = []
        current.append(char)
        prev_group_key = group_key
        prev_advance = advance
    if current:
        runs.append(current)
    return runs


def normalise_page_text(page: Any) -> str:
    """Returns page.extract_text()'s output with every rotated-text run's
    correctly-ordered text appended. Upright text is untouched --
    pdfplumber already extracts it correctly, as confirmed against this
    document's own non-rotated qualification codes. The original
    (possibly still wrong-order) text is left in place rather than
    surgically removed -- harmless duplication for presence-based signal
    extraction, and far more robust than guessing where in pdfplumber's
    output a corrected run belongs (see module docstring)."""
    baseline = page.extract_text() or ""

    non_upright = [c for c in page.chars if not c.get("upright", True)]
    if not non_upright:
        return baseline

    corrected_runs = ["".join(c["text"] for c in run) for run in _group_runs(non_upright)]
    return baseline + "\n" + "\n".join(corrected_runs)


def looks_reversed(token: str, code_pattern: str) -> bool:
    """True if `token` looks like it was extracted backwards: it fails
    code_pattern but its reverse matches, or it's a known reversed
    structural marker -- a percentage-in-parens cell (')+%06(' for
    '(60%+)') or the accept/reject marker ('detpecca'/'toN' for
    'accepted'/'Not'). Does not touch a PDF; operates on any already-
    extracted string, e.g. for spot-checking output in tests or ad-hoc QA.

    Known limitation, confirmed by direct computation rather than assumed:
    a code whose shape is symmetric under reversal (letter, digit, letter,
    letter, digit, letter -- e.g. 'B8BA3Q' vs 'Q3AB8B') matches
    code_pattern in BOTH directions, so this function can't tell them
    apart from shape alone and returns False for both. This is a real
    ambiguity, not a bug -- normalise_page_text never hits it, because it
    derives direction from the PDF's own character matrix instead of
    guessing from string shape.
    """
    if not token:
        return False

    reversed_token = token[::-1]
    if not re.fullmatch(code_pattern, token) and re.fullmatch(code_pattern, reversed_token):
        return True

    if _PERCENT_CELL_PATTERN.fullmatch(token):
        return True

    if token.lower() in _KNOWN_REVERSED_PHRASES:
        return True

    return False
