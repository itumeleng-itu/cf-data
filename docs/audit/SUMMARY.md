# Audit Summary — coursefind-data × courseFinder

**Read-only audit. Full detail in `01`–`05` in this directory. This file
only summarizes and prioritizes.**

## The question this had to answer: which system is telling learners the truth?

**Neither, uniformly — but every confirmed disagreement in this audit,
without exception, has the API right and the frontend wrong**, and every
one of those errors is a false negative: a learner who genuinely qualifies
being told they don't. No case was found anywhere in this audit of the
frontend wrongly telling someone they qualify when they don't. The two
systems disagree because the frontend's `checkSubjectRequirements` ANDs
every top-level requirement key with no way to express "this key OR that
one" across keys, and several real requirements (language bands, an
unnamed second language) need exactly that — so every encoding mistake
found narrows eligibility, never widens it.

## Every divergence found

| Divergence | Correct side | Learner impact | Severity |
|---|---|---|---|
| Compound unsatisfiable language key (`"english home language or first additional language"`) | API | **67 courses nationally, 47 of Wits' 102 (46%)** — unqualifiable for literally every applicant, any level, any variant | **Critical** |
| Dangling generic `"Additional Language"` key | API | **12 courses** (not just LLB) — unqualifiable for every applicant regardless of their actual second language | **Critical** |
| Dual ANDed HL+FAL keys | API | **106 courses** — unqualifiable for every FAL applicant; also rejects HL applicants below the FAL threshold when bands differ | **Critical** |
| HL-only key, no FAL entry | API | **147 courses** — unqualifiable for every FAL applicant for that language | **Critical** |
| **Union of the four language-encoding bugs above** | API | **320 of 1,668 frontend courses (19.2%) nationally; 71 of UJ's 98 (72%)** | **Critical** |
| Live scoring is one flat formula for all 26 institutions (5 bespoke formulas exist in code, dead, never called) | API (where it has a config at all) | Every Wits/UWC/UFH/MUT/CUT applicant, today — 4-point APS difference on the canonical fixture just for Wits | **Critical, and already live** |
| Flattened conditional APS (Maths-vs-Maths-Lit threshold collapsed to the lower figure) | API | Confirmed on 3+ UJ programmes; systemic pattern, not isolated | High |
| Missing Technical Mathematics alternative on 6 UJ Engineering codes | **Unresolved** — flagged, not adjudicated | 2 of 6 proven as live pass/fail disagreements via adversarial profile | High, but unverified which side is wrong |
| BSc Actuarial Science APS: 40 (API) vs 33 (frontend) | API | One programme, 7-point understatement | Medium (isolated) |
| Math/Maths-Lit mutual exclusion (1 course, Univen) | API (structurally moot — UI also blocks it) | 1 course | Low |
| No `excluded_subjects` at the scoring layer | API | Diffuse, not counted per-record; can inflate a frontend-computed APS | Low–Medium |
| Missing 2 subjects from dropdown (`design`, `hospitality_studies`) | API | 0 live UJ programmes affected today; latent | Low |

**Severity rule applied as instructed:** an unqualifiable-for-everyone bug
outranks a wrong APS number, because the first hides a real opportunity
completely (invisible to the learner — no near-miss, no reason shown, just
absence) while the second is at least visible as *some* result. On that
basis, the four language-encoding bugs and the dead per-institution scoring
are the most serious findings in this audit — not the more dramatic-looking
single 7-point APS error.

## The five things most worth fixing, ordered by learner impact (not effort)

1. **The compound unsatisfiable language key** — 67 courses, concentrated
   catastrophically in Wits (46% of its whole catalogue). Fixing this is
   mechanical (rewrite the key using the `alternatives` structure the
   codebase already uses correctly elsewhere) — SPU's own file proves the
   correct pattern exists 2 records away from a broken one.
2. **The dual ANDed and HL-only key patterns together** — 253 courses, same
   root cause and same mechanical fix as #1.
3. **Wiring the five already-written, currently-dead per-institution
   scoring functions live** (`lib/aps-calculator.ts` passing an actual
   institution id instead of the hardcoded `"default"`) — a one-line-call-
   site fix that changes the *actual live score* every Wits/UWC/UFH/MUT/CUT
   applicant sees today, for institutions that together hold hundreds of
   frontend course records.
4. **The 12 dangling `"Additional Language"` keys** — smaller in count than
   1–3 but each one is a total, invisible block, and the fix (route these
   through something resembling the API's `any_additional_language`, or at
   minimum name a real subject) is well-scoped.
5. **Resolving the Technical Mathematics FEBE question with a working PDF
   reader** — this audit could not settle whether the API or two
   independent extractions plus the frontend are right, and this is the one
   open question that could flip a "confirmed API bug" finding into a
   "confirmed API bug" of the opposite kind. Worth doing before trusting
   the API's Engineering-programme data as a migration source unchanged.

## Wrong in production, right now — flagged separately, since this is what learners use today

- The compound-key, dual-key, and HL-only-key bugs (320 courses) are live
  on the current production site today, independent of anything in
  `coursefind-data` or the in-flight integration.
- The flat "one formula for all 26 institutions" scoring is live today for
  every Wits/UWC/UFH/MUT/CUT applicant.
- The LLB-and-11-siblings dangling-key bug is live today.
- **None of the above are caused by, or fixed by, the integration in
  flight** — they exist in the frontend's local matcher, which the
  integration leaves running unconditionally for extended-curriculum/TVET
  matching (all institutions) and for the main list of every institution
  except UJ (Section 4).

## What the migration would break if shipped as-is

- **A silent main-list coverage regression for 25 institutions**: nothing
  routes their main-list requests back to local matching once the API call
  becomes the only path, so their learners lose the main course list
  entirely (Section 4) — worse than today's known-buggy-but-present list.
- **`QUALIFY_API_URL` has no configured production value anywhere in either
  repo** — deployed as-is, the one institution (UJ) this integration is
  built for would also fail, every time, for every real user, until this is
  set outside of code (Section 4).
- **Near-misses and `requires_additional_assessment` are fetched and
  discarded** — the API's best capability (telling a learner *why* they
  narrowly missed) is wired all the way to the frontend's network layer and
  then thrown away before rendering (Section 3/4).

## What could not be determined, and what's needed

- **Whether UJ's FEBE genuinely accepts Technical Mathematics** for the 6
  affected Engineering programmes — needs a working PDF renderer
  (`pdftoppm`/poppler-utils is not installed in this environment) to read
  `data/downloads/uj_2027.pdf` directly, since the two available text
  extractions and the API's verified data disagree with each other.
- **Whether the other 25 institutions' frontend data is accurate beyond
  the 2 spot-checked (Wits, SPU)** — only those two were checked against
  independent evidence in the time available; the other 23 are unaudited.
- **Whether Wits' or SPU's real admission-scoring formula is what either
  system claims** — both `coursefind-data`'s `custom_points_with_bonus`
  (this session's own earlier work) and the frontend's dead
  `calculateWitsAPS` are unverified against a real worked example; neither
  can currently be called correct.
- **Python-side execution could not be independently re-run** in this
  environment (Application Control policy blocking the venv) — API-side
  numbers in this audit come from a careful line-for-line JS port of the
  read source, cross-checked once against the project's own established
  ground truth (the canonical fixture's APS 41 / 28 qualifying figure), not
  from running `pytest` directly.
