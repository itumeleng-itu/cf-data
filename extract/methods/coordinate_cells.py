"""Coordinate-based table-cell reconstruction, shared by Method D
(extract/methods/coordinate.py). Ported near-verbatim from the verified
reference implementation (universities/uj_extract.py) per phase 8.5 --
this primitive is WHY that script works where Methods A and B's
table-cell reading does not, so it must not be rewritten, only relocated.

table.extract() (Method B) and a manual page.crop(bbox).extract_text()
call both interleave the words of a multi-line ROTATED cell -- confirmed
on real UJ data: "25 with Mathematics OR / 26 with Mathematical Literacy"
degrades to "Literacy OR Mathematics Mathematical with with 25 26". No
string reversal recovers that, because the LINE GROUPING itself is wrong
-- the cell has to be rebuilt from glyph coordinates instead of trusted
to either API's own cell-text assembly.
"""

from typing import Optional, Tuple


def cell_text(page, bbox: Optional[Tuple[float, float, float, float]]) -> str:
    """
    Read one table cell, reconstructing 90-degree-rotated text correctly.

      * pdfplumber tags each word with `upright`. If most words in the cell
        are rotated, the cell is treated as rotated.
      * For bottom-to-top text one visual LINE shares an x0, and reading
        order within that line runs from LARGER top to SMALLER top. Lines
        themselves run left-to-right by x0.
      * Each word's characters are still emitted in reverse, so we flip
        them.

    Bucketing x0 and top by 3pt absorbs sub-point baseline jitter.
    """
    if bbox is None:
        return ""
    x0, top, x1, bottom = bbox
    # Inset half a point so the ruling lines are not sampled as glyphs.
    crop = page.crop((x0 + 0.5, top + 0.5, x1 - 0.5, bottom - 0.5), strict=False)
    words = crop.extract_words(extra_attrs=["upright"], use_text_flow=False)
    if not words:
        return ""

    rotated = [w for w in words if not w["upright"]]
    if len(rotated) <= len(words) / 2:
        ordered = sorted(words, key=lambda w: (round(w["top"] / 3), w["x0"]))
        return " ".join(w["text"] for w in ordered)

    lines: dict[int, list[dict]] = {}
    for w in rotated:
        lines.setdefault(round(w["x0"] / 3), []).append(w)
    return "\n".join(
        " ".join(w["text"][::-1] for w in sorted(lines[k], key=lambda w: -w["top"]))
        for k in sorted(lines)
    )
