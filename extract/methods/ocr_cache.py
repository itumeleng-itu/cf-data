"""Cache bridge between an offline Unlimited-OCR run (GPU-only, see
scripts/run_unlimited_ocr.py) and the live pipeline. textlayer_ocr.py
never calls the OCR model itself -- it only ever reads whatever
scripts/run_unlimited_ocr.py already wrote here, keeping the live
pipeline free of any GPU dependency.
"""

import re
from pathlib import Path

DEFAULT_CACHE_DIR = Path("ocr_cache")

# Pattern taken from the Unlimited-OCR paper's own <|det|> position-anchor
# tag format. NOT yet verified against a real Unlimited-OCR markdown
# sample -- no GPU run has produced one in this repo yet. Calibrate this
# against scripts/run_unlimited_ocr.py's actual output before trusting it
# on a real page.
_DET_TAG_RE = re.compile(r"<\|det\|>([^<\s]+)(?:\s*\[[^\]]*\])?\s*<\|/det\|>", re.DOTALL)


def remove_det(text: str) -> str:
    """Strips every <|det|>token [bbox]<|/det|> wrapper, keeping the
    token text. Used both when writing cache (run_unlimited_ocr.py) and
    when reading it (textlayer_ocr.py) -- lives here once, not twice."""
    return _DET_TAG_RE.sub(r"\1", text)


def _cache_path(pdf_path: Path, page_num: int, cache_dir: Path) -> Path:
    return Path(cache_dir) / Path(pdf_path).stem / f"page_{page_num:04d}.md"


def get_cached_markdown(pdf_path: Path, page_num: int, cache_dir: Path = DEFAULT_CACHE_DIR) -> str | None:
    path = _cache_path(pdf_path, page_num, cache_dir)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def store_cached_markdown(pdf_path: Path, page_num: int, markdown: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:
    path = _cache_path(pdf_path, page_num, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
