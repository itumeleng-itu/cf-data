"""Page classification -- heuristics only, no model calls. Given an
ingested PDF, classify every page so later sub-phases spend model tokens
only on pages that contain programme tables.

Signal computation is deliberately kept separate from PDF I/O:
PagePrimitives is the cheap, deterministic measurement extracted from a
real pdfplumber page; every signal function and classify_page() operate
on it (or on plain text/dataclasses), so they're unit-testable with
synthetic values -- no PDF file required. Only classify_pages() itself
touches pdfplumber.

Per-institution tuning (weights, over-inclusion margin, the table-evidence
ruled-line floor, code pattern, header keywords) lives in
extract/institutions/registry.json, not here -- see extract/profiles.py.
This module is the general mechanism; the registry is what makes it work
for a specific document.

Over-inclusion bias, by design: when a page is borderline between
PROGRAMME_TABLE and anything else, it classifies as PROGRAMME_TABLE. A
prose page misclassified as a table costs a few wasted tokens downstream
and yields zero records -- cheap. A missed table page produces no record,
no flag, and no way to notice except manually counting against the
prospectus -- a learner never sees a programme they qualified for.
Precision is cheap to buy back later; recall is not. This is encoded
explicitly as each profile's classification.overinclusion_margin, not
left implicit in the weights.

The bias is narrowed, not unconditional: it only fires when the page
shows actual table-shaped evidence (a matched qualification code, or a
ruled-line count clearing classification.table_evidence_ruled_line_floor).
A page with zero matched codes and no ruled lines is not a borderline
table -- it's prose that happens to score close on a couple of signals,
and rescuing it was never the bias's purpose.

_SCORING_PHRASES stays a shared, cross-institution constant rather than a
per-profile field: these are generic English admissions-methodology
phrases ("admission point score", "how to determine", ...), not an
institution-specific formatting quirk like a code pattern or header
label -- there was nowhere principled for it in the registry schema, and
unlike the weights/margin/floor (which are tuned per-document because
each document's signal ranges differ) this vocabulary is not expected to
vary the same way per institution.

ALTERNATIVE_ADMISSION: pages describing admission routes or eligibility
criteria that apply ACROSS programmes rather than to a specific one --
alternative qualification types (NCV, NASCA, SC(a)), subject-combination
eligibility guidance, mature-age or RPL routes. Real admission
information, but not per-programme rows, and therefore not an extraction
target in 8.4. Like SCORING_METHODOLOGY, these pages route to human
review for the scoring/eligibility report rather than to record
extraction. Added after two institutions (UJ and CPUT) independently
produced pages that fit none of the other four classes -- confirmed
independently, not assumed from one document's quirk.
"""

import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

import pdfplumber

from text_repair import normalise_page_text


class PageClass(StrEnum):
    PROGRAMME_TABLE = "programme_table"
    REQUIREMENTS_PROSE = "requirements_prose"
    SCORING_METHODOLOGY = "scoring_methodology"
    ADMIN = "admin"
    DECORATIVE = "decorative"
    ALTERNATIVE_ADMISSION = "alternative_admission"


@dataclass(frozen=True, slots=True)
class PagePrimitives:
    """Raw measurements pulled from one PDF page. Kept separate from any
    PDF library so signal functions can be tested with plain values."""
    text: str
    char_count: int
    width: float
    height: float
    line_count: int          # pdfplumber .lines + .rects (ruled-line proxy)
    image_area_ratio: float  # sum of image areas / page area, clamped [0,1]


@dataclass(frozen=True, slots=True)
class PageSignals:
    text_density: float      # chars per unit area
    code_matches: int        # lines matching profile["code_pattern"]
    keyword_hits: int        # distinct profile["header_keywords"] found (case-insensitive)
    numeric_ratio: float     # digits / (digits + alpha), 0 if neither present
    ruled_line_count: int
    image_coverage: float
    scoring_phrase_hits: int
    alt_admission_phrase_hits: int


_SCORING_PHRASES = [
    "admission point score",
    "how to determine",
    "achievement rating",
    "aps is calculated",
]

# Standardised South African alternative-admission-route terminology --
# defined nationally by the Department of Higher Education and Training,
# not an institution-specific formatting quirk, so this stays shared like
# _SCORING_PHRASES rather than living per-profile. Confirmed present on
# UJ's own known ALTERNATIVE_ADMISSION examples (pages 35/36/50) by direct
# text search before being added here, not assumed.
#
# This signal alone does NOT reliably separate an alternative-admission
# page from a real programme-table page: some real UJ table pages
# footnote-reference these routes for a specific programme (e.g. page 62
# scores 6 phrase hits, more than pages 36/50's 4) and still correctly
# classify as PROGRAMME_TABLE, because their code_matches/keyword_hits/
# ruled_line_count are large enough to keep programme_table's own score
# well ahead regardless -- verified directly against the real document,
# not assumed. The weight below is calibrated with that margin in mind.
_ALT_ADMISSION_PHRASES = [
    "national certificate (vocational)",
    "ncv",
    "national senior certificate for adults",
    "nasca",
    "amended senior certificate",
    "sc(a)",
    "recognition of prior learning",
    "rpl",
    "mature age",
]


def text_density(primitives: PagePrimitives) -> float:
    area = primitives.width * primitives.height
    return primitives.char_count / area if area else 0.0


def code_pattern_matches(text: str, code_pattern: str) -> int:
    return len(re.findall(code_pattern, text, flags=re.MULTILINE))


def keyword_hits(text: str, keywords: list[str]) -> int:
    lowered = text.lower()
    return sum(1 for kw in keywords if kw.lower() in lowered)


def numeric_alpha_ratio(text: str) -> float:
    digits = sum(1 for c in text if c.isdigit())
    alpha = sum(1 for c in text if c.isalpha())
    total = digits + alpha
    return digits / total if total else 0.0


def scoring_phrase_hits(text: str) -> int:
    lowered = text.lower()
    return sum(1 for phrase in _SCORING_PHRASES if phrase in lowered)


def alt_admission_phrase_hits(text: str) -> int:
    lowered = text.lower()
    return sum(1 for phrase in _ALT_ADMISSION_PHRASES if phrase in lowered)


def compute_signals(primitives: PagePrimitives, layout: dict) -> PageSignals:
    return PageSignals(
        text_density=text_density(primitives),
        code_matches=code_pattern_matches(primitives.text, layout["code_pattern"]),
        keyword_hits=keyword_hits(primitives.text, layout["header_keywords"]),
        numeric_ratio=numeric_alpha_ratio(primitives.text),
        ruled_line_count=primitives.line_count,
        image_coverage=primitives.image_area_ratio,
        scoring_phrase_hits=scoring_phrase_hits(primitives.text),
        alt_admission_phrase_hits=alt_admission_phrase_hits(primitives.text),
    )


def _weighted_score(signals: PageSignals, weights: dict[str, float]) -> float:
    return sum(getattr(signals, name) * weight for name, weight in weights.items())


def classify_page(signals: PageSignals, classification: dict) -> tuple[PageClass, dict[PageClass, float]]:
    """classification is a profile's "classification" sub-dict (see
    extract/profiles.py): weights keyed by PageClass.value, plus
    admin_baseline / overinclusion_margin / table_evidence_ruled_line_floor.
    All per-institution tuning; see extract/institutions/registry.json."""
    weights = classification["weights"]
    admin_baseline = classification["admin_baseline"]
    overinclusion_margin = classification["overinclusion_margin"]
    ruled_line_floor = classification["table_evidence_ruled_line_floor"]

    scores = {cls: _weighted_score(signals, weights[cls.value]) for cls in PageClass}
    scores[PageClass.ADMIN] += admin_baseline

    best_class = max(scores, key=scores.get)
    table_score = scores[PageClass.PROGRAMME_TABLE]
    has_table_evidence = signals.code_matches >= 1 or signals.ruled_line_count >= ruled_line_floor
    if (
        best_class != PageClass.PROGRAMME_TABLE
        and has_table_evidence
        and (scores[best_class] - table_score) <= overinclusion_margin
    ):
        best_class = PageClass.PROGRAMME_TABLE

    return best_class, scores


def _extract_primitives(page: "pdfplumber.page.Page") -> PagePrimitives:
    text = normalise_page_text(page)
    width, height = float(page.width), float(page.height)
    area = width * height
    image_area = sum(
        float(img.get("width", 0)) * float(img.get("height", 0)) for img in page.images
    )
    image_ratio = min(1.0, image_area / area) if area else 0.0
    return PagePrimitives(
        text=text,
        char_count=len(page.chars),
        width=width,
        height=height,
        line_count=len(page.lines) + len(page.rects),
        image_area_ratio=image_ratio,
    )


def classify_pages(pdf_path: Path, profile: dict) -> tuple[dict[int, PageClass], dict[int, dict]]:
    """Returns (classification per 1-indexed page, per-page signal/score
    report) -- the report is not optional decoration, it's how a
    misclassification gets debugged without re-running instrumented code."""
    classifications: dict[int, PageClass] = {}
    signal_report: dict[int, dict] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            primitives = _extract_primitives(page)
            signals = compute_signals(primitives, profile["layout"])
            page_class, scores = classify_page(signals, profile["classification"])
            classifications[page_number] = page_class
            signal_report[page_number] = {
                "class": page_class.value,
                "signals": asdict(signals),
                "scores": {cls.value: score for cls, score in scores.items()},
            }
    return classifications, signal_report
