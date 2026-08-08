"""Adapter for apply.org.za's prospectus pages.

Undergraduate only: discover() scrapes the site's own
/prospectus-type/undergraduate/ listing (confirmed by hand, 2026-08-08, to
already exclude postgraduate entries -- it returns exactly 26 cards,
matching SA public universities plus a few non-public entries plus one
multi-institution document, not a larger set that would need separate
postgraduate filtering applied here).

Dropped outright, per explicit instruction, regardless of what the
listing contains: the 4 non-SA-public entries (regenesys, eduvos, swgc,
nul) -- a private college, a business school, a Lesotho university, and a
TVET college have no NSC admission requirements to extract.

Detail pages (https://apply.org.za/prospectuses/{slug}/) have no plain
.pdf link: the "Download PDF" button is a Pretty-Link short redirect
(confirmed by hand: curl -sIL on https://apply.org.za/ujpp/ 307-redirects
to https://assets.apply.org.za/u-files/Prospectuses/UJ2027.pdf).
resolve_pdf_url() returns that short link as-is -- the shared downloader
follows redirects and validates the final bytes -- rather than
pre-resolving the redirect here and risking it changing between calls.

The listing has no year-specific URL: it always reflects whichever year
is currently live, so a requested year could silently mismatch what's
actually on the page. resolve_pdf_url() checks the detail page's own
<title> for the requested year and refuses (returns None) rather than
resolve a PDF for the wrong year.
"""

import re

from bs4 import BeautifulSoup

from . import DiscoveredProspectus
from .http import new_session, polite_get

_LISTING_URL = "https://apply.org.za/prospectus-type/undergraduate/"

_EXCLUDED_SLUGS = {"regenesys", "eduvos", "swgc", "nul"}


class ApplyOrgZaSource:
    source_id = "apply"

    def discover(self, year: int) -> list[DiscoveredProspectus]:
        session = new_session()
        response = polite_get(session, _LISTING_URL)
        soup = BeautifulSoup(response.text, "html.parser")

        entries: list[DiscoveredProspectus] = []
        for heading in soup.select("h2.elementor-heading-title"):
            link_el = heading.select_one("a[href*='/prospectuses/']")
            if link_el is None:
                continue
            detail_url = link_el["href"]
            slug = detail_url.rstrip("/").rsplit("/", 1)[-1]
            if slug in _EXCLUDED_SLUGS:
                continue

            raw_title = link_el.get_text(" ", strip=True)
            display_name = _strip_prospectus_suffix(raw_title)

            entries.append(DiscoveredProspectus(
                institution_id=None,
                display_name=display_name,
                academic_year=year,
                detail_url=detail_url,
                source_id=slug,
                multi_institution=False,
            ))
        return entries

    def resolve_pdf_url(self, entry: DiscoveredProspectus) -> str | None:
        session = new_session()
        response = polite_get(session, entry.detail_url)
        soup = BeautifulSoup(response.text, "html.parser")

        title_el = soup.select_one("title")
        title_text = title_el.get_text(strip=True) if title_el else ""
        if str(entry.academic_year) not in title_text:
            return None

        # The download button is identified by its download= attribute --
        # a real structural marker, not button text/styling that could
        # change without the underlying link structure changing.
        link_el = soup.select_one("a[download]")
        if link_el is None:
            return None
        href = link_el.get("href")
        if not href:
            return None
        return href


def _strip_prospectus_suffix(raw_title: str) -> str:
    return re.sub(r"\s*Prospectus\s*$", "", raw_title, flags=re.IGNORECASE).strip()
