# UCT 2027 — NSC scoring investigation

Read-only investigation. No scoring function written, `api/src/app/scoring.py`
not touched, `institutions` table not touched. Source: `data/downloads/uct_2027.pdf`
(89 pages), fetched 2026-08-08.

## 1. Vocabulary search (every page)

Searched every page for: `national senior certificate`, `nsc`, `achievement level`,
`aps`, `admission point score`, `composite`, and the percentage-band shape `(NN-NN%)`.

- `admission point score` / `aps`: concentrated on pages 16, 54, 57, 58 — the
  methodology and per-qualification requirement pages.
- `national senior certificate` / `nsc`: appears throughout page 16's
  methodology text and scattered eligibility notes.
- `composite`: does not appear — UCT does not use Wits' "Composite Index"
  terminology; UCT's equivalent concepts are named **FPS** (Faculty Points
  Score) and **WPS** (Weighted Points Score).
- **The `(NN-NN%)` percentage-band shape appears on ZERO pages.** Like Wits,
  UCT does not express NSC subject requirements as raw percentage ranges —
  it uses the numeric APS/points scale throughout.

## 2. NSC requirement pages vs international-conversion pages

- **Page 16** is the single methodology page and covers BOTH pathways at
  once: a conversion table (NSSC/Cambridge IGCSE/IB SL/IB HL/AS-Levels/
  A-Levels → points) sits alongside the prose that defines APS → FPS → WPS
  for NSC applicants specifically. Unlike Wits, UCT does not fully separate
  "NSC requirements" and "international conversions" into different pages —
  the NSC-specific admission-point methodology (what this doc needs) is
  interleaved with the non-SA conversion table on the same page.
- **Pages 54, 57**: NBT (National Benchmark Test) process/eligibility text —
  applies to NSC applicants specifically (SA-resident/schooled applicants).
- **Page 58**: `ADMISSION REQUIREMENTS BY QUALIFICATION` — the actual
  per-programme APS numbers NSC applicants are evaluated against (e.g.
  Bachelor of Arts: APS 32), alongside a smaller Cambridge/IB/NSSC-to-English
  conversion sub-table for the same qualifications.
- **Page 30** (from an earlier pass over this same document): per-programme
  requirement lines that additionally cite an NBT proficiency band by name
  (e.g. "NBT scores of Upper Intermediate for AL & QL" for Bachelor of
  Business Science / Commerce specialisations) — see section 4.

## 3. Representative pages (first 800 characters)

**Page 16 — Score calculation methodology (the definitive page):**
```
SCORE CALCULATION FOR SELECTED NON-SOUTH GENERAL ELIGIBILITY FOR ADMISSION TO
AFRICAN EXAMINING AUTHORITIES UNDERGRADUATE PROGRAMMES
ADMISSION POINTS TABLE
NSSC Cambridge Cambridge
Points IGCSE IB SL IB HL
HL AS-LEVELS A-LEVELS
 National Senior Certificate (NSC) applicants must, for
10 A 7 admission to higher certificate, diploma or degree programmes
have met the NSC requirements for such endorsement...
9 B 6
8 C 5
...
To calculate your FPS, the APS will be adjusted as described
below in the calculation examples. Two faculties (Health
Sciences and Science) adjust the APS when calculating the FPS.
```
*(table rows abbreviated here — full column set confirmed present: points
10 down to lower values mapped against IGCSE/IB SL/IB HL/AS/A-Level grades;
this is the non-SA conversion table interleaved on the same page as the
NSC-relevant APS/FPS/WPS prose quoted in full in section 4 below.)*

**Page 54 — National Benchmark Tests:**
```
UNDERGRADUATE ADMISSIONS 2027 | 54
HOW TO APPLY
...how to calculate your Admission Point Score (APS), can be found in the
table on page 16.
NATIONAL BENCHMARK TESTS (NBTS)
All applicants are required to write the National Benchmark Tests (NBTs).
The NBT scores are used to complement the Faculty Point Score (FPS) in
making admissions decisions. As the NBT assesses entry-level academic
proficiency, an applicant with a Lower Intermediate or Basic score on the
Academic Literacy (AL) portion of the NBT will...
```

**Page 58 — Admission requirements by qualification:**
```
ADMISSION REQUIREMENTS BY QUALIFICATION
Bachelor of Arts Admission Point Score 32
Bachelor of Social Science Admission Point Score 38
Bachelor of Social Work Admission Point Score 39
...
[Cambridge/IB/NSSC-to-English-requirement conversion sub-table follows,
same qualifications, non-SA pathway]
```

## 4. How admission score is computed for NSC applicants

Sourced verbatim from page 16, the full relevant paragraph:

> "To calculate your FPS, the APS will be adjusted as described below in
> the calculation examples. **Two faculties (Health Sciences and Science)
> adjust the APS when calculating the FPS. For the rest (Commerce,
> Engineering & the Built Environment, Humanities and Law), the APS equals
> the FPS.** In order to calculate the FPS for the Faculty of Science,
> double the scores achieved for Mathematics and Physical Sciences (the
> Science FPS is out of 800)... **When calculating the FPS for the Faculty
> of Health Sciences (a score out of a maximum of 900), add the sum of the
> three NBT scores to the APS.** For South African applicants only, in
> order to calculate the WPS, adjust the FPS by the disadvantage factor
> applicable to you. This is a percentage from 0% to 10%, except for
> applications for admission to the programmes in the Faculty of Health
> Sciences, where the range is from 0% to 20%."

Three-tier model, confirmed directly from this text:

| Tier | What it is | Faculty-dependent? |
|---|---|---|
| **APS** | Base score, sum of NSC subject points (standard model, matches our existing data model) | No — same computation for everyone |
| **FPS** (Faculty Points Score) | APS adjusted per faculty | Yes — see breakdown below |
| **WPS** (Weighted Points Score) | FPS adjusted by a 0-10%/0-20% "disadvantage factor" | SA applicants only; factor is UCT-determined, not a mark the learner supplies |

### FPS breakdown by faculty

- **Commerce, Engineering & the Built Environment, Humanities, Law**:
  FPS = APS exactly. No NBT number involved in the score itself.
- **Science**: FPS = APS with Mathematics and Physical Sciences scores
  doubled (FPS out of 800 instead of the standard maximum). Still purely
  NSC-derived — no NBT number, just a different formula/scale.
- **Health Sciences**: FPS = APS + sum of three NBT scores (FPS out of
  900). **This is the one and only place NBT is a direct numeric input to
  the UCT admission score.**

### The NBT-as-eligibility-gate nuance (Commerce/Business Science)

Separately from the FPS formula, page 30 (from an earlier pass over this
document) shows specific programme listings citing an NBT proficiency
*band* by name rather than a number — e.g. Bachelor of Business Science
and Commerce specialisations requiring "NBT scores of Upper Intermediate
for AL & QL". Read together with page 16's "APS equals the FPS" statement
for Commerce, this reads as a **pass/fail minimum-proficiency threshold**
(a gate, like a minimum subject level) rather than a numeric contribution
to the score — consistent with, not contradicting, page 16. This distinct
from the Health Sciences case and was not exhaustively verified across
every Commerce/Business Science programme page; flagged here as a
secondary, lower-confidence finding rather than folded into the primary
answer below.

Separately, and unconditionally: page 57 states **"All applicants who are
normally resident, or at school, in South Africa must write the NBT"** —
writing the test is mandatory process-wise for essentially every NSC
applicant, independent of whether their faculty's FPS formula uses the
resulting number.

## 5. Direct answer to the central question

**Does UCT require NBT scores as an input to its admission calculation?**

**Yes, but only for the Faculty of Health Sciences.** For that faculty,
FPS = APS + sum of three NBT scores — a required, unavoidable numeric
input with no computation possible without it. For the other four faculty
groupings (Commerce, Engineering & Built Environment, Humanities, Law,
Science), **FPS is computed from APS alone; no NBT number is required to
produce a score**, even though writing the NBT is a separate, near-universal
process requirement, and Commerce/Business Science programmes appear to
gate on an NBT proficiency band as pass/fail rather than a number.

### Bottom line for `/v1/qualify` schema planning

This is a **narrower** problem than "UCT needs NBT scores," and the same
shape recurs at Wits (see `wits.md` — Faculty of Health Sciences' Composite
Index is 40% NBT-weighted): both institutions require NBT scores as a
numeric score input **specifically, and only, for their Faculty of Health
Sciences programmes.** Concretely, this suggests:

- Adding NBT fields to the base `/v1/qualify` request schema is not
  justified by the majority of UCT or Wits programmes — most compute
  cleanly from NSC data alone under the existing model.
  - The WPS "disadvantage factor" is a UCT-internal equity adjustment, not
  a learner-supplied input — it does not require a new schema field, but
  does mean UCT's true final score is not fully computable from NSC marks
  alone even outside Health Sciences; whether/how to represent "WPS may be
  lower than FPS" (e.g. as a caveat rather than a number) is a separate,
  smaller decision than the NBT question.
- This is presented as a decision point, not resolved here: whether to
  (a) add NBT scores as an *optional* schema field scoped only to
  Health-Sciences-faculty programmes at both institutions, (b) exclude
  Health Sciences programmes at both institutions from scoring entirely
  until NBT collection is designed, or (c) some other treatment — is left
  for deliberate decision before extraction begins on either institution's
  Health Sciences faculty.
