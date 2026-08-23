"""extract/institutions/uj_overlay.json is HAND-CORRECTED FACTS, not
extraction logic (phase 8.5 step 5) -- an undocumented correction is
indistinguishable from a bug, so every entry must carry a non-empty
source and note. This is a standing test per the spec, not a one-off
check."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from methods.coordinate import _load_overlay  # noqa: E402

_OVERLAY_PATH = ROOT / "extract" / "institutions" / "uj_overlay.json"


def test_overlay_file_is_valid_json() -> None:
    json.loads(_OVERLAY_PATH.read_text(encoding="utf-8"))  # must not raise


def test_every_overlay_entry_has_non_empty_source_and_note() -> None:
    overlay = _load_overlay()
    assert overlay  # not vacuously true
    for code, entry in overlay.items():
        assert entry.get("source"), f"{code}: missing/empty source"
        assert entry.get("note"), f"{code}: missing/empty note"


def test_every_overlay_entry_has_a_non_empty_patch() -> None:
    overlay = _load_overlay()
    for code, entry in overlay.items():
        assert entry.get("patch"), f"{code}: empty patch -- a no-op overlay entry"


def test_known_hard_case_codes_are_present() -> None:
    # Spot-check a few of the reference script's own named corrections
    # survived the JSON port intact.
    overlay = _load_overlay()
    for code in ("B34HRQ", "B34PKQ", "B34PSQ", "B2P82Q"):
        assert code in overlay


def test_b2p82q_merges_both_corrections_from_the_reference_scripts_dict_collision() -> None:
    # The reference script's Python OVERLAY dict defines "B2P82Q" twice
    # (a plain correction under "corrections", then again under "Physical
    # Sciences footnotes" with a _cond patch) -- ordinary dict-literal key
    # collision means the second silently wins at runtime, dropping the
    # first. Both facts are independently true and were merged into one
    # entry when porting to JSON; this pins that fix in place.
    overlay = _load_overlay()
    patch = overlay["B2P82Q"]["patch"]
    assert patch["minimum_aps"] == 31
    assert "physical_science" in patch["requirements"]["conditions"]
