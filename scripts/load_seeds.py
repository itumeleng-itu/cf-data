import json, os, sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from seed_loader import load  # noqa: E402

load_dotenv()


def main() -> int:
    data = load()
    institutions = data["institutions"]
    programmes = data["programmes"]

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        for i in institutions:
            cur.execute(
                """insert into institutions (id, name, scoring_strategy, scoring_config)
                   values (%s, %s, %s, %s)
                   on conflict (id) do update set
                     name = excluded.name,
                     scoring_strategy = excluded.scoring_strategy,
                     scoring_config = excluded.scoring_config""",
                (i["id"], i["name"], i["scoring_strategy"], json.dumps(i["scoring_config"])),
            )

        for p in programmes:
            cur.execute(
                """insert into programmes (
                     institution_id, academic_year, qualification_code, name, faculty,
                     campus, duration_years, extended, requirements, selection_notes,
                     career_text, source_doc, source_page, confidence, updated_at)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                   on conflict (institution_id, academic_year, qualification_code)
                   do update set
                     name = excluded.name, faculty = excluded.faculty,
                     campus = excluded.campus, duration_years = excluded.duration_years,
                     extended = excluded.extended, requirements = excluded.requirements,
                     selection_notes = excluded.selection_notes,
                     career_text = excluded.career_text,
                     source_doc = excluded.source_doc, source_page = excluded.source_page,
                     confidence = excluded.confidence, updated_at = now()""",
                (
                    p["institution_id"], p["academic_year"], p["qualification_code"],
                    p["name"], p.get("faculty"), p.get("campus", []),
                    p.get("duration_years"), p.get("extended", False),
                    json.dumps(p["requirements"]), p.get("selection_notes", []),
                    p.get("career_text"), p.get("source_doc"), p.get("source_page"),
                    p.get("confidence", "extracted"),
                ),
            )
        conn.commit()

    print(f"loaded {len(institutions)} institutions, {len(programmes)} programmes")
    return 0


if __name__ == "__main__":
    sys.exit(main())