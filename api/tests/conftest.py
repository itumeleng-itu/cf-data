import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from seed_loader import load  # noqa: E402


@pytest.fixture
def programmes_data_file(tmp_path: Path) -> Path:
    data = load()
    for p in data["programmes"]:
        if p.get("duration_years") is not None:
            p["duration_years"] = float(p["duration_years"])
    path = tmp_path / "programmes.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, programmes_data_file: Path) -> Iterator[TestClient]:
    from app.main import app

    monkeypatch.setenv("PROGRAMMES_DATA_PATH", str(programmes_data_file))
    monkeypatch.setenv("DATA_VERSION", "2027.1-test")
    with TestClient(app) as c:
        yield c
