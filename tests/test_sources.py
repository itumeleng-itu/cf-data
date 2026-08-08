"""Tests for extract/sources/ adapters -- the REAL discover()/
resolve_pdf_url() methods run end-to-end against saved HTML fixtures, not
a re-implementation of their parsing logic, by monkeypatching polite_get
so no network call ever happens. Fixtures are trimmed real page fragments
(saved 2026-08-08 by hand, via curl) plus a couple of synthetic edge
cases for the "no link found" failure path.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "sources"
sys.path.insert(0, str(ROOT / "extract"))

import sources.apply_org_za as apply_org_za  # noqa: E402
import sources.universityqualifications as universityqualifications  # noqa: E402
from sources import DiscoveredProspectus  # noqa: E402


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


def _fake_polite_get(fixture_name: str):
    text = (FIXTURES / fixture_name).read_text(encoding="utf-8")

    def _get(session, url, **kwargs):
        return _FakeResponse(text)

    return _get


# --- universityqualifications.py ---------------------------------------

def test_uq_discover_parses_all_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universityqualifications, "polite_get", _fake_polite_get("uq_listing_2027.html"))
    source = universityqualifications.UniversityQualificationsSource()
    entries = source.discover(2027)
    assert len(entries) == 3
    assert all(e.institution_id is None for e in entries)  # never resolved by the adapter itself
    assert all(e.academic_year == 2027 for e in entries)


def test_uq_discover_strips_prospectus_year_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universityqualifications, "polite_get", _fake_polite_get("uq_listing_2027.html"))
    source = universityqualifications.UniversityQualificationsSource()
    names = {e.display_name for e in source.discover(2027)}
    assert "Cape Peninsula University of Technology (CPUT)" in names
    assert "University of Johannesburg (UJ)" in names


def test_uq_clean_display_name_handles_prospectus_then_year() -> None:
    assert universityqualifications._clean_display_name(
        "Cape Peninsula University of Technology (CPUT) Prospectus 2027", 2027
    ) == "Cape Peninsula University of Technology (CPUT)"


def test_uq_clean_display_name_handles_year_then_prospectus() -> None:
    # Univen's real card text on the live site puts the year BEFORE
    # "Prospectus", not after -- confirmed by hand, not assumed to match
    # the common ordering every other card uses.
    assert universityqualifications._clean_display_name(
        "University Of Venda (Univen) 2027 Prospectus", 2027
    ) == "University Of Venda (Univen)"


def test_uq_resolve_pdf_url_parses_adobe_viewer_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(universityqualifications, "polite_get", _fake_polite_get("uq_detail_uj.html"))
    source = universityqualifications.UniversityQualificationsSource()
    entry = DiscoveredProspectus(
        institution_id=None, display_name="University of Johannesburg (UJ)",
        academic_year=2027, detail_url="https://universityqualifications.co.za/pdf-prospectus/x",
        source_id="x",
    )
    url = source.resolve_pdf_url(entry)
    assert url == (
        "https://d1yqwmn8pjyrsu.cloudfront.net/pdf-prospectus/"
        "university-of-johannesburg-uj-prospectus-2027.pdf"
    )


def test_uq_resolve_pdf_url_returns_none_without_guessing(monkeypatch: pytest.MonkeyPatch) -> None:
    # No Adobe viewer script on this page at all -- must not fall back to
    # guessing a URL from the slug.
    monkeypatch.setattr(universityqualifications, "polite_get", _fake_polite_get("uq_detail_no_pdf.html"))
    source = universityqualifications.UniversityQualificationsSource()
    entry = DiscoveredProspectus(
        institution_id=None, display_name="Some Institution", academic_year=2027,
        detail_url="https://universityqualifications.co.za/pdf-prospectus/x", source_id="x",
    )
    assert source.resolve_pdf_url(entry) is None


# --- apply_org_za.py -----------------------------------------------------

def test_apply_discover_excludes_non_sa_public_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apply_org_za, "polite_get", _fake_polite_get("apply_undergraduate_listing.html"))
    source = apply_org_za.ApplyOrgZaSource()
    entries = source.discover(2027)
    slugs = {e.source_id for e in entries}
    assert "eduvos" not in slugs
    assert "uj" in slugs
    assert "cput" in slugs
    # "cao" is NOT excluded by the adapter -- it's not a named non-SA-public
    # entry, it's an unregistered multi-institution document; institution_map
    # is what reports it UNMAPPED, not the adapter dropping it silently.
    assert "cao" in slugs


def test_apply_discover_strips_prospectus_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apply_org_za, "polite_get", _fake_polite_get("apply_undergraduate_listing.html"))
    source = apply_org_za.ApplyOrgZaSource()
    names = {e.display_name for e in source.discover(2027)}
    assert "University of Johannesburg (UJ)" in names


def test_apply_resolve_pdf_url_returns_the_short_redirect_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apply_org_za, "polite_get", _fake_polite_get("apply_detail_uj.html"))
    source = apply_org_za.ApplyOrgZaSource()
    entry = DiscoveredProspectus(
        institution_id="uj", display_name="University of Johannesburg (UJ)", academic_year=2027,
        detail_url="https://apply.org.za/prospectuses/uj/", source_id="uj",
    )
    assert source.resolve_pdf_url(entry) == "https://apply.org.za/ujpp/"


def test_apply_resolve_pdf_url_refuses_on_year_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    # apply.org.za's listing is year-agnostic -- the fixture page is for
    # 2027 (per its <title>); requesting 2026 against it must not silently
    # resolve a PDF that's actually a different year's document.
    monkeypatch.setattr(apply_org_za, "polite_get", _fake_polite_get("apply_detail_uj.html"))
    source = apply_org_za.ApplyOrgZaSource()
    entry = DiscoveredProspectus(
        institution_id="uj", display_name="University of Johannesburg (UJ)", academic_year=2026,
        detail_url="https://apply.org.za/prospectuses/uj/", source_id="uj",
    )
    assert source.resolve_pdf_url(entry) is None


def test_apply_resolve_pdf_url_returns_none_without_guessing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apply_org_za, "polite_get", _fake_polite_get("apply_detail_no_download.html"))
    source = apply_org_za.ApplyOrgZaSource()
    entry = DiscoveredProspectus(
        institution_id=None, display_name="Some Institution", academic_year=2027,
        detail_url="https://apply.org.za/prospectuses/x/", source_id="x",
    )
    assert source.resolve_pdf_url(entry) is None
