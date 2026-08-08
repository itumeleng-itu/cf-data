"""Watch seeds/ for changes and re-validate on every save. Ctrl+C to stop.

Polls mtimes instead of using a filesystem-events library, since no such
dependency was requested and this only needs to feel instant to a human
typing JSON, not to react in microseconds.
"""

import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent))
from validate_seeds import main as run_validate  # noqa: E402

ROOT = Path(__file__).parent.parent
SEEDS = ROOT / "seeds"
POLL_SECONDS = 0.5


def snapshot() -> dict[Path, float]:
    return {f: f.stat().st_mtime for f in SEEDS.rglob("*.json")}


def main() -> int:
    print(f"watching {SEEDS} (ctrl+C to stop)")
    last = snapshot()
    run_validate()
    try:
        while True:
            time.sleep(POLL_SECONDS)
            current = snapshot()
            if current != last:
                last = current
                print("\n--- change detected ---")
                run_validate()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
