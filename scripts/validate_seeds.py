"""Validate seeds/ directly, no export step needed. Reports offending file:line.

Run standalone (`uv run python scripts/validate_seeds.py`) or via
scripts/watch_seeds.py for a live authoring loop.
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "api" / "src"))

from seed_loader import load_with_sources, locate_line  # noqa: E402
from validate_data import validate  # noqa: E402


def main() -> int:
    data, sources = load_with_sources()
    errs = validate(data)

    if not errs:
        n_files = len({f for f in sources.values()})
        print(f"✓ {len(data['programmes'])} programmes valid across {n_files} files")
        return 0

    for e in errs:
        tag, _, msg = e.partition(": ")
        institution_id, _, rest = tag.partition("/")
        code = rest.split(".", 1)[0]
        file = sources.get((institution_id, code))
        if file is None:
            print(f"?: {e}")
            continue
        line = locate_line(file, code)
        print(f"{file}:{line}: {msg}")
    print(f"✗ {len(errs)} errors")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
