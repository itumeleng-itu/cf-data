"""Footnote marker detection and legend resolution -- first-class, not an
afterthought, per the task: a footnote that materially changes a
requirement and can't be encoded in the rule tree must surface, not
silently vanish.

Confirmed on the real UJ 2027 PDF before writing this (not assumed): a
footnote's LEGEND is not necessarily on the same page as the marked cell.
B2M43Q (page 89) carries a "**" marker on its Physical Science cell; the
legend defining "**" is printed once at the bottom of page 88 and shared
across the whole multi-page Faculty of Science section. find_legend_text
therefore searches backward across pages, not just the current one.

Known real case this directly targets: UJ B2M43Q publishes Physical
Sciences level 5, with the "**" footnote lowering it to 4 depending on
which first-year module (Chemistry/Physics variant) is included -- the
schema has no concept of module choice. Methods A/B already encode the
PUBLISHED value (5, the stricter one) because that's the literal printed
cell content, so no special "pick the stricter value" logic is needed
here; this module's job is purely to detect and attach the footnote so
the record gets flagged for review rather than silently accepted as
unconditional.
"""

import re
from typing import Any

_LEGEND_LINE_PATTERN = re.compile(r"^(\*{1,3})\s+([A-Za-z].*)$")


def detect_footnote_markers(text: str, markers: list[str]) -> list[str]:
    """Longest markers first, consuming matched characters before
    checking shorter ones -- a "**" marker must not also be reported as a
    bare "*" footnote just because "*" is a substring of "**"."""
    remaining = text
    found: list[str] = []
    for marker in sorted(set(markers), key=len, reverse=True):
        if marker and marker in remaining:
            found.append(marker)
            remaining = remaining.replace(marker, "")
    return found


def find_legend_text(pdf: Any, page_num: int, marker: str, max_lookback: int = 5) -> str | None:
    """Searches page_num, then up to max_lookback pages before it, for a
    line that STARTS with exactly this marker (the legend definition),
    as opposed to a line that merely contains the marker somewhere (a
    marked data cell)."""
    earliest = max(page_num - max_lookback - 1, 0)
    for p in range(page_num, earliest, -1):
        text = pdf.pages[p - 1].extract_text() or ""
        for line in text.split("\n"):
            match = _LEGEND_LINE_PATTERN.match(line.strip())
            if match and match.group(1) == marker:
                return match.group(2).strip()
    return None


def _row_window(text: str, qualification_code: str, code_pattern: re.Pattern) -> str | None:
    """The block of page text belonging to one programme's row: from its
    own code (forward or reversed -- rotated pages store it reversed) up
    to wherever the NEXT programme's code appears."""
    start = None
    for candidate in (qualification_code, qualification_code[::-1]):
        idx = text.find(candidate)
        if idx != -1 and (start is None or idx < start):
            start = idx
    if start is None:
        return None

    next_positions = [m.start() for m in code_pattern.finditer(text, start + 1)]
    end = min(next_positions) if next_positions else len(text)
    return text[start:end]


def find_footnotes_for_code(
    pdf: Any, page_num: int, qualification_code: str, profile: dict, max_lookback: int = 5,
) -> list[dict]:
    """Returns [{marker, cell_ref, footnote_text}, ...] for footnote
    markers found in this programme's own row on the page, each resolved
    against its legend. A marker with no resolvable legend is dropped
    rather than attached with an empty explanation."""
    markers = profile["layout"].get("footnote_markers", [])
    if not markers:
        return []

    code_pattern = re.compile(profile["layout"]["code_pattern"])
    page = pdf.pages[page_num - 1]
    text = page.extract_text() or ""
    window = _row_window(text, qualification_code, code_pattern)
    if window is None:
        return []

    results = []
    for marker in detect_footnote_markers(window, markers):
        legend = find_legend_text(pdf, page_num, marker, max_lookback)
        if legend:
            results.append({"marker": marker, "cell_ref": qualification_code, "footnote_text": legend})
    return results
