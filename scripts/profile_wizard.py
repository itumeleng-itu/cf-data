"""Proposes a DRAFT per-institution profile from a real PDF -- sub-phase
8.3's tool for bootstrapping a new institution without hand-deriving
everything from scratch each time. Samples pages, detects candidate
code-shaped token patterns (several shapes, since institutions use
different conventions -- UJ's requires a digit in position 2, CPUT's is
a pure 6-letter shape), recurring short strings that look like column
headers, whether rotated text is present, and short all-caps tokens that
look like campus abbreviations.

Writes to extract/institutions/{id}.draft.json -- NEVER to registry.json.
A proposed profile is a hypothesis a human must read, verify against the
real document, and correct before it becomes real per-institution data;
this script has no way to know which candidate pattern is real vs noise
(see, for example, how many ordinary English words a generic 6-letter
shape matches on a real document -- confirmed during CPUT's derivation).
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pdfplumber

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent / "extract"))
from text_repair import normalise_page_text  # noqa: E402

# Candidate code shapes to test, not a single assumed pattern -- different
# institutions use different conventions (confirmed: UJ requires a digit
# in position 2; CPUT's real codes never do). Each is reported with its
# match count and a small sample so a human can judge which, if any, is
# real.
_CANDIDATE_CODE_PATTERNS = {
    "letter+digit+alnum{3,4} (UJ-style)": r"\b[A-Z]\d[A-Z0-9]{3,4}\b",
    "letter+(letter|digit)+letter{4} (CPUT-style, 6 chars)": r"\b[A-Z][A-Z0-9][A-Z]{4}\b",
    "letters{2,4}+digits{2,4}": r"\b[A-Z]{2,4}\d{2,4}\b",
    "digit+letters{2,5}": r"\b\d[A-Z]{2,5}\b",
}

_STOPWORDS = {
    "THE", "AND", "FOR", "ARE", "YOU", "WITH", "THIS", "THAT", "FROM", "WILL",
    "YOUR", "HAVE", "CAN", "NOT", "ALL", "BUT", "WHO", "OUR",
}


def _sample_pages(pdf: "pdfplumber.PDF", sample_size: int | None) -> list[int]:
    total = len(pdf.pages)
    if sample_size is None or sample_size >= total:
        return list(range(1, total + 1))
    step = total / sample_size
    return sorted({int(i * step) + 1 for i in range(sample_size)})


def _candidate_code_patterns(texts: dict[int, str]) -> list[dict]:
    results = []
    for label, pattern in _CANDIDATE_CODE_PATTERNS.items():
        counter: Counter = Counter()
        pages_hit = 0
        for page_number, text in texts.items():
            matches = re.findall(pattern, text)
            if matches:
                pages_hit += 1
                counter.update(matches)
        results.append({
            "pattern": pattern,
            "label": label,
            "total_matches": sum(counter.values()),
            "pages_with_matches": pages_hit,
            "most_common_samples": [tok for tok, _ in counter.most_common(10)],
        })
    return results


def _candidate_header_keywords(texts: dict[int, str], min_page_fraction: float = 0.3) -> list[dict]:
    # Recurring short ALL-CAPS words (2-20 chars) that appear on a
    # meaningful fraction of sampled pages -- candidate column headers.
    # Common short stopwords filtered out; still noisy by nature (a human
    # must judge these against the real table, exactly as CPUT's
    # DEPARTMENT/QUALIFICATION/APS SCORE/METHOD were judged this session).
    page_sets: dict[str, set[int]] = {}
    for page_number, text in texts.items():
        words = set(re.findall(r"\b[A-Z]{2,20}\b", text))
        for word in words:
            if word in _STOPWORDS:
                continue
            page_sets.setdefault(word, set()).add(page_number)

    threshold = max(2, int(len(texts) * min_page_fraction))
    candidates = [
        {"word": word, "page_count": len(pages)}
        for word, pages in page_sets.items()
        if len(pages) >= threshold
    ]
    candidates.sort(key=lambda c: -c["page_count"])
    return candidates[:20]


def _campus_token_candidates(texts: dict[int, str]) -> list[dict]:
    # Short (2-4 char) all-caps tokens recurring across pages -- a subset
    # of the header-keyword search, filtered to campus-abbreviation length.
    page_sets: dict[str, set[int]] = {}
    for page_number, text in texts.items():
        words = set(re.findall(r"\b[A-Z]{2,4}\b", text))
        for word in words:
            if word in _STOPWORDS:
                continue
            page_sets.setdefault(word, set()).add(page_number)

    candidates = [
        {"token": word, "page_count": len(pages)}
        for word, pages in page_sets.items()
        if len(pages) >= 2
    ]
    candidates.sort(key=lambda c: -c["page_count"])
    return candidates[:15]


def _rotation_summary(pdf: "pdfplumber.PDF", page_numbers: list[int]) -> dict:
    total_chars = 0
    non_upright_chars = 0
    pages_with_rotation = 0
    for page_number in page_numbers:
        page = pdf.pages[page_number - 1]
        chars = page.chars
        total_chars += len(chars)
        non_upright = sum(1 for c in chars if not c.get("upright", True))
        non_upright_chars += non_upright
        if non_upright > 0:
            pages_with_rotation += 1
    ratio = non_upright_chars / total_chars if total_chars else 0.0
    return {
        "total_chars_sampled": total_chars,
        "non_upright_chars": non_upright_chars,
        "non_upright_ratio": ratio,
        "pages_with_any_rotation": pages_with_rotation,
        "pages_sampled": len(page_numbers),
        "likely_rotated_headers": ratio > 0.01,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--institution", required=True, help="candidate institution id, e.g. 'tut'")
    ap.add_argument("--sample", type=int, default=None, help="number of pages to sample; defaults to all")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"no such file: {pdf_path}")
        return 1

    out_path = Path(__file__).parent.parent / "extract" / "institutions" / f"{args.institution}.draft.json"

    with pdfplumber.open(pdf_path) as pdf:
        page_numbers = _sample_pages(pdf, args.sample)
        print(f"sampling {len(page_numbers)}/{len(pdf.pages)} pages: {page_numbers}")

        texts = {p: normalise_page_text(pdf.pages[p - 1]) for p in page_numbers}
        code_candidates = _candidate_code_patterns(texts)
        header_candidates = _candidate_header_keywords(texts)
        campus_candidates = _campus_token_candidates(texts)
        rotation = _rotation_summary(pdf, page_numbers)

    print("\n--- candidate code patterns ---")
    for c in code_candidates:
        print(f"  {c['label']}: {c['total_matches']} matches on {c['pages_with_matches']} page(s)")
        print(f"    sample: {c['most_common_samples']}")

    print("\n--- candidate header keywords (recurring all-caps words) ---")
    for h in header_candidates:
        print(f"  {h['word']!r}: appears on {h['page_count']}/{len(page_numbers)} sampled pages")

    print("\n--- candidate campus tokens (short all-caps, 2-4 chars) ---")
    for c in campus_candidates:
        print(f"  {c['token']!r}: appears on {c['page_count']}/{len(page_numbers)} sampled pages")

    print("\n--- rotation ---")
    print(f"  non-upright ratio: {rotation['non_upright_ratio']:.2%}")
    print(f"  pages with any rotation: {rotation['pages_with_any_rotation']}/{rotation['pages_sampled']}")
    print(f"  likely_rotated_headers (heuristic, >1% non-upright): {rotation['likely_rotated_headers']}")

    draft = {
        "_comment": (
            "DRAFT profile proposed by scripts/profile_wizard.py -- a hypothesis, "
            "not a fact. A human must read the evidence below, verify each field "
            "against the real PDF, and move a corrected version into "
            "extract/institutions/registry.json by hand. This file is never "
            "loaded by extract/profiles.py."
        ),
        "institution_id": args.institution,
        "pdf_sampled": str(pdf_path),
        "pages_sampled": page_numbers,
        "evidence": {
            "code_pattern_candidates": code_candidates,
            "header_keyword_candidates": header_candidates,
            "campus_token_candidates": campus_candidates,
            "rotation": rotation,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDraft written to {out_path} -- review and correct before promoting to registry.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
