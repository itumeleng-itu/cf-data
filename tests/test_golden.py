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
# --- UJ 2027 -------------------------------------------------------------
    "B1CISQ", "B2I01Q", "B2I02Q", "B2I04Q", "B2M43Q", "B2M52Q",
    "B2M55Q", "B2M56Q", "B2M57Q", "B34A5Q", "B34CAQ", "B34F5Q",
    "B34HRQ", "B3N14Q", "B4L03Q", "B5BFPQ", "B6CS0Q", "B6CV3Q",
    "B6EL1Q", "B6ES0Q", "B6MC2Q", "B6MS0Q", "B8CD2Q", "B9E01Q",
    "B9M01Q", "B9N02Q", "B9O02Q", "B9S15Q",
# --- Wits 2027 (re-added with the verified extraction, 60 programmes) -----
# The canonical fixture (English HL 87, Maths 88, Physical Sciences 73,
# Life Sciences 87) clears 58 of the 60. The two it does not are checked
# individually rather than taken on trust:
#   SBA03 Actuarial Science     - page 123: English 7, Mathematics 7,
#   SBA08 Mathematical Sciences - page 126: Physical Sciences 7
# The fixture's 73% is Level 6, so both correctly fail the subject rule.
#
# This set was RE-DERIVED after Wits was removed and re-added from a
# corrected extraction -- not restored from the previous commit. It comes
# out identical, which is the point: the extractor changed how it reads
# five pages' COURSE LISTS, and course lists have no bearing on who gets
# in. A change here would have meant an admission requirement moved, and
# none did.
    "ABA00", "ABA02", "AFA01", "AFA02", "AFA04", "AFA10",
    "AFA11", "AFA12", "AFA13", "AFA14", "CBA00", "CBA08",
    "CBA10", "CBA12", "CBA13", "CBA14", "CBA17", "CBA18",
    "EBA00", "EBA01", "EFA00", "EFA01", "EFA03", "EFA05",
    "EFA06", "EFA07", "EFA08", "EFA09", "FBA00", "FBA04",
    "FBA05", "FBA07", "HFA00", "HFA01", "HFA02", "LFA12",
    "LFA13", "LFA14", "MBA01", "MBA04", "MBA05", "MFA00",
    "MFA02", "MFA03", "MFA04", "MFA07", "MFA08", "SBA04",
    "SBA09", "SBA10", "SBA11", "SBA12", "SBA13", "SBA15",
    "SBA20", "SBA21", "SBA22", "WITS-BSC-GEN",
# --- TUT 2027 (first encoding, from TUT's own prospectus) ----------------
# TUT's APS bars run 18-30 and this fixture scores 41 there (7+7+7+7+7+6
# on its best six excluding Life Orientation, with zero_below_level 2),
# so it clears almost everything. The FOUR it does not were each checked
# rather than taken on trust:
#   BEd Senior Phase (Consumer/Hospitality) - needs Consumer Studies or
#                                             Hospitality Studies
#   BEd Senior Phase (Commerce)             - needs Accounting, Business
#                                             Studies or Economics
#   Dip (Credit Management)                 - needs Accounting
#   Dip (Fire Technology)                   - scoreable: false, admitted
#                                             on service and certificates
#
# Nothing was LOST when TUT was added: every UJ and Wits code above still
# qualifies, which is what makes this an addition rather than a change to
# anyone's existing result.
    "tut-barch-bachelor-of-architecture",
    "tut-barch-bachelor-of-architecture-extended",
    "tut-bed-foundation-phase-teaching",
    "tut-bed-intermediate-phase-teaching",
    "tut-bed-senior-phase-and-further-education-and-train",
    "tut-bed-senior-phase-and-further-education-and-train-4",
    "tut-bed-senior-phase-and-further-education-and-train-5",
    "tut-bed-senior-phase-and-further-education-and-train-6",
    "tut-bed-senior-phase-and-further-education-and-train-7",
    "tut-bed-senior-phase-and-further-education-and-train-8",
    "tut-beng-materials-engineering-polymer-technology",
    "tut-bengtech-chemical-engineering", "tut-bengtech-civil-engineering",
    "tut-bengtech-electrical-engineering",
    "tut-bengtech-industrial-engineering",
    "tut-bengtech-mechanical-engineering",
    "tut-bengtech-mechatronics-engineering",
    "tut-bengtech-metallurgical-engineering", "tut-benvironmental-health",
    "tut-bgeomatics", "tut-bhsci-biokinetics",
    "tut-bhsci-clinical-technology", "tut-bhsci-medical-laboratory-science",
    "tut-bhsci-medical-orthotics-and-prosthetics",
    "tut-bhsci-veterinary-technology", "tut-bnursing",
    "tut-bpharm-bachelor-of-pharmacy",
    "tut-brad-diagnostic-bachelor-of-radiography-in-diagn",
    "tut-bsc-industrial-chemistry", "tut-dip-accounting",
    "tut-dip-administrative-information-management",
    "tut-dip-adult-and-community-education-and-training-s",
    "tut-dip-adult-and-community-education-and-training-s-2",
    "tut-dip-adult-and-community-education-and-training-s-3",
    "tut-dip-adventure-tourism-management-only-mbombela-c",
    "tut-dip-analytical-chemistry", "tut-dip-animal-sciences",
    "tut-dip-biotechnology", "tut-dip-building-science",
    "tut-dip-casino-resort-management", "tut-dip-civil-engineering",
    "tut-dip-commercial-photography", "tut-dip-computer-science",
    "tut-dip-computer-science-extended",
    "tut-dip-computer-systems-engineering",
    "tut-dip-computer-systems-engineering-extended",
    "tut-dip-contact-centre-management",
    "tut-dip-correctional-and-rehabilitation-studies",
    "tut-dip-crop-production", "tut-dip-economics",
    "tut-dip-ecotourism-management-only-mbombela-campus",
    "tut-dip-electrical-engineering", "tut-dip-entrepreneurship",
    "tut-dip-environmental-sciences", "tut-dip-equine-science",
    "tut-dip-event-management", "tut-dip-fashion-design-and-technology",
    "tut-dip-financial-management", "tut-dip-financial-planning",
    "tut-dip-fine-and-applied-arts", "tut-dip-food-operations-management",
    "tut-dip-food-technology", "tut-dip-geology", "tut-dip-geomatics",
    "tut-dip-horticulture", "tut-dip-hospitality-management",
    "tut-dip-human-resource-management", "tut-dip-industrial-design",
    "tut-dip-industrial-physics", "tut-dip-informatics",
    "tut-dip-informatics-extended", "tut-dip-information-technology",
    "tut-dip-information-technology-extended",
    "tut-dip-integrated-communication",
    "tut-dip-integrated-communication-design", "tut-dip-interior-design",
    "tut-dip-internal-auditing", "tut-dip-jewellery-design-and-manufacture",
    "tut-dip-journalism", "tut-dip-kinesiology-and-coaching-science",
    "tut-dip-landscape-technology", "tut-dip-language-practice",
    "tut-dip-law", "tut-dip-legal-support", "tut-dip-marketing",
    "tut-dip-motion-picture-production", "tut-dip-multimedia-computing",
    "tut-dip-multimedia-computing-extended", "tut-dip-nature-conservation",
    "tut-dip-operations-management", "tut-dip-performing-arts-dance",
    "tut-dip-performing-arts-jazz-music", "tut-dip-performing-arts-opera",
    "tut-dip-performing-arts-technical-theatre-and-design",
    "tut-dip-performing-arts-theatre-arts-and-performance",
    "tut-dip-policing", "tut-dip-public-affairs-admin-of-state",
    "tut-dip-public-affairs-local-government", "tut-dip-public-finance",
    "tut-dip-retail-business-management", "tut-dip-somatic-therapy",
    "tut-dip-sport-management", "tut-dip-supply-chain-management",
    "tut-dip-tourism-management", "tut-dip-water-science-and-technology",
    "tut-dip-wildlife-management", "tut-dip-work-study",
    "tut-hcert-accounting",
    "tut-hcert-administrative-information-management-onli",
    "tut-hcert-construction-engineering-material-test",
    "tut-hcert-construction-engineering-water-and-waste",
    "tut-hcert-contact-centre-management-online-presentat",
    "tut-hcert-dental-assisting", "tut-hcert-electrical-engineering",
    "tut-hcert-forestry-management-only-mbombela-campus",
    "tut-hcert-industrial-engineering", "tut-hcert-mechanical-engineering",
    "tut-hcert-music", "tut-hcert-resource-and-waste-management",
    "tut-hcert-water-treatment",
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
