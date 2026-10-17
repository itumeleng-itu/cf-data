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

# Regenerated 2026-10-16, when the UJ 2027 prospectus extraction took UJ
# from 29 encoded programmes to 179 and this set from 210 to 347.
#
# The regeneration was only accepted because the diff was 137 GAINED and
# ZERO LOST. This fixture is a strong one (English 87, Maths 88, Physical
# Sciences 73, Life Sciences 87), so it clears the newly-added bars; what
# matters is that no programme which qualified before stopped qualifying.
# A single loss would have meant a requirement had changed somewhere and
# would have had to be explained before this line was touched.
#
# Verified 2026-08-02 against the 29 then-encoded UJ programmes by
# actually running the pipeline, not by inspection. B5LAZQ is the one
# expected non-qualifier (requires isiZulu, which this fixture doesn't have).
# Grew 5 -> 11 (Science), 11 -> 17 (CBE), 17 -> 23 (FEBE), 23 -> 28 (Health:
# B9N02Q, B9O02Q, B9M01Q, B9E01Q, B9S15Q) -- this fixture's English 87,
# Maths 88 (7), Physical Sciences 73 (6), Life Sciences 87 (7) clear all
# five, including the four-simultaneous-subjects programmes. B9O02Q (APS
# 34, three level-5 bars, the second-highest APS encoded after B2M52Q's 40)
# is the highest bar in this tranche and was checked individually.
#
# 2026-10-17, Stellenbosch: 347 -> 399. Gained 63 SU programmes, which
# this fixture's marks clear comfortably -- SU's bars are percentages
# and the highest aggregate in the booklet is 80% (MBChB 75%, BDatSci
# and BCom Actuarial Science 80%), against a fixture averaging in the
# high 80s.
#
# LOST 11, and unlike every earlier tranche these losses are the point
# rather than something to explain away. LFA12, LFA13, MBA01, MBA04,
# MBA05, MFA00, MFA02, MFA03, MFA04, MFA07 and MFA08 are Wits'
# scoreable=false programmes -- MBChB, BDS, BPharm, BNurs and the
# rest, admitted on National Benchmark Test results this dataset never
# collects. main.py routes every one of them to
# requires_additional_assessment and never reports them as qualifying,
# so they should never have been in this set.
#
# They were here because each carried an invented "min_score": 0,
# added only to satisfy a schema that demanded a score from
# programmes that are never scored. This loop then read 0 as a real
# threshold, found the learner's score above it, and counted the
# programme as qualifying. The fixture was asserting that a
# matriculant qualifies for Wits medicine on school marks alone.
#
# Fixed at source: the schema now permits an unscoreable programme to
# state no score, those eleven records state none, and this loop skips
# scoreable=false exactly as the engine does.
EXPECTED_QUALIFYING_CODES = frozenset({
    "ABA00",
    "ABA02",
    "AFA01",
    "AFA02",
    "AFA04",
    "AFA10",
    "AFA11",
    "AFA12",
    "AFA13",
    "AFA14",
    "B1CEMQ",
    "B1CISQ",
    "B1CMMQ",
    "B2E02Q",
    "B2E10Q",
    "B2E11Q",
    "B2E12Q",
    "B2E13Q",
    "B2E14Q",
    "B2E17Q",
    "B2E18Q",
    "B2E19Q",
    "B2E20Q",
    "B2E22Q",
    "B2E40Q",
    "B2E41Q",
    "B2E42Q",
    "B2E43Q",
    "B2E44Q",
    "B2E45Q",
    "B2E46Q",
    "B2E49Q",
    "B2E70Q",
    "B2E71Q",
    "B2E72Q",
    "B2E73Q",
    "B2E74Q",
    "B2I01Q",
    "B2I02Q",
    "B2I04Q",
    "B2L10Q",
    "B2L11Q",
    "B2L12Q",
    "B2L13Q",
    "B2L14Q",
    "B2L15Q",
    "B2L16Q",
    "B2L17Q",
    "B2L18Q",
    "B2L20Q",
    "B2L24Q",
    "B2L25Q",
    "B2L26Q",
    "B2M40Q",
    "B2M41Q",
    "B2M42Q",
    "B2M43Q",
    "B2M44Q",
    "B2M45Q",
    "B2M46Q",
    "B2M47Q",
    "B2M52Q",
    "B2M54Q",
    "B2M55Q",
    "B2M56Q",
    "B2M57Q",
    "B2P70Q",
    "B2P71Q",
    "B2P72Q",
    "B2P77Q",
    "B2P78Q",
    "B2P81Q",
    "B2P82Q",
    "B2P83Q",
    "B34A5Q",
    "B34ACC",
    "B34AEQ",
    "B34BEQ",
    "B34BMQ",
    "B34CAQ",
    "B34F5Q",
    "B34FEQ",
    "B34HNQ",
    "B34HRC",
    "B34HRQ",
    "B34I7Q",
    "B34PKQ",
    "B34TDQ",
    "B34TLQ",
    "B3N14Q",
    "B3NE4Q",
    "B4A01Q",
    "B4C01Q",
    "B4L03Q",
    "B5BFPQ",
    "B5BITQ",
    "B5BSAQ",
    "B5BSBQ",
    "B5BSEQ",
    "B5LAEQ",
    "B5LAFQ",
    "B5LOPQ",
    "B5SGEQ",
    "B5SLSQ",
    "B5SMMQ",
    "B5SPSQ",
    "B6CE1Q",
    "B6CN0Q",
    "B6CS0Q",
    "B6CV3Q",
    "B6EL1Q",
    "B6ES0Q",
    "B6EX0Q",
    "B6EXTQ",
    "B6IN2Q",
    "B6L1XQ",
    "B6MC2Q",
    "B6MINQ",
    "B6MS0Q",
    "B6PX2Q",
    "B6PY2Q",
    "B6SU0Q",
    "B6UP0Q",
    "B7015Q",
    "B7023Q",
    "B7024Q",
    "B7025Q",
    "B7026Q",
    "B7EX2Q",
    "B7EX3Q",
    "B7EX4Q",
    "B7EX5Q",
    "B8BA3Q",
    "B8BA6Q",
    "B8BA7Q",
    "B8CD2Q",
    "B8DM3Q",
    "B8FD1Q",
    "B8ID1Q",
    "B9B01Q",
    "B9C01Q",
    "B9CM1Q",
    "B9E01Q",
    "B9ENV1",
    "B9M01Q",
    "B9M02Q",
    "B9M03Q",
    "B9M04Q",
    "B9N02Q",
    "B9O02Q",
    "B9P01Q",
    "B9S14Q",
    "B9S15Q",
    "B9SE1Q",
    "BA-DEVELOPMENT-ENVIRONMENT",
    "BA-DRAMA-THEATRE-STUDIES",
    "BA-HUMAN-RESOURCE-MANAGEMENT",
    "BA-HUMANITIES",
    "BA-INTERNATIONAL-STUDIES",
    "BA-LANGUAGE-CULTURE",
    "BA-LAW",
    "BA-MUSIC",
    "BA-POLITICAL-PHILOSOPHICAL-ECONOMIC-STUDIES-PPE",
    "BA-VISUAL-ARTS",
    "BACC",
    "BACCLLB",
    "BACHELOR-DATA-SCIENCE-BDATSCI",
    "BACHELOR-MUSIC-BMUS",
    "BACHELOR-NURSING",
    "BACHELOR-OCCUPATIONAL-THERAPY",
    "BACHELOR-SOCIAL-WORK",
    "BACHELOR-SPEECH-LANGUAGE-HEARING-THERAPY",
    "BAGRIC-AGRIBUSINESS-MANAGEMENT",
    "BAGRIC-AGRICULTURAL-PRODUCTION-MANAGEMENT-ELSENB",
    "BCOM-ACTUARIAL-SCIENCE",
    "BCOM-ECONOMIC-SCIENCES",
    "BCOM-FINANCIAL-ACCOUNTING",
    "BCOM-INDUSTRIAL-PSYCHOLOGY",
    "BCOM-INTERNATIONAL-BUSINESS",
    "BCOM-LAW",
    "BCOM-MANAGEMENT-ACCOUNTING",
    "BCOM-MANAGEMENT-SCIENCES",
    "BCOM-MATHEMATICAL-SCIENCES",
    "BDIV-BACHELOR-DIVINITY",
    "BED-FOUNDATION-PHASE-EDUCATION",
    "BED-INTERMEDIATE-PHASE-EDUCATION",
    "BENG-CHEMICAL",
    "BENG-CIVIL",
    "BENG-ELECTRICAL-ELECTRONIC",
    "BENG-ELECTRICAL-ELECTRONIC-DATA-ENGINEERING",
    "BENG-INDUSTRIAL",
    "BENG-MECHANICAL",
    "BENG-MECHATRONIC",
    "BSC",
    "BSC-BIODIVERSITY-ECOLOGY",
    "BSC-CHEMISTRY",
    "BSC-COMPUTER-SCIENCE",
    "BSC-CONSERVATION-ECOLOGY",
    "BSC-DIETETICS",
    "BSC-EARTH-SCIENCE",
    "BSC-FOOD-SCIENCE",
    "BSC-FORESTRY-FORESTRY-WOOD-SCIENCES-BSCFOR",
    "BSC-GEOINFORMATICS",
    "BSC-HUMAN-LIFE-SCIENCES",
    "BSC-MATHEMATICAL-SCIENCES",
    "BSC-MOLECULAR-BIOLOGY-BIOTECHNOLOGY",
    "BSC-PHYSICS",
    "BSC-PHYSIOTHERAPY",
    "BSC-SPORT-SCIENCE",
    "BSCAGRIC-AGRICULTURAL-ECONOMICS",
    "BSCAGRIC-ANIMAL-PRODUCTION-SYSTEMS",
    "BSCAGRIC-PLANT-SOIL-SCIENCE",
    "BSCAGRIC-VITICULTURE-OENOLOGY",
    "BTH-BACHELOR-THEOLOGY",
    "CBA00",
    "CBA08",
    "CBA10",
    "CBA12",
    "CBA13",
    "CBA14",
    "CBA17",
    "CBA18",
    "D34F9Q",
    "D34FBQ",
    "D34LEQ",
    "D34LGQ",
    "D34MKQ",
    "D34P2Q",
    "D34PEQ",
    "D34RMQ",
    "D34SBQ",
    "D34SEQ",
    "D34TEQ",
    "D34TMQ",
    "D34TRQ",
    "D3A15Q",
    "D6MAEQ",
    "D6MASQ",
    "D6OPEQ",
    "D6OPMQ",
    "D7002Q",
    "D7EX2Q",
    "D8AT1Q",
    "D8FP1Q",
    "D8JD1Q",
    "D9S01Q",
    "DI1401",
    "DIPLOMA-SUSTAINABLE-DEVELOPMENT",
    "EBA00",
    "EBA01",
    "EFA00",
    "EFA01",
    "EFA03",
    "EFA05",
    "EFA06",
    "EFA07",
    "EFA08",
    "EFA09",
    "FBA00",
    "FBA04",
    "FBA05",
    "FBA07",
    "HFA00",
    "HFA01",
    "HFA02",
    "LFA14",
    "LLB-FOUR-YEAR",
    "MBCHB",
    "SBA04",
    "SBA09",
    "SBA10",
    "SBA11",
    "SBA12",
    "SBA13",
    "SBA15",
    "SBA20",
    "SBA21",
    "SBA22",
    "WITS-BSC-GEN",
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
    "tut-bengtech-chemical-engineering",
    "tut-bengtech-civil-engineering",
    "tut-bengtech-electrical-engineering",
    "tut-bengtech-industrial-engineering",
    "tut-bengtech-mechanical-engineering",
    "tut-bengtech-mechatronics-engineering",
    "tut-bengtech-metallurgical-engineering",
    "tut-benvironmental-health",
    "tut-bgeomatics",
    "tut-bhsci-biokinetics",
    "tut-bhsci-clinical-technology",
    "tut-bhsci-medical-laboratory-science",
    "tut-bhsci-medical-orthotics-and-prosthetics",
    "tut-bhsci-veterinary-technology",
    "tut-bnursing",
    "tut-bpharm-bachelor-of-pharmacy",
    "tut-brad-diagnostic-bachelor-of-radiography-in-diagn",
    "tut-bsc-industrial-chemistry",
    "tut-dip-accounting",
    "tut-dip-administrative-information-management",
    "tut-dip-adult-and-community-education-and-training-s",
    "tut-dip-adult-and-community-education-and-training-s-2",
    "tut-dip-adult-and-community-education-and-training-s-3",
    "tut-dip-adventure-tourism-management-only-mbombela-c",
    "tut-dip-analytical-chemistry",
    "tut-dip-animal-sciences",
    "tut-dip-biotechnology",
    "tut-dip-building-science",
    "tut-dip-casino-resort-management",
    "tut-dip-civil-engineering",
    "tut-dip-commercial-photography",
    "tut-dip-computer-science",
    "tut-dip-computer-science-extended",
    "tut-dip-computer-systems-engineering",
    "tut-dip-computer-systems-engineering-extended",
    "tut-dip-contact-centre-management",
    "tut-dip-correctional-and-rehabilitation-studies",
    "tut-dip-crop-production",
    "tut-dip-economics",
    "tut-dip-ecotourism-management-only-mbombela-campus",
    "tut-dip-electrical-engineering",
    "tut-dip-entrepreneurship",
    "tut-dip-environmental-sciences",
    "tut-dip-equine-science",
    "tut-dip-event-management",
    "tut-dip-fashion-design-and-technology",
    "tut-dip-financial-management",
    "tut-dip-financial-planning",
    "tut-dip-fine-and-applied-arts",
    "tut-dip-food-operations-management",
    "tut-dip-food-technology",
    "tut-dip-geology",
    "tut-dip-geomatics",
    "tut-dip-horticulture",
    "tut-dip-hospitality-management",
    "tut-dip-human-resource-management",
    "tut-dip-industrial-design",
    "tut-dip-industrial-physics",
    "tut-dip-informatics",
    "tut-dip-informatics-extended",
    "tut-dip-information-technology",
    "tut-dip-information-technology-extended",
    "tut-dip-integrated-communication",
    "tut-dip-integrated-communication-design",
    "tut-dip-interior-design",
    "tut-dip-internal-auditing",
    "tut-dip-jewellery-design-and-manufacture",
    "tut-dip-journalism",
    "tut-dip-kinesiology-and-coaching-science",
    "tut-dip-landscape-technology",
    "tut-dip-language-practice",
    "tut-dip-law",
    "tut-dip-legal-support",
    "tut-dip-marketing",
    "tut-dip-motion-picture-production",
    "tut-dip-multimedia-computing",
    "tut-dip-multimedia-computing-extended",
    "tut-dip-nature-conservation",
    "tut-dip-operations-management",
    "tut-dip-performing-arts-dance",
    "tut-dip-performing-arts-jazz-music",
    "tut-dip-performing-arts-opera",
    "tut-dip-performing-arts-technical-theatre-and-design",
    "tut-dip-performing-arts-theatre-arts-and-performance",
    "tut-dip-policing",
    "tut-dip-public-affairs-admin-of-state",
    "tut-dip-public-affairs-local-government",
    "tut-dip-public-finance",
    "tut-dip-retail-business-management",
    "tut-dip-somatic-therapy",
    "tut-dip-sport-management",
    "tut-dip-supply-chain-management",
    "tut-dip-tourism-management",
    "tut-dip-water-science-and-technology",
    "tut-dip-wildlife-management",
    "tut-dip-work-study",
    "tut-hcert-accounting",
    "tut-hcert-administrative-information-management-onli",
    "tut-hcert-construction-engineering-material-test",
    "tut-hcert-construction-engineering-water-and-waste",
    "tut-hcert-contact-centre-management-online-presentat",
    "tut-hcert-dental-assisting",
    "tut-hcert-electrical-engineering",
    "tut-hcert-forestry-management-only-mbombela-campus",
    "tut-hcert-industrial-engineering",
    "tut-hcert-mechanical-engineering",
    "tut-hcert-music",
    "tut-hcert-resource-and-waste-management",
    "tut-hcert-water-treatment",
})


def _qualifying_codes() -> frozenset[str]:
    data = load()
    programmes = {p["qualification_code"]: p for p in data["programmes"]}
    institutions = {i["id"]: i for i in data["institutions"]}

    qualifying = set()
    for code, programme in programmes.items():
        if not programme.get("scoreable", True):
            # Mirrors the engine. main.py routes a scoreable=false
            # programme to requires_additional_assessment and never
            # scores or evaluates it, so it can never be in the
            # qualifying set -- and it may legitimately state no score
            # and no subject tree at all, which is what this loop
            # tripped over when Stellenbosch's two audition-entry
            # music programmes arrived.
            continue
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
