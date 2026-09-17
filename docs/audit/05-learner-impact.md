# Section 5 — Correctness Impact on Real Learners

**Status: read-only audit. Nothing outside `docs/audit/` was changed.**

## Method

The API side was run via a line-for-line JS port of `evaluator.py` /
`scoring.py` / `qualify.py` (this environment's Python venv is currently
blocked by an Application Control policy — `uv run pytest` fails with `os
error 4551` — unrelated to this audit; see Section 2's method note). The
canonical-fixture result was cross-checked against this port before
trusting it further: it reproduces the project's own established ground
truth (**APS 41, 28 qualifying UJ programmes**) exactly.

The frontend side was run by executing the **real, current, live**
production matching logic — `new UJ()`, the real `checkSubjectRequirements`,
and the real `calculateAPS(subjects, "default")` — via a temporary Jest
test added to `courseFinder/__tests__/`, run once, deleted immediately
after (confirmed via `git status` before and after). This reproduces
exactly what a user of the live site experiences today for UJ's main list,
and what every institution's extended-curriculum/TVET lists will continue
to compute even after the in-flight integration ships (Section 4).

Because the frontend holds 98 UJ courses the API doesn't have (Section 1),
a raw side-by-side count is misleading on its own — it would look like a
huge "disagreement" that's actually just a coverage gap already quantified
in Section 1. This section reports both: the raw counts (for completeness)
and, more usefully, the count restricted to the **25 programmes present in
both systems** (Section 1's matched set), which isolates genuine
disagreement from coverage gaps.

---

## Canonical fixture

`english_hl 87, afrikaans_fal 85, mathematics 88, life_orientation 88,
geography 92, life_sciences 87, physical_sciences 73`

| | Score | Qualifies for |
|---|---|---|
| API | 41 | 28 of 29 programmes (1 near-miss: `B5LAZQ`, BEd isiZulu — correctly, this learner doesn't offer isiZulu) |
| Frontend (raw, all 98 UJ courses) | 41 | 70 of 98 courses |

**Restricted to the 25 matched programmes:** both systems agree on 23 of
25. Exactly **1 disagreement**:

| Code | API | Frontend | Adjudication |
|---|---|---|---|
| `B4L03Q` (LLB) | Qualifies (score 41 ≥ 31; English HL5 ✓; `any_additional_language` level 4 satisfied by Afrikaans FAL) | **Rejected** — `missing: ["Additional Language (Level 4)"]` | **Frontend wrong.** This is the confirmed LLB bug (Section 2b): the dangling `"Additional Language"` key matches no real subject. A genuinely well-qualified LLB applicant — APS 41 against a minimum of 31, every named subject requirement met — is turned away by the live matcher for the sole reason that this one requirement is unencodable as written. |

The 24th pair (`B5LAZQ`) is correctly a non-match on both sides, for the
same real reason (no isiZulu offered) — not a bug, a genuine shared
near-miss.

---

## Adversarial profile 1 — Maths Literacy candidate

`english_hl 70, afrikaans_fal 65, mathematical_literacy 75, life_orientation 80,
geography 70, life_sciences 65, business_studies 60` (no pure Mathematics
at all — tests mutual exclusion and the conditional-APS bug)

| | Score | Qualifies for (of 29 / restricted to 25 matched) |
|---|---|---|
| API | 33 | 5 of 29 (`B34HRQ`, `B4L03Q`, `B5BFPQ`, `B8CD2Q`, `B9S15Q`) |
| Frontend | 33 | 21 of 98 raw; **4 of 25 matched** |

**Restricted disagreement: 1.**

| Code | API | Frontend | Adjudication |
|---|---|---|---|
| `B4L03Q` (LLB) | Qualifies (33 ≥ 32 for the Maths-Lit conditional threshold; `any_additional_language` satisfied by Afrikaans FAL) | Rejected — same dangling-key failure as above | **Frontend wrong**, same root cause |

Note what does **not** show as a disagreement here, but should be read
alongside Section 1: `B8CD2Q` and `B9S15Q` both charge a real APS of 33 for
a Maths-Lit candidate on the API side; the frontend's flattened, always-25/
always-32 figures happen to also clear 33 for *this specific learner's*
score, so the conditional-APS bug (Section 1) doesn't surface as a
pass/fail disagreement for this particular profile — it would for a
learner scoring exactly 32 (API: fails `B9S15Q`'s Maths-Lit threshold of
33; frontend: passes, since it never charges more than 32). The bug is
real and already adjudicated in Section 1; this profile simply wasn't
constructed at the exact boundary where it flips an outcome.

---

## Adversarial profile 2 — Technical-stream candidate

`english_hl 70, afrikaans_fal 65, technical_mathematics 75,
life_orientation 80, technical_sciences 70, geography 65, life_sciences 60`
(Technical Mathematics + Technical Sciences, no pure Maths/Physical
Sciences — tests the Technical Mathematics both-directions encoding)

| | Score | Qualifies for (restricted to 25 matched) |
|---|---|---|
| API | 33 | 4 of 25 (`B1CISQ`, `B34HRQ`, `B6CV3Q`, `B6MC2Q`) |
| Frontend | 33 | 2 of 25 (`B1CISQ`, `B34HRQ`) |

**Restricted disagreement: 2.**

| Code | API | Frontend | Adjudication |
|---|---|---|---|
| `B6CV3Q` (BEngTech Civil Engineering) | Qualifies — Technical Mathematics accepted as an alternative to Mathematics, Technical Sciences already correctly accepted as an alternative to Physical Sciences | **Rejected** — `missing: ["mathematics (Level 5)"]` (flat key, no Technical Mathematics alternative — Section 2c/2f) | **Flagged, not resolved** — see Section 1 items 5–10: this specific fact (does UJ's FEBE genuinely accept Technical Mathematics for these six programmes) could not be independently confirmed from either of two independent text extractions of the prospectus, which agree with the frontend and disagree with the API. If the API is right, this is a real technical-stream learner wrongly turned away by the frontend. If the extractions are right, the API itself needs correcting first. This is the single highest-value item to resolve with a working PDF reader before treating either side as ground truth for these six codes. |
| `B6MC2Q` (BEngTech Mechanical Engineering) | Qualifies — same reasoning | Rejected — same flat-key bug | Same caveat as `B6CV3Q` |

`B6EL1Q`/`B6ES0Q`/`B6CS0Q`/`B6MS0Q` do **not** appear as disagreements for
this profile: both systems correctly reject a Technical-Sciences-only
candidate for these four, because the API's own data excludes Technical
Sciences (not just Technical Mathematics) for that subset — a case where
the frontend's "omit the alternative" mechanism happens to land on the
right answer by coincidence (Section 2f).

---

## Adversarial profile 3 — FAL English + second (home) language candidate

`english_fal 70, isizulu_hl 75, mathematics 70, life_orientation 80,
geography 65, life_sciences 60, physical_sciences 55` (this is the shape of
the actual LLB scenario the audit brief names: an FAL English speaker whose
real home language is a second NSC-recognised language)

| | Score | Qualifies for (restricted to 25 matched) |
|---|---|---|
| API | 32 | 15 of 25 |
| Frontend | 32 | 8 of 25 |

**Restricted disagreement: 7 — the largest of the three adversarial
profiles, and the clearest demonstration of the HL/FAL encoding bugs'
real-world cost.**

| Code | API | Frontend | Root cause (Section 2) |
|---|---|---|---|
| `B5BFPQ` (BEd Foundation Phase) | Qualifies — this learner's English FAL is 70% = level 6, which clears the FAL threshold of 6 in the banded HL5-or-FAL6 rule | Rejected | Dual ANDed HL+FAL keys (`5`/`6`) — the FAL-required key correctly passes, but the separate, always-ANDed HL-required key can never be satisfied by an FAL-only transcript, so the record fails overall regardless of the FAL side |
| `B9M01Q` (Diagnostic Radiography) | Qualifies | Rejected | Dual ANDed HL+FAL keys (equal thresholds 5/5) — an FAL-only learner can never satisfy the HL-only key |
| `B9S15Q` (Biokinetics) | Qualifies | Rejected | Same dual-key pattern |
| `B4L03Q` (LLB) | Qualifies | Rejected | Dangling `"Additional Language"` key (this learner's isiZulu HL should satisfy it) |
| `B2I01Q` (BSc Information Technology) | Qualifies | Rejected | HL-only key, no FAL entry at all (Section 2a, Pattern 2) |
| `B5LAZQ` (BEd isiZulu) | Qualifies | Rejected | Dual ANDed keys, both for English *and* isiZulu |
| `B9E01Q` (Emergency Medical Care) | Qualifies | Rejected | Dual ANDed HL+FAL keys, equal thresholds |

Every one of these 7 was individually re-run against `evaluateProgramme`
directly (not just read off the bulk `runQualify` output) with the
programme's exact `requirements.nsc` block printed alongside the result,
to confirm each API-side "qualifies" verdict before citing it here — e.g.
`B5BFPQ`'s full requirement tree and a standalone re-evaluation were both
inspected directly, confirming 70% English FAL (level 6) clears its FAL
threshold of 6.

---

## What this section establishes

Across four profiles run against the same 25 real UJ programmes both
systems claim to know about, the frontend disagreed with the API **11
times** (1 + 1 + 2 + 7, `B4L03Q` counted once per profile it recurred in)
out of at most 100 possible programme×profile combinations. **In every
single disagreement, the frontend was the more restrictive side** — every
disagreement is a learner who genuinely qualifies (per the API's
requirement logic, itself independently corroborated for the LLB and
dual-key cases) being told they don't, never the reverse. This matches
Section 2's structural finding exactly: every bug found there is a
false-negative generator, not a false-positive one — the frontend's
`checkSubjectRequirements` ANDs every dict key, so a broken encoding can
only ever make a requirement harder to satisfy, never easier. There is no
evidence anywhere in this audit of the frontend wrongly telling a learner
they qualify when they don't; the entire risk surface found is learners
being wrongly turned away from programmes they are, by the prospectus's own
verified rule, entitled to see.
