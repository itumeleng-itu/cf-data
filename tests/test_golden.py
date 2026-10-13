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
# --- Wits 2027 (added with seeds/wits/, 60 programmes) ----------------
# The canonical fixture (English HL 87, Maths 88, Physical Sciences 73,
# Life Sciences 87) clears 58 of the 60. The two it does not are checked
# individually rather than taken on trust:
#   SBA03 Actuarial Science    - needs Physical Sciences Level 7
#   SBA08 Mathematical Sciences- needs Physical Sciences Level 7
# The fixture's 73% is Level 6, so both correctly fail the subject rule.
# The 11 Wits programmes marked scoreable=false (Health Sciences on its
# Composite Index, and the two graduate LLB streams) are never scored and
# so never appear here at all.
#
# CBA10 (BCom Information Systems) and CBA12 (BCom Politics, Philosophy and
# Economics) joined the set deliberately. Prospectus page 16 prints ONE
# requirements row headed "Bachelor of Commerce (BCom) in the fields of:"
# over three sub-bullets -- General, Politics Philosophy and Economics,
# Information Systems -- and the admissions extract had collapsed all three
# into the parent row, so only General (CBA00) existed as a record. They
# share CBA00's requirements exactly (APS 38+, English 5, Mathematics 5),
# which pages 51 and 52 each print independently, so a fixture that clears
# CBA00 must clear these two as well. Nothing was lost from the set.
    "ABA00", "ABA02", "AFA01", "AFA02", "AFA04", "AFA10", "AFA11", "AFA12",
    "AFA13", "AFA14", "CBA00", "CBA08", "CBA10", "CBA12", "CBA13", "CBA14",
    "CBA17", "CBA18",
    "EBA00", "EBA01", "EFA00", "EFA01", "EFA03", "EFA05", "EFA06", "EFA07",
    "EFA08", "EFA09", "FBA00", "FBA04", "FBA05", "FBA07", "HFA00", "HFA01",
    "HFA02", "LFA12", "LFA13", "LFA14", "MBA01", "MBA04", "MBA05", "MFA00",
    "MFA02", "MFA03", "MFA04", "MFA07", "MFA08", "SBA04", "SBA09", "SBA10",
    "SBA11", "SBA12", "SBA13", "SBA15", "SBA20", "SBA21", "SBA22", "WITS-BSC-GEN",

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
        achieved = SCORERS[institution["scoring_strategy"]](CANONICAL_MARKS, institution.get("scoring_config", {}))
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
