"""Regression guard: the canonical 2009 NSC fixture run against the full
encoded seed set must produce a stable set of qualifying codes. As more
programmes are encoded, an unrelated typo (wrong min_level, wrong
requires_subject, a stray excluded_subjects entry) can silently flip
someone else's outcome -- this catches that.

EXPECTED_QUALIFYING_CODES must be updated deliberately when the seed set
changes in a way that legitimately changes this fixture's results, never
reflexively just to make a failing test pass. If this test fails, work out
WHY the set changed before touching the assertion.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api" / "src"))

from seed_loader import load  # noqa: E402

from app.evaluator import evaluate  # noqa: E402
from app.qualify import select_score_threshold  # noqa: E402
from app.scoring import SCORERS  # noqa: E402

CANONICAL_MARKS = {
    "english_hl": 87,
    "afrikaans_fal": 85,
    "mathematics": 88,
    "life_orientation": 88,
    "geography": 92,
    "life_sciences": 87,
    "physical_sciences": 73,
}

# Verified 2026-08-02 against the 29 currently-encoded UJ programmes by
# actually running the pipeline, not by inspection. B5LAZQ is the one
# expected non-qualifier (requires isiZulu, which this fixture doesn't have).
# Grew 5 -> 11 (Science), 11 -> 17 (CBE), 17 -> 23 (FEBE), 23 -> 28 (Health:
# B9N02Q, B9O02Q, B9M01Q, B9E01Q, B9S15Q) -- this fixture's English 87,
# Maths 88 (7), Physical Sciences 73 (6), Life Sciences 87 (7) clear all
# five, including the four-simultaneous-subjects programmes. B9O02Q (APS
# 34, three level-5 bars, the second-highest APS encoded after B2M52Q's 40)
# is the highest bar in this tranche and was checked individually.
EXPECTED_QUALIFYING_CODES = frozenset({
    "B1CISQ", "B2I01Q", "B2I02Q", "B2I04Q", "B2M43Q", "B2M52Q", "B2M55Q", "B2M56Q", "B2M57Q",
    "B34A5Q", "B34CAQ", "B34F5Q", "B34HRQ", "B3N14Q",
    "B4L03Q", "B5BFPQ",
    "B6CS0Q", "B6CV3Q", "B6EL1Q", "B6ES0Q", "B6MC2Q", "B6MS0Q",
    "B8CD2Q",
    "B9E01Q", "B9M01Q", "B9N02Q", "B9O02Q", "B9S15Q",
})


def _qualifying_codes() -> frozenset[str]:
    data = load()
    programmes = {p["qualification_code"]: p for p in data["programmes"]}
    institutions = {i["id"]: i for i in data["institutions"]}

    qualifying = set()
    for code, programme in programmes.items():
        nsc = programme["requirements"]["nsc"]
        excluded = set(nsc.get("excluded_subjects") or [])
        institution = institutions[programme["institution_id"]]
        achieved = SCORERS[institution["scoring_strategy"]](CANONICAL_MARKS)
        required = select_score_threshold(nsc["score"], CANONICAL_MARKS)
        failures = evaluate(nsc["subjects"], CANONICAL_MARKS, excluded)
        if required is not None and achieved >= required and not failures:
            qualifying.add(code)
    return frozenset(qualifying)


def test_canonical_fixture_qualifying_set_is_stable() -> None:
    actual = _qualifying_codes()
    assert actual == EXPECTED_QUALIFYING_CODES, (
        f"qualifying set changed: gained={actual - EXPECTED_QUALIFYING_CODES}, "
        f"lost={EXPECTED_QUALIFYING_CODES - actual}. "
        f"If this is an intentional consequence of new/edited seed data, update "
        f"EXPECTED_QUALIFYING_CODES deliberately -- don't just paste in the new set."
    )
