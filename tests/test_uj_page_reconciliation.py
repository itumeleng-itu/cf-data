"""The UJ extraction must still account for every page of the prospectus.

The manifest this checks is generated FROM THE EXTRACTION, never from the
seed, so it cannot drift into agreement with a broken converter: it records
which qualification codes came off which page, and the seed is then held to
it. If a future converter change drops a page's rows, the counts stop
matching and this fails.

Pairs with scripts/verify_uj_programmes.py, which does the heavier check
against poppler and against the table's drawn rectangles but needs the PDF.
This one needs only the seed and runs anywhere.
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

MANIFEST = json.loads(
    (ROOT / "tests" / "fixtures" / "uj_2027_page_codes.json").read_text(encoding="utf-8")
)
SEED = json.loads((ROOT / "seeds" / "uj" / "uj_2027.json").read_text(encoding="utf-8"))

# Codes the prospectus prints that are deliberately not programmes; each
# reason is recorded in scripts/verify_uj_programmes.py.
EXCLUDED = {"S3M01Q", "MKT010", "B34INQ", "B34HRP", "B34ACP"}


def _seed_codes_by_page() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for p in SEED:
        out.setdefault(str(p["source_page"]), set()).add(p["qualification_code"])
        for alt in p.get("alternate_codes") or []:
            out[str(p["source_page"])].add(alt)
    return out


def test_every_page_in_the_manifest_is_in_the_seed() -> None:
    seed_pages = _seed_codes_by_page()
    for page, codes in MANIFEST.items():
        if not codes:
            continue
        missing = set(codes) - seed_pages.get(page, set()) - EXCLUDED
        assert not missing, f"page {page}: {sorted(missing)} extracted but absent from the seed"


def test_the_seed_invents_no_page() -> None:
    for page, codes in _seed_codes_by_page().items():
        assert page in MANIFEST, f"seed cites page {page}, which the extraction never read"
        extra = codes - set(MANIFEST[page])
        assert not extra, f"page {page}: {sorted(extra)} in the seed but not extracted from that page"


def test_the_whole_faculty_range_is_accounted_for() -> None:
    """Every page the extraction found a table on produced records, and the
    totals agree -- 179 programmes over the eight faculties."""
    assert len(SEED) == 179
    pages_with_rows = {p for p, c in MANIFEST.items() if c}
    assert pages_with_rows == set(_seed_codes_by_page())


def test_each_faculty_is_present() -> None:
    """Humanities is the point of this one: it was absent from the seed
    entirely before the 2027 extraction, and nothing would have noticed."""
    counts = Counter(p["faculty"] for p in SEED)
    assert set(counts) == {
        "Art, Design and Architecture", "Business and Economics", "Education",
        "Engineering and the Built Environment", "Health Sciences", "Humanities",
        "Law", "Science",
    }
    assert all(n > 0 for n in counts.values())


def test_every_record_is_traceable_to_its_source() -> None:
    for p in SEED:
        assert p["source_doc"] == "uj_undergrad_prospectus2027"
        assert 30 <= p["source_page"] <= 97, p["qualification_code"]
        assert p["confidence"] == "verified"
