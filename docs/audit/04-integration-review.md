# Section 4 — The Integration In Flight

**Status: read-only audit. Nothing outside `docs/audit/` was changed.**

Reviewed as written, from disk, in `courseFinder`: `lib/subject-slugs.ts`,
`app/api/qualify/route.ts`, `lib/qualify-api.ts`, and their callers
(`hooks/use-course-matcher.ts`, `app/find-course/page.tsx`). None of these
files were modified for this audit — everything below describes the
staged-but-uncommitted state as it exists on disk.

---

## Is the subject-slug mapping exhaustive and correct?

**Yes, exhaustive relative to what the dropdown offers; the dropdown itself
is missing 2 of the API's 46 recognised subjects, and the mapping's own
comment already says so.**

`api/src/app/subjects.py`'s `Subject` enum has 46 members: 22 language
entries (11 languages × HL/FAL) and 24 non-language subjects.
`lib/subject-slugs.ts`'s `SUBJECT_SLUGS` table has 44 entries: all 22
language pairs, correctly matched one-for-one against `LANGUAGE_FAMILIES`
in `subjects.py` (same 11 languages, same slugs — `english_hl`/`english_fal`,
`afrikaans_hl`/`afrikaans_fal`, ... `isindebele_hl`/`isindebele_fal`,
verified by direct comparison), plus 22 of the 24 non-language subjects.

The 2 missing — `design` and `hospitality_studies` — are called out by name
in the file's own comment (`lib/subject-slugs.ts:79-86`): *"The API also
recognises 'design' and 'hospitality_studies' as subject slugs, but
data/subjects.ts's dropdown has no entry for either — a learner can never
select them."* Confirmed by checking `data/subjects.ts` directly: neither
appears in its dropdown categories. The file also has a load-time assertion
(`if (process.env.NODE_ENV !== "production")`, bottom of the file) that
throws if any dropdown value is ever added without a corresponding slug —
so this exhaustiveness is enforced going forward, not just true today.

**Live impact today: zero.** Checked every UJ programme in `programmes.json`
for a requirement naming `design` or `hospitality_studies` — none exist.
This is a real, self-documented gap, but a dormant one; it will only matter
once a programme requiring either subject by name is added to the dataset
(UJ or otherwise).

---

## Does the proxy handle failure sensibly?

`app/api/qualify/route.ts`, reviewed line by line:

| Failure mode | Handling | What the learner sees |
|---|---|---|
| Request body isn't valid JSON | Caught, `400` | `{"error": "Request body must be valid JSON"}` |
| Network failure reaching `QUALIFY_API_URL` | Caught, `502` | `"The course-matching service is unreachable. Please try again shortly."` |
| Upstream returns non-2xx | Passed through with upstream's status | `{"error": "The course-matching service rejected the request.", detail: <upstream body>}` |
| Upstream returns malformed JSON | `.catch(() => null)`, `payload` is `null`, still returns whatever status upstream sent | handled, doesn't crash the route |

This is reasonable, complete failure handling — every path is covered and
none of them throw an unhandled exception. `lib/qualify-api.ts`'s
`fetchQualification()` wraps all of this again client-side into a single
`QualifyApiError`, and `hooks/use-course-matcher.ts` surfaces
`err.message` via a `matchError` state the page renders as a toast. No gap
found here.

## Is there a fallback to the old local matcher on API failure?

**No silent fallback for the main list — confirmed by reading the
`catch` block directly: on failure it sets `matchError`, clears
`qualifyingCourses` to `[]`, and returns the error. This is the correct
design** (the audit brief is right that a silent fallback would be worse
than a visible error, since it would reintroduce every Section 2 bug
invisibly) and it's what's actually implemented.

**But the old local matcher is not merely a fallback that never fires — it
is a second code path that runs unconditionally, every time, for two of
the three result lists.** `hooks/use-course-matcher.ts`'s own comment says
so directly: *"Extended curriculum programs... and TVET colleges:
coursefind-data's dataset does not yet carry an 'extended' flag... and does
not cover TVET colleges at all — both stay locally computed."* Reading the
function: `extendedPrograms` and `recommendedColleges` are built via
`checkSubjectRequirements(subjects, course.subjectRequirements)` against
`getAllUniversityInstances()` and `getAllColleges()` — the exact same local
data and matching logic audited in Section 2, unconditionally, regardless
of whether the API call for the main list succeeded, failed, or was ever
made. **This means every bug found in Sections 1–2 (the HL/FAL encodings,
the flattened conditional APS, the dangling `"Additional Language"` key,
the missing Technical Mathematics alternatives, the dead per-institution
scoring) remains live in production today, for the Extended Curriculum
Programmes and Recommended TVET Colleges sections of the UJ results page,
even after this integration ships.** This is not a fallback in the
resilience sense — it's an intentionally-scoped second feature area the
API doesn't cover yet, but it means "the old matcher" is a misleading
singular: there are two matchers running side by side indefinitely, one
per feature area, not one being retired.

## Does the response shape match, including near-misses and requires_additional_assessment?

**The TypeScript types match the Pydantic models field-for-field** (checked
directly, side by side): `QualifyResponse`, `QualifyProgrammeResult`,
`QualifyUnscoreableResult`, `QualifyFailure` in `lib/qualify-api.ts` mirror
`main.py`'s `QualifyResponse`/`ProgrammeResult`/`UnscoreableProgrammeResult`/
`FailureOut` exactly, key names and types both. The file's own comment
flags the risk correctly: *"there is no shared schema package between the
two repos"* — a future change to one side's shape would only be caught by
this manual mirror going stale, not by a type checker.

**But per Section 3, the shape matching correctly doesn't mean the data is
used.** `hooks/use-course-matcher.ts`'s `toCourseMatch()` reads only
`result.institution/qualification_code/name/faculty/score_required/
duration_years/campus` and `result.score_actual` (for display in
`metRequirements`) — never `failures`. The response's `near_misses` and
`requires_additional_assessment` arrays are fetched over the wire and
never referenced by any variable after `fetchQualification()` returns.
**A learner who narrowly misses a programme today sees nothing about it at
all** — the same behaviour as the pre-integration local matcher, just now
backed by better data the frontend still doesn't surface.

## `QUALIFY_API_URL` — is it configured, and what does it point at?

**Defaults to `http://localhost:8000`, and nothing in either repo currently
configures it to point anywhere else.** `app/api/qualify/route.ts:23`:
`const QUALIFY_API_URL = process.env.QUALIFY_API_URL || "http://localhost:8000"`.
`.env.example` documents the variable as a template
(`QUALIFY_API_URL=http://localhost:8000`, server-only) but courseFinder's
`.gitignore` has a blanket `.env*` rule with no exception, so no actual
`.env.production` or Vercel-dashboard-equivalent value is present in the
repository to check — there is no evidence anywhere in the repo that a
publicly-reachable URL has been set.

**This is an operational gap, not a code gap, but it is the one that
determines whether any of this works for a real user today.** The API
"currently runs only in local k3d," per the audit brief's own framing — if
this integration is deployed to Vercel as-is without also (a) deploying
`coursefind-data`'s API somewhere publicly reachable and (b) setting
`QUALIFY_API_URL` in Vercel's environment configuration to that address,
every request to `/api/qualify` from a real deployed user will attempt to
reach `http://localhost:8000` **from inside Vercel's serverless runtime**,
which has no route to this developer's local k3d cluster, and will fail
every time with the 502 path already reviewed above. The failure mode is
handled gracefully (a clear error, not a crash) — but it means, as staged,
the entire main-university-list feature is non-functional for any user who
isn't running the API locally, until this is addressed outside of code.

## Does the old matcher still exist and is it still reachable?

**Yes, on two axes.** (1) As covered above, it is unconditionally reachable
today for the extended-curriculum and TVET-college result lists, for every
institution including UJ. (2) For every institution other than UJ, it is
still the *only* matcher for the main list too, since `/v1/qualify` has no
data for them — there's no institution filter or fallback logic to route
"ask the API for UJ, ask locally for everyone else"; the current code
simply always calls the API for the main list and lets `institutions` in
the request go unfiltered, meaning the API itself narrows the response to
whatever it has data for (UJ) and the other 25 institutions' main-list
courses **currently do not appear in the main list at all post-integration**
— they were previously shown (via local matching) and now are not, since
nothing routes them back to the local matcher for that specific list. This
is a real, unflagged regression in coverage for 25 institutions' main
course lists, distinct from the (already-covered, intentional) extended/
college paths.

---

## The sequencing question

Switching to the API today serves 1 institution's main list (UJ) instead
of 26 (Section 1: 1.7% of the frontend's total course catalogue). The
trade-offs, not a recommendation:

**Ship as-is (current staged state).** Simplest change, already written
and tested (per the earlier session's own test files). Cost: the 25-
institution main-list regression just described is real and currently
unmitigated — every non-UJ learner loses their main course list entirely,
not just gets an unenhanced one, unless `QUALIFY_API_URL` also happens to
be pointed at a server that has been extended to hold their institution's
data too (which it isn't yet). This regression exists regardless of the
`QUALIFY_API_URL` deployment gap above — it would also occur talking to a
correctly-deployed API that still only has UJ's data.

**Staged path — API for UJ, local matching for the other 25 institutions'
main lists.** Would require: (a) an explicit institution allowlist/denylist
so `useCourseMatcher` calls the API only for institutions it actually
covers and falls back to the *existing* local main-list logic (the one this
integration deleted from `use-course-matcher.ts`, still recoverable from
git history) for everything else, (b) a way to merge two result lists from
two different code paths into one sorted `qualifyingCourses` array without
conflating a `near_misses`-aware API result with a local result that has no
such concept, and (c) accepting that this reintroduces, for 25
institutions, every bug found in Sections 1–2 as a *visible, permanent*
part of the product rather than a temporary gap closed institution-by-
institution. This is more code (a merge/dispatch layer that doesn't exist
today) for a result that is honest about being partially wrong, versus the
current staged state, which is honest about being incomplete but silently
drops coverage rather than degrading it.

Neither option was implemented or recommended by this audit — this section
only establishes what each would cost, per the brief's own framing.
