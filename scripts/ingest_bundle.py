"""Ingests a bundle (a .zip of flat per-institution-year JSON files, a
directory of them, or a single bare .json file) into Postgres.

This is the missing entrance to the pipeline: load_seeds.py reads from
seeds/, which someone has to hand-write in tree form first. This script
is the other way in -- an operator transcribes a prospectus into the flat
format (docs/BUNDLE_FORMAT.md), and this turns it into rows.

STAGES, in order. A failure at any stage aborts the WHOLE bundle for that
INSTITUTION (not the whole run -- a zip's other institutions still get
their own chance) before anything is written for it:

  1. UNPACK        zip/directory -> a list of (name, dict) bundle files,
                    in a temp directory that is never the repo.
  2. IDENTIFY       institution.id + academic_year, from the file's own
                    CONTENTS, never the filename. An institution.id this
                    repo doesn't know is rejected with the list it does.
  3. STRUCTURAL     +
  4. CONVERT        validation and flat->tree conversion are one call
                    into scripts/convert_bundle.py's convert_bundle() --
                    see _convert_and_check_strategy's docstring for why
                    these are implemented together rather than as two
                    separate passes.
  5. SEMANTIC       scripts/validate_data.py's validate(), unchanged,
                    reused rather than reimplemented -- this is the exact
                    check seeds/ itself is held to.
  6. DIFF           every converted record classified against whatever
                    is already in Postgres for that institution-year:
                    new / changed (with old->new per field) / removed /
                    unchanged.
  7. PERSIST        (skipped for --dry-run) upsert new/changed records
                    ONLY -- an unchanged record is never even sent to the
                    database, which is what makes re-ingesting the same
                    bundle a true no-op rather than just a no-visible-
                    effect one. confidence is ALWAYS 'extracted' for a
                    written record, even if it was 'verified' before --
                    see _persist_institution's docstring.
  8. REPORT         a markdown file under data/reports/, plus a stdout
                    summary.

--dry-run runs every stage except 7: it still opens a (read-only, from
this script's point of view) connection to compute the stage-6 diff, and
prints the exact report a real run would produce.

WHAT THIS SCRIPT DELIBERATELY DOES NOT DO
------------------------------------------
It never deletes a REMOVED programme (one that exists in Postgres for
this institution-year but not in the bundle). A programme silently
disappearing between bundles is exactly how a learner stops seeing
something they qualify for, and there is no way for a script to tell
"this institution genuinely discontinued a programme" apart from "this
transcription accidentally dropped a row" -- so removals are reported as
loudly as possible and left for a human to act on, never auto-deleted.
Constraint: nothing under api/ changes, and load_seeds.py/export_data.py/
validate_data.py keep working exactly as they do -- this script is
additive, calling into the same convert_bundle.py and validate_data.py
those already use.
"""

import argparse
import decimal
import json
import os
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(ROOT / "api" / "src"))

import convert_bundle  # noqa: E402
from institution_map import INSTITUTIONS as KNOWN_INSTITUTIONS  # noqa: E402
from validate_data import validate  # noqa: E402

from app.scoring import SCORERS  # noqa: E402

load_dotenv()

# Every non-key, non-audit column a bundle can actually change. confidence
# and updated_at are deliberately excluded -- confidence is never bundle-
# controlled (see _persist_institution), and updated_at is a consequence
# of a write, not an input to deciding whether one is needed.
_DIFF_FIELDS = (
    "name", "faculty", "campus", "duration_years", "extended", "requirements",
    "selection_notes", "career_text", "source_doc", "source_page",
    "scoring_override", "scoring_strategy_override", "scoreable",
)


class IngestError(Exception):
    """One institution-year's bundle cannot be ingested at all. Caught per
    file so one bad institution in a multi-institution zip never blocks
    the others."""


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    old: Any
    new: Any


@dataclass(slots=True)
class RecordDiff:
    qualification_code: str
    status: str  # "new" | "changed" | "removed" | "unchanged"
    changes: list[FieldChange] = field(default_factory=list)
    was_verified: bool = False  # only meaningful when status == "changed"


@dataclass(slots=True)
class InstitutionReport:
    source_file: str
    institution_id: str
    academic_year: int | None
    status: str  # "persisted" | "dry_run" | "rejected"
    diffs: list[RecordDiff] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def counts(self) -> dict[str, int]:
        out = {"new": 0, "changed": 0, "removed": 0, "unchanged": 0}
        for d in self.diffs:
            out[d.status] += 1
        return out


# --- stage 1: unpack -----------------------------------------------------

def _reject_unsafe_zip_member(name: str) -> None:
    """A zip is untrusted input. Refuses the WHOLE zip (not just the bad
    entry) on the first sign of path traversal or an absolute path --
    Path.resolve()/relative_to() tricks are exactly how a malicious zip
    escapes an extraction directory ("zip slip"), and there is no
    legitimate bundle that needs a '..' segment or a drive letter."""
    if name.endswith("/"):
        return  # a directory entry, not a file
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized.split("/")[0]:
        raise IngestError(f"unsafe zip entry (absolute path): {name!r}")
    if any(part == ".." for part in normalized.split("/")):
        raise IngestError(f"unsafe zip entry (path traversal): {name!r}")
    if not normalized.split("/")[-1] or "/" in normalized:
        raise IngestError(f"zip entries must be flat, top-level files: {name!r}")
    if not normalized.endswith(".json"):
        raise IngestError(f"zip contains a non-JSON top-level entry: {name!r}")


def _unpack(path: Path, tmp_dir: Path) -> list[Path]:
    """Returns the list of .json files to read, either extracted from a
    zip into tmp_dir (never the repo -- tmp_dir is caller-supplied and
    always a tempfile.TemporaryDirectory) or found directly in a plain
    directory, or the single file itself."""
    if not path.exists():
        raise IngestError(f"no such path: {path}")

    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise IngestError(f"no *.json files at the top level of {path}")
        return files

    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if not names:
                raise IngestError(f"{path}: empty zip")
            for name in names:
                _reject_unsafe_zip_member(name)
            zf.extractall(tmp_dir)
        return sorted(tmp_dir.glob("*.json"))

    if path.suffix == ".json":
        return [path]

    raise IngestError(f"{path}: expected a .zip, a directory, or a .json file")


# --- stage 2/3/4: identify, structural validation, convert ---------------

def _check_known_institution(institution_id: str) -> None:
    if institution_id not in KNOWN_INSTITUTIONS:
        known = ", ".join(sorted(KNOWN_INSTITUTIONS))
        raise IngestError(f"unknown institution.id {institution_id!r}. Known ids: {known}")


def _check_scoring_strategy(strategy: str, warnings: list[str]) -> None:
    """Registered-but-unverified WARNS and still loads -- the UNVERIFIED
    doc in docs/scoring/ is that algorithm's own audit trail, already
    accepted as good enough to ship (see api/src/app/scoring.py's module
    docstring). Unregistered is rejected outright: there is no formula at
    all to compute a score with, which is a different problem than "this
    one hasn't been checked against a prospectus yet."""
    if strategy not in SCORERS:
        known = ", ".join(sorted(SCORERS))
        raise IngestError(f"unknown scoring_strategy {strategy!r}. Registered: {known}")
    doc = ROOT / "docs" / "scoring" / f"{strategy}.md"
    if doc.exists() and "UNVERIFIED" in doc.read_text(encoding="utf-8"):
        warnings.append(
            f"scoring_strategy {strategy!r} has no worked-example test yet "
            f"(see {doc.relative_to(ROOT)}) -- loading anyway, per docs/scoring/'s own audit trail"
        )


def _convert_and_validate(bundle: dict, warnings: list[str]) -> tuple[dict, list[dict]]:
    """Stages 3 (structural) and 4 (convert) as ONE call, deliberately.

    convert_bundle.convert_bundle() already raises BundleError for every
    structural fault stage 3 is asked to catch -- an unknown subject key,
    a level outside 1-7, an unknown minimum_aps variant key, a missing
    required field (see convert_record's own guards). Re-implementing
    those checks as a separate pre-pass here would be exactly the
    "reimplement tree-building" this project's constraints forbid: the
    structural rules ARE the tree-building rules, they're just enforced
    on the way in instead of checked afterwards.

    The one structural check that genuinely lives outside convert_bundle
    (which has no idea what SCORERS contains) is the scoring_strategy
    check, run separately by the caller before this."""
    try:
        return convert_bundle.convert_bundle(bundle)
    except (convert_bundle.BundleError, KeyError) as exc:
        raise IngestError(str(exc)) from exc


# --- stage 6: diff ---------------------------------------------------------

def _normalise(value: Any) -> Any:
    """Postgres numeric -> Decimal, JSON -> float; normalise before
    comparing so a real value doesn't get flagged as CHANGED purely
    because of its Python type."""
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


def _diff_record(new: dict, existing: dict | None) -> RecordDiff:
    code = new["qualification_code"]
    if existing is None:
        return RecordDiff(code, "new")

    changes = [
        FieldChange(f, _normalise(existing.get(f)), new.get(f))
        for f in _DIFF_FIELDS
        if _normalise(existing.get(f)) != new.get(f)
    ]
    if not changes:
        return RecordDiff(code, "unchanged")
    return RecordDiff(code, "changed", changes, was_verified=existing.get("confidence") == "verified")


def _fetch_existing(conn: psycopg.Connection, institution_id: str, academic_year: int) -> dict[str, dict]:
    rows = conn.execute(
        "select * from programmes where institution_id = %s and academic_year = %s",
        (institution_id, academic_year),
    ).fetchall()
    return {r["qualification_code"]: r for r in rows}


def _diff_institution(new_records: list[dict], existing_by_code: dict[str, dict]) -> list[RecordDiff]:
    diffs = [_diff_record(r, existing_by_code.get(r["qualification_code"])) for r in new_records]
    new_codes = {r["qualification_code"] for r in new_records}
    for code in existing_by_code:
        if code not in new_codes:
            diffs.append(RecordDiff(code, "removed"))
    return diffs


# --- stage 7: persist -------------------------------------------------------

def _persist_institution(conn: psycopg.Connection, institution: dict, records: list[dict], diffs: list[RecordDiff]) -> None:
    """Writes ONLY new/changed records, in one transaction per
    institution (a mid-institution failure rolls back that institution
    alone, never leaving it half-loaded). confidence is unconditionally
    'extracted' here -- constraint: nothing ingestion writes or changes
    is ever 'verified'. Only a human, editing the row directly after
    reading the report, can set that. A record that WAS 'verified' and
    IS changed by this bundle therefore drops back to 'extracted'
    automatically -- RecordDiff.was_verified is what the report uses to
    call that out. An UNCHANGED record is never sent to the database at
    all, so its confidence (verified or not) is left completely alone."""
    by_code = {r["qualification_code"]: r for r in records}
    to_write = [d for d in diffs if d.status in ("new", "changed")]

    with conn.transaction():
        conn.execute(
            """insert into institutions (id, name, scoring_strategy, scoring_config)
               values (%s, %s, %s, %s)
               on conflict (id) do update set
                 name = excluded.name,
                 scoring_strategy = excluded.scoring_strategy,
                 scoring_config = excluded.scoring_config""",
            (institution["id"], institution["name"], institution["scoring_strategy"],
             json.dumps(institution.get("scoring_config") or {})),
        )
        for d in to_write:
            p = by_code[d.qualification_code]
            conn.execute(
                """insert into programmes (
                     institution_id, academic_year, qualification_code, name, faculty,
                     campus, duration_years, extended, requirements, selection_notes,
                     career_text, source_doc, source_page, confidence,
                     scoring_override, scoring_strategy_override, scoreable, updated_at)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'extracted',%s,%s,%s, now())
                   on conflict (institution_id, academic_year, qualification_code)
                   do update set
                     name = excluded.name, faculty = excluded.faculty,
                     campus = excluded.campus, duration_years = excluded.duration_years,
                     extended = excluded.extended, requirements = excluded.requirements,
                     selection_notes = excluded.selection_notes,
                     career_text = excluded.career_text,
                     source_doc = excluded.source_doc, source_page = excluded.source_page,
                     confidence = 'extracted',
                     scoring_override = excluded.scoring_override,
                     scoring_strategy_override = excluded.scoring_strategy_override,
                     scoreable = excluded.scoreable, updated_at = now()""",
                (
                    p["institution_id"], p["academic_year"], p["qualification_code"],
                    p["name"], p.get("faculty"), p.get("campus", []),
                    p.get("duration_years"), p.get("extended", False),
                    json.dumps(p["requirements"]), p.get("selection_notes", []),
                    p.get("career_text"), p.get("source_doc"), p.get("source_page"),
                    json.dumps(p["scoring_override"]) if p.get("scoring_override") else None,
                    p.get("scoring_strategy_override"), p.get("scoreable", True),
                ),
            )


# --- orchestration ----------------------------------------------------------

def ingest_one(name: str, bundle: dict, conn: psycopg.Connection | None, dry_run: bool) -> InstitutionReport:
    """Runs every stage for one institution-year bundle file. conn is
    None only when there is genuinely no database to diff/persist
    against -- ingest_bundle.py's own CLI always supplies one, even for
    --dry-run (the diff stage needs it); a None conn is for callers (like
    a future offline preview) that accept a diff-free report."""
    warnings: list[str] = []
    institution = bundle.get("institution") or {}
    institution_id = institution.get("id")
    academic_year = bundle.get("academic_year")

    try:
        if not institution_id:
            raise IngestError("institution.id is required")
        _check_known_institution(institution_id)
        if not institution.get("name"):
            raise IngestError("institution.name is required")
        if not academic_year:
            raise IngestError("academic_year is required")
        strategy = institution.get("scoring_strategy")
        if not strategy:
            raise IngestError("institution.scoring_strategy is required")
        _check_scoring_strategy(strategy, warnings)

        institution_out, records = _convert_and_validate(bundle, warnings)

        errs = validate({"institutions": [institution_out], "programmes": records})
        if errs:
            raise IngestError(f"{len(errs)} semantic validation error(s):\n" + "\n".join(f"  {e}" for e in errs))

    except IngestError as exc:
        return InstitutionReport(name, institution_id or "?", academic_year, "rejected", error=str(exc))

    existing = _fetch_existing(conn, institution_id, academic_year) if conn is not None else {}
    diffs = _diff_institution(records, existing)

    if dry_run or conn is None:
        return InstitutionReport(name, institution_id, academic_year, "dry_run", diffs, warnings)

    _persist_institution(conn, institution_out, records, diffs)
    return InstitutionReport(name, institution_id, academic_year, "persisted", diffs, warnings)


def _render_report(reports: list[InstitutionReport], dry_run: bool) -> str:
    lines = [
        f"# Bundle ingestion report ({'dry run' if dry_run else 'persisted'})",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
    ]
    for r in reports:
        lines.append(f"## {r.source_file} -- {r.institution_id} {r.academic_year or ''}".rstrip())
        lines.append(f"Status: **{r.status}**")
        if r.error:
            lines.append("")
            lines.append(f"**REJECTED:** {r.error}")
            lines.append("")
            continue

        counts = r.counts()
        lines.append(
            f"Records in bundle: {sum(1 for d in r.diffs if d.status != 'removed')} "
            f"-- new {counts['new']}, changed {counts['changed']}, "
            f"unchanged {counts['unchanged']}, removed {counts['removed']}"
        )
        if r.warnings:
            lines.append("")
            for w in r.warnings:
                lines.append(f"⚠️  {w}")

        downgraded = [d for d in r.diffs if d.status == "changed" and d.was_verified]
        if downgraded:
            lines.append("")
            lines.append(
                f"**{len(downgraded)} previously-verified record(s) changed and dropped back "
                f"to confidence='extracted' -- a human verified the OLD value and has not seen "
                f"the new one:**"
            )
            for d in downgraded:
                lines.append(f"- `{d.qualification_code}`")

        changed = [d for d in r.diffs if d.status == "changed"]
        if changed:
            lines.append("")
            lines.append("### Changed")
            for d in changed:
                lines.append(f"- `{d.qualification_code}`" + (" (was verified)" if d.was_verified else ""))
                for c in d.changes:
                    lines.append(f"  - `{c.field}`: {c.old!r} -> {c.new!r}")

        removed = [d for d in r.diffs if d.status == "removed"]
        if removed:
            lines.append("")
            lines.append(
                "### REMOVED -- present in Postgres, absent from this bundle. "
                "NOT deleted automatically; a learner stops seeing these if that's wrong."
            )
            for d in removed:
                lines.append(f"- `{d.qualification_code}`")

        new = [d for d in r.diffs if d.status == "new"]
        if new:
            lines.append("")
            lines.append("### New")
            for d in new:
                lines.append(f"- `{d.qualification_code}`")

        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("bundle", type=Path, help="a .zip, a directory, or a single .json bundle file")
    ap.add_argument("--dry-run", action="store_true", help="run every stage but stage 7 (persist); writes nothing")
    ap.add_argument("--only", default=None, help="comma-separated institution_ids to restrict to")
    ap.add_argument("--year", type=int, default=None, help="restrict to bundle files for this academic_year")
    ap.add_argument("--report", type=Path, default=None, help="where to write the markdown report")
    args = ap.parse_args()

    only = set(args.only.split(",")) if args.only else None

    with tempfile.TemporaryDirectory(prefix="ingest_bundle_") as tmp:
        try:
            files = _unpack(args.bundle, Path(tmp))
        except IngestError as exc:
            print(f"✗ {exc}")
            return 1

        bundles: list[tuple[str, dict]] = []
        for f in sorted(files):
            try:
                bundles.append((f.name, json.loads(f.read_text(encoding="utf-8"))))
            except json.JSONDecodeError as exc:
                print(f"✗ {f.name}: not valid JSON ({exc})")
                return 1

        reports: list[InstitutionReport] = []
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
            for name, bundle in bundles:
                institution_id = (bundle.get("institution") or {}).get("id")
                if only is not None and institution_id not in only:
                    continue
                if args.year is not None and bundle.get("academic_year") != args.year:
                    continue
                reports.append(ingest_one(name, bundle, conn, args.dry_run))
            if not args.dry_run:
                conn.commit()

    report_text = _render_report(reports, args.dry_run)
    report_path = args.report
    if report_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_path = ROOT / "data" / "reports" / f"ingest_{timestamp}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    print(report_text)
    print(f"\n(report written to {report_path})")

    return 1 if any(r.status == "rejected" for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
