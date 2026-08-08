import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validate_data import validate  # noqa: E402


def test_validate_rejects_empty_programmes_list() -> None:
    errs = validate({"institutions": [], "programmes": []})
    assert errs
    assert any("empty" in e.lower() for e in errs)


def test_validate_cli_exits_1_on_empty_dataset(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.json"
    empty_file.write_text('{"institutions": [], "programmes": []}', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_data.py"), str(empty_file)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 1
    assert "0 programmes" not in result.stdout.split("\n")[0]  # not the old silent-pass message


@pytest.mark.db
def test_export_refuses_below_min_records(tmp_path: Path) -> None:
    out_file = tmp_path / "programmes.json"
    result = subprocess.run(
        [
            sys.executable, str(ROOT / "scripts" / "export_data.py"),
            "--years", "2027",
            "--out", str(out_file),
            "--min-records", "999999",
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 1
    assert "refusing to export" in result.stdout
    assert not out_file.exists()
