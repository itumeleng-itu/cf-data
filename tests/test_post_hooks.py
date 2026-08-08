"""Tests for extract/post_hooks.py -- the registry-dispatched
per-institution post-extraction resolution seam (CPUT needs its
qualification codes resolved by matching programme NAME against a
cross-reference page; that resolver itself stays parked, per the task,
but the dispatch mechanism it will plug into is built now).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
import post_hooks  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_registry():
    # register_hook mutates module-level state; tests must not leak
    # registrations into each other or into the real pipeline's registry.
    before = dict(post_hooks._HOOKS)
    yield
    post_hooks._HOOKS.clear()
    post_hooks._HOOKS.update(before)


def test_unregistered_institution_passes_records_through_unchanged() -> None:
    records = [{"qualification_code": None, "name": "Bachelor of Something"}]
    result = post_hooks.apply_post_extraction_hook("uj", records, Path("data/downloads/uj_2027.pdf"))
    assert result == records
    assert result is records


def test_registered_hook_is_invoked_with_records_and_pdf_path() -> None:
    calls = []

    @post_hooks.register_hook("cput")
    def _resolve_codes(records: list[dict], pdf_path: Path) -> list[dict]:
        calls.append((records, pdf_path))
        return [{**r, "qualification_code": "RESOLVED"} for r in records]

    records = [{"qualification_code": None, "name": "Bachelor of Something"}]
    pdf_path = Path("data/downloads/cput_2027.pdf")
    result = post_hooks.apply_post_extraction_hook("cput", records, pdf_path)

    assert result == [{"qualification_code": "RESOLVED", "name": "Bachelor of Something"}]
    assert calls == [(records, pdf_path)]


def test_hook_for_one_institution_does_not_affect_another() -> None:
    @post_hooks.register_hook("cput")
    def _resolve_codes(records: list[dict], pdf_path: Path) -> list[dict]:
        return [{**r, "qualification_code": "RESOLVED"} for r in records]

    records = [{"qualification_code": None}]
    result = post_hooks.apply_post_extraction_hook("uj", records, Path("uj.pdf"))
    assert result == records
