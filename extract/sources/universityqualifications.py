"""Adapter for universityqualifications.co.za's PDF prospectus listing.

Two-hop resolution, confirmed by hand (curl + reading the real pages,
2026-08-08), not assumed from a URL-naming convention:
  1. The year listing (https://.../undergraduate/pdf-prospectus/{year})
     gives "View PDF Document" links to per-institution DETAIL pages, not
     to files -- each is a <div class="card"> with an <h5 class="card-title">
     display name and an <a href="https://.../pdf-prospectus/{slug}">.
  2. Each detail page embeds the real PDF location inside an Adobe DC View
     SDK previewFile() call -- there is no plain <a href=*.pdf> anywhere on
     these pages. resolve_pdf_url() parses that script rather than
     guessing a URL from the slug, even though the PDF URL happens to
     mirror the slug on every detail page checked -- that's a coincidence
     of this site's convention, not something to rely on for a page this
     adapter hasn't actually read.
"""

import re

from bs4 import BeautifulSoup

from . import DiscoveredProspectus
from .http import new_session, polite_get

_BASE = "https://universityqualifications.co.za"

# Matches the Adobe DC View SDK's previewFile({content: {location: {url: "..."}}})
# call. The site emits escaped forward slashes (\/) inside the JS string.
_ADOBE_URL_PATTERN = re.compile(r'location:\s*\{\s*url:\s*"([^"]+)"', re.DOTALL)


class UniversityQualificationsSource:
    source_id = "universityqualifications"

    def discover(self, year: int) -> list[DiscoveredProspectus]:
        session = new_session()
        listing_url = f"{_BASE}/undergraduate/pdf-prospectus/{year}"
        response = polite_get(session, listing_url)
        soup = BeautifulSoup(response.text, "html.parser")

        entries: list[DiscoveredProspectus] = []
        for card in soup.select("div.card"):
            title_el = card.select_one("h5.card-title")
            link_el = card.select_one("a[href*='/pdf-prospectus/']")
            if title_el is None or link_el is None:
                continue

            raw_title = title_el.get_text(" ", strip=True)
            display_name = _clean_display_name(raw_title, year)
            detail_url = link_el["href"]
            slug = detail_url.rstrip("/").rsplit("/", 1)[-1]

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
        match = _ADOBE_URL_PATTERN.search(response.text)
        if match is None:
            return None
        url = match.group(1).replace("\\/", "/")
        if not url.lower().endswith(".pdf"):
            return None
        return url


def _clean_display_name(raw_title: str, year: int) -> str:
    text = raw_title.strip()
    year_str = str(year)
    # Both orderings observed for real: "... Prospectus {year}" on most
    # cards, "... {year} Prospectus" on Univen's -- strip whichever
    # trailing combination is present rather than assuming one.
    for pattern in (rf"\s*Prospectus\s*{year_str}\s*$", rf"\s*{year_str}\s*Prospectus\s*$"):
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()
