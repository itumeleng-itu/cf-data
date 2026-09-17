# Section 2 — Semantic Divergence

**Status: read-only audit. Nothing outside `docs/audit/` was changed.**

## Method

Every claim below about frontend *behaviour* (not just data) was checked by
actually executing the real functions — `checkSubjectRequirements`
(`app/find-course/utils.ts`), `languageMatches`/`findMatchingSubject`
(`lib/subject-aliases.ts`), and `calculateAPS` (`lib/aps-calculator.ts`) —
against constructed inputs, via a temporary Jest test file added to
`courseFinder/__tests__/`, run once, and deleted immediately after (the
repo's `git status` was clean of it before and after; it is not part of
this deliverable and was never intended to be). This was necessary because
a prior pass on this exact codebase reportedly produced two contradictory
readings of `lib/subject-aliases.ts` from reasoning about the source rather
than running it — this audit does not repeat that mistake. Where a claim
below says "executed" or "confirmed by running," that means the real
TypeScript function was called and its actual return value is quoted.
Python-side claims (`evaluator.py`, `scoring.py`) are read directly; this
environment's Python venv could not be invoked to execute it (`uv run
pytest` fails with `Application Control policy has blocked this file, os
error 4551` — an environment restriction unrelated to this audit), so a
line-for-line JS port of the exact logic read from `evaluator.py`/`scoring.py`/
`qualify.py`/`subjects.py` was used to compute API-side outputs. This is a
transliteration, not a reimplementation from intent — every branch was
checked against the source it was ported from.

---

## (a) HL vs FAL

**Verdict: the frontend does NOT correctly implement the "HL 5 OR FAL 6"
band. It implements three different, all-broken, encodings, chosen
inconsistently even within a single institution's file.**

`languageMatches()` (`lib/subject-aliases.ts:70-80`) itself is correctly
written — quoted in full:

```ts
export function languageMatches(studentSubject: string, requiredSubject: string): boolean {
    const student = parseLanguageLevel(studentSubject)
    const required = parseLanguageLevel(requiredSubject)
    const studentLang = normalizeSubjectName(student.language)
    const requiredLang = normalizeSubjectName(required.language)

    if (studentLang !== requiredLang) return false
    if (required.level === 'HL') return student.level === 'HL'
    if (required.level === 'FAL') return student.level === 'HL' || student.level === 'FAL'
    if (required.level === 'SAL') return student.level === 'HL' || student.level === 'FAL' || student.level === 'SAL'
    return true
}
```

This correctly encodes "an HL student also satisfies an FAL-or-lower
requirement." The bug is entirely in how `checkSubjectRequirements` is
*called* — `courseRequirements` is a flat `Record<string, RequirementLevel>`
and every key in it is ANDed (`missing.length === 0` gates the whole
result). Three distinct anti-patterns were found in the actual data, all
three confirmed broken by executing the real function:

**Pattern 1 — dual ANDed keys** (e.g. UJ's `B5BFPQ`:
`{"english home language": 5, "english first additional language": 6}`).
Executed against the real `checkSubjectRequirements`:

| Student | Result |
|---|---|
| HL, level 5 (exactly the printed minimum) | **REJECTED** — `missing: ["english first additional language (Level 6)"]` |
| HL, level 6 | Passes |
| FAL, level 6 (exactly the printed minimum) | **REJECTED** — `missing: ["english home language (Level 5)"]` |

An HL student below the FAL number, and *every* FAL student regardless of
level, are wrongly rejected. Where the two thresholds happen to be equal
(e.g. UJ's Engineering programmes, `4`/`4`), the bug narrows to "every FAL
student rejected, HL students fine" — executed and confirmed the same way.

**Pattern 2 — HL-only key, no FAL entry at all** (e.g. UJ's `B2I01Q`:
`{"english home language": 5, "mathematics": 6}`, no FAL key). Any FAL
student is rejected outright — `findStudentSubject` never finds a match for
an HL-required key against an FAL-only transcript, regardless of the
learner's percentage.

**Pattern 3 — compound literal key** (e.g. Wits: `"english home language or
first additional language": 5`). This is the worst of the three. Executed:

```
parseLanguageLevel(compound key) -> {"language":"english or first additional language","level":"HL"}
languageMatches(HL student, compound key) -> false
findMatchingSubject(HL student, compound key) -> undefined
checkSubjectRequirements(HL student, {compound key: 5}) -> meets:false
checkSubjectRequirements(FAL student, {compound key: 5}) -> meets:false
```

The string-stripping regex inside `parseLanguageLevel` only removes the
literal substrings `"home language"` or `"first additional language"` (not
both, and not the word `"or"` between them), so the parsed "language" for
this key becomes the garbage string `"english or first additional
language"`, which never equals any real student's parsed language
(`"english"`). **This key can never be satisfied by any input, for any
learner, at all** — the same failure class as the LLB bug the audit brief
already confirmed, but broader.

**Quantified impact across all 26 institutions** (every `_courses` array
parsed and scanned programmatically):

| Pattern | Courses affected | Worst-hit institutions |
|---|---|---|
| Dual ANDed HL+FAL keys | 106 | UJ (41), Wits, NWU, DUT |
| HL-only key, no FAL entry | 147 | UJ (30), UKZN, Rhodes, DUT |
| Compound unsatisfiable key | 67 | **Wits (47 — 46% of Wits' entire 102-course catalogue)**, UP (13) |
| **Union (any of the three)** | **320 of 1,668 (19.2%)** | UJ: 71/98 (72%), Wits: 59/102 (58%) |

The API's mechanism (`evaluator.py`'s `_evaluate_language_subject`: one
rule per language, `min_level` + optional `min_level_fal`, resolved at
evaluation time against whichever variant the learner's marks actually
contain, with correct "closest branch" near-miss reporting) does not have
this problem. It is a genuinely better design, not just better-populated
data — and, notably, it's a design the frontend's own `alternatives`
structure could express (see (c) below): SPU's own file proves this by
using it correctly on 2 of 3 spot-checked records.

---

## (b) `any_additional_language`

**Verdict: confirmed — the frontend has no equivalent at all, and the
consequence is not limited to LLB.**

The API's `_evaluate_any_additional_language` (`evaluator.py:299-339`)
scans every language family the learner offers, skips whichever one already
satisfied an earlier requirement (`consumed_language`, threaded explicitly
so English can't satisfy both "English" and "a second language"), and
reports the best remaining candidate. There is no corresponding concept
anywhere in `app/find-course/utils.ts`, `lib/subject-aliases.ts`, or
`lib/utils/subject-validator.ts` — grepped for "additional" outside the
HL/FAL parsing and found nothing that means "any other language, unnamed."

Instead, at least one programme's data encodes this need with a literal
dict key `"Additional Language"` — a string with no HL/FAL suffix, so
`parseLanguageLevel` classifies it as `level: 'ANY'`, `language: "additional
language"` — which matches nothing, because no real subject is ever named
"Additional Language" (confirmed: `data/subjects.ts`'s dropdown, grepped in
full, has no such option — a student cannot select it even if they wanted
to). **This affects 12 courses, not 1**, found by searching every
institution's data for this exact dangling key:

`rhodes:ru-bedfp, tut:tut-dip-legal-support, uj:uj-ba-law, uj:uj-bcom-law,
uj:uj-llb, ul:ul-ba-criminology-psychology, ul:ul-ba-cultural-studies,
ul:ul-ba-sociology-anthropology, ul:ul-bpsych, ul:ul-bsw, ump:ump-b-laws,
uwc:uwc-bnurs-nursing`

Every one of these 12 programmes is unqualifiable for every learner today,
on the frontend, regardless of their actual second language — the exact
same severity class as the confirmed LLB bug, at 12x its stated scope.

---

## (c) AND vs OR — the B6CV3Q case

**Verdict: the frontend's type system CAN express this. The specific
record doesn't use it. This is a data bug, not an architectural gap.**

`RequirementLevel = number | { alternatives: RequirementAlternative[] }`
(`lib/types.ts:13`) lets any *one* dict key hold an OR-group, and
`checkSubjectRequirements` ANDs across keys — so "Maths-or-TechMaths AND
PhysSci-or-TechSci" (B6CV3Q's actual shape, per the API) is representable
as two separate keys, each with its own `alternatives`. UJ's own data
proves the encoder knows this pattern: `B6MC2Q`'s frontend record correctly
encodes `"physical sciences": {alternatives: [physical sciences 5,
technical sciences 5]}`.

But `B6CV3Q` itself, and five siblings (`B6EL1Q`, `B6MC2Q`, `B6ES0Q`,
`B6CS0Q`, `B6MS0Q`), all encode `"mathematics": 5` as a **flat** number —
no Technical Mathematics alternative — even though the API's data says all
six accept it. Executed directly against a technical-stream candidate
(Technical Mathematics + Technical Sciences, no pure Maths/Physical
Sciences) for the `B6CV3Q` shape:

```
checkSubjectRequirements(techStudent, {mathematics: 5, physical_sciences: {alternatives:[...tech sciences...]}})
-> {"meets":false,"missing":["mathematics (Level 5)"],"met":["english home language","english first additional language","physical sciences"]}
```

The Physical-Sciences-or-Technical-Sciences alternative correctly passes;
the flat Mathematics key wrongly rejects. **The schema is not the
limitation — the specific data entry is wrong.** (Whether the API is
actually right that Technical Mathematics is accepted here is itself
unresolved — see Section 1's item 5–10; this section is only about whether
the frontend's *structure* could represent it, and the answer is yes.)

---

## (d) Mutual exclusion — Mathematics vs Mathematical Literacy

**Verdict: essentially not a live problem, for two independent reasons —
but the one case that exists is real.**

Searched all 1,668 frontend courses for any record requiring `mathematics`
**and** a Mathematical-Literacy variant as two separate ANDed keys
(exactly the shape that would wrongly reject every Maths Lit candidate,
since no NSC learner offers both). Found exactly **one**: Univen's `BCom
in Tourism Management` (`univen-bcom-tm`). Every other course in the
dataset either uses `alternatives` correctly for this pair, or requires
only one of the two.

This one course is unqualifiable for everyone by construction — and doubly
so, because the frontend's own UI layer (`lib/utils/subject-validator.ts`'s
`CONFLICTING_SUBJECTS` list, which includes `["Mathematics", "Mathematical
Literacy"]`) actively **prevents** a user from ever selecting both subjects
in the picker in the first place. So the one course that needs both is
structurally impossible to satisfy from the UI, not just from the matcher.

The API's data model (`aps_best6_excl_lo`'s config plus the requirement
tree's `any` nodes) has no equivalent hard-coded assumption that Math/
MathLit are mutually exclusive — it just never happens to require both
because no real prospectus does. Both systems arrive at the same practical
outcome here; the frontend does so partly by accident (one bad record) and
partly by a genuinely correct UI guardrail.

---

## (e) "Not accepted" vs absent (`excluded_subjects`)

**Verdict: the frontend has no first-class concept of this, but for
*requirement matching* specifically it rarely matters, because
Mathematics/Maths Lit/Technical Mathematics are kept genuinely distinct
subjects in `data/subject-aliases.ts` (confirmed by reading the file: they
are three separate map entries with no cross-aliasing, with an explicit
comment stating this is deliberate). A requirement naming "mathematics"
already can't be satisfied by a Technical Mathematics transcript entry, so
"absent" and "excluded" collapse to the same outcome for matching.**

There is a real gap, but it's at the **scoring** layer, not the
requirement-matching layer: the frontend's live APS formula
(`calculateAPS(subjects, "default")`, see (g) below) takes the top 6
percentages from *whatever the learner entered*, with no concept of a
per-programme excluded-subjects list. The API's `excluded_subjects`
governs both matching *and* scoring (`main.py`'s `_evaluate_programme`
passes `excluded` into `evaluate()`, and `scoring.py`'s scorers accept an
`exclude_subjects` config key). A learner with a very high Technical
Mathematics mark would have it count toward their frontend-computed APS
even for a programme (like UJ's Faculty of Science ones) whose real rule
excludes it from the score entirely — inflating their apparent APS. This
was not exhaustively checked against all 1,668 courses; it's a mechanism-
level gap, not a per-record count.

Direction of error: **too lenient** at the scoring layer (a disqualifying
subject can still inflate the score), **roughly neutral** at the
requirement-matching layer (the alias separation already does most of the
job `excluded_subjects` would do, for this specific subject family).

---

## (f) Technical Mathematics, both directions

**Verdict: confirmed — same subject, opposite intended treatment in two
faculties, and the frontend only gets one direction right, by omission
rather than by design.**

- **Faculty of Science** (`B2I01Q`, `B2I02Q`, `B2I04Q`, `B2M52Q`): API
  explicitly excludes `technical_mathematics`. Frontend's flat single-value
  Mathematics keys simply never list Technical Mathematics as an
  alternative — so it's correctly rejected, but only because nothing in
  this dataset ever treats "omitted from `alternatives`" as anything other
  than "not accepted."
- **FEBE / CBE** (`B34HRQ`, `B1CISQ` correctly; `B6CV3Q` and 5 siblings
  incorrectly): API says Technical Mathematics **is** an accepted
  alternative. The frontend gets `B34HRQ` and `B1CISQ` right (both
  correctly use `alternatives` including Technical Mathematics) but gets
  the six BEng/BEngTech programmes wrong (flat key, no alternative) — see
  (c).

The frontend's single mechanism — "an alternative is accepted only if it's
explicitly listed" — is structurally sound and happens to be correct by
default for exclusion cases. It fails specifically wherever a programme
needs Technical Mathematics *included* and the data entry didn't add it.
This is not a case of the frontend getting one direction systematically
wrong; it's inconsistent data entry within faculties that otherwise use
the same subject.

---

## (g) Scoring — the biggest single finding in this section

**Verdict: the frontend has bespoke per-institution scoring code for 5
institutions (Wits, UWC, UFH, MUT, CUT) — genuinely more sophisticated than
"one formula for all 26" — and none of it is reachable. Every institution,
UJ included, is scored live by the exact same generic formula.**

`app/find-course/page.tsx:45`:

```ts
const calculatedDefaultAPS = useMemo(() => {
  ...
  return Number(calculateAPSFromLib(libSubjects, "default").aps || 0)
}, [...])
```

`calculateAPS(subjects, universityId)` (`lib/aps-calculator.ts`) branches on
`universityId` — `"wits"` → `calculateWitsAPS`, `"uwc"` → `calculateUWCAPS`,
`"ufh"`/`"mut"`/`"cut"` → their own functions, `"uct"`/`"nmu"` → raw
percentage sum, `"rhodes"`/`"ru"` → sum÷10, `"stellenbosch"`/`"sun"` →
average, default → standard best-6-excluding-LO. **The only call site in
the entire app passes the literal string `"default"`** — confirmed by
grepping every file under `app/`, `hooks/`, and `components/` for
`calculateAPS(` and `calculateApsScore(`; the only match is the one above.
Every branch except `default` is dead code. This was true before this
session's backend-integration changes and remains true after them — the
integration didn't touch this file.

**Concrete impact, using the canonical fixture** (`english_hl 87,
afrikaans_fal 85, mathematics 88, life_orientation 88, geography 92,
life_sciences 87, physical_sciences 73`):

- Live formula (what every UJ, Wits, UWC, ... learner actually sees today):
  **41**.
- Wits' own dead `calculateWitsAPS` on the identical input: best-7-
  including-LO on an 8-point scale, LO halved → 7+7+7+8+7+6 + floor(7/2)=3
  → **45**. A 4-point difference for the exact same learner, for an
  institution whose real formula (per this session's earlier deep-research,
  `docs/scoring/wits.md`) is genuinely NOT the generic best-6 shape.

So the answer to "does the frontend compute one national APS or
per-institution?" is: **the code was written to be per-institution, but the
live product computes exactly one national APS for all 26, silently.**
This is a "wrong in production today" finding, not a migration-planning
one — it doesn't depend on anything from `coursefind-data` shipping.

---

## (h) Subject count

Frontend: hard requirement of **exactly ≥7** subjects before the "Calculate
APS" action is even enabled (`app/find-course/page.tsx:72-73`: `if
(subjects.length < 7) { toast(...'Please add at least 7 subjects.'...) }`).
API: `QualifyRequest.subjects` accepts **6–9** (`main.py:187`,
`Field(min_length=6, max_length=9)`).

A real NSC certificate always has Life Orientation plus at least 6 other
subjects (7 total, by policy) — so the frontend's "≥7" is not wrong about
the real minimum. The API's "6" most plausibly exists to let a caller omit
Life Orientation entirely, since it never affects the standard score and
several scoring strategies exclude it outright — a reasonable convenience,
not a looser correctness bar. **This is a legitimate design difference, not
a clear bug on either side**: a learner who reports exactly 6 subjects
(omitting LO) is blocked with a clear message by the frontend today, and
would be served normally by the API. Neither behaviour produces a wrong
answer; the frontend is simply less permissive about what counts as a
complete submission.
