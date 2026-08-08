"""Folder watcher / ingestion entry point for the prospectus pipeline.

Dropping a PDF at data/inbox/{institution_id}/{year}/*.pdf is the entire
user action; this module notices it, hashes it for idempotency, resolves
the institution against the existing institutions table (stubbing and
halting for unknown ones rather than guessing layout parameters), uploads
to R2, and hands off to pipeline.run() for classification and (in later
sub-phases) extraction.

Content is deduplicated globally by sha256, not per institution/year: if
the exact same bytes are ever dropped under two different paths, the
second drop is treated as already-processed and skipped -- intentional,
not a bug.
"""

import argparse
import hashlib
import os
import re
import sys
import time
import uuid
from pathlib import Path

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402
import storage  # noqa: E402

load_dotenv()

# {institution_id}/{year}/{filename}.pdf, exactly three segments relative
# to the inbox root.
_PATH_RE = re.compile(r"^(?P<institution_id>[^/\\]+)[/\\](?P<year>\d{4})[/\\][^/\\]+\.pdf$", re.IGNORECASE)

_UNCONFIGURED = "unconfigured"


class MalformedInboxPath(ValueError):
    pass


def parse_inbox_path(path: Path, inbox_root: Path) -> tuple[str, int]:
    """Returns (institution_id, year). Raises MalformedInboxPath with a
    clear message if the path doesn't match {institution_id}/{year}/*.pdf."""
    try:
        rel = path.relative_to(inbox_root)
    except ValueError as exc:
        raise MalformedInboxPath(f"{path} is not under inbox root {inbox_root}") from exc
    match = _PATH_RE.match(str(rel).replace("\\", "/"))
    if not match:
        raise MalformedInboxPath(
            f"expected {{institution_id}}/{{year}}/*.pdf under {inbox_root}, got '{rel}'"
        )
    return match.group("institution_id"), int(match.group("year"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ingest_file(path: Path, inbox_root: Path, conn: psycopg.Connection) -> None:
    institution_id, year = parse_inbox_path(path, inbox_root)
    content_hash = sha256_file(path)

    with conn.cursor() as cur:
        cur.execute("select 1 from ingestions where content_sha256 = %s", (content_hash,))
        if cur.fetchone() is not None:
            return  # already processed, content-addressed -- not path-addressed

        cur.execute("select scoring_strategy from institutions where id = %s", (institution_id,))
        row = cur.fetchone()
        needs_profile = row is None or row[0] == _UNCONFIGURED

        if needs_profile:
            cur.execute(
                """insert into institutions (id, name, scoring_strategy, scoring_config)
                   values (%s, %s, %s, '{}') on conflict (id) do nothing""",
                (institution_id, institution_id.upper(), _UNCONFIGURED),
            )
            cur.execute(
                """insert into ingestions
                     (institution_id, academic_year, source_filename, content_sha256, status)
                   values (%s, %s, %s, %s, 'needs_profile')""",
                (institution_id, year, path.name, content_hash),
            )
            conn.commit()
            return

        ingestion_id = str(uuid.uuid4())
        cur.execute(
            """insert into ingestions
                 (id, institution_id, academic_year, source_filename, content_sha256, status)
               values (%s, %s, %s, %s, %s, 'pending')""",
            (ingestion_id, institution_id, year, path.name, content_hash),
        )
        conn.commit()

    try:
        r2_key = storage.upload_prospectus(institution_id, year, path)
        with conn.cursor() as cur:
            cur.execute(
                "update ingestions set r2_key = %s, updated_at = now() where id = %s",
                (r2_key, ingestion_id),
            )
        conn.commit()
        pipeline.run(ingestion_id, path, conn)
    except Exception as exc:  # noqa: BLE001 -- must not kill the poll loop for other files
        with conn.cursor() as cur:
            cur.execute(
                "update ingestions set status = 'failed', error = %s, updated_at = now() where id = %s",
                (str(exc), ingestion_id),
            )
        conn.commit()


def run_once(inbox_root: Path, conn: psycopg.Connection) -> list[Path]:
    processed = []
    for path in sorted(inbox_root.rglob("*.pdf")):
        try:
            ingest_file(path, inbox_root, conn)
        except MalformedInboxPath as exc:
            print(f"skipping {path}: {exc}")
            continue
        processed.append(path)
    return processed


def main() -> int:
    ap = argparse.ArgumentParser(prog="watch-inbox")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll-seconds", type=float, default=5)
    ap.add_argument("--inbox", default="data/inbox")
    args = ap.parse_args()

    inbox_root = Path(args.inbox)
    inbox_root.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        if args.once:
            run_once(inbox_root, conn)
            return 0
        print(f"watching {inbox_root} (ctrl+C to stop)")
        try:
            while True:
                run_once(inbox_root, conn)
                time.sleep(args.poll_seconds)
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
