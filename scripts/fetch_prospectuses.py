"""Downloads prospectus PDFs discovered by discover_prospectuses.py.

Never converts a PDF to text, markdown, or any other format -- the
pipeline reads PDFs natively (char["upright"]/char["matrix"] for
rotated-text repair, page.lines/page.rects for ruled_line_count,
character coordinates for column clustering, image boxes, page
rendering for later vision extraction) and a conversion would destroy
exactly the binary structure those depend on. Downloads stay as PDFs,
always.

Downloads go to data/downloads/ (or --dest) and stay there until staged
by hand into data/inbox/. This script never writes into data/inbox/
itself -- the watcher is live, and a file landing there triggers real
ingestion.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent / "extract"))
from sources import DiscoveredProspectus  # noqa: E402
from sources.apply_org_za import ApplyOrgZaSource  # noqa: E402
from sources.http import NotAPdfError, download_pdf, new_session  # noqa: E402
from sources.universityqualifications import UniversityQualificationsSource  # noqa: E402

_SOURCES = {
    "universityqualifications": UniversityQualificationsSource,
    "apply": ApplyOrgZaSource,
}


def _refuse_if_inside_inbox(dest: Path) -> None:
    inbox_root = (Path(__file__).parent.parent / "data" / "inbox").resolve()
    resolved = dest.resolve()
    if resolved == inbox_root or inbox_root in resolved.parents:
        raise SystemExit(
            f"refusing: --dest {dest} resolves inside data/inbox/ -- this script must "
            f"never write there. The watcher is live; a file landing in data/inbox/ "
            f"triggers real ingestion. Downloads stay in data/downloads/ until staged by hand."
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_file", required=True)
    ap.add_argument("--only", default=None, help="comma-separated institution_ids to restrict to")
    ap.add_argument("--dest", default="data/downloads")
    args = ap.parse_args()

    dest = Path(args.dest)
    _refuse_if_inside_inbox(dest)
    dest.mkdir(parents=True, exist_ok=True)

    discovery_path = Path(args.from_file)
    data = json.loads(discovery_path.read_text(encoding="utf-8"))
    source_name = data["source"]
    year = data["year"]
    source = _SOURCES[source_name]()

    only = set(args.only.split(",")) if args.only else None

    fetched: list[str] = []
    skipped: list[str] = []
    for record in data["entries"]:
        if record["status"] != "MAPPED":
            continue
        institution_id = record["institution_id"]
        if only is not None and institution_id not in only:
            continue

        entry = DiscoveredProspectus(
            institution_id=record["institution_id"],
            display_name=record["display_name"],
            academic_year=record["academic_year"],
            detail_url=record["detail_url"],
            source_id=record["source_id"],
            multi_institution=record["multi_institution"],
        )

        pdf_url = source.resolve_pdf_url(entry)
        if pdf_url is None:
            print(f"  {institution_id}: could not resolve a PDF link on {entry.detail_url} -- skipping")
            skipped.append(institution_id)
            continue

        pdf_path = dest / f"{institution_id}_{year}.pdf"
        session = new_session()
        try:
            byte_count = download_pdf(session, pdf_url, pdf_path)
        except NotAPdfError as exc:
            print(f"  {institution_id}: {exc} -- skipping")
            skipped.append(institution_id)
            continue

        sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        sidecar = {
            "institution_id": institution_id,
            "academic_year": year,
            "source": source_name,
            "source_url": pdf_url,
            "detail_url": entry.detail_url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "sha256": sha256,
            "byte_size": byte_count,
        }
        sidecar_path = dest / f"{institution_id}_{year}.json"
        sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        print(f"  {institution_id}: {byte_count:,} bytes -> {pdf_path}")
        fetched.append(institution_id)

    print(f"\nfetched {len(fetched)}, skipped {len(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
