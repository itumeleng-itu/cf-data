"""Whole certificates, scored end to end through the API.

WHY THIS FILE EXISTS
--------------------
test_scoring.py checks the scoring functions and test_evaluator.py checks
the requirement tree, each in isolation. Neither asks the question a learner
asks: "I have THESE marks -- what can I do?" Everything in between -- the
subject list, the request shape, APS, subject rules, which bucket a
programme lands in -- only runs together when a whole certificate goes
through /v1/qualify.

Three real National Senior Certificates were scored by hand against
prospectus page 13 and then run through the API, and the agreement is
pinned here so a future scoring change has to keep it. But three
certificates that agree is weaker evidence than it sounds, for two reasons
this file tries to address:

1. All three are the SAME SHAPE -- KwaZulu-Natal, an African-language Home
   Language with English First Additional, exactly seven subjects, standard
   November NSC. Two real defects hid in that shape: Life Orientation being
   droppable (invisible at exactly seven subjects) and the "any" group
   reporting its first branch rather than its nearest. So the synthetic
   cases below deliberately break the shape: eight and nine subjects,
   Afrikaans as Home Language, and a learner strong enough to qualify.

2. Not one of the three qualified for anything at Wits -- all scored 0
   qualified -- so until TestQualifyingLearner below, the qualifying path
   had never been exercised end to end by a whole certificate at all.

WHAT THIS FILE CANNOT DO
------------------------
Every expected APS here was hand-computed from the same reading of the same
page-13 table the implementation uses. If that table was misread, the hand
calculation and the code agree and both are wrong. Wits publishes no worked
arithmetic -- page 13's worksheet is blank -- so these are consistency
fixtures, NOT worked examples, and they cannot discharge
tests/test_scoring_worked_examples.py. See docs/scoring/wits.md section 10.
"""

import pytest

# --- the three real certificates -------------------------------------------
# Marks transcribed from the statements of results. Each was cross-checked
# against the NSC achievement level printed beside it on the certificate
# itself, which catches a misread digit: a wrong percentage almost always
# falls in a different band.

CERT_2017 = {  # NSC Nov 2017, Ukhahlamba KZN
    "isizulu_hl": 77, "english_fal": 75, "mathematics": 8,
    "life_orientation": 83, "geography": 72, "history": 78, "life_sciences": 50,
}
CERT_2022 = {  # NSC Nov 2022, eThekwini KZN -- a Mathematical Literacy learner
    "isizulu_hl": 76, "english_fal": 61, "mathematical_literacy": 40,
    "life_orientation": 73, "business_studies": 67, "economics": 64, "tourism": 48,
}
CERT_2024 = {  # NSC Nov 2024, Ukhahlamba KZN -- Physical Sciences at exactly 30%
    "isizulu_hl": 83, "english_fal": 75, "mathematics": 41,
    "life_orientation": 87, "geography": 51, "life_sciences": 54,
    "physical_sciences": 30,
}

# --- synthetic learners, each breaking the shape of the three above --------

STRONG = {  # English HOME Language, Mathematics and Physical Sciences
    "english_hl": 82, "afrikaans_fal": 74, "mathematics": 78,
    "physical_sciences": 71, "life_sciences": 68, "geography": 66,
    "life_orientation": 85,
}
AFRIKAANS_HL = {  # Afrikaans as Home Language -- the bonus must NOT follow it
    "afrikaans_hl": 80, "english_fal": 72, "mathematics": 65,
    "accounting": 70, "business_studies": 68, "economics": 64,
    "life_orientation": 77,
}


def qualify(client, marks, **extra):
    body = {"subjects": [{"subject": k, "percentage": v} for k, v in marks.items()],
            "academic_year": 2027, "institutions": ["wits"]}
    body.update(extra)
    response = client.post("/v1/qualify", json=body)
    assert response.status_code == 200, response.text
    return response.json()


class TestRealCertificates:
    """The three statements of results, end to end."""

    @pytest.mark.parametrize("marks,expected_aps", [
        (CERT_2017, 33),
        (CERT_2022, 31),
        (CERT_2024, 29),
    ])
    def test_aps_matches_the_hand_calculation(self, client, marks, expected_aps):
        assert qualify(client, marks)["scores"]["wits"] == expected_aps

    def test_every_wits_programme_is_accounted_for(self, client):
        """evaluated_count must equal the programmes on file, and the three
        buckets must not exceed it. They do not SUM to it: a programme
        failing on three or more criteria is deliberately left out of
        near_misses to keep "near" meaningful, and nothing counts those."""
        body = qualify(client, CERT_2017)
        listed = len(client.get("/v1/programmes",
                                params={"institution": "wits",
                                        "academic_year": 2027}).json())
        assert body["evaluated_count"] == listed
        shown = (len(body["qualified"]) + len(body["near_misses"])
                 + len(body["requires_additional_assessment"]))
        assert shown <= body["evaluated_count"]

    def test_the_2017_certificate_is_rescued_only_by_waitlists(self, client):
        """APS 33 clears nothing outright, but sits at the top of the
        30-33 band printed on prospectus page 98."""
        body = qualify(client, CERT_2017)
        assert body["qualified"] == []
        score_only = [p for p in body["near_misses"]
                      if {f["kind"] for f in p["failures"]} == {"score"}]
        assert any("30-33" in note for p in score_only for note in p["selection_notes"])

    def test_the_2024_certificate_is_below_every_waitlist_floor(self, client):
        """APS 29 is one point under 30, the lowest waitlist floor in the
        catalogue -- the difference between "nothing yet" and "nothing at
        all", and worth a test because it is one mark wide."""
        body = qualify(client, CERT_2024)
        assert body["scores"]["wits"] == 29
        assert body["qualified"] == []
        floors = []
        for p in body["near_misses"]:
            for note in p["selection_notes"]:
                if "APS " in note and "-" in note:
                    for token in note.split():
                        if "-" in token and token.split("-")[0].isdigit():
                            floors.append(int(token.split("-")[0]))
        assert floors and min(floors) == 30

    def test_a_maths_literacy_learner_is_not_told_to_take_mathematics(self, client):
        """Prospectus pages 102 and 103 print "Mathematics Level 4 OR Maths
        Literacy Level 5 OR Technical Mathematics Level 5". Reporting only
        the first branch tells a Mathematical Literacy learner they are
        barred by a Grade 10 subject choice, when the programme is open to
        them two levels up."""
        body = qualify(client, CERT_2022)
        bed = [p for p in body["near_misses"]
               if p["qualification_code"] in ("HFA00", "HFA01")]
        assert len(bed) == 2
        for programme in bed:
            message = next(f["message"] for f in programme["failures"]
                           if f["kind"] != "score")
            assert "Mathematical Literacy level 5" in message
            assert "Technical Mathematics level 5" in message
            assert "you have Mathematical Literacy level 3" in message

    def test_a_learner_holding_a_subject_is_never_told_they_lack_it(self, client):
        """The 2024 certificate offers Mathematics and Physical Sciences,
        both too low. Every failure must therefore be a level shortfall,
        never an absence -- the distinction a learner acts on."""
        for programme in qualify(client, CERT_2024)["near_misses"]:
            for failure in programme["failures"]:
                if failure["kind"] != "score":
                    assert failure["actual_level"] is not None, failure["message"]


class TestQualifyingLearner:
    """The branch no real certificate has reached. All three scored 0."""

    def test_a_strong_learner_qualifies(self, client):
        body = qualify(client, STRONG)
        assert body["scores"]["wits"] == 42
        assert len(body["qualified"]) > 0
        assert all(p["failures"] == [] for p in body["qualified"])

    def test_qualifying_at_exactly_the_threshold_counts_as_qualified(self, client):
        """Chemical Engineering (page 59) and Biomedical Engineering (page
        64) both require APS 42 with English, Mathematics and Physical
        Sciences at level 5. This learner has exactly 42. An off-by-one in
        the comparison puts them in near_misses instead, which is the
        difference between "apply" and "do not bother"."""
        body = qualify(client, STRONG)
        at_threshold = [p for p in body["qualified"] if p["margin"] == 0]
        assert {"EFA00", "EBA00"} <= {p["qualification_code"] for p in at_threshold}
        assert all(p["score_required"] == 42 for p in at_threshold
                   if p["qualification_code"] in ("EFA00", "EBA00"))

    def test_qualified_and_near_miss_are_disjoint(self, client):
        body = qualify(client, STRONG)
        qualified = {p["qualification_code"] for p in body["qualified"]}
        near = {p["qualification_code"] for p in body["near_misses"]}
        unscoreable = {p["qualification_code"]
                       for p in body["requires_additional_assessment"]}
        assert not qualified & near
        assert not qualified & unscoreable
        assert not near & unscoreable

    def test_unscoreable_programmes_never_qualify_anyone(self, client):
        """Health Sciences uses a Composite Index (60% academic, 40% NBT)
        and the graduate LLBs use no matric calculation at all. However
        strong the learner, these must stay in their own bucket rather
        than being silently passed or failed on an APS that does not
        apply to them."""
        body = qualify(client, STRONG)
        assert len(body["requires_additional_assessment"]) == 11
        for programme in body["requires_additional_assessment"]:
            assert "score_required" not in programme
            assert programme["selection_notes"]


class TestHomeLanguageIsNotTheBonus:
    """Wits' bonus column is headed "English and Mathematics". It follows
    the SUBJECT English -- Home Language or First Additional -- and
    Mathematics, never whichever language a learner happens to offer as
    their Home Language. Getting this wrong awards +2 to most South
    African learners."""

    def test_afrikaans_home_language_takes_no_bonus(self, client):
        body = qualify(client, AFRIKAANS_HL)
        # Afrikaans HL 80 -> 7 (no bonus), English FAL 72 -> 6+2 = 8,
        # Mathematics 65 -> 5+2 = 7, Accounting 70 -> 6, Business 68 -> 5,
        # Economics 64 -> 5, Life Orientation 77 -> 2.  Total 40.
        assert body["scores"]["wits"] == 40

    def test_english_home_and_first_additional_score_alike(self, client):
        """The bonus attaches to English either way round, so mirroring
        which language is Home Language must not change the total."""
        as_fal = qualify(client, {
            "english_fal": 75, "isizulu_hl": 77, "mathematics": 8,
            "life_orientation": 83, "geography": 72, "history": 78,
            "life_sciences": 50})["scores"]["wits"]
        as_hl = qualify(client, {
            "english_hl": 75, "isizulu_fal": 77, "mathematics": 8,
            "life_orientation": 83, "geography": 72, "history": 78,
            "life_sciences": 50})["scores"]["wits"]
        assert as_fal == as_hl == 33

    def test_a_higher_home_language_mark_can_score_lower(self, client):
        """The counter-intuitive consequence, stated as a test so nobody
        "fixes" it: isiZulu HL at 77% is worth 6 and English FAL at 75% is
        worth 8."""
        higher_hl = qualify(client, {"isizulu_hl": 77, "life_orientation": 0,
                                     "geography": 0, "history": 0,
                                     "life_sciences": 0, "mathematics": 0})
        lower_english = qualify(client, {"english_fal": 75, "life_orientation": 0,
                                         "geography": 0, "history": 0,
                                         "life_sciences": 0, "mathematics": 0})
        assert higher_hl["scores"]["wits"] == 6
        assert lower_english["scores"]["wits"] == 8


class TestSubjectCountSelection:
    """Best-seven selection, which does nothing at all until a learner
    offers an eighth subject -- which is exactly why a real defect lived
    here through three certificates."""

    EIGHT = {"english_hl": 85, "isizulu_fal": 88, "life_orientation": 90,
             "history": 86, "geography": 84, "business_studies": 82,
             "accounting": 80, "tourism": 78}

    def test_life_orientation_always_occupies_one_of_the_seven(self, client):
        """Page 13: "the best seven subjects INCLUDING Life Orientation".
        LO is scored on the compressed 0-4 scale, so it is almost always
        the lowest-scoring subject a learner holds, and a best-seven that
        lets it compete drops it the moment an eighth subject outranks it.

        Correct: LO's 4 plus the best six others (9+7+7+7+7+7) = 48.
        Letting it compete gives the top seven of eight = 50."""
        assert qualify(client, self.EIGHT)["scores"]["wits"] == 48

    def test_removing_life_orientation_changes_the_score(self, client):
        """The sharpest statement of that defect: before the fix, deleting
        Life Orientation from this learner's marks left their APS
        untouched, because it was contributing nothing."""
        without = {k: v for k, v in self.EIGHT.items() if k != "life_orientation"}
        assert qualify(client, without)["scores"]["wits"] != \
               qualify(client, self.EIGHT)["scores"]["wits"]

    def test_seven_subjects_are_unaffected_by_the_rule(self, client):
        """Everything counts when there are exactly seven, so the three
        real certificates must not move."""
        for marks, expected in ((CERT_2017, 33), (CERT_2022, 31), (CERT_2024, 29)):
            assert len(marks) == 7
            assert qualify(client, marks)["scores"]["wits"] == expected

    def test_a_ninth_subject_helps_only_if_it_displaces_a_counted_one(self, client):
        """With Life Orientation forced in, six places are contested. This
        learner's sixth-best non-LO subject is worth 7, so a ninth subject
        has to beat 7 -- matching it changes nothing, which is easy to get
        wrong by assuming any strong subject must help."""
        base = qualify(client, self.EIGHT)["scores"]["wits"]
        assert base == 48
        for percentage, expected in ((35, 48),   # worth 0, far below
                                     (85, 48),   # worth 7, ties, displaces nothing
                                     (90, 49)):  # worth 8, displaces a 7
            nine = {**self.EIGHT, "consumer_studies": percentage}
            assert qualify(client, nine)["scores"]["wits"] == expected

    @pytest.mark.xfail(reason=(
        "Faculty-specific subjects are not forced into the counted set. "
        "Page 13: 'faculty specific subjects must be included in the "
        "calculation'. Which subject is compulsory varies per programme "
        "while scoring_config is institution-wide, so only Life "
        "Orientation is configured. A per-programme scoring_override is "
        "the fix. See docs/scoring/wits.md section 10.2."), strict=True)
    def test_a_weak_faculty_subject_is_not_dropped(self, client):
        """A learner with nine subjects whose Mathematics is weak. Wits
        counts Mathematics for a Commerce application whether or not it is
        among their best; best-seven drops it and overstates them."""
        nine = {**CERT_2017, "accounting": 88, "business_studies": 85}
        # Life Orientation 3 + Mathematics 0 + best five others
        # (8+7+7+6+6) = 37. Without forcing Mathematics: 43.
        assert qualify(client, nine)["scores"]["wits"] == 37


class TestTheRequestContract:
    """What the API accepts, stated deliberately rather than left to be
    discovered by a learner who gets nothing back."""

    BASE = {"english_hl": 70, "isizulu_fal": 70, "mathematics": 70,
            "life_orientation": 70, "history": 70, "geography": 70}

    @pytest.mark.parametrize("subject", [
        "south_african_sign_language_hl",  # named as a language option on
                                           # Wits' own BA pages
        "dance_studies",
        "french_sal",
        "nonsense_subject",
    ])
    def test_an_unrecognised_subject_rejects_the_whole_request(self, client, subject):
        """Currently a hard 422: the learner gets no answer at all rather
        than an answer computed from the subjects that ARE recognised.
        Pinned as the current contract, not endorsed as the right one --
        the first three are real NSC subjects. See docs/scoring/wits.md
        section 10.4."""
        response = client.post("/v1/qualify", json={
            "subjects": [{"subject": k, "percentage": v}
                         for k, v in {**self.BASE, subject: 70}.items()],
            "academic_year": 2027})
        assert response.status_code == 422

    @pytest.mark.parametrize("count", [5, 10])
    def test_too_few_or_too_many_subjects_are_rejected(self, client, count):
        """A real NSC carries six to nine subjects; outside that the input
        is more likely a mistake than a candidate."""
        marks = {f"{s}": 70 for s in list(self.BASE)[:min(count, 6)]}
        while len(marks) < count:
            marks[f"extra_{len(marks)}"] = 70
        response = client.post("/v1/qualify", json={
            "subjects": [{"subject": k, "percentage": v} for k, v in marks.items()],
            "academic_year": 2027})
        assert response.status_code == 422

    @pytest.mark.parametrize("percentage", [-1, 101])
    def test_an_impossible_percentage_is_rejected(self, client, percentage):
        marks = dict(self.BASE)
        marks["geography"] = percentage
        response = client.post("/v1/qualify", json={
            "subjects": [{"subject": k, "percentage": v} for k, v in marks.items()],
            "academic_year": 2027})
        assert response.status_code == 422


class TestPage13Bands:
    """Every boundary of the page-13 table, exercised through the API one
    subject at a time. Band edges are where an off-by-one hides, and two
    of these bands are the ones a national-scale APS calculator gets
    wrong."""

    @staticmethod
    def _one(client, subject, percentage):
        """Score a single subject by padding with subjects worth zero --
        the request shape demands at least six."""
        marks = {subject: percentage}
        for filler in ("history", "geography", "life_sciences",
                       "accounting", "tourism", "economics"):
            if filler != subject:
                marks[filler] = 0
            if len(marks) == 6:
                break
        return qualify(client, marks)["scores"]["wits"]

    @pytest.mark.parametrize("percentage,points", [
        (0, 0), (29, 0),
        (30, 0), (39, 0),      # Wits scores 30-39 as ZERO, not NSC level 2
        (40, 3), (49, 3),
        (50, 4), (59, 4),
        (60, 5), (69, 5),
        (70, 6), (79, 6),
        (80, 7), (89, 7),
        (90, 8), (100, 8),
    ])
    def test_an_ordinary_subject(self, client, percentage, points):
        assert self._one(client, "geography", percentage) == points

    @pytest.mark.parametrize("percentage,points", [
        (39, 0),
        (40, 3), (50, 4), (59, 4),   # no bonus below 60
        (60, 7), (69, 7),            # 5 +2
        (70, 8), (79, 8),            # 6 +2
        (80, 9), (89, 9),            # 7 +2
        (90, 10), (100, 10),         # 8 +2
    ])
    def test_english_takes_the_bonus_only_from_60(self, client, percentage, points):
        assert self._one(client, "english_fal", percentage) == points

    @pytest.mark.parametrize("percentage,points", [
        (8, 0), (29, 0), (30, 0), (39, 0),
        (40, 3), (55, 4), (59, 4),
        (60, 7), (70, 8), (80, 9), (90, 10),
    ])
    def test_mathematics_takes_the_bonus_only_from_60(self, client, percentage, points):
        """A flat +2 would award two points for Mathematics at 8%."""
        assert self._one(client, "mathematics", percentage) == points

    @pytest.mark.parametrize("percentage,points", [
        (0, 0), (29, 0), (30, 0), (59, 0),
        (60, 1), (69, 1),
        (70, 2), (79, 2),
        (80, 3), (89, 3),
        (90, 4), (100, 4),
    ])
    def test_life_orientation_uses_the_compressed_scale(self, client, percentage, points):
        """NSC level 7 at 90%; Wits pays 4. A learner with an excellent LO
        mark gains about half what any other subject would give them."""
        assert self._one(client, "life_orientation", percentage) == points

    def test_mathematical_literacy_takes_no_bonus(self, client):
        """The bonus column is headed "English and Mathematics".
        Mathematical Literacy is neither."""
        assert self._one(client, "mathematical_literacy", 70) == 6
        assert self._one(client, "mathematics", 70) == 8
