"""Extraction pipeline. Sub-phase 8.1 left this as a no-op seam; sub-phase
8.2 fills in the classification stage only -- load the PDF, classify every
page via extract.classify, persist per-page classification and signal
values, and mark the ingestion ready for human review. Extraction proper,
reconciliation, diffing, and corroboration (8.3 onward) still start from
here; this sub-phase ends at classification.
"""

import json
from pathlib import Path

import psycopg

import classify
import profiles


def run(ingestion_id: str, pdf_path: Path, conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("select institution_id from ingestions where id = %s", (ingestion_id,))
        row = cur.fetchone()
        institution_id = row[0]

        cur.execute(
            "update ingestions set status = 'classifying', updated_at = now() where id = %s",
            (ingestion_id,),
        )
    conn.commit()

    profile = profiles.get_profile(institution_id)
    classifications, signal_report = classify.classify_pages(pdf_path, profile)
    table_pages = sorted(
        page for page, cls in classifications.items()
        if cls == classify.PageClass.PROGRAMME_TABLE
    )

    with conn.cursor() as cur:
        cur.execute(
            """update ingestions
                 set status = 'review_ready',
                     page_count = %s,
                     table_pages = %s,
                     stats = %s,
                     updated_at = now()
               where id = %s""",
            (len(classifications), table_pages, json.dumps(signal_report), ingestion_id),
        )
    conn.commit()
