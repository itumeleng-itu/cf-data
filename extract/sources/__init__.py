"""Prospectus source adapters -- one module per aggregator site, each
implementing ProspectusSource. A real package (has __init__.py), unlike
the rest of extract/, specifically so sibling modules can do
`from .http import ...` without extract/sources/http.py shadowing the
stdlib http package for anything else that happens to share sys.path.

discover() never invents an institution_id -- see extract/institution_map.py.
resolve_pdf_url() never guesses a URL; if the actual PDF link can't be
identified confidently on a detail page, it returns None. A loose
fallback here is how a privacy policy gets saved as a university's name.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DiscoveredProspectus:
    institution_id: str | None  # None until mapped by institution_map.py; never guessed
    display_name: str
    academic_year: int
    detail_url: str
    source_id: str
    multi_institution: bool = False


class ProspectusSource(Protocol):
    source_id: str

    def discover(self, year: int) -> list[DiscoveredProspectus]: ...
    def resolve_pdf_url(self, entry: DiscoveredProspectus) -> str | None: ...
