# The bundle format

A **bundle** is the hand-typed input to this repository: one JSON file per
institution per academic year, holding a flat transcription of that
institution's prospectus admission tables. `scripts/convert_bundle.py`
turns it into the requirement trees the API evaluates.

You write what the table *looks like*. The converter works out what it
*means*.

- **Schema:** `seeds/bundle.schema.json` — point your editor at it and it
  validates while you type.
- **Converter:** `scripts/convert_bundle.py`
- **Output schema:** `seeds/programme.schema.json`

---

## Shape

```json
{
  "institution": {
    "id": "uj",
    "name": "University of Johannesburg",
    "scoring_strategy": "aps_best6_excl_lo",
    "scoring_config": { "excludes_life_orientation": true, "subject_count": 6 }
  },
  "academic_year": 2027,
  "source": {
    "document": "uj/2027/prospectus.pdf",
    "retrieved_at": "2026-06-25"
  },
  "programmes": [ ... ]
}
```

`source.document` is the R2 key returned by `scripts/archive_source.py`,
not a bare filename. It is copied onto every record's `source_doc`, so a
record plus its `source_page` points at a real page of a real archived
document. That is what settles a dispute about a learner's result.

One file per institution-year. Ship several by zipping them together —
`convert_bundle.py` accepts either a `.json` or a `.zip` of them.

---

## A programme record

```json
{
  "qualification_code": "B34CAQ",
  "name": "Bachelor of Accounting",
  "faculty": "College of Business and Economics",
  "qualification_type": "Bachelor Degree (3 years)",
  "duration_years": 3,
  "campus": ["APK"],
  "source_page": 40,
  "confidence": "verified",
  "minimum_aps": { "with_mathematics": 33 },
  "requirements": {
    "english": 4,
    "mathematics": 5,
    "mathematical_literacy": "not_accepted",
    "technical_mathematics": "not_accepted"
  }
}
```

| Field | Notes |
|---|---|
| `qualification_code` | Required. Must be unique within the institution-year. |
| `name` | Required. |
| `duration_years` | **Required, and never guessed from the name.** "BEng" is 4 years, "BEngTech" is 3, and neither says so. Read it off the section heading. |
| `minimum_aps` | Required. A plain integer, or a variants object — see below. |
| `requirements` | Required. One entry per subject column in the source table. |
| `qualification_type` | Optional. The section heading the row sat under. A value starting `Extended` sets `extended: true`. |
| `extended` | Optional. Overrides the value derived from `qualification_type`. |
| `faculty`, `campus`, `source_page`, `career_text`, `selection_notes` | Optional, carried through as-is. |
| `excluded_subjects` | Optional. Exclusions stated in prose *under* the table rather than in a column. Merged with those derived from `not_accepted`. |
| `confidence` | `verified`, `extracted` (default) or `flagged`. |
| `scoring_override` | Optional. Merges over the institution's `scoring_config` for this one programme — see below. |
| `scoring_strategy_override` | Optional. Replaces the institution's `scoring_strategy` outright for this one programme — see below. |
| `scoreable` | Optional, defaults `true`. `false` means no formula produces a trustworthy score for this programme at all — see below. |

---

## Scoring: per-institution, sometimes per-programme

`institution.scoring_strategy` and `scoring_config` pick the algorithm and
its parameters for every programme at that institution by default — see
`api/src/app/scoring.py` for the registered algorithms (`aps_best6_excl_lo`,
`percentage_sum_div_10`, `weighted_levels`) and what each one's config
accepts.

Two escape hatches exist for a programme that genuinely departs from its
own institution's default, because that happens at the FACULTY level, not
just the institution level — UCT's Faculty of Science doubles Mathematics
and Physical Sciences within an otherwise-standard APS; its Commerce
faculty doesn't (`docs/scoring/uct.md`):

- **`scoring_override`** — a config dict merged *over* the institution's
  own `scoring_config` for this one programme. Use this when the
  ALGORITHM is the same but a parameter differs (e.g. a faculty-specific
  `subject_count`).
- **`scoring_strategy_override`** — replaces the institution's
  `scoring_strategy` outright. Use this when the faculty uses a genuinely
  different algorithm, not just different parameters of the same one.

Both are rare. Leave them out unless a specific programme's prospectus
states a different formula than the rest of its institution.

### `scoreable: false` — when no formula applies at all

Some programmes cannot be scored by any formula this dataset implements,
because admission depends on an input `/v1/qualify` deliberately never
collects. The known case: Wits's and UCT's Faculty of Health Sciences
fold National Benchmark Test (NBT) results into a Composite Index /
Weighted Points Score (`docs/scoring/wits.md`, `uct.md`) — most learners
have no NBT results, so the request schema was deliberately never given
an NBT field for the sake of a handful of programmes at two institutions.

Set `"scoreable": false` on such a programme and `/v1/qualify` reports it
in its own `requires_additional_assessment` bucket — carrying only its
name and `selection_notes`, never a score, never in `qualified` or
`near_misses`. Put the human-readable explanation of what else the
learner needs (e.g. "Composite Index includes NBT results — see
wits.ac.za/nbt") in `selection_notes`, since that's the only field this
bucket carries.

`minimum_aps` and `requirements` are still required even when
`scoreable: false` — `/v1/qualify` never evaluates them for such a
programme, but this format doesn't yet have a shape for "admission
depends on something other than an NSC score and subject tree" beyond
"mark it unscoreable and explain in selection_notes." A best-effort
transcription of the printed NSC-side requirements (if any) is fine.

---

## `requirements`: levels, not percentages

Every value is an **NSC achievement level, 1–7**. The prospectus prints
cells like `5 (60%+)`; the number you want is the **5**. Typing `60` is
the single likeliest transcription slip, so the validator rejects any
level outside 1–7 rather than quietly accepting it as a percentage.

Four value forms:

| Value | Meaning |
|---|---|
| `5` | Required at level 5. |
| `"not_accepted"` | **Excluded** — a learner offering this subject is barred. |
| `null`, or the key omitted | Not mentioned. Bars nobody. |
| `{"home_language": 5, "first_additional_language": 6}` | A language required at different levels depending on how it was taken. |

### `"not_accepted"` is the opposite of absent

This is the one distinction the format exists to capture, and the one it
cannot recover if you get it wrong.

```json
"mathematical_literacy": "not_accepted"   // -> excluded_subjects
"physical_science": null                   // -> nothing at all
```

Both render as a dash in the printed table. Both are real:

- **B34CAQ** (Bachelor of Accounting) — Mathematical Literacy is
  *"Not accepted"*. A learner offering it instead of Mathematics is
  rejected. This must become an `excluded_subjects` entry.
- **B2I02Q** — Physical Science is *"Not applicable"*. The programme
  simply doesn't ask for it. This must produce **nothing**.

The retired PDF extractor could not tell these apart from the page and had
to restore the distinction from a hand-maintained correction table. You
can tell them apart, by reading the sentence under the table. Say which,
and the converter will trust you literally.

### Subject keys

Use the canonical subject name (`mathematics`, `physical_sciences`,
`life_sciences`, `accounting`, …). Common prospectus spellings are
accepted too — `physical_science`, `technical_science`, `life_science`,
`maths`, `technical_maths`, `maths_literacy`.

Languages are written as the **family** — `english`, `afrikaans`,
`isizulu` — never as `english_hl` / `english_fal`. The band object above
is how you express the HL/FAL split. `additional_language` means "any
recognised additional language", and the converter always places it last
in the tree so a named language rule is consumed first.

The vocabulary is **closed**: an unrecognised key is an error, never
silently dropped, because a dropped column is a lost requirement.

### `"<a>_or_<b>"`: one printed level, either subject

When the table prints one level satisfied by either of two subjects:

```json
"mathematics_or_technical_mathematics": 5
"physical_sciences_or_technical_sciences": 5
```

Both become an `any` node.

### What you do *not* have to write

Mathematics / Mathematical Literacy / Technical Mathematics is a national
NSC subject-choice group — a learner picks between them in matric and can
never hold two. So whenever **two or more of them carry a level in the
same record**, the converter merges them into one `any` node on its own,
whether or not the table prints an "OR":

```json
"mathematics": 3, "mathematical_literacy": 4
```
→ `any(mathematics 3, mathematical_literacy 4)`  *(this is B8CD2Q)*

Three of them merge into one flat three-way `any`, not nested pairs:

```json
"mathematics_or_technical_mathematics": 4, "mathematical_literacy": 5
```
→ `any(mathematics 4, technical_mathematics 4, mathematical_literacy 5)`
*(this is B34HRQ)*

An **excluded** group member is never merged, because it never becomes a
node at all — which is exactly why B34CAQ above stays a plain `all` with
Mathematics required, rather than becoming "Mathematics OR Mathematical
Literacy" and admitting learners UJ rejects.

Physical Sciences / Technical Sciences is deliberately **not** such a
group: a learner can hold both. If a programme accepts either, say so
with the compound key.

---

## `minimum_aps`

A plain integer:

```json
"minimum_aps": 26
```

Or, when the published APS depends on which maths subject the learner
offers:

```json
"minimum_aps": {
  "with_mathematics": 31,
  "with_mathematical_literacy": 32
}
```

Valid variant keys are `with_mathematics`, `with_technical_mathematics`
and `with_mathematical_literacy`. Each becomes its own threshold, and the
API picks the one matching the learner's actual subjects.

There is one further shape, for programmes keying the APS off the
**English rating** rather than a subject — the schema has no equivalent,
so the converter encodes the strictest printed value and records the
original in `selection_notes`:

```json
"minimum_aps": {
  "with_english_rating_5": 24,
  "with_english_rating_5_upper": 26,
  "with_english_rating_4": 27
}
```
→ `min_score: 27`, plus a note. Under-qualifying a few learners is safer
than over-promising.

---

## Worked example

Two records from UJ 2027, chosen because they are the pair that makes the
`not_accepted`/absent distinction concrete.

```json
{
  "institution": {
    "id": "uj",
    "name": "University of Johannesburg",
    "scoring_strategy": "aps_best6_excl_lo",
    "scoring_config": { "excludes_life_orientation": true, "subject_count": 6 }
  },
  "academic_year": 2027,
  "source": {
    "document": "uj/2027/prospectus.pdf",
    "retrieved_at": "2026-06-25"
  },
  "programmes": [
    {
      "qualification_code": "B34CAQ",
      "name": "Bachelor of Accounting",
      "faculty": "College of Business and Economics",
      "campus": ["APK"],
      "duration_years": 3,
      "source_page": 40,
      "confidence": "verified",
      "minimum_aps": { "with_mathematics": 33 },
      "requirements": {
        "english": 4,
        "mathematics": 5,
        "mathematical_literacy": "not_accepted",
        "technical_mathematics": "not_accepted"
      }
    },
    {
      "qualification_code": "B2I02Q",
      "name": "BSc Information Technology",
      "faculty": "Science",
      "campus": ["APK"],
      "duration_years": 3,
      "source_page": 30,
      "confidence": "verified",
      "minimum_aps": 30,
      "requirements": {
        "english": 5,
        "mathematics": 6,
        "technical_mathematics": "not_accepted",
        "technical_science": "not_accepted",
        "physical_science": null
      }
    }
  ]
}
```

B34CAQ converts to:

```json
{
  "score": [{ "min_score": 33, "requires_subject": "mathematics" }],
  "subjects": {
    "kind": "all",
    "rules": [
      { "kind": "subject", "language": "english", "min_level": 4 },
      { "kind": "subject", "subject": "mathematics", "min_level": 5 }
    ]
  },
  "excluded_subjects": ["mathematical_literacy", "technical_mathematics"]
}
```

Note what did **not** happen: Mathematics and Mathematical Literacy are in
the same exclusive group and both appear in the record, yet the result is
a plain `all` with Mathematics required — because Mathematical Literacy
was excluded, not levelled. B2I02Q likewise excludes Technical
Mathematics and Technical Sciences, while its `null` Physical Science
produces nothing at all.

---

## Working on a bundle

```bash
# 1. Archive the source PDF; keep the key it prints.
uv run python scripts/archive_source.py --institution uj --year 2027 \
    --pdf data/downloads/uj_2027.pdf

# 2. Type the bundle, with seeds/bundle.schema.json wired into your editor.

# 3. Convert and validate, writing nothing.
uv run python scripts/convert_bundle.py bundles/uj_2027.json --dry-run

# 4. Write the seed files.
uv run python scripts/convert_bundle.py bundles/uj_2027.json
```

Step 3 runs the full validator, including the semantic checks — swapped
Mathematics/Maths-Literacy columns, implausible APS, missing English,
missing duration. Those fire on records that are structurally perfect and
still wrong, which is the failure mode hand-typed data actually has. They
**report**; they never repair.

For UJ specifically there is a second opinion available: `tools/uj_extract.py`
reads the 2027 prospectus directly and prints its own numbers. It is
UJ-only and its output is not a bundle, but it is a free cross-check on a
page you have just typed.
