# Wits 2027 — NSC scoring investigation

Read-only investigation. No scoring function written, `api/src/app/scoring.py`
not touched, `institutions` table not touched. Source: `data/downloads/wits_2027.pdf`
(144 pages), fetched 2026-08-08.

## 1. Vocabulary search (every page)

Searched every page for: `national senior certificate`, `nsc`, `achievement level`,
`aps`, `admission point score`, `composite`, and the percentage-band shape `(NN-NN%)`.

- `national senior certificate` / `nsc`: present on ~90 of 144 pages — dominant
  vocabulary throughout the per-programme requirement section (pages ~45-130).
- `aps`: co-occurs with `nsc` on nearly every one of those same pages.
- `composite`: present on pages 14, 20, 60, 76-86, 142 — the Composite Index
  methodology explanation plus every Faculty of Health Sciences programme page.
- `achievement level`: only page 104 — Wits' per-programme pages say `Level N`,
  not the phrase "achievement level".
- **The `(NN-NN%)` percentage-band shape (UFH/UJ's convention) appears on
  ZERO pages.** Wits does not express NSC subject requirements as percentage
  ranges at all.

## 2. NSC requirement pages vs international-conversion pages

Two genuinely distinct sections, easy to conflate if only skimmed:

- **International Qualifications conversion table** (page 19, referenced again
  from many per-programme pages as "International Qualifications: Page 17" or
  similar): Cambridge/IB grade bands (`HL 4-7`, `A-C`, `A-D`), partially rotated
  (15-33% non-upright characters on some of these pages, confirmed via
  `char["upright"]`). **This is the section that produced last session's "Wits
  uses Cambridge/IB grade bands" finding — that finding described this
  conversion table specifically, not the primary NSC requirement format.**
- **Per-programme NSC requirement blocks** (pages ~45-130, one or two
  programmes per page, each headed `NSC REQUIREMENTS`): plain NSC achievement
  **levels** (1-7) per subject plus a numeric **APS** threshold. This is the
  section a South African NSC applicant actually reads, and it matches our
  existing `Subject.min_level` + `min_score` model directly.

## 3. Representative NSC requirement pages (first 800 characters)

**Page 45 — Bachelor of Commerce (General), code CBA00:**
```
CAREERS
Bachelor of Commerce
 Chartered Certified Accountant
(General)  Chartered Financial Analyst
 Internal Auditor
 Management Accountant
Bachelor of Commerce (General)
 Management Consultant
CBA00  Professional Accountant
DURATION: 3 YEARS
PROGRAMME OUTLINE
NSC REQUIREMENTS
APS 38 +
English Home Language or First Additional Language FIRST YEAR
Level 5
 Business Accounting I
Mathematics Level 5  Computational Mathematics I
Waitlisting  Business Statistics I
Applicants with an APS of 35-37, as well as English Level 5  Commercial Law I
and Mathematics Level 5, may be wait-listed subject to place  Economics IA (Microeconomics)
availability.
```

**Page 60 — Bachelor of Science in Engineering, Metallurgy and Materials Engineering, code EFA08:**
```
PROGRAMME OUTLINE
Metallurgy and
FIRST YEAR
Materials Engineering
 Engineering Chemistry
Bachelor of Science in Engineering in  Introduction to the Engineering Profession
 Engineering Analysis and Design IA AND IB
Metallurgy and Materials Engineering
 Engineering Mathematics IA AND IB
EFA08  Engineering Physics IA AND IB
DURATION: 4 YEARS  Applied Physics I
NSC REQUIREMENTS
AND, one of the following courses:
APS 42 +
 Elementary IsiZulu Language and Culture IA
English Home Language or First Additional Language
Level 5  Elementary Sesotho Language and Culture IA
Mathematics Level 5  The International Relations of South Africa and Africa
Physical Sciences Level 5  Introduction to Political Studies
Waitlisting
```

**Page 89 — Bachelor of Arts (General), code ABA00:**
```
Bachelor of Arts (General)
ABA00
DURATION: 3 YEARS
NSC REQUIREMENTS Compulsory Requirement
APS 36 +
Across all BA Programmes
English Home Language or First Additional Language
Level 5
A student of the Bachelor of Arts is required to
Waitlisting
complete two semester courses in one of the
Applicants with entry requirements of at least 30-35 APS
following languages: isiZulu or Sesotho or South
points are wait-listed, subject to place availability.
African Sign Language (SASL). If a student is
```

All three follow the identical shape: programme name, code, duration, a
`NSC REQUIREMENTS` heading, an `APS N +` threshold, then one subject-per-line
with a bare `Level N` (1-7) — no percentages, no international grades, no NBT
mention. This shape held consistently across every non-Health-Sciences page
sampled (Commerce, Engineering, Arts; also spot-checked Science, Law pages,
same shape).

## 4. How admission score is computed for NSC applicants

**Two distinct models coexist in this document, split cleanly by faculty:**

### Standard model (every faculty except Health Sciences)

A plain **APS threshold** (sum of NSC achievement levels, e.g. "APS 38+")
plus per-subject **minimum achievement levels** (e.g. "Mathematics Level 5").
This is exactly `evaluate()`'s subject-tree model plus a single `min_score`
conditional entry — no new scoring function or schema field needed for these
programmes. Some programmes additionally publish a **waitlist band**
(e.g. "APS of 35-37... may be wait-listed") — a second, lower conditional
threshold, also already representable via `qualify.py`'s existing
multi-entry `score_entries` design (would just resolve to a different
`kind`/note, not a new mechanism).

### Composite Index model (Faculty of Health Sciences only)

Confirmed via direct text, not inferred: the phrase **"The Faculty of Health
Sciences uses a Composite Index (CI) score to guide applicant selection"**
appears verbatim on every Health Sciences programme page checked (Bachelor of
Health Sciences in Health Systems Sciences, page 78; Bachelor of Dental
Science, page 80; Bachelor of Nursing, page 83). The formula, from page 20:

> "A Composite Index (CI) is calculated, taking into consideration a 60%
> weighting for, (i) your academic results for five subjects and a 40%
> weighting for (ii) your National Benchmark Test scores. Only five subjects
> are used to derive an academic score, which is calculated according to
> **the percentages obtained, NOT symbols**."

This is a fundamentally different input shape than the standard model:

- Uses raw **percentages** (not achievement levels) for exactly five subjects
  (English, Mathematics, best of Physical Sciences/Life Sciences, best two
  others) — our current API request schema already accepts NSC percentages,
  so the percentage side is representable.
- Requires **National Benchmark Test (NBT) scores** as a direct numeric
  input to the weighted formula (40% of the total) — **not currently
  collected by `/v1/qualify`'s request schema.**
- The Graduate Entry Medical Programme (GEMP) and Graduate Entry
  Physiotherapy Programme (GEPP) are explicitly *excluded* from the standard
  NBT requirement (page 14) — these are graduate-entry programmes (prior
  degree required) and likely use an entirely separate, non-NSC evaluation
  path not covered by this investigation.

### Bottom line for 8.4/schema planning

- Every non-Health-Sciences Wits programme (the large majority) fits the
  existing data model and schema with zero changes.
- Wits' Faculty of Health Sciences requires the **same category of new
  input as UCT's Health Sciences FPS** (see `uct.md`): NBT scores as a
  direct, weighted numeric input to the score, not just a subject
  requirement. This strengthens the case for treating "NBT scores" as a
  deliberate, cross-institution schema decision rather than a one-off for
  UCT.
