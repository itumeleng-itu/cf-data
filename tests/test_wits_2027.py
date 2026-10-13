"""Wits 2027 — bundle round-trip and scorer behaviour.

The bundle fixture is a transcription of the Wits 2027 prospectus admission
tables (pages 13, 16, 18, 20, 22, 24), verified field by field against the
source. These tests hold it to the same bar seeds/ is held to, and pin the
three Wits-specific scoring behaviours that are easy to get wrong.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api" / "src"))

from app.evaluator import evaluate  # noqa: E402
from app.scoring import SCORERS  # noqa: E402
from scripts.convert_bundle import convert_bundle  # noqa: E402
from scripts.validate_data import validate  # noqa: E402

BUNDLE = json.loads(
    (ROOT / "tests" / "fixtures" / "bundles" / "wits_2027.json").read_text("utf-8"))

# NSC November 2017, Ukhahlamba KZN, Bachelor's degree pass.
# The defining fact is Mathematics at 8%: under 30% Wits scores a flat zero
# and the +2 bonus does not apply, so a whole subject slot is lost.
LEARNER = {"english_fal": 75, "isizulu_hl": 77, "mathematics": 8,
           "life_orientation": 83, "geography": 72, "history": 78,
           "life_sciences": 50}
LEARNER_APS = 33


@pytest.fixture(scope="module")
def converted():
    return convert_bundle(BUNDLE)


class TestBundleRoundTrip:
    def test_converts_without_error(self, converted):
        _, recs = converted
        assert len(recs) == len(BUNDLE["programmes"]) == 60

    def test_passes_the_same_semantic_validation_as_seeds(self, converted):
        inst, recs = converted
        assert validate({"institutions": [inst], "programmes": recs}) == []

    def test_qualification_codes_are_unique(self):
        codes = [p["qualification_code"] for p in BUNDLE["programmes"]]
        assert len(set(codes)) == len(codes)

    def test_four_year_llb_publishes_an_aps_above_the_national_ceiling(self):
        """Wits' own points table runs to 60, so its thresholds exceed the
        national scale's ~42. This is why $defs.aps and validate_data's
        APS_MAX were widened; a regression there fails here first."""
        llb = [p for p in BUNDLE["programmes"]
               if p["qualification_code"] == "LFA14"][0]
        assert llb["minimum_aps"] == 46

    def test_unscoreable_programmes_carry_no_meaningless_threshold(self):
        """Health Sciences scores on a Composite Index (60% academic, 40%
        NBT) and the graduate LLBs use no matric calculation at all."""
        un = [p for p in BUNDLE["programmes"] if p.get("scoreable") is False]
        assert len(un) == 11
        assert all(p["selection_notes"] for p in un)


class TestWitsScoring:
    CONFIG = None

    @pytest.fixture(autouse=True)
    def _cfg(self, converted):
        type(self).CONFIG = converted[0]["scoring_config"]

    def score(self, marks, **over):
        return SCORERS["custom_points_with_bonus"](marks, {**self.CONFIG, **over})

    def test_learner_scores_33(self):
        assert self.score(LEARNER) == LEARNER_APS

    def test_english_takes_the_bonus_and_another_home_language_does_not(self):
        """Wits' column is headed "English and Mathematics". The bonus
        follows the SUBJECT English, HL or FAL -- never a Home Language that
        is not English. IsiZulu HL at 77% must score BELOW English FAL at
        75%. Configuring bonus_for_home_language here would hand +2 to every
        African-language Home Language candidate."""
        one = {"english_fal": 75, "life_orientation": 0}
        two = {"isizulu_hl": 77, "life_orientation": 0}
        assert self.score(one) == 8      # band 6, +2
        assert self.score(two) == 6      # same band, no bonus

    def test_the_bonus_stops_below_60_percent(self):
        """The table prints the bonus only on the top four rows. A flat +2
        would award two points for Mathematics at 8%."""
        assert self.score({"mathematics": 8}) == 0
        assert self.score({"mathematics": 55}) == 4      # band value, no bonus
        assert self.score({"mathematics": 65}) == 7      # 5 +2

    def test_life_orientation_uses_its_own_compressed_scale(self):
        assert self.score({"life_orientation": 83}) == 3   # NSC level 7, but 3

    def test_required_subjects_are_never_dropped_by_best_n(self):
        """"Faculty specific subjects must be included in the calculation"
        (prospectus p13). Without this, best-7 drops a weak compulsory
        subject and OVERSTATES the score."""
        nine = {**LEARNER, "accounting": 88, "business_studies": 85}
        assert self.score(nine) == 44                                   # drops maths
        assert self.score(nine, required_subjects=["mathematics"]) == 40


class TestLearnerOutcomes:
    def test_qualifies_outright_for_nothing_and_is_short_on_eight(self, converted):
        inst, recs = converted
        score = SCORERS[inst["scoring_strategy"]](LEARNER, inst["scoring_config"])
        assert score == LEARNER_APS

        qualifies, subjects_met_aps_short = [], []
        for r in recs:
            if r.get("scoreable") is False:
                continue
            nsc = r["requirements"]["nsc"]
            if evaluate(nsc["subjects"], LEARNER, set(nsc.get("excluded_subjects") or [])):
                continue
            thresholds = [t["min_score"] for t in nsc.get("score", []) if "min_score" in t]
            if thresholds and score >= min(thresholds):
                qualifies.append(r["name"])
            else:
                subjects_met_aps_short.append(r["name"])

        assert qualifies == []
        assert len(subjects_met_aps_short) == 8
        assert "Bachelor of Arts (BA)" in subjects_met_aps_short
        assert "Bachelor of Social Work" in subjects_met_aps_short

    def test_commerce_fails_on_mathematics_not_on_aps(self, converted):
        _, recs = converted
        bcom = [r for r in recs if r["qualification_code"] == "CBA00"][0]
        nsc = bcom["requirements"]["nsc"]
        fails = evaluate(nsc["subjects"], LEARNER, set(nsc.get("excluded_subjects") or []))
        assert fails, "BCom requires Mathematics Level 5; this learner has 8%"


class TestCurriculum:
    def test_curricula_are_carried_through_conversion(self, converted):
        _, recs = converted
        with_cur = [r for r in recs
                    if any(s.get("curriculum") for s in r.get("streams") or [])]
        assert len(with_cur) == 54
        assert sum(len(r["streams"]) for r in recs) == 68

    def test_each_prospectus_page_becomes_its_own_stream(self, converted):
        """SBA11 is printed over six pages, one per major, all sharing one
        APS and one subject set. Conversion must keep the six course lists
        apart while keeping them on ONE record -- six records would
        duplicate the requirements and return SBA11 six times per query."""
        _, recs = converted
        sba11 = [r for r in recs if r["qualification_code"] == "SBA11"][0]
        assert len(sba11["streams"]) == 6
        pages = [s["source_page"] for s in sba11["streams"]]
        assert pages == sorted(pages) == [113, 114, 115, 116, 117, 118]
        assert len({s["name"] for s in sba11["streams"]}) == 6
        # The defect this guards: as one flat list, first year read as
        # "Introductory Life Sciences" six times over.
        first = sba11["streams"][0]["curriculum"]["first_year"]
        assert sum(1 for c in first if c.get("name") == "Introductory Life Sciences") == 1

    def test_a_single_page_programme_has_one_unnamed_stream(self, converted):
        """With nothing to distinguish it from, a stream name would just
        repeat the programme's own name."""
        _, recs = converted
        bcom = [r for r in recs if r["qualification_code"] == "CBA00"][0]
        assert len(bcom["streams"]) == 1
        assert bcom["streams"][0]["name"] is None

    def test_a_choice_keeps_both_options(self, converted):
        _, recs = converted
        bcom = [r for r in recs if r["qualification_code"] == "CBA00"][0]
        first = bcom["streams"][0]["curriculum"]["first_year"]
        choices = [c for c in first if c.get("choice")]
        assert choices, "page 45 prints two OR choices in first year"
        assert all(len(c["options"]) >= 2 for c in choices)

    def test_instruction_prose_is_not_stored_as_a_course(self, converted):
        _, recs = converted
        for r in recs:
            for stream in r.get("streams") or []:
                for items in stream["curriculum"].values():
                    for c in items:
                        for name in (c["options"] if c.get("choice") else [c["name"]]):
                            assert "credits" not in name.lower()
                            assert not name.endswith(":")
