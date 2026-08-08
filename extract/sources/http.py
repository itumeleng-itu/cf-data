"""Shared HTTP rules for extract/sources/ adapters -- one place, not
duplicated per adapter. These are small third-party sites (not CDNs built
for scraping load), so the rules here exist specifically to avoid
hammering them: a capped worker count, a mandatory delay between
requests, a real User-Agent, and a robots.txt check before every fetch.

PDF validation happens by content, not by size or Content-Type header: a
size threshold alone would pass a 200KB HTML error page as a "large
enough" download. download_pdf() only writes to disk once the actual
bytes are confirmed to start with b"%PDF-" -- nothing is written, so
nothing needs deleting, on a validation failure.
"""

import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests

USER_AGENT = "CourseFindBot/1.0 (+https://coursefind.co.za; prospectus discovery)"

# Small sites, not built for scraping load -- keep both of these
# conservative. MAX_WORKERS is read by the scripts that drive concurrency
# (this module doesn't spawn threads itself); REQUEST_DELAY_SECONDS is
# enforced on every single request made through this module.
MAX_WORKERS = 2
REQUEST_DELAY_SECONDS = 1.0

_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


class NotAPdfError(ValueError):
    """Raised when a URL expected to return a PDF returned something else."""


def new_session() -> requests.Session:
    """One Session per worker -- requests.Session is not thread-safe and
    must never be shared across threads/processes."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def _robots_for(origin: str, session: requests.Session) -> urllib.robotparser.RobotFileParser:
    if origin not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{origin}/robots.txt")
        try:
            resp = session.get(f"{origin}/robots.txt", timeout=10)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp.parse([])  # no robots.txt -- nothing disallowed
        except requests.RequestException:
            rp.parse([])  # unreachable -- fail open rather than block all discovery
        _robots_cache[origin] = rp
    return _robots_cache[origin]


def allowed_by_robots(url: str, session: requests.Session) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_for(origin, session)
    return rp.can_fetch(USER_AGENT, url)


def polite_get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """GET with a mandatory delay and a robots.txt check. Every fetch an
    adapter makes against its source site should go through this (or
    download_pdf below), not session.get directly."""
    if not allowed_by_robots(url, session):
        raise PermissionError(f"robots.txt disallows fetching {url}")
    time.sleep(REQUEST_DELAY_SECONDS)
    response = session.get(url, timeout=30, **kwargs)
    response.raise_for_status()
    return response


def download_pdf(session: requests.Session, url: str, dest: Path) -> int:
    """Downloads url (following redirects) to dest, validating the actual
    response bytes start with %PDF- before writing anything to disk.
    Returns the byte count. Raises NotAPdfError (dest untouched) if the
    response isn't a real PDF, and PermissionError if robots.txt disallows
    the URL."""
    if not allowed_by_robots(url, session):
        raise PermissionError(f"robots.txt disallows fetching {url}")
    time.sleep(REQUEST_DELAY_SECONDS)
    response = session.get(url, timeout=60, allow_redirects=True)
    response.raise_for_status()
    content = response.content
    if not content.startswith(b"%PDF-"):
        raise NotAPdfError(f"{url} did not return PDF bytes (got {content[:20]!r})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return len(content)
