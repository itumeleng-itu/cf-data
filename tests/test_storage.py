"""Pure unit tests for extract/storage.py against a hand-rolled fake S3
client -- no moto, no real R2 credentials needed. Covers key formatting
and the skip-if-unchanged upload logic; the real boto3/R2 wiring itself
is untested here (no R2 credentials exist in this environment yet)."""

import sys
from pathlib import Path

from botocore.exceptions import ClientError

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from storage import signed_url, upload_page_render, upload_prospectus  # noqa: E402


class FakeS3Client:
    """Stateful, not just pre-seeded: put_object actually records metadata
    into `existing`, so head_object reflects what was really uploaded --
    the same way real R2 does. This is deliberate: a fake that only ever
    returns a hand-configured head_object response can't catch a real bug
    like "put_object forgot to attach the sha256 metadata it computed" --
    that class of bug only showed up against real R2 once, and this
    statefulness is what makes the fast unit tests catch it too now."""

    def __init__(self, existing: dict[str, str] | None = None) -> None:
        self.existing = dict(existing or {})  # key -> sha256
        self.put_calls: list[dict] = []
        self.presign_calls: list[dict] = []

    def head_object(self, Bucket: str, Key: str) -> dict:
        if Key not in self.existing:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {"Metadata": {"sha256": self.existing[Key]}}

    def put_object(self, Bucket: str, Key: str, Body: bytes, Metadata: dict[str, str]) -> dict:
        self.put_calls.append({"Bucket": Bucket, "Key": Key, "Body": Body, "Metadata": Metadata})
        self.existing[Key] = Metadata["sha256"]
        return {}

    def generate_presigned_url(self, ClientMethod: str, Params: dict, ExpiresIn: int) -> str:
        self.presign_calls.append({"ClientMethod": ClientMethod, "Params": Params, "ExpiresIn": ExpiresIn})
        return f"https://fake-r2.example/{Params['Key']}?expires={ExpiresIn}"


def test_upload_prospectus_key_format(tmp_path: Path) -> None:
    pdf = tmp_path / "prospectus.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    client = FakeS3Client()
    key = upload_prospectus("uj", 2027, pdf, client=client, bucket="test-bucket")
    assert key == "uj/2027/prospectus.pdf"


def test_upload_page_render_key_format() -> None:
    client = FakeS3Client()
    key = upload_page_render("uj", 2027, 7, b"fake png bytes", client=client, bucket="test-bucket")
    assert key == "uj/2027/pages/007.png"


def test_upload_skipped_when_key_exists_with_matching_hash(tmp_path: Path) -> None:
    pdf = tmp_path / "prospectus.pdf"
    content = b"%PDF-1.4 fake content"
    pdf.write_bytes(content)
    import hashlib
    digest = hashlib.sha256(content).hexdigest()

    client = FakeS3Client(existing={"uj/2027/prospectus.pdf": digest})
    upload_prospectus("uj", 2027, pdf, client=client, bucket="test-bucket")
    assert client.put_calls == []


def test_upload_proceeds_when_key_missing(tmp_path: Path) -> None:
    pdf = tmp_path / "prospectus.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    client = FakeS3Client()
    upload_prospectus("uj", 2027, pdf, client=client, bucket="test-bucket")
    assert len(client.put_calls) == 1
    assert client.put_calls[0]["Key"] == "uj/2027/prospectus.pdf"


def test_upload_proceeds_when_hash_differs(tmp_path: Path) -> None:
    pdf = tmp_path / "prospectus.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")
    client = FakeS3Client(existing={"uj/2027/prospectus.pdf": "not-the-real-hash"})
    upload_prospectus("uj", 2027, pdf, client=client, bucket="test-bucket")
    assert len(client.put_calls) == 1


def test_reupload_of_identical_bytes_is_skipped_end_to_end(tmp_path: Path) -> None:
    # Starts with an EMPTY fake (no pre-seeded metadata) -- exercises the
    # real round trip: first upload must attach sha256 metadata, second
    # upload must read it back and skip. This is what the live-R2 test
    # caught missing; keep it here too so a regression fails fast.
    pdf = tmp_path / "prospectus.pdf"
    pdf.write_bytes(b"%PDF-1.4 identical content")
    client = FakeS3Client()

    upload_prospectus("uj", 2027, pdf, client=client, bucket="test-bucket")
    upload_prospectus("uj", 2027, pdf, client=client, bucket="test-bucket")

    assert len(client.put_calls) == 1


def test_signed_url_passes_expected_params() -> None:
    client = FakeS3Client()
    url = signed_url("uj/2027/prospectus.pdf", expires=1800, client=client, bucket="test-bucket")
    assert client.presign_calls[0]["Params"]["Key"] == "uj/2027/prospectus.pdf"
    assert client.presign_calls[0]["ExpiresIn"] == 1800
    assert url == "https://fake-r2.example/uj/2027/prospectus.pdf?expires=1800"
