import argparse, json, os, sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2027")
    ap.add_argument("--out", default="api/src/app/data/programmes.json")
    ap.add_argument("--verified-only", action="store_true")
    ap.add_argument("--min-records", type=int, default=1)
    args = ap.parse_args()

    years = [int(y) for y in args.years.split(",")]

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        institutions = conn.execute("select * from institutions order by id").fetchall()
        sql = """select institution_id, academic_year, qualification_code, name, faculty,
                        campus, duration_years, extended, requirements, selection_notes,
                        career_text, source_doc, source_page, confidence
                 from programmes
                 where academic_year = any(%s)"""
        params: list = [years]
        if args.verified_only:
            sql += " and confidence = 'verified'"
        sql += " order by institution_id, faculty, qualification_code"
        programmes = conn.execute(sql, params).fetchall()

    if len(programmes) < args.min_records:
        print(
            f"refusing to export {len(programmes)} records "
            f"(expected at least {args.min_records}) — is the database seeded?"
        )
        return 1

    for p in programmes:
        p["duration_years"] = float(p["duration_years"]) if p["duration_years"] else None

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"institutions": institutions, "programmes": programmes},
        indent=2, ensure_ascii=False,
    ), encoding="utf-8")
    print(f"exported {len(programmes)} programmes → {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())