"""Tests for extract/methods/ocr_cache.py and extract/methods/
textlayer_ocr.py. No real PDFs, no GPU, no real Unlimited-OCR calls --
tmp_path covers all file I/O, and the fallback/cache-hit tests monkeypatch
the module-level get_cached_markdown/extract_textlayer names directly.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
import methods.textlayer_ocr as textlayer_ocr  # noqa: E402
from methods.ocr_cache import get_cached_markdown, store_cached_markdown  # noqa: E402
from methods.textlayer_ocr import extract_textlayer_ocr  # noqa: E402

_PROFILE = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}


# --- ocr_cache.py -----------------------------------------------------------

def test_get_cached_markdown_returns_none_on_cache_miss(tmp_path) -> None:
    result = get_cached_markdown(Path("uj_2027.pdf"), 60, cache_dir=tmp_path)
    assert result is None


def test_store_then_get_cached_markdown_round_trips(tmp_path) -> None:
    store_cached_markdown(Path("uj_2027.pdf"), 60, "| Code | English |\n|---|---|\n| B6CS0Q | 5 |", cache_dir=tmp_path)
    result = get_cached_markdown(Path("uj_2027.pdf"), 60, cache_dir=tmp_path)
    assert result == "| Code | English |\n|---|---|\n| B6CS0Q | 5 |"


# --- extract_textlayer_ocr: cache miss falls back -------------------------

def test_extract_textlayer_ocr_falls_back_to_extract_textlayer_on_cache_miss(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(textlayer_ocr, "get_cached_markdown", lambda pdf_path, page_num, cache_dir: None)

    fallback_calls = []

    def _fake_extract_textlayer(pdf_path, profile, table_pages):
        fallback_calls.append(table_pages)
        return [{"qualification_code": "FALLBACK", "source_page": table_pages[0]}]

    monkeypatch.setattr(textlayer_ocr, "extract_textlayer", _fake_extract_textlayer)

    records = extract_textlayer_ocr(Path("uj_2027.pdf"), _PROFILE, [60], cache_dir=tmp_path)

    assert fallback_calls == [[60]]
    assert records == [{"qualification_code": "FALLBACK", "source_page": 60}]


# --- extract_textlayer_ocr: cache hit uses cached markdown, no fallback ---

def test_extract_textlayer_ocr_uses_cache_and_does_not_call_extract_textlayer(monkeypatch, tmp_path) -> None:
    markdown = (
        "| Qualification Code | Programme | English |\n"
        "|---|---|---|\n"
        "| B6CS0Q | BSc Computer Science | 5 |\n"
    )
    monkeypatch.setattr(textlayer_ocr, "get_cached_markdown", lambda pdf_path, page_num, cache_dir: markdown)

    fallback_calls = []
    monkeypatch.setattr(
        textlayer_ocr, "extract_textlayer",
        lambda pdf_path, profile, table_pages: fallback_calls.append(table_pages) or [],
    )

    records = extract_textlayer_ocr(Path("uj_2027.pdf"), _PROFILE, [60], cache_dir=tmp_path)

    assert fallback_calls == []
    assert len(records) == 1
    assert records[0]["qualification_code"] == "B6CS0Q"
    assert records[0]["source_page"] == 60


def test_extract_textlayer_ocr_returns_empty_for_non_rotated_layout(tmp_path) -> None:
    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": False}}
    assert extract_textlayer_ocr(Path("uj_2027.pdf"), profile, [60], cache_dir=tmp_path) == []
