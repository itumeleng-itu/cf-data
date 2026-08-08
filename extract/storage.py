"""Cloudflare R2 storage (S3-compatible) for prospectus PDFs and rendered
page images. Extraction-only dependency (boto3) -- never imported from
api/, never enters the production image (see Phase 8 architecture
decision #6).

The real R2 client is constructed lazily, only when a call actually needs
one, so importing this module never requires R2 credentials to be set --
useful for tests, which inject a fake client instead.
"""

import hashlib
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


class S3Client(Protocol):
    def head_object(self, Bucket: str, Key: str) -> dict: ...
    def put_object(self, Bucket: str, Key: str, Body: bytes, Metadata: dict[str, str]) -> dict: ...
    def generate_presigned_url(self, ClientMethod: str, Params: dict, ExpiresIn: int) -> str: ...


_client: S3Client | None = None


def _default_client() -> S3Client:
    global _client
    if _client is None:
        import os

        endpoint = os.environ.get("R2_ENDPOINT")
        if not endpoint:
            endpoint = f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
        _client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            # R2 has no real regions -- "auto" is required, boto3 errors without it.
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                # Newer boto3 sends x-amz-checksum-* headers by default; R2
                # rejects them (400) on some operations.
                request_checksum_calculation="when_required",
            ),
        )
    return _client


def _bucket() -> str:
    import os

    return os.environ["R2_BUCKET"]


def _put_if_new(client: S3Client, bucket: str, key: str, body: bytes) -> str:
    digest = hashlib.sha256(body).hexdigest()
    try:
        existing = client.head_object(Bucket=bucket, Key=key)
        if existing.get("Metadata", {}).get("sha256") == digest:
            return key
    except ClientError:
        pass  # not found (or any other head error) -- fall through to upload
    client.put_object(Bucket=bucket, Key=key, Body=body, Metadata={"sha256": digest})
    return key


def upload_prospectus(
    institution: str, year: int, path: Path, client: S3Client | None = None, bucket: str | None = None,
) -> str:
    client = client or _default_client()
    bucket = bucket or _bucket()
    key = f"{institution}/{year}/prospectus.pdf"
    return _put_if_new(client, bucket, key, path.read_bytes())


def upload_page_render(
    institution: str, year: int, page: int, png: bytes,
    client: S3Client | None = None, bucket: str | None = None,
) -> str:
    client = client or _default_client()
    bucket = bucket or _bucket()
    key = f"{institution}/{year}/pages/{page:03d}.png"
    return _put_if_new(client, bucket, key, png)


def signed_url(
    key: str, expires: int = 3600, client: S3Client | None = None, bucket: str | None = None,
) -> str:
    client = client or _default_client()
    bucket = bucket or _bucket()
    return client.generate_presigned_url(
        ClientMethod="get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires,
    )
