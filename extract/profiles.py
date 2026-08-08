"""Per-institution layout + classification profiles, loaded from
extract/institutions/registry.json -- declarative data, not code
branches, per sub-phase 8.3. Every field for a registered institution
must be justified by something actually observed in its own PDF, not
copied from another institution or invented for a hypothetical one.

DEFAULT_PROFILE is the fallback for an institution not yet in the
registry (e.g. a freshly-stubbed 'unconfigured' institution row from
extract/watcher.py) -- a generic starting point, not real per-institution
data. It reuses UJ's calibrated classification weights as a reasonable
baseline (the same "start from UJ's, diverge only with evidence"
principle this sub-phase applies to CPUT), not because it is UJ-specific.
"""

import json
import re
from pathlib import Path

_REGISTRY_PATH = Path(__file__).parent / "institutions" / "registry.json"

_REQUIRED_TOP_KEYS = {"name", "layout", "classification"}
_ALLOWED_TOP_KEYS = _REQUIRED_TOP_KEYS | {"source_url", "quirks"}

_REQUIRED_LAYOUT_KEYS = {"code_pattern", "header_keywords", "rotated_headers"}
_ALLOWED_LAYOUT_KEYS = _REQUIRED_LAYOUT_KEYS | {
    "footnote_markers", "campus_tokens", "not_accepted_phrases", "alternative_phrases",
}

_REQUIRED_CLASSIFICATION_KEYS = {
    "weights", "admin_baseline", "overinclusion_margin", "table_evidence_ruled_line_floor",
}

_VALID_PAGE_CLASSES = {
    "programme_table", "requirements_prose", "scoring_methodology", "admin", "decorative",
    "alternative_admission",
}
_VALID_SIGNAL_NAMES = {
    "text_density", "code_matches", "keyword_hits", "numeric_ratio",
    "ruled_line_count", "image_coverage", "scoring_phrase_hits", "alt_admission_phrase_hits",
}


class ProfileValidationError(ValueError):
    pass


def _validate_layout(institution_id: str, layout: dict) -> None:
    unknown = set(layout) - _ALLOWED_LAYOUT_KEYS
    if unknown:
        raise ProfileValidationError(f"{institution_id}: unknown layout key(s) {sorted(unknown)}")
    missing = _REQUIRED_LAYOUT_KEYS - set(layout)
    if missing:
        raise ProfileValidationError(f"{institution_id}: layout missing required key(s) {sorted(missing)}")

    try:
        re.compile(layout["code_pattern"])
    except re.error as exc:
        raise ProfileValidationError(f"{institution_id}: layout.code_pattern does not compile: {exc}") from exc

    if not isinstance(layout["header_keywords"], list) or not layout["header_keywords"]:
        raise ProfileValidationError(f"{institution_id}: layout.header_keywords must be a non-empty list")

    if not isinstance(layout["rotated_headers"], bool):
        raise ProfileValidationError(f"{institution_id}: layout.rotated_headers must be a boolean")


def _validate_classification(institution_id: str, classification: dict) -> None:
    unknown = set(classification) - _REQUIRED_CLASSIFICATION_KEYS
    if unknown:
        raise ProfileValidationError(f"{institution_id}: unknown classification key(s) {sorted(unknown)}")
    missing = _REQUIRED_CLASSIFICATION_KEYS - set(classification)
    if missing:
        raise ProfileValidationError(f"{institution_id}: classification missing required key(s) {sorted(missing)}")

    weights = classification["weights"]
    unknown_classes = set(weights) - _VALID_PAGE_CLASSES
    if unknown_classes:
        raise ProfileValidationError(f"{institution_id}: unknown page class(es) in weights {sorted(unknown_classes)}")
    missing_classes = _VALID_PAGE_CLASSES - set(weights)
    if missing_classes:
        raise ProfileValidationError(f"{institution_id}: weights missing page class(es) {sorted(missing_classes)}")
    for page_class, signal_weights in weights.items():
        unknown_signals = set(signal_weights) - _VALID_SIGNAL_NAMES
        if unknown_signals:
            raise ProfileValidationError(
                f"{institution_id}: weights.{page_class} has unknown signal name(s) {sorted(unknown_signals)}"
            )

    for key in ("admin_baseline", "overinclusion_margin", "table_evidence_ruled_line_floor"):
        if not isinstance(classification[key], (int, float)):
            raise ProfileValidationError(f"{institution_id}: classification.{key} must be numeric")


def validate_profile(institution_id: str, profile: dict) -> None:
    unknown = set(profile) - _ALLOWED_TOP_KEYS
    if unknown:
        raise ProfileValidationError(f"{institution_id}: unknown top-level key(s) {sorted(unknown)}")
    missing = _REQUIRED_TOP_KEYS - set(profile)
    if missing:
        raise ProfileValidationError(f"{institution_id}: missing required top-level key(s) {sorted(missing)}")

    _validate_layout(institution_id, profile["layout"])
    _validate_classification(institution_id, profile["classification"])


DEFAULT_PROFILE: dict = {
    "name": "unconfigured institution",
    "layout": {
        "code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}",
        "header_keywords": ["APS", "Qualification Code", "Campus", "Programme"],
        "rotated_headers": False,
    },
    "classification": {
        "weights": {
            "programme_table": {
                "code_matches": 4.0, "keyword_hits": 3.0, "ruled_line_count": 0.05,
                "numeric_ratio": 3.0, "text_density": 200.0,
            },
            "requirements_prose": {
                "text_density": 800.0, "code_matches": -3.0, "ruled_line_count": -0.05, "numeric_ratio": -3.0,
            },
            "scoring_methodology": {
                "scoring_phrase_hits": 8.0, "text_density": 600.0, "code_matches": -2.0,
            },
            "admin": {
                "text_density": -100.0, "code_matches": -2.0, "image_coverage": -3.0,
            },
            "decorative": {
                "image_coverage": 10.0, "text_density": -500.0,
            },
            "alternative_admission": {
                "alt_admission_phrase_hits": 6.0, "text_density": 300.0,
                "ruled_line_count": -0.05, "code_matches": -3.0, "keyword_hits": -1.0,
            },
        },
        "admin_baseline": 1.0,
        "overinclusion_margin": 0.5,
        "table_evidence_ruled_line_floor": 50,
    },
}
validate_profile("default", DEFAULT_PROFILE)


def _load_registry() -> dict[str, dict]:
    data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    for institution_id, profile in data.items():
        validate_profile(institution_id, profile)
    return data


PROFILES: dict[str, dict] = _load_registry()


def get_profile(institution_id: str) -> dict:
    return PROFILES.get(institution_id, DEFAULT_PROFILE)
