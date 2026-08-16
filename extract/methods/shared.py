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


def _strip_footnote_markers(text: str, profile: dict) -> str:
    """Removes profile.layout.footnote_markers substrings before any
    pattern matching -- diagnosed directly against the real UJ B2M43Q
    case before writing this: the marker sits on the HEADER text itself
    ("Physical Science **"), not only on data cells, which broke
    resolve_subject_column's exact alias match outright (interpret_cell's
    \\b-bounded patterns already tolerate a trailing "**" on a data cell
    fine -- confirmed directly, "5 (60%+)**" already parsed to level 5
    before this fix; stripping there is defensive, not the actual fix)."""
    stripped = text
    for marker in profile["layout"].get("footnote_markers", []):
        stripped = stripped.replace(marker, "")
    return stripped


def _normalise_header(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def resolve_subject_column(header_text: str, profile: dict) -> str | None:
    """Maps a column header to a Subject slug or a language-family name
    (e.g. 'english'). Returns None rather than guessing when the header
    isn't recognised -- an unmapped column is dropped, not misattributed."""
    normalised = _normalise_header(_strip_footnote_markers(header_text, profile))
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
    # raw keeps the ORIGINAL text (marker included) for footnote-marker
    # detection downstream -- only the copy used for pattern matching is
    # stripped.
    matchable = _strip_footnote_markers(stripped, profile)
    lowered = matchable.lower()

    if any(_phrase_words_present(phrase, lowered) for phrase in layout.get("not_accepted_phrases", [])):
        return CellValue(kind="not_accepted", raw=stripped)

    level_match = _LEVEL_PATTERN.search(matchable)
    level = int(level_match.group(1)) if level_match else None

    is_alternative = any(
        re.search(rf"\b{re.escape(phrase)}\b", matchable) for phrase in layout.get("alternative_phrases", [])
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


def _group_mutually_exclusive(nodes: list[dict], profile: dict) -> list[dict]:
    """Some subject alternatives carry no table-level marker at all --
    Mathematics vs Mathematical Literacy is a national NSC convention (no
    SA university requires both; they're alternative subject choices a
    learner picks between in matric), not a per-cell "/" merge or "OR"
    marker UJ happens to print. profile.layout.mutually_exclusive_subjects
    declares these groups per institution -- when 2+ PLAIN subject nodes
    from the same configured group are both present (each already carried
    its own level from a level cell, not an exclusion), they're combined
    into one `any` node. A group member that was excluded never reaches
    this function as a node at all (excluded subjects short-circuit to
    the excluded set in build_subject_tree, never becoming a node), so
    "required X, excluded Y" from the same group is structurally
    unaffected -- only two or more REQUIRED members of a group trigger
    this."""
    groups = profile.get("layout", {}).get("mutually_exclusive_subjects", [])
    if not groups:
        return nodes

    remaining = list(nodes)
    grouped: list[dict] = []
    for group in groups:
        group_set = set(group)
        matched = [n for n in remaining if n.get("kind") == "subject" and n.get("subject") in group_set]
        if len(matched) < 2:
            continue
        for node in matched:
            remaining.remove(node)
        grouped.append({"kind": "any", "rules": matched})

    return grouped + remaining


APS_MIN, APS_MAX = 14, 48
_APS_NUMBER_RE = re.compile(r"\b([1-4]\d)\b(?!\s*%)")


def find_aps_candidates(text: str) -> list[tuple[int, int, int]]:
    """Every APS-plausible 2-digit number (14-48) in text, as (value,
    start, end) -- excludes a number immediately followed by '%' so a
    subject-level percentage band cell like "3 (40%+)" is never mistaken
    for an APS score just because 40 falls inside the plausible range."""
    out = []
    for m in _APS_NUMBER_RE.finditer(text):
        value = int(m.group(1))
        if APS_MIN <= value <= APS_MAX:
            out.append((value, m.start(), m.end()))
    return out


_ALIAS_VOCAB: list[tuple[str, str]] | None = None


def _alias_vocab() -> list[tuple[str, str]]:
    """The exact vocabulary resolve_subject_column() draws from (Subject
    enum full names, _MANUAL_HEADER_ALIASES, LANGUAGE_FAMILIES), reused
    here rather than a second alias table -- sorted longest-phrase-first
    so "technical mathematics" matches before the shorter "mathematics"
    substring it also contains."""
    global _ALIAS_VOCAB
    if _ALIAS_VOCAB is None:
        vocab = [(member.value.replace("_", " "), member.value) for member in Subject]
        vocab += list(_MANUAL_HEADER_ALIASES.items())
        vocab += [(lang, lang) for lang in LANGUAGE_FAMILIES]
        vocab.sort(key=lambda pair: -len(pair[0]))
        _ALIAS_VOCAB = vocab
    return _ALIAS_VOCAB


def find_subject_alias(text: str) -> str | None:
    """Longest-match substring search for a KNOWN subject/language alias
    inside free text (e.g. a score cell's qualifier phrase, "with
    Mathematics"), not a whole-string match like resolve_subject_column()
    does for column headers. Only recognises the SAME full-word forms
    resolve_subject_column() already knows -- an abbreviation the source
    text uses that isn't in that vocabulary ("Maths", "Tech Maths") is not
    invented here and simply won't resolve."""
    normalised = _normalise_header(text)
    for phrase, slug in _alias_vocab():
        if re.search(rf"\b{re.escape(phrase)}\b", normalised):
            return slug
    return None


def find_all_subject_aliases(text: str) -> list[str]:
    """All non-overlapping known aliases in text, in the order they
    appear -- used when a cell has exactly one distinct APS value but
    several subject qualifiers sharing it (e.g. "28 with Maths/Tech Maths
    OR 28 with Mathematical Literacy", all three branches at the same
    score). Matching itself still prefers the LONGEST vocabulary phrase
    when phrases overlap (so "technical mathematics" claims its span
    before the shorter "mathematics" can), but results are returned by
    text position, not vocabulary order."""
    normalised = _normalise_header(text)
    consumed = [False] * len(normalised)
    found: list[tuple[int, str]] = []
    for phrase, slug in _alias_vocab():
        for m in re.finditer(rf"\b{re.escape(phrase)}\b", normalised):
            if any(consumed[m.start():m.end()]):
                continue
            found.append((m.start(), slug))
            for i in range(m.start(), m.end()):
                consumed[i] = True
    found.sort(key=lambda pair: pair[0])
    return [slug for _pos, slug in found]


def parse_aps_cell(text: str | None) -> list[dict] | None:
    """Turns one score cell's raw text into a list of {"min_score":...,
    "requires_subject":...} entries, or None if genuinely nothing/
    ambiguous is found -- an abstention reconcile() already treats as "no
    vote", not a guess.

    A cell with exactly ONE distinct plausible APS value produces one
    entry per subject alias found anywhere in the cell (all sharing that
    value), or a single alias-less entry if none is found. A cell with
    MORE THAN ONE distinct value is only resolved if each value has its
    own qualifier phrase in the text strictly between it and the next
    value -- a clean, sequential "N with X OR N with Y" layout. Anything
    else (no qualifier in a span, or a genuinely scrambled multi-line
    cell -- confirmed on real UJ data: Table.extract()'s cell assembly
    can interleave a rotated cell's words out of source order) abstains
    on the WHOLE cell rather than guessing which number pairs with which
    qualifier."""
    if not text:
        return None
    joined = text.replace("\n", " ")
    candidates = find_aps_candidates(joined)
    if not candidates:
        return None

    distinct_values = sorted({value for value, _start, _end in candidates})
    if len(distinct_values) == 1:
        value = distinct_values[0]
        aliases = find_all_subject_aliases(joined)
        if not aliases:
            return [{"min_score": value}]
        return [{"min_score": value, "requires_subject": slug} for slug in aliases]

    ordered = sorted(candidates, key=lambda c: c[1])
    entries = []
    for i, (value, _start, end) in enumerate(ordered):
        next_start = ordered[i + 1][1] if i + 1 < len(ordered) else len(joined)
        span = joined[end:next_start]
        slug = find_subject_alias(span)
        if slug is None:
            return None
        entries.append({"min_score": value, "requires_subject": slug})
    return entries


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _phrase_pattern(phrase: str) -> re.Pattern:
    """Prose is upright and already correctly ordered (unlike a rotated
    table cell, which interpret_cell's word-order-insensitive matching
    exists to tolerate) -- so this matches the phrase's own words
    in order, not merely present somewhere in the text. That's what
    makes a match POSITION meaningful: scan_page_exclusions uses it to
    separate the subjects a clause actually names from unrelated
    subjects mentioned later in the same sentence."""
    words = [re.escape(w) for w in phrase.split()]
    return re.compile(r"\b" + r"\s+".join(words) + r"\b", re.IGNORECASE)


def scan_page_exclusions(page_text: str, profile: dict) -> list[str]:
    """Page-level (not per-cell) subject exclusions stated as prose --
    e.g. UJ's Faculty of Science footer: "Technical Mathematics and
    Technical Science are not accepted for Degree programmes in the
    Faculty of Science." interpret_cell only ever sees one row's own
    cell text; this note isn't inside any row's cell at all, so no
    amount of per-cell interpretation finds it. Both methods call this
    once per page and union the result into every record extracted from
    that page (see textlayer.py/geometric.py) -- the note applies
    faculty-wide, not to one row.

    Subjects are resolved only from the text BEFORE each phrase match
    within its sentence (find_all_subject_aliases on that prefix), never
    the whole sentence -- confirmed necessary against a second real UJ
    note (page 75): "Technical Mathematics is not accepted, and where
    Mathematics is selected as a major, the Faculty of Science's minimum
    requirements for Grade 12 Mathematics ... should be met." Whole
    -sentence scanning wrongly excludes plain Mathematics too, from the
    SAME sentence that requires it a few words later -- the exclusion
    clause's own grammar (subject(s), then "is/are not accepted") puts
    what's actually excluded before the phrase, not after it.

    Matching happens per LINE of page_text, split further into SENTENCEs
    (on .!?) -- never across lines or across sentences -- since a
    genuine prose line can hold more than one unrelated sentence
    (confirmed on real UJ pages: marketing prose immediately precedes
    the exclusion note on the same joined line), and
    text_repair.page_prose_text() gives each table cell's rotated marker
    its own line for exactly this reason: a bare one-word data cell like
    "Not applicable" has no subject alias on its own line and so
    contributes nothing here, only to its own row via interpret_cell --
    confirmed directly against real UJ data, where this cell's phrase is
    even split across two SEPARATE runs ("Not " and "applicable") that
    individually don't complete the phrase at all.

    A sentence containing one of THIS institution's own qualification
    codes (profile.layout.code_pattern) is skipped outright, never
    treated as prose -- confirmed as a real false positive on real UJ
    page 54: several unrelated programmes' own upright "Not applicable"
    subject cells (Accounting, Economics) sit on that page with no
    punctuation between them at all, so without this guard they'd
    coalesce with every other upright word on the page -- including
    unrelated codes and subject names three programmes away -- into one
    giant false "sentence" once page_prose_text's single joined line
    only splits on real sentence punctuation. A genuine footer/margin
    note names no qualification code at all, so this costs it nothing."""
    phrases = profile["layout"].get("not_accepted_phrases", [])
    if not phrases:
        return []
    code_pattern = re.compile(profile["layout"]["code_pattern"])
    patterns = [_phrase_pattern(p) for p in phrases]

    found: set[str] = set()
    for line in page_text.splitlines():
        for sentence in _SENTENCE_SPLIT.split(line.strip()):
            if not sentence or code_pattern.search(sentence):
                continue
            for pattern in patterns:
                for match in pattern.finditer(sentence):
                    found.update(find_all_subject_aliases(sentence[:match.start()]))
    return sorted(found)


def build_subject_tree(row: list[tuple[str, CellValue]], profile: dict) -> tuple[dict, set[str]]:
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

    nodes = _group_mutually_exclusive(nodes, profile)
    return {"kind": "all", "rules": nodes}, excluded


def group_programme_rows(rows: list[list[str | None]], profile: dict) -> list[list[list[str | None]]]:
    """Groups a table's DATA rows (never a header row -- callers pass only
    the rows between one header occurrence and the next, exactly what
    Method B's own _extract_page loop already isolates) into one list per
    programme -- for institutions where Method B's usual row-per-
    programme assumption doesn't hold. Confirmed on two real, differently
    -shaped documents: DUT prints one row per NSC subject requirement
    (code/name/score only populated on the row that also states English,
    every later row blank in those columns); UFH wraps a whole
    programme's later subjects inside physically separate table rows the
    same way, code/name/APS populated once on the first.

    A new group starts at a row where ANY cell fullmatches
    profile.layout.code_pattern -- that row's OWN cells supply the
    group's scalar fields (code, name, score, campus); every row after it
    up to the next code match belongs to the same group (see
    extract_row_subject_cells / geometric._merge_programme_group for what
    happens to them). Rows before the FIRST code-bearing row are
    discarded outright -- there is no programme yet to attach them to.

    Institutions where the code never appears in the table at ALL (DUT's
    own requirements table is one confirmed case -- the code sits in page
    prose above it, never in a cell Table.extract() returns) will
    correctly produce ZERO groups here: grouping cannot invent a
    programme boundary that isn't present in the rows it's given. That is
    a distinct, later problem (resolving the code from page prose) that
    this function is not responsible for solving."""
    code_pattern = re.compile(profile["layout"]["code_pattern"])
    groups: list[list[list[str | None]]] = []
    for row in rows:
        if any(cell and code_pattern.fullmatch(cell.strip()) for cell in row):
            groups.append([row])
        elif groups:
            groups[-1].append(row)
        # else: no group started yet -- discarded, per the docstring above
    return groups


def extract_row_subject_cells(row: list[str | None], profile: dict) -> list[tuple[str, CellValue]]:
    """One row's subject contribution, for a 'rows_per_programme: many'
    institution where a subject's name is DATA (one cell) rather than a
    column HEADER -- every column-header-driven mechanism in this module
    (resolve_subject_column, build_subject_tree's own column walk) is
    unusable here, since there is no per-subject column to resolve at
    all.

    Scans every ADJACENT cell pair (name_cell, level_cell) left to right.
    A pair counts only when name_cell resolves to a KNOWN subject/
    language alias (find_subject_alias -- the same vocabulary
    resolve_subject_column always draws from) -- an unrecognised label
    like DUT's 'In addition: TWO recognized' note or UFH's 'Other
    Subjects (2)' is silently skipped, never guessed at. Matched cells
    are consumed (both indices) so a level cell can never ALSO be read as
    the next pair's name cell.

    Each cell is split on '\\n' before pairing, name_lines against
    level_lines line-by-line -- confirmed necessary on real UFH data,
    where a single row's cell already holds MULTIPLE subjects ('Mathematics
    OR\\nMathematics Literacy' paired with '4 (50-59%)\\n5 (60-69%)').
    A mismatched line count between the two cells is genuinely ambiguous
    (which line pairs with which?) and the whole pair abstains rather
    than guessing.

    The level side is run through interpret_cell (not a bare level-number
    search) so a 'Not accepted' cell in this shape is treated exactly the
    same as it would be in a column-per-subject table -- one cell
    -interpretation function, never two."""
    cells: list[tuple[str, CellValue]] = []
    consumed: set[int] = set()
    for i in range(len(row) - 1):
        if i in consumed or (i + 1) in consumed:
            continue
        name_cell, level_cell = row[i], row[i + 1]
        if not name_cell or not level_cell:
            continue
        name_lines = name_cell.split("\n")
        level_lines = level_cell.split("\n")
        if len(name_lines) != len(level_lines):
            continue
        matched_any = False
        for name_line, level_line in zip(name_lines, level_lines):
            slug = find_subject_alias(name_line)
            if slug is None:
                continue
            cell_value = interpret_cell(level_line, profile)
            if cell_value.kind == "empty":
                continue
            cells.append((slug, cell_value))
            matched_any = True
        if matched_any:
            consumed.add(i)
            consumed.add(i + 1)
    return cells
