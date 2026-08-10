"""Offline preprocessing script -- NOT part of the live pipeline, never
imported by extract/selftest.py or extract/methods/textlayer_ocr.py. Run
this once per prospectus (on a GPU machine, 8GB+ VRAM) to fill the on-disk
Markdown cache that textlayer_ocr.py reads at request time with no GPU
involved.

torch/transformers are imported lazily, only inside _load_model(), so
importing this module -- or anything that happens to import it -- never
pulls in GPU libraries. The rest of the pipeline must never hard-depend
on them.

The model-loading call in _load_model()/_run_ocr() is written from the
parameters given in the task spec (model.infer(), prompt='<image>Free
OCR.', base_size=1024, image_size=640, crop_mode=True) -- the checkpoint
identifier is a placeholder (marked TODO below) and has NOT been verified
against a real GPU run in this repo. Confirm it against the actual model
card before trusting any output this script produces.

Page rendering uses pdfplumber (already a project dependency, and the
same library vision.py's Method C actually uses to render pages -- NOT
PyMuPDF, despite that being mentioned as "the same approach already used
in vision.py" when this script was speced; that claim was checked against
vision.py's real code and found inaccurate, so pdfplumber was used here
instead to avoid adding an unnecessary dependency for a script that isn't
executable without a GPU anyway).
"""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extract" / "methods"))
from ocr_cache import remove_det, store_cached_markdown  # noqa: E402

_RENDER_DPI = 300


def _render_page_png(pdf_path: Path, page_num: int, out_path: Path) -> None:
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_num - 1]
        image = page.to_image(resolution=_RENDER_DPI)
        image.original.save(out_path, format="PNG")


def _load_model():
    """Lazy import -- torch/transformers only load when this is actually
    called, never at module import time."""
    import torch
    from transformers import AutoModel, AutoTokenizer

    checkpoint = "unlimited-ocr/unlimited-ocr"  # TODO: confirm the real checkpoint id before use
    tokenizer = AutoTokenizer.from_pretrained(checkpoint, trust_remote_code=True)
    model = AutoModel.from_pretrained(checkpoint, trust_remote_code=True, torch_dtype=torch.bfloat16)
    model = model.eval().cuda()
    return model, tokenizer


def _run_ocr(model, tokenizer, image_path: Path) -> str:
    raw = model.infer(
        tokenizer,
        prompt="<image>Free OCR.",
        image_file=str(image_path),
        base_size=1024,
        image_size=640,
        crop_mode=True,  # gundam mode -- single page
    )
    return remove_det(raw)


def main() -> int:
    ap = argparse.ArgumentParser(prog="run_unlimited_ocr")
    ap.add_argument("--pdf", required=True, help="path to the prospectus PDF")
    ap.add_argument("--pages", required=True, help="comma-separated page numbers, e.g. 32,33,34")
    ap.add_argument("--cache-dir", default="ocr_cache")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    cache_dir = Path(args.cache_dir)
    pages = [int(p) for p in args.pages.split(",") if p.strip()]

    model, tokenizer = _load_model()

    written: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp:
        for page_num in pages:
            png_path = Path(tmp) / f"page_{page_num:04d}.png"
            _render_page_png(pdf_path, page_num, png_path)
            markdown = _run_ocr(model, tokenizer, png_path)
            store_cached_markdown(pdf_path, page_num, markdown, cache_dir)
            cache_path = cache_dir / pdf_path.stem / f"page_{page_num:04d}.md"
            written.append(cache_path)
            print(f"  page {page_num}: wrote {cache_path}")

    print(f"Processed {len(pages)} pages, wrote {len(written)} cache file(s) under {cache_dir / pdf_path.stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
