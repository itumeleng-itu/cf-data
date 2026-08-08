"""Verifies extract/storage.py against real Cloudflare R2. Marked
@pytest.mark.r2 and skipped when R2 credentials aren't set (both via the
marker, for `-m "not r2"` exclusion, and via skipif, so the plain default
run -- no -m flag at all -- also skips cleanly rather than failing)."""

import os
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from storage import _default_client, signed_url, upload_page_render, upload_prospectus  # noqa: E402

load_dotenv()

pytestmark = [
    pytest.mark.r2,
    pytest.mark.skipif(not os.environ.get("R2_ACCOUNT_ID"), reason="R2 credentials not set in .env"),
]

_SENTINEL_INSTITUTION = f"zztest{uuid.uuid4().hex[:8]}"
_YEAR = 2027


def _bucket() -> str:
    return os.environ["R2_BUCKET"]


def test_upload_prospectus_reupload_skip_and_signed_url_fetch(tmp_path: Path) -> None:
    client = _default_client()
    bucket = _bucket()

    pdf = tmp_path / "prospectus.pdf"
    content = b"%PDF-1.4 real r2 verification content"
    pdf.write_bytes(content)

    prospectus_key = None
    page_key = None
    try:
        # 1. First upload.
        prospectus_key = upload_prospectus(_SENTINEL_INSTITUTION, _YEAR, pdf)
        assert prospectus_key == f"{_SENTINEL_INSTITUTION}/{_YEAR}/prospectus.pdf"

        first_head = client.head_object(Bucket=bucket, Key=prospectus_key)
        first_last_modified = first_head["LastModified"]

        # 2. Re-upload identical bytes -- put_object must be skipped. Real R2
        # has no request-spy, so this is verified indirectly: LastModified
        # only changes if put_object actually ran.
        upload_prospectus(_SENTINEL_INSTITUTION, _YEAR, pdf)
        second_head = client.head_object(Bucket=bucket, Key=prospectus_key)
        assert second_head["LastModified"] == first_last_modified, (
            "object was re-uploaded even though bytes were unchanged -- "
            "the sha256-metadata skip path did not trigger"
        )

        # 3. Page render key formatting.
        page_key = upload_page_render(_SENTINEL_INSTITUTION, _YEAR, 3, b"fake png bytes")
        assert page_key == f"{_SENTINEL_INSTITUTION}/{_YEAR}/pages/003.png"

        # 4. Signed URL -- actually fetch it. This is the check that matters:
        # the review UI depends on signed URLs resolving, and a
        # misconfigured signature version fails exactly here.
        url = signed_url(prospectus_key, expires=300)
        resp = httpx.get(url, timeout=10)
        assert resp.status_code == 200, f"signed URL fetch failed: {resp.status_code} {resp.text[:500]}"
        assert resp.content == content
    finally:
        for key in (prospectus_key, page_key):
            if key is not None:
                client.delete_object(Bucket=bucket, Key=key)

        remaining = client.list_objects_v2(Bucket=bucket, Prefix=_SENTINEL_INSTITUTION)
        assert remaining.get("KeyCount", 0) == 0, (
            f"leftover zztest objects in R2: {[o['Key'] for o in remaining.get('Contents', [])]}"
        )
