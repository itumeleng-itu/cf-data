"""Tests for extract/methods/vision.py (Method C). Unit tests use a fake
http_post callable -- no real network call, no cost. time.sleep is
monkeypatched to a no-op so rate-limit/backoff tests run instantly while
still verifying the delay logic was exercised. The one real-API
integration is exercised separately by whatever orchestration script
actually runs Method C for real; that costs real network time (or money,
for a paid provider) and does not belong in the regular test suite.

Provider-specific fake response shapes live here (OpenAI-style for
OpenRouter, Gemini-style for AI Studio) since vision.py's own retry/
parse/abstain logic is provider-agnostic and tested once against
whichever shape is convenient (OpenRouter's, matching the pre-existing
tests) plus one shape-specific pass per provider to prove the real
parsing path for each.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
import methods.vision as vision  # noqa: E402
from methods.vision import _extract_programmes, _normalise_record, _try_parse_json, extract_vision  # noqa: E402
from providers import RateLimitError  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(vision.time, "sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


def _find_uj_2027_pdf() -> Path | None:
    downloads = ROOT / "data" / "downloads" / "uj_2027.pdf"
    return downloads if downloads.exists() else None


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


# --- _try_parse_json / _extract_programmes --------------------------------

def test_try_parse_json_returns_none_on_malformed_json() -> None:
    assert _try_parse_json("not json at all {{{") is None


def test_try_parse_json_returns_parsed_object_on_success() -> None:
    assert _try_parse_json(json.dumps({"programmes": []})) == {"programmes": []}


def test_extract_programmes_extracts_array() -> None:
    parsed = {
        "programmes": [
            {"qualification_code": "B6CS0Q", "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}}},
            {"qualification_code": "B6CV3Q", "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}}},
        ],
    }
    records = _extract_programmes(parsed, page_num=60)
    assert {r["qualification_code"] for r in records} == {"B6CS0Q", "B6CV3Q"}
    assert all(r["source_page"] == 60 for r in records)


def test_extract_programmes_missing_key_returns_empty_list() -> None:
    assert _extract_programmes({"unexpected": "shape"}, page_num=60) == []


def test_extract_programmes_drops_records_with_bad_codes_keeps_good_ones() -> None:
    parsed = {
        "programmes": [
            {"qualification_code": "B6CS0Q", "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}}},
            {"name": "malformed, no code"},
        ],
    }
    records = _extract_programmes(parsed, page_num=60)
    assert len(records) == 1
    assert records[0]["qualification_code"] == "B6CS0Q"


# --- extract_vision via the OpenRouter provider: fake HTTP ---------------

class _FakeResponse:
    def __init__(self, payload: dict | None = None, status_code: int = 200, headers: dict | None = None) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}")

    def json(self) -> dict:
        return self._payload


def _openrouter_response(content_obj: dict) -> _FakeResponse:
    return _openrouter_raw_response(json.dumps(content_obj))


def _openrouter_raw_response(text: str) -> _FakeResponse:
    message = {"content": text}
    choice = {"message": message}
    return _FakeResponse({"choices": [choice]})


def test_extract_vision_uses_injected_http_post_not_real_network() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    payload = {"programmes": [
        {"qualification_code": "B6CS0Q", "requirements": {"nsc": {"score": [{"min_score": 32}], "subjects": {"kind": "all", "rules": []}}}},
    ]}
    fake_post = lambda url, *, headers, json, timeout: _openrouter_response(payload)  # noqa: E731

    records, stats = extract_vision(
        pdf_path, profile, [60], api_key="fake-key-not-a-real-secret", provider_name="openrouter", http_post=fake_post,
    )
    assert len(records) == 1
    assert records[0]["qualification_code"] == "B6CS0Q"
    assert records[0]["source_page"] == 60
    assert stats == {
        "provider": "openrouter", "model": vision._DEFAULT_OPENROUTER_MODEL,
        "pages_attempted": 1, "pages_parsed": 1, "pages_abstained": 0,
    }


def test_extract_vision_abstains_on_request_exception() -> None:
    import requests

    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    def _failing_post(url, *, headers, json, timeout):
        raise requests.ConnectionError("simulated network failure")

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    records, stats = extract_vision(
        pdf_path, profile, [60], api_key="fake-key", provider_name="openrouter", http_post=_failing_post,
    )
    assert records == []
    assert stats["pages_abstained"] == 1
    assert stats["pages_parsed"] == 0


def test_extract_vision_abstains_after_json_parse_fails_twice() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    calls = []

    def _garbage_post(url, *, headers, json, timeout):
        calls.append(1)
        return _openrouter_raw_response("not json at all {{{")

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    records, stats = extract_vision(
        pdf_path, profile, [60], api_key="fake-key", provider_name="openrouter", http_post=_garbage_post,
    )
    assert records == []
    assert stats["pages_abstained"] == 1
    assert len(calls) == 2  # initial attempt + one retry, per _JSON_PARSE_RETRIES = 1


def test_extract_vision_recovers_if_retry_returns_valid_json() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    calls = []

    def _flaky_post(url, *, headers, json, timeout):
        calls.append(1)
        if len(calls) == 1:
            return _openrouter_raw_response("garbage {{{")
        return _openrouter_response({"programmes": [
            {"qualification_code": "B6CS0Q", "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}}},
        ]})

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    records, stats = extract_vision(
        pdf_path, profile, [60], api_key="fake-key", provider_name="openrouter", http_post=_flaky_post,
    )
    assert stats["pages_parsed"] == 1
    assert len(records) == 1


def test_extract_vision_retries_on_429_then_succeeds(_no_real_sleep) -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    calls = []

    def _rate_limited_post(url, *, headers, json, timeout):
        calls.append(1)
        if len(calls) == 1:
            return _FakeResponse(status_code=429, headers={"Retry-After": "1"})
        return _openrouter_response({"programmes": [
            {"qualification_code": "B6CS0Q", "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}}},
        ]})

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    records, stats = extract_vision(
        pdf_path, profile, [60], api_key="fake-key", provider_name="openrouter", http_post=_rate_limited_post,
    )
    assert len(calls) == 2
    assert stats["pages_parsed"] == 1
    assert len(records) == 1
    assert 1.0 in _no_real_sleep  # honoured the Retry-After header


def test_extract_vision_abstains_after_exhausting_429_retries() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    def _always_429(url, *, headers, json, timeout):
        return _FakeResponse(status_code=429)

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    records, stats = extract_vision(
        pdf_path, profile, [60], api_key="fake-key", provider_name="openrouter", http_post=_always_429,
    )
    assert records == []
    assert stats["pages_abstained"] == 1


def test_extract_vision_sleeps_between_pages_not_before_the_first(_no_real_sleep) -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    payload = {"programmes": []}
    fake_post = lambda url, *, headers, json, timeout: _openrouter_response(payload)  # noqa: E731

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    extract_vision(
        pdf_path, profile, [60, 61], api_key="fake-key", provider_name="openrouter",
        http_post=fake_post, request_delay_seconds=2.5,
    )
    assert _no_real_sleep == [2.5]  # one sleep, between the two pages -- none before the first


def test_extract_vision_calls_on_page_complete_after_every_page_including_abstained_ones() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    calls = []

    # Page 60 succeeds, page 61 abstains (garbage twice) -- proves the
    # hook fires for BOTH outcomes, in page order, not just successes.
    responses = iter([
        _openrouter_response({"programmes": [
            {"qualification_code": "B6CS0Q", "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}}},
        ]}),
        _openrouter_raw_response("garbage {{{"),
        _openrouter_raw_response("still garbage {{{"),
    ])

    def _sequenced_post(url, *, headers, json, timeout):
        return next(responses)

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    extract_vision(
        pdf_path, profile, [60, 61], api_key="fake-key", provider_name="openrouter",
        http_post=_sequenced_post, on_page_complete=lambda page_num, records, status: calls.append((page_num, len(records), status)),
    )
    assert calls == [(60, 1, "parsed"), (61, 0, "abstained")]


def test_extract_vision_model_defaults_and_is_overridable() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    seen_models = []

    def _capturing_post(url, *, headers, json, timeout):
        seen_models.append(json["model"])
        return _openrouter_response({"programmes": []})

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    _records, stats = extract_vision(
        pdf_path, profile, [60], api_key="fake-key", provider_name="openrouter",
        model="some/other-model:free", http_post=_capturing_post,
    )
    assert seen_models == ["some/other-model:free"]
    assert stats["model"] == "some/other-model:free"


def test_default_openrouter_model_reads_env_var(monkeypatch) -> None:
    import importlib

    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")
    importlib.reload(vision)
    try:
        assert vision._DEFAULT_OPENROUTER_MODEL == "google/gemma-4-31b-it:free"
    finally:
        monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
        importlib.reload(vision)


# --- extract_vision via the AI Studio provider: fake HTTP -----------------

def _aistudio_response(text: str) -> _FakeResponse:
    part = {"text": text}
    content = {"parts": [part]}
    candidate = {"content": content}
    return _FakeResponse({"candidates": [candidate]})


def test_extract_vision_uses_aistudio_by_default() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    payload = {"programmes": [
        {"qualification_code": "B6CS0Q", "requirements": {"nsc": {"score": None, "subjects": {"kind": "all", "rules": []}}}},
    ]}
    fake_post = lambda url, *, headers, json, timeout: _aistudio_response(__import__("json").dumps(payload))  # noqa: E731

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    records, stats = extract_vision(pdf_path, profile, [60], api_key="fake-key", http_post=fake_post)
    assert stats["provider"] == "aistudio"
    assert stats["model"] == vision._DEFAULT_AISTUDIO_MODEL
    assert len(records) == 1


def test_extract_vision_aistudio_sends_x_goog_api_key_header() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    seen_headers = []

    def _capturing_post(url, *, headers, json, timeout):
        seen_headers.append(headers)
        return _aistudio_response('{"programmes": []}')

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    extract_vision(pdf_path, profile, [60], api_key="my-real-looking-key", http_post=_capturing_post)
    assert seen_headers[0]["x-goog-api-key"] == "my-real-looking-key"


def test_extract_vision_aistudio_url_includes_model_name() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    seen_urls = []

    def _capturing_post(url, *, headers, json, timeout):
        seen_urls.append(url)
        return _aistudio_response('{"programmes": []}')

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    extract_vision(pdf_path, profile, [60], api_key="fake-key", model="gemini-2.5-flash", http_post=_capturing_post)
    assert seen_urls[0].endswith("models/gemini-2.5-flash:generateContent")


def test_default_aistudio_model_reads_env_var(monkeypatch) -> None:
    import importlib

    monkeypatch.setenv("AISTUDIO_MODEL", "gemini-2.0-flash")
    importlib.reload(vision)
    try:
        assert vision._DEFAULT_AISTUDIO_MODEL == "gemini-2.0-flash"
    finally:
        monkeypatch.delenv("AISTUDIO_MODEL", raising=False)
        importlib.reload(vision)


def test_vision_provider_env_var_selects_provider(monkeypatch) -> None:
    import importlib

    monkeypatch.setenv("VISION_PROVIDER", "openrouter")
    importlib.reload(vision)
    try:
        assert vision._DEFAULT_PROVIDER == "openrouter"
    finally:
        monkeypatch.delenv("VISION_PROVIDER", raising=False)
        importlib.reload(vision)


def test_unknown_provider_name_raises() -> None:
    pdf_path = _find_uj_2027_pdf()
    if pdf_path is None:
        pytest.skip("UJ 2027 PDF not present -- skipping on this clone")

    profile = {"layout": {"code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}", "rotated_headers": True}}
    with pytest.raises(ValueError, match="unknown VISION_PROVIDER"):
        extract_vision(pdf_path, profile, [60], api_key="fake-key", provider_name="carrier-pigeon")
