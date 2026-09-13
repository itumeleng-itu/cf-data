"""Verifies every registered scorer against a worked example taken
VERBATIM from the institution's own prospectus.

A wrong REQUIREMENT breaks one programme. A wrong SCORER breaks every
programme at that institution — consistently and invisibly, with nothing
about any individual record looking anomalous, because the arithmetic is
internally consistent even when the formula is wrong. Nothing else in the
test suite can catch this class of error: scripts/validate_data.py's
semantic checks compare a programme's own numbers against themselves, not
an institution's formula against the institution's own published
arithmetic. The university's own worked example is the only independent
check available, which is why every scorer registered in
api/src/app/scoring.py's SCORERS is required to have one here.

Fixture shape (per the task that created this file):
    {institution, source_page, subjects: {slug: percentage}, expected_score}
extended with `strategy` and `config` so one fixture format can drive every
registered algorithm generically rather than hardcoding which scorer each
institution uses -- the literal shape above has no way to say that.

Sources:
  UJ    2027 Undergraduate Prospectus, p.16, "How to determine your
        Admission Point Score (APS)" -- the table lists 6 subjects with
        their percentages and the resulting APS. (Section heading on the
        contents page reads "p.15"; the table with numbers prints on the
        following page, p.16 -- both page references appear here for
        that reason.)
  CPUT  2027 Prospectus, p.3, "CALCULATING THE APS SCORE", Method 1
        ("Best of six subjects") -- the only one of CPUT's three
        published methods with no per-subject weighting, matching
        percentage_sum_div_10 exactly.

Every registered scorer (SCORERS in api/src/app/scoring.py) must appear
in WORKED_EXAMPLES at least once, or in docs/scoring/{id}.md as
explicitly UNVERIFIED -- see test_every_registered_scorer_is_covered.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "api" / "src"))

from app.scoring import SCORERS  # noqa: E402

WORKED_EXAMPLES = [
    {
        "institution": "uj",
        "strategy": "aps_best6_excl_lo",
        "config": {},
        "source_page": 16,
        "subjects": {
            "english_hl": 65,       # "First language (language of teaching and learning)"
            "afrikaans_fal": 71,    # "Additional recognised language"
            "mathematics": 61,      # "Mathematics or Mathematical Literacy"
            "accounting": 68,
            "history": 81,
            "geography": 86,
        },
        "expected_score": 35,
    },
    {
        "institution": "cput",
        "strategy": "percentage_sum_div_10",
        "config": {},
        "source_page": 3,
        "subjects": {
            "english_hl": 57,
            "mathematics": 55,
            "accounting": 50,       # prospectus prints "Subject 3"
            "business_studies": 54,  # prospectus prints "Subject 4"
            "geography": 43,         # prospectus prints "Subject 5"
            "history": 45,           # prospectus prints "Subject 6"
        },
        # The prospectus's own arithmetic: 57+55+50+54+43+45 = 304,
        # 304 / 10 = 30.4. This scorer floors to 30 -- see scoring.py's
        # module docstring for why that never changes a qualify/fail
        # outcome against any integer APS threshold.
        "expected_score": 30,
    },
]


@pytest.mark.parametrize(
    "example", WORKED_EXAMPLES, ids=[f"{e['institution']}_p{e['source_page']}" for e in WORKED_EXAMPLES],
)
def test_worked_example_reproduces_the_prospectus(example: dict) -> None:
    scorer = SCORERS[example["strategy"]]
    assert scorer(example["subjects"], example["config"]) == example["expected_score"]


def test_uj_worked_example_sum_matches_the_printed_total() -> None:
    # Independent of percentage_to_level's own correctness: this pins
    # that our understanding of the SOURCE table's arithmetic (each
    # printed percentage's printed APS contribution) is right, before
    # trusting the scorer to reproduce it.
    from app.subjects import percentage_to_level

    example = next(e for e in WORKED_EXAMPLES if e["institution"] == "uj")
    levels = [percentage_to_level(pct) for pct in example["subjects"].values()]
    assert levels == [5, 6, 5, 5, 7, 7]  # printed APS column, in table order
    assert sum(levels) == 35  # printed "Total 35"


def test_cput_worked_example_sum_matches_the_printed_total() -> None:
    example = next(e for e in WORKED_EXAMPLES if e["institution"] == "cput")
    assert sum(example["subjects"].values()) == 304  # printed "304 ÷ 10 = 30.4"


def test_every_registered_scorer_is_covered() -> None:
    """Every strategy in SCORERS must either have a worked-example fixture
    here, or be explicitly recorded as UNVERIFIED in docs/scoring/ --
    silence is not an acceptable third option for a scorer that, if
    wrong, is wrong for an entire institution at once."""
    tested = {e["strategy"] for e in WORKED_EXAMPLES}
    untested = set(SCORERS) - tested
    for strategy in untested:
        doc = ROOT / "docs" / "scoring" / f"{strategy}.md"
        assert doc.exists(), (
            f"{strategy!r} has no worked-example fixture and no "
            f"docs/scoring/{strategy}.md recording it as unverified"
        )
        assert "UNVERIFIED" in doc.read_text(encoding="utf-8")
