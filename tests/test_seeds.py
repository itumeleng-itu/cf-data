import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "api" / "src"))

from seed_loader import load_with_sources  # noqa: E402
from validate_data import validate  # noqa: E402


def test_all_seed_programmes_validate() -> None:
    data, _sources = load_with_sources()
    errs = validate(data)
    assert errs == [], "\n".join(errs)


def test_every_programme_traces_to_a_seed_file() -> None:
    data, sources = load_with_sources()
    for p in data["programmes"]:
        assert (p["institution_id"], p["qualification_code"]) in sources
