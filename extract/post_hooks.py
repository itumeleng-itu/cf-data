"""Registry-dispatched per-institution post-extraction resolution hooks --
the general mechanism CPUT's known problem needs (its qualification codes
appear only on a cross-reference page, never in the requirement tables
themselves, so a code has to be resolved by matching programme NAME
against that list), built the same way extract/profiles.py dispatches
layout config: by institution_id, declaratively where possible, never a
branch buried in the main pipeline.

No hook is registered here -- CPUT's actual resolution logic stays
parked (the real CPUT prospectus hasn't been onboarded yet). This module
only proves the seam exists and is a no-op for every institution that
doesn't need one.
"""

from collections.abc import Callable
from pathlib import Path

_HOOKS: dict[str, Callable[[list[dict], Path], list[dict]]] = {}


def register_hook(institution_id: str) -> Callable[[Callable[[list[dict], Path], list[dict]]], Callable]:
    def _decorator(fn: Callable[[list[dict], Path], list[dict]]) -> Callable[[list[dict], Path], list[dict]]:
        _HOOKS[institution_id] = fn
        return fn

    return _decorator


def apply_post_extraction_hook(institution_id: str, records: list[dict], pdf_path: Path) -> list[dict]:
    hook = _HOOKS.get(institution_id)
    return hook(records, pdf_path) if hook is not None else records
