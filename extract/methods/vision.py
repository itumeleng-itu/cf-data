"""Method C: renders a page at 200dpi and sends the image PLUS Method A's
text dump (extract/text_repair.py's normalise_page_text -- read-only
context for the model, never used here to derive structure the way
Method A does) to a vision model via OpenRouter, requesting strict JSON
matching the Programme candidate shape Methods A/B already produce.

Model: Claude, via OpenRouter (anthropic/claude-sonnet-4.5 by default) --
a deliberate choice for independence from whatever model a later
verification step uses. If a separate verification pass is added, it
MUST be a different model family (GPT or Gemini) -- otherwise Method C
and verification could share correlated blind spots, and the ensemble's
independence assumption (three genuinely different ways of being wrong)
stops holding.

Scoped deliberately: this module extracts whatever pages it's given, no
more, no less -- which pages to run it on (ideally: only pages where
Methods A and B already disagree, not the whole document) is the
caller's decision, made in extract/selftest.py or an orchestration
script, not here. This keeps vision.py a plain, reusable extraction
primitive rather than something that has to know about reconciliation.
"""

import base64
import io
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

import pdfplumber
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from text_repair import normalise_page_text  # noqa: E402

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
_RENDER_DPI = 200
_REQUEST_TIMEOUT = 180.0

# Real, hand-verified UJ 2027 records (seeds/uj/*.json), each chosen to
# demonstrate one or more of the structures the extraction prompt must
# get right. Never invented -- every value here is copied from a
# confidence="verified" seed record or, for B9ENV1, from direct PDF
# verification (not in seeds, see tests/test_methods_textlayer.py).
_FEW_SHOT_EXAMPLES = """
Example 1 -- conditional APS thresholds AND language HL/FAL scope AND an
implicit Mathematics/Mathematical-Literacy alternative AND a non-subject
selection gate (real record, B4L03Q, LLB, page 82):
{
  "qualification_code": "B4L03Q", "name": "LLB", "faculty": "Law",
  "campus": ["APK"], "duration_years": 4, "extended": false,
  "requirements": {"nsc": {
    "score": [
      {"min_score": 31, "requires_subject": "mathematics"},
      {"min_score": 32, "requires_subject": "mathematical_literacy"}
    ],
    "subjects": {"kind": "all", "rules": [
      {"kind": "subject", "language": "english", "min_level": 5},
      {"kind": "any_additional_language", "min_level": 4},
      {"kind": "any", "rules": [
        {"kind": "subject", "subject": "mathematics", "min_level": 3},
        {"kind": "subject", "subject": "mathematical_literacy", "min_level": 4}
      ]}
    ]},
    "excluded_subjects": []
  }},
  "selection_notes": ["NCV, NASCA and SC(a) not accepted"],
  "career_text": null
}
Note: "NCV, NASCA and SC(a) not accepted" is an ADMISSION-PROCESS gate
(which qualification TYPE is accepted at all), not a subject requirement
-- it goes in selection_notes, never into the subjects rule tree.

Example 2 -- excluded_subjects from a "Not accepted" cell, no `any` even
though the excluded subject is in the same national mutual-exclusion
group as the required one (real record, B34CAQ, Bachelor of Accounting):
{
  "qualification_code": "B34CAQ", "name": "Bachelor of Accounting",
  "faculty": "College of Business and Economics", "campus": ["APK"],
  "duration_years": 3, "extended": false,
  "requirements": {"nsc": {
    "score": [{"min_score": 33, "requires_subject": "mathematics"}],
    "subjects": {"kind": "all", "rules": [
      {"kind": "subject", "language": "english", "min_level": 4},
      {"kind": "subject", "subject": "mathematics", "min_level": 5}
    ]},
    "excluded_subjects": ["mathematical_literacy", "technical_mathematics"]
  }},
  "selection_notes": [], "career_text": null
}
Note: Mathematics is REQUIRED and Mathematical Literacy is EXPLICITLY
EXCLUDED for this specific programme -- do not turn this into an `any`
just because Mathematics/Mathematical Literacy/Technical Mathematics are
alternative NSC subject choices in general. Only wrap them in `any` when
the table shows two or more of that group as REQUIRED alternatives for
THIS row.

Example 3 -- the SAME subject as an accepted alternative (opposite
encoding from Example 2's exclusion), with TWO SIBLING `any` nodes in one
`all` (real record, B6CV3Q, BEngTech Civil Engineering):
{
  "qualification_code": "B6CV3Q",
  "name": "Bachelor of Engineering Technology in Civil Engineering",
  "faculty": "Engineering and the Built Environment", "campus": ["DFC"],
  "duration_years": 3, "extended": false,
  "requirements": {"nsc": {
    "score": [
      {"min_score": 28, "requires_subject": "mathematics"},
      {"min_score": 28, "requires_subject": "technical_mathematics"}
    ],
    "subjects": {"kind": "all", "rules": [
      {"kind": "subject", "language": "english", "min_level": 4},
      {"kind": "any", "rules": [
        {"kind": "subject", "subject": "mathematics", "min_level": 5},
        {"kind": "subject", "subject": "technical_mathematics", "min_level": 5}
      ]},
      {"kind": "any", "rules": [
        {"kind": "subject", "subject": "physical_sciences", "min_level": 5},
        {"kind": "subject", "subject": "technical_sciences", "min_level": 5}
      ]}
    ]},
    "excluded_subjects": []
  }},
  "selection_notes": [], "career_text": null
}
Note: Technical Mathematics/Technical Science are EXCLUDED for other
Engineering programmes on the same page (Bachelor of Engineering, not
Technology) and ACCEPTED here -- same subject, opposite encoding, driven
only by what the table actually shows for THIS row, never a fixed rule
about the subject itself.

Example 4 -- language HL/FAL scope, distinct thresholds for each (real
record, B5BFPQ, BEd Foundation Phase Teaching):
  {"kind": "subject", "language": "english", "min_level": 5, "min_level_fal": 6}
Note: min_level applies if the applicant took English as a Home Language;
min_level_fal applies if they took it as a First Additional Language.
Only include min_level_fal when the table publishes a DIFFERENT
threshold for FAL -- omit it entirely if HL and FAL share one threshold.

Example 5 -- four simultaneous subject requirements, no alternatives (real
record, B9O02Q, Bachelor of Optometry):
{"kind": "all", "rules": [
  {"kind": "subject", "language": "english", "min_level": 5},
  {"kind": "subject", "subject": "mathematics", "min_level": 5},
  {"kind": "subject", "subject": "physical_sciences", "min_level": 5},
  {"kind": "subject", "subject": "life_sciences", "min_level": 5}
]}
Note: all four are independently required (kind: "all"), not
alternatives to each other.
"""

_SYSTEM_PROMPT = f"""You are extracting South African university admission
requirements from ONE PAGE of a UJ prospectus. You are given the page as
an image AND a text dump of the page (text_repair.py's
normalise_page_text -- may contain some duplicated or reordered rotated
text; the IMAGE is authoritative when the two disagree).

Output STRICT JSON: a single object {{"programmes": [...]}} where each
element matches this shape exactly:
{{
  "qualification_code": string,
  "name": string,
  "faculty": string | null,
  "campus": [string, ...],
  "duration_years": number | null,
  "extended": boolean | null,
  "requirements": {{"nsc": {{
    "score": [{{"min_score": integer, "requires_subject": string (optional)}}, ...] | null,
    "subjects": {{"kind": "all"|"any", "rules": [ruleNode, ...]}},
    "excluded_subjects": [string, ...]
  }}}},
  "selection_notes": [string, ...],
  "career_text": null
}}
A ruleNode is one of:
  {{"kind": "subject", "subject": SLUG, "min_level": 1-7}}
  {{"kind": "subject", "language": FAMILY, "min_level": 1-7, "min_level_fal": 1-7 (optional)}}
  {{"kind": "any_additional_language", "min_level": 1-7}}
  {{"kind": "all"|"any", "rules": [ruleNode, ...]}}
SLUG values: mathematics, mathematical_literacy, technical_mathematics,
physical_sciences, technical_sciences, life_sciences, life_orientation,
accounting, business_studies, economics, geography, history, tourism,
consumer_studies, visual_arts, dramatic_arts, music, design,
information_technology, computer_applications_technology,
engineering_graphics_and_design, agricultural_sciences,
hospitality_studies, religion_studies.
FAMILY values: english, afrikaans, isizulu, isixhosa, sepedi, sesotho,
setswana, xitsonga, siswati, tshivenda, isindebele.

Rules:
- career_text is ALWAYS null. Never populate it, never paraphrase or
  summarise the prospectus's marketing/career-description prose -- that
  text must never be reproduced, in any form, in this output.
- A non-subject admission gate (which qualification type is accepted,
  waitlisting, application-process notes) goes in selection_notes as
  plain text, NEVER encoded into the subjects rule tree.
- A subject marked "Not accepted" for this specific row becomes an entry
  in excluded_subjects, never a node in the rule tree.
- Two or more subjects from the SAME row that the table shows as
  alternatives (a "/" merged header, an explicit "OR", or -- for
  Mathematics/Mathematical Literacy/Technical Mathematics specifically,
  which are alternative NSC subject choices by national convention, not
  a UJ-specific table feature -- two of them both carrying a level for
  this row with no marker at all) become an `any` node. A subject
  EXCLUDED for this row is never wrapped in an `any` just because it
  belongs to the same group as a required subject (see Example 2).
- Extract every programme row visible on the page. If a value genuinely
  is not visible/determinable for a field, use null (or [] for list
  fields) rather than guessing.

{_FEW_SHOT_EXAMPLES}
"""


def _render_page_png_base64(page: Any) -> str:
    image = page.to_image(resolution=_RENDER_DPI)
    buf = io.BytesIO()
    image.original.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _build_messages(image_b64: str, page_text: str, page_num: int) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Page {page_num}. Text dump:\n{page_text}"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ],
        },
    ]


def _call_openrouter(messages: list[dict], api_key: str, model: str, http_post: Callable) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = http_post(_OPENROUTER_URL, headers=headers, json=payload, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


_CODE_LIKE = re.compile(r"^[A-Za-z0-9]{4,8}$")


def _normalise_record(raw: dict, page_num: int) -> dict | None:
    code = raw.get("qualification_code")
    if not isinstance(code, str) or not _CODE_LIKE.match(code.strip()):
        return None
    record = dict(raw)
    record["qualification_code"] = code.strip()
    record["career_text"] = None  # enforced here too, never trust the model alone
    record["source_page"] = page_num
    record.setdefault("selection_notes", [])
    record.setdefault("requirements", {}).setdefault("nsc", {}).setdefault("excluded_subjects", [])
    return record


def _parse_response(content: str, page_num: int) -> list[dict]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return []
    programmes = parsed.get("programmes") if isinstance(parsed, dict) else None
    if not isinstance(programmes, list):
        return []
    records = [_normalise_record(p, page_num) for p in programmes if isinstance(p, dict)]
    return [r for r in records if r is not None]


def extract_vision(
    pdf_path: Path,
    profile: dict,
    table_pages: list[int],
    api_key: str,
    model: str = _DEFAULT_MODEL,
    http_post: Callable | None = None,
) -> list[dict]:
    """One OpenRouter call per page in table_pages -- callers decide which
    pages to pass; this function does not filter or judge them. A page
    whose call fails (network error, malformed model output) contributes
    no records for that page rather than aborting the whole run -- the
    caller's reconciliation step already treats a missing record as an
    abstention, not an error."""
    http_post = http_post or requests.post
    records: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num in table_pages:
            if not 1 <= page_num <= len(pdf.pages):
                continue
            page = pdf.pages[page_num - 1]
            image_b64 = _render_page_png_base64(page)
            page_text = normalise_page_text(page)
            messages = _build_messages(image_b64, page_text, page_num)
            try:
                content = _call_openrouter(messages, api_key, model, http_post)
            except (requests.RequestException, KeyError, IndexError):
                continue
            records.extend(_parse_response(content, page_num))
    return records
