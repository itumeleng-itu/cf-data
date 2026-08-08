"""Tests for extract/profiles.py's registry loader and validation --
sub-phase 8.3 turned UJ's hardcoded classification constants into
declarative data (extract/institutions/registry.json); this is what
keeps a malformed profile from silently loading instead of failing loud.
"""

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "extract"))
from profiles import (  # noqa: E402
    DEFAULT_PROFILE,
    PROFILES,
    ProfileValidationError,
    get_profile,
    validate_profile,
)

_VALID_PROFILE = {
    "name": "Test Institution",
    "layout": {
        "code_pattern": r"[A-Z]\d[A-Z0-9]{3,4}",
        "header_keywords": ["APS", "Programme"],
        "rotated_headers": False,
    },
    "classification": {
        "weights": {
            "programme_table": {"code_matches": 4.0},
            "requirements_prose": {"text_density": 800.0},
            "scoring_methodology": {"scoring_phrase_hits": 8.0},
            "admin": {"text_density": -100.0},
            "decorative": {"image_coverage": 10.0},
            "alternative_admission": {"alt_admission_phrase_hits": 6.0},
        },
        "admin_baseline": 1.0,
        "overinclusion_margin": 0.5,
        "table_evidence_ruled_line_floor": 50,
    },
}


def test_valid_profile_passes_validation() -> None:
    validate_profile("test", copy.deepcopy(_VALID_PROFILE))  # must not raise


def test_registry_loads_uj_and_cput() -> None:
    assert "uj" in PROFILES
    assert "cput" in PROFILES


def test_uj_profile_is_internally_consistent() -> None:
    validate_profile("uj", PROFILES["uj"])  # must not raise


def test_cput_profile_is_internally_consistent() -> None:
    validate_profile("cput", PROFILES["cput"])  # must not raise


def test_default_profile_is_internally_consistent() -> None:
    validate_profile("default", DEFAULT_PROFILE)  # must not raise


def test_get_profile_returns_default_for_unknown_institution() -> None:
    assert get_profile("some-institution-not-in-the-registry") is DEFAULT_PROFILE


def test_get_profile_returns_registered_profile() -> None:
    assert get_profile("uj")["name"] == "University of Johannesburg"


def test_unknown_top_level_key_rejected() -> None:
    profile = copy.deepcopy(_VALID_PROFILE)
    profile["unexpected_field"] = "surprise"
    with pytest.raises(ProfileValidationError, match="unknown top-level key"):
        validate_profile("test", profile)


def test_missing_required_top_level_key_rejected() -> None:
    profile = copy.deepcopy(_VALID_PROFILE)
    del profile["classification"]
    with pytest.raises(ProfileValidationError, match="missing required top-level key"):
        validate_profile("test", profile)


def test_unknown_layout_key_rejected() -> None:
    profile = copy.deepcopy(_VALID_PROFILE)
    profile["layout"]["unexpected"] = True
    with pytest.raises(ProfileValidationError, match="unknown layout key"):
        validate_profile("test", profile)


def test_non_compiling_code_pattern_rejected() -> None:
    profile = copy.deepcopy(_VALID_PROFILE)
    profile["layout"]["code_pattern"] = "[unclosed"
    with pytest.raises(ProfileValidationError, match="does not compile"):
        validate_profile("test", profile)


def test_empty_header_keywords_rejected() -> None:
    profile = copy.deepcopy(_VALID_PROFILE)
    profile["layout"]["header_keywords"] = []
    with pytest.raises(ProfileValidationError, match="header_keywords"):
        validate_profile("test", profile)


def test_missing_classification_key_rejected() -> None:
    profile = copy.deepcopy(_VALID_PROFILE)
    del profile["classification"]["overinclusion_margin"]
    with pytest.raises(ProfileValidationError, match="missing required key"):
        validate_profile("test", profile)


def test_unknown_page_class_in_weights_rejected() -> None:
    profile = copy.deepcopy(_VALID_PROFILE)
    profile["classification"]["weights"]["not_a_real_page_class"] = {"text_density": 1.0}
    with pytest.raises(ProfileValidationError, match="unknown page class"):
        validate_profile("test", profile)


def test_missing_page_class_in_weights_rejected() -> None:
    profile = copy.deepcopy(_VALID_PROFILE)
    del profile["classification"]["weights"]["decorative"]
    with pytest.raises(ProfileValidationError, match="missing page class"):
        validate_profile("test", profile)


def test_unknown_signal_name_in_weights_rejected() -> None:
    profile = copy.deepcopy(_VALID_PROFILE)
    profile["classification"]["weights"]["admin"]["not_a_real_signal"] = 1.0
    with pytest.raises(ProfileValidationError, match="unknown signal name"):
        validate_profile("test", profile)


def test_non_numeric_classification_value_rejected() -> None:
    profile = copy.deepcopy(_VALID_PROFILE)
    profile["classification"]["admin_baseline"] = "not a number"
    with pytest.raises(ProfileValidationError, match="must be numeric"):
        validate_profile("test", profile)
