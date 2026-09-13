"""Uploads a source prospectus PDF to R2 and prints the key to put in a
bundle's source.document.

This is what makes provenance real. Every programme record carries a
source_doc and a source_page; unless the document those point at still
exists somewhere, they are a filename and a number, and a learner
disputing a result cannot be answered. With the PDF archived, source_doc
resolves to a document and source_page points at the page that was read.

Uploads are content-addressed by sha256 and skipped when the stored copy
already matches, so re-running it on the same file costs one HEAD and
nothing else.

    uv run python scripts/archive_source.py --institution uj --year 2027 \\
        --pdf data/downloads/uj_2027.pdf

Prints the key (e.g. "uj/2027/prospectus.pdf"). Pass --signed-url to also
print a time-limited link for checking the upload by eye.
"""

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent / "extract"))

from dotenv import load_dotenv  # noqa: E402

from storage import signed_url, upload_prospectus  # noqa: E402

load_dotenv()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--institution", required=True, help="institution_id, e.g. uj")
    ap.add_argument("--year", required=True, type=int, help="academic year the document is for")
    ap.add_argument("--pdf", required=True, type=Path, help="the source PDF to archive")
    ap.add_argument("--signed-url", action="store_true", help="also print a 1-hour signed URL")
    args = ap.parse_args()

    if not args.pdf.exists():
        print(f"no such file: {args.pdf}")
        return 1

    key = upload_prospectus(args.institution, args.year, args.pdf)
    print(key)
    if args.signed_url:
        print(signed_url(key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
