"""Shared seed-directory discovery/loading. Not a CLI entrypoint."""

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def programme_files() -> list[Path]:
    return sorted((ROOT / "seeds").rglob("*/*.json"))


def institutions_file() -> Path:
    return ROOT / "seeds" / "institutions.json"


def load() -> dict:
    return load_with_sources()[0]


def load_with_sources() -> tuple[dict, dict[tuple[str, str], Path]]:
    institutions = json.loads(institutions_file().read_text(encoding="utf-8"))
    programmes: list[dict] = []
    sources: dict[tuple[str, str], Path] = {}
    for f in programme_files():
        for p in json.loads(f.read_text(encoding="utf-8")):
            programmes.append(p)
            sources[(p["institution_id"], p["qualification_code"])] = f
    return {"institutions": institutions, "programmes": programmes}, sources


def locate_line(file: Path, qualification_code: str) -> int:
    text = file.read_text(encoding="utf-8")
    idx = text.find(f'"qualification_code": "{qualification_code}"')
    return text.count("\n", 0, idx) + 1 if idx != -1 else 1
