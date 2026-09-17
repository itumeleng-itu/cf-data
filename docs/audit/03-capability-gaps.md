# Section 3 — What Each System Has That the Other Lacks

**Status: read-only audit. Nothing outside `docs/audit/` was changed.**

This is not a scoring exercise — both sides have real things worth keeping.
For each item: what it is, and (per the audit's request) whether the
in-flight integration (`lib/subject-slugs.ts`, `app/api/qualify/route.ts`,
`lib/qualify-api.ts`, and the changes to `hooks/use-course-matcher.ts` /
`app/find-course/page.tsx`) preserves it, discards it, or hasn't addressed
it yet. See Section 4 for the integration code itself.

---

## In the frontend, not the API

**26 institutions of programme data vs the API's 1.** Quantified in
Section 1: 1,570 of 1,668 frontend courses have no API equivalent.
*Integration status: preserved — the integration is additive. It only
replaces the main university-list matching for institutions the API
covers (currently only UJ, gated by which `institution_id`s appear in
`programmes.json`); local data for the other 25 is untouched and still
renders. See Section 4 for the more important nuance: local matching is
also still live for UJ's own extended-curriculum and TVET-college paths.*

**UI-layer subject-selection guardrails.** `lib/utils/subject-validator.ts`'s
`SubjectValidator` prevents a learner from selecting two conflicting
subjects at once — two home languages, two first-additional languages, or
both Mathematics and Mathematical Literacy (`CONFLICTING_SUBJECTS`,
`isSubjectDisabled`/`getDisabledReason`). This has real admission meaning
(it enforces "you only ever have one of X" at the point of data entry,
which the API's request schema doesn't need to since it just receives a
marks dict) and is orthogonal to the matching engine — a UI built directly
against the API would still want this. *Integration status: not addressed
— this lives entirely in the subject-picker UI, which the integration
didn't touch. Not at risk, not yet leveraged for anything new either.*

**The five bespoke (but dead) per-institution scoring functions**
(`lib/aps/methods.ts`: Wits, UWC, UFH, MUT, CUT — see Section 2g). These
represent real prior effort at exactly the problem `coursefind-data`'s
`scoring.py` solves, and partially agree with this session's own
independent research on Wits' formula shape (best-7-including-LO, 0–8
scale). *Integration status: not addressed — dead code before, dead code
after. Worth a decision either way (port the useful parts' domain
knowledge into `coursefind-data`'s own verification work, or delete as
unreachable code) rather than leaving it silently unreferenced.*

**The AI-assisted chat feature** (`app/api/chat/route.ts`, 293 lines).
Imports `SYSTEM_PROMPT`, a local fallback responder, study-tips data,
calendar events, and `universities` from `data/universities`. That last
import already resolves to an empty placeholder array today
(`base-university.ts`: `export const universities: University[] = [] //
Placeholder export to preserve existing imports (not used by class-based
files)`) — so the chat feature's dependency on "local university data" is
already effectively nil, independent of any migration. This is a
pre-existing fact, not something either the audit or the integration
changed. *Integration status: n/a — nothing to preserve or discard here.*

**Bursary / report-generation features.** Searched for `bursary`/
`bursaries` under `app/` — no route or component found. Not present in
this codebase today (contrary to what the audit brief anticipated
checking); nothing to report.

---

## In the API, not the frontend

**`any_additional_language` and consumed-language threading.** No
equivalent anywhere in the frontend (Section 2b). *Integration status:
preserved and now live — this is exactly the mechanism the new
`lib/qualify-api.ts` routes UJ's main-list matching through. Its own
docstring says so explicitly: "This REPLACES the local matching that used
to live in app/find-course/utils.ts's checkSubjectRequirements... [which]
could not correctly express... 'a second, unspecified language' (LLB's
'Additional Language' requirement matched no real subject at all)." This
is the one item on this list the integration was specifically built to
fix, and — for UJ's main list only — it does.*

**Per-institution scoring strategies with worked-example verification**
(`scoring.py`'s `SCORERS` registry, gated by `tests/test_scoring_worked_examples.py`
requiring either a real worked example or an explicit `UNVERIFIED` doc
before a strategy is trusted). *Integration status: preserved for UJ (the
only institution currently registered with a real, tested config);
irrelevant for the other 25 until they're onboarded — there's nothing yet
for the integration to preserve or discard there.*

**Near-miss output with structured per-field failure reasons.** Confirmed
by reading `main.py`'s response models: `QualifyResponse.near_misses` is a
full `list[ProgrammeResult]`, each with `failures: list[FailureOut]`
carrying `kind`/`message`/`required_level`/`actual_level` — e.g. "Requires
Mathematics level 5; you have level 4." The frontend's old local matcher
returns match/no-match only (`checkSubjectRequirements` returns `missing`
strings, but nothing upstream of it ever showed a learner *why* they
narrowly missed something — `use-course-matcher.ts`'s old main-list loop
just skipped non-matches silently). **Confirmed discarded by the current
integration**, not just "not yet used": `lib/qualify-api.ts`'s
`QualifyResponse` type correctly mirrors `near_misses` and
`requires_additional_assessment` field-for-field, but
`hooks/use-course-matcher.ts`'s `toCourseMatch()` only ever reads
`response.qualified` — `near_misses` and `requires_additional_assessment`
are fetched over the wire on every request and then never referenced
again. The API can tell a learner why they missed; as wired today, the
frontend throws that answer away.

**`excluded_subjects` as a first-class concept.** Section 2e: partially
redundant with the frontend's own subject-alias separation for matching,
but a real gap for scoring. *Integration status: preserved for UJ's main
list (the API's own scorer honours it internally); not addressed for the
extended-curriculum/TVET paths, which still use the frontend's
excluded-subjects-free local scoring.*

**Conditional score thresholds (`requires_subject`).** Confirmed in
Section 1 (`B8CD2Q`, `B9S15Q`, `B4L03Q` all have a real Maths-vs-Maths-Lit
conditional APS the frontend flattens to the lower figure).
*Integration status: preserved for UJ's main list (this is exactly
`qualify.py`'s `select_score_threshold`, unchanged, still doing this
correctly server-side); the frontend's own flattened figures remain live
wherever local matching still runs (extended/TVET, and every non-UJ
institution).*

**`scoreable: false` / `requires_additional_assessment`.** Confirmed via
`main.py`: programmes needing an assessment the API can't compute (e.g. a
Composite Index needing NBT scores — see `docs/scoring/wits.md`'s
description of Wits' Health Sciences faculty) are carried in their own
response bucket, never silently scored as a pass or fail. No frontend
equivalent found — the frontend's model has no "can't be scored" state at
all; every course is either shown or not. **Currently 0 UJ programmes in
this dataset are actually `scoreable: false`**, so there's no live
discrepancy yet, but the frontend has no mechanism ready for when one is
added. *Integration status: not addressed — the type exists in
`lib/qualify-api.ts` but, like `near_misses`, is fetched and never
rendered.*

**Structural + semantic validation** (`scripts/validate_data.py`, read
directly): duplicate qualification codes per year, `mathematical_literacy`
level below `mathematics` level for the same programme (a physically
impossible NSC combination if both were mechanically generated), and
implausible APS values outside a configured min/max range. No equivalent
validation pass exists anywhere in the frontend's data pipeline — the 26
`data/universities/*.ts` files are hand-authored TypeScript with no
schema or consistency check run against them at all (confirmed: no
validation script references `data/universities` anywhere in the
repository). *Integration status: n/a — this is a data-authoring-time
tool, not a runtime one; nothing for the integration to preserve or
discard.*

**Provenance** (`source_doc`, `source_page`, `confidence: extracted|verified`
on every programme record). No equivalent field exists anywhere in the
frontend's `Course` type (`lib/types.ts`, read in full — no `source`,
`page`, or `confidence`-shaped field). Every one of the 1,668 frontend
course records is, structurally, un-attributable to any specific
prospectus page or confidence level. *Integration status: n/a for the same
reason as validation — this is authoring-time metadata the API has and the
frontend's data model has no field for, migration or not.*
