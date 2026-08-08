"""Docker packaging smoke test.

Catches exactly the failure mode a stale COPY path produces: an image that
builds cleanly, a container that reports healthy, and an API that quietly
serves zero programmes. Unit tests can't catch this -- they never go
through the Dockerfile. Marked @pytest.mark.docker so it can be skipped
with -m "not docker" where Docker isn't available (e.g. CI runners).
"""

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from seed_loader import load  # noqa: E402

pytestmark = pytest.mark.docker

_SUFFIX = uuid.uuid4().hex[:8]
IMAGE_TAG = f"coursefind-api-smoketest:{_SUFFIX}"
CONTAINER_NAME = f"coursefind-api-smoketest-{_SUFFIX}"
HOST_PORT = 18123
DATA_VERSION = "smoketest-2027.1"
EXPECTED_PROGRAMME_COUNT = 29
EXPECTED_QUALIFYING_COUNT = 28

CANONICAL_MARKS = [
    {"subject": "english_hl", "percentage": 87},
    {"subject": "afrikaans_fal", "percentage": 85},
    {"subject": "mathematics", "percentage": 88},
    {"subject": "life_orientation", "percentage": 88},
    {"subject": "geography", "percentage": 92},
    {"subject": "life_sciences", "percentage": 87},
    {"subject": "physical_sciences", "percentage": 73},
]


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **kwargs)


def test_docker_image_serves_real_data() -> None:
    # The Dockerfile expects api/src/app/data/programmes.json to already
    # exist in the build context (normally produced by the CI export
    # step). Stage a fresh export from the current seeds there for the
    # duration of this test, then restore whatever was there before (or
    # remove it if nothing was).
    data = load()
    for p in data["programmes"]:
        if p.get("duration_years") is not None:
            p["duration_years"] = float(p["duration_years"])
    assert len(data["programmes"]) == EXPECTED_PROGRAMME_COUNT, (
        "seed count drifted -- update EXPECTED_PROGRAMME_COUNT/EXPECTED_QUALIFYING_COUNT "
        "deliberately if this is an intentional consequence of new seed data"
    )

    real_data_path = ROOT / "api" / "src" / "app" / "data" / "programmes.json"
    backup_path = real_data_path.with_suffix(".json.smoketest-backup")
    had_existing = real_data_path.exists()
    if had_existing:
        real_data_path.replace(backup_path)
    real_data_path.parent.mkdir(parents=True, exist_ok=True)
    real_data_path.write_text(json.dumps(data), encoding="utf-8")

    built = False
    container_started = False
    try:
        build = _run(
            [
                "docker", "build",
                "-f", "api/Dockerfile",
                "-t", IMAGE_TAG,
                "--build-arg", f"DATA_VERSION={DATA_VERSION}",
                "--provenance=false", "--sbom=false",
                ".",
            ],
            cwd=ROOT, timeout=300,
        )
        assert build.returncode == 0, build.stdout + build.stderr
        built = True

        run = _run(
            ["docker", "run", "-d", "--name", CONTAINER_NAME, "-p", f"{HOST_PORT}:8000", IMAGE_TAG],
            timeout=30,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        container_started = True

        base = f"http://localhost:{HOST_PORT}"
        deadline = time.monotonic() + 30
        ready = False
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base}/readyz", timeout=1).status_code == 200:
                    ready = True
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.5)
        if not ready:
            logs = _run(["docker", "logs", CONTAINER_NAME])
            assert ready, f"container did not become ready within 30s\n{logs.stdout}\n{logs.stderr}"

        meta = httpx.get(f"{base}/v1/meta", timeout=5).json()
        assert meta["programme_count"] == EXPECTED_PROGRAMME_COUNT
        assert meta["data_version"] == DATA_VERSION

        qualify = httpx.post(f"{base}/v1/qualify", json={"subjects": CANONICAL_MARKS}, timeout=5).json()
        assert len(qualify["qualified"]) == EXPECTED_QUALIFYING_COUNT
    finally:
        if container_started:
            _run(["docker", "rm", "-f", CONTAINER_NAME])
        if built:
            _run(["docker", "rmi", "-f", IMAGE_TAG])
        real_data_path.unlink(missing_ok=True)
        if had_existing:
            backup_path.replace(real_data_path)
