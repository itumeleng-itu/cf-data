"""Tests for extract/methods/vision.py (Method C). Unit tests use a fake
http_post callable -- no real network call, no OpenRouter cost. The one
real-API integration is exercised separately by whatever orchestration
script actually runs Method C against OpenRouter; that costs money and
does not belong in the regular test suite.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from methods.vision import _normalise_record, _parse_response, extract_vision  # noqa: E402


# --- _normalise_record -----------------------------------------------------

def test_normalise_record_forces_career_text_none_even_if_model_populated_it() -> None:
    raw = {
        "qualification_code": "B6CS0Q",
        "career_text": "This should never survive -- marketing prose the model must not have written.",
        "requirements": {"nsc": {"score": [{"min_score": 32}], "subjects": {"kind": "all", "rules": []}}},
    }
    record = _normalise_record(raw, page_num=60)
    assert record["career_text"] is None


def test_normalise_record_stamps_source_page() -> None:
    raw = {
        "qualification_code": "B6CS0Q",
        "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}},
    }
    record = _normalise_record(raw, page_num=60)
    assert record["source_page"] == 60


def test_normalise_record_rejects_missing_code() -> None:
    assert _normalise_record({"name": "No code at all"}, page_num=60) is None


def test_normalise_record_rejects_implausible_code_shape() -> None:
    # A hallucinated "code" that's actually a sentence fragment, not a
    # real qualification code -- must not silently pass through.
    assert _normalise_record({"qualification_code": "see page 12 for details"}, page_num=60) is None


def test_normalise_record_defaults_missing_selection_notes_and_excluded_subjects() -> None:
    raw = {
        "qualification_code": "B6CS0Q",
        "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}},
    }
    record = _normalise_record(raw, page_num=60)
    assert record["selection_notes"] == []
    assert record["requirements"]["nsc"]["excluded_subjects"] == []


# --- _parse_response ---------------------------------------------------

def test_parse_response_extracts_programmes_array() -> None:
    content = json.dumps({
        "programmes": [
            {"qualification_code": "B6CS0Q", "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}}},
            {"qualification_code": "B6CV3Q", "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}}},
        ],
    })
    records = _parse_response(content, page_num=60)
    assert {r["qualification_code"] for r in records} == {"B6CS0Q", "B6CV3Q"}
    assert all(r["source_page"] == 60 for r in records)


def test_parse_response_malformed_json_returns_empty_list() -> None:
    assert _parse_response("not json at all {{{", page_num=60) == []


def test_parse_response_missing_programmes_key_returns_empty_list() -> None:
    assert _parse_response(json.dumps({"unexpected": "shape"}), page_num=60) == []


def test_parse_response_drops_records_with_bad_codes_keeps_good_ones() -> None:
    content = json.dumps({
        "programmes": [
            {"qualification_code": "B6CS0Q", "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}}},
            {"name": "malformed, no code"},
        ],
    })
    records = _parse_response(content, page_num=60)
    assert len(records) == 1
    assert records[0]["qualification_code"] == "B6CS0Q"


# --- extract_vision: fake HTTP, no real network -------------------------

class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


def _fake_post_returning(content_obj: dict):
    def _post(url, *, headers, json, timeout):
        return _FakeResponse({"choices": [{"message": {"content": __import__("json").dumps(content_obj)}}]})
    return _post


def _find_uj_2027_pdf() -> Path | None:
    downloads = ROOT / "data" / "downloads" / "uj_2027.pdf"
    return downloads if downloads.exists() else None


def test_extract_vision_uses_injected_http_post_not_real_network() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    fake_post = _fake_post_returning({
        "programmes": [
            {"qualification_code": "B6CS0Q", "requirements": {"nsc": {"score": [{"min_score": 32}], "subjects": {"kind": "all", "rules": []}}}},
        ],
    })

    records = extract_vision(pdf_path, profile, [60], api_key="fake-key-not-a-real-secret", http_post=fake_post)
    assert len(records) == 1
    assert records[0]["qualification_code"] == "B6CS0Q"
    assert records[0]["source_page"] == 60


def test_extract_vision_skips_page_on_request_exception() -> None:
    import requests

    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    def _failing_post(url, *, headers, json, timeout):
        raise requests.ConnectionError("simulated network failure")

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    records = extract_vision(pdf_path, profile, [60], api_key="fake-key", http_post=_failing_post)
    assert records == []
