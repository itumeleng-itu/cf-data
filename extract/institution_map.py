"""Explicit, hand-written institution-name mapping for South Africa's 26
public universities. Never derive an institution_id by parsing a display
name at runtime -- every name variant listed here was either directly
observed on universityqualifications.co.za / apply.org.za (fetched and
read by hand 2026-08-08) or is the university's standard official name
added proactively for institutions absent from both sources today (UMP,
UNISA). An unmapped name is reported for a human to add, never guessed.

MULTI_INSTITUTION_DOCUMENTS covers documents that are not a single
institution's prospectus -- see kzn-cao's entry for the full rationale.
Matched the same way: explicit name/source_id substrings, not inference.
"""

import re

# institution_id -> canonical full name, for reference/reporting only.
INSTITUTIONS: dict[str, str] = {
    "cput": "Cape Peninsula University of Technology",
    "cut": "Central University of Technology",
    "dut": "Durban University of Technology",
    "mut": "Mangosuthu University of Technology",
    "nmu": "Nelson Mandela University",
    "nwu": "North-West University",
    "ru": "Rhodes University",
    "smu": "Sefako Makgatho Health Sciences University",
    "spu": "Sol Plaatje University",
    "su": "Stellenbosch University",
    "tut": "Tshwane University of Technology",
    "uct": "University of Cape Town",
    "ufh": "University of Fort Hare",
    "ufs": "University of the Free State",
    "uj": "University of Johannesburg",
    "ukzn": "University of KwaZulu-Natal",
    "ul": "University of Limpopo",
    "ump": "University of Mpumalanga",
    "unisa": "University of South Africa",
    "univen": "University of Venda",
    "unizulu": "University of Zululand",
    "up": "University of Pretoria",
    "uwc": "University of the Western Cape",
    "vut": "Vaal University of Technology",
    "wits": "University of the Witwatersrand",
    "wsu": "Walter Sisulu University",
}
assert len(INSTITUTIONS) == 26, f"expected 26 SA public universities, got {len(INSTITUTIONS)}"


def _normalize(name: str) -> str:
    lowered = name.strip().lower()
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


# Every display-name variant actually observed on the two sources this
# project scrapes, normalized lowercase. Extend by hand as new variants
# are seen on new sources -- never infer a mapping from a name we haven't
# actually seen or from the institution's own abbreviation alone.
_RAW_NAME_VARIANTS: dict[str, list[str]] = {
    "cput": [
        "Cape Peninsula University of Technology (CPUT)",
        "Cape Peninsula University of Technology",
        "CPUT",
    ],
    "cut": [
        "Central University of Technology (CUT)",
        "Central University of Technology",
        "CUT",
    ],
    "dut": [
        "Durban University Of Technology (DUT)",
        "Durban University of Technology (DUT)",
        "Durban University of Technology",
        "DUT",
    ],
    "mut": [
        "Mangosuthu University Of technology (MUT)",
        "Mangosuthu University of Technology (MUT)",
        "Mangosuthu University of Technology",
        "MUT",
    ],
    "nmu": [
        "Nelson Mandela University (NMU)",
        "Nelson Mandela University",
        "NMU",
    ],
    "nwu": [
        "North West University (NWU)",
        "North-West University (NWU)",
        "North-West University",
        "NWU",
    ],
    "ru": [
        "Rhodes University (RU)",
        "Rhodes University",
        "RU",
    ],
    "smu": [
        "Sefako Makgatho University (SMU)",
        "Sefako Makgatho Health Sciences University (SMU)",
        "Sefako Makgatho Health Sciences University",
        "SMU",
    ],
    "spu": [
        "Sol Plaatje University (SPU)",
        "Sol Plaatje University",
        "SPU",
    ],
    "su": [
        "Stellenbosch University (SU)",
        "Stellenbosch University",
        "SU",
    ],
    "tut": [
        "Tshwane University Of Technology (TUT)",
        "Tshwane University of Technology (TUT)",
        "Tshwane University of Technology",
        "TUT",
    ],
    "uct": [
        "University of Cape Town (UCT)",
        "University of Cape Town",
        "UCT",
    ],
    "ufh": [
        "University Of Fort Hare (UFH)",
        "University of Fort Hare (UFH)",
        "University of Fort Hare",
        "UFH",
    ],
    "ufs": [
        "University Of Free State (UFS)",
        "University of Free State (UFS)",
        "University of the Free State (UFS)",
        "University of the Free State",
        "UFS",
    ],
    "uj": [
        "University Of Johannesburg (UJ)",
        "University of Johannesburg (UJ)",
        "University of Johannesburg",
        "UJ",
    ],
    "ukzn": [
        "University Of KwaZulu Natal (UKZN)",
        "University of KwaZulu-Natal (UKZN)",
        "University of KwaZulu Natal (UKZN)",
        "University of KwaZulu-Natal",
        "UKZN",
    ],
    "ul": [
        "Limpopo University (UL)",
        "University of Limpopo (UL)",
        "University of Limpopo",
        "UL",
    ],
    "ump": [
        "University of Mpumalanga (UMP)",
        "University of Mpumalanga",
        "UMP",
    ],
    "unisa": [
        "University of South Africa (UNISA)",
        "University of South Africa",
        "UNISA",
    ],
    "univen": [
        "University Of Venda (Univen)",
        "University of Venda (UNIVEN)",
        "University of Venda",
        "UNIVEN",
        "Univen",
    ],
    "unizulu": [
        "University of Zululand (UNIZULU)",
        "University of Zululand",
        "UNIZULU",
    ],
    "up": [
        "University Of Pretoria (UP)",
        "University of Pretoria (UP)",
        "University of Pretoria",
        "UP",
    ],
    "uwc": [
        "University Of Western Cape (UWC)",
        "University of Western Cape (UWC)",
        "University of the Western Cape (UWC)",
        "University of the Western Cape",
        "UWC",
    ],
    "vut": [
        "Vaal University Of Technology (VUT)",
        "Vaal University of Technology (VUT)",
        "Vaal University of Technology",
        "VUT",
    ],
    "wits": [
        "University of Witwatersrand (WITS)",
        "University of the Witwatersrand (WITS)",
        "University of the Witwatersrand",
        "Wits",
        "WITS",
    ],
    "wsu": [
        "Walter Sisulu University (WSU)",
        "iYunivesithi Walter Sisulu (WSU)",
        "Walter Sisulu University",
        "WSU",
    ],
}

_NAME_MAP: dict[str, str] = {
    _normalize(variant): institution_id
    for institution_id, variants in _RAW_NAME_VARIANTS.items()
    for variant in variants
}


def resolve_institution_id(display_name: str) -> str | None:
    """Never guesses: returns None (not a slug-derived guess) for any
    name not explicitly listed in _RAW_NAME_VARIANTS above."""
    return _NAME_MAP.get(_normalize(display_name))


# Multi-institution documents: not a single institution's prospectus, so
# never onboardable as-is. Matched against a discovered entry's
# display_name/source_id by substring, same "explicit, never inferred"
# discipline as the institution map above.
MULTI_INSTITUTION_DOCUMENTS: dict[str, dict] = {
    "kzn-cao": {
        "covers": ["ukzn", "dut", "mut", "unizulu"],
        "skip_reason": (
            "Central Applications Office handbook -- one document, four "
            "institutions interleaved. The data model's unit is the "
            "institution (FK on programmes, per-institution scoring "
            "strategy and layout profile, inbox path "
            "{institution_id}/{year}/). Using it would require a "
            "per-row institution-attribution stage existing solely for "
            "this document, and would apply four different scoring "
            "strategies within one extraction. UKZN, DUT and MUT all "
            "publish standalone 2027 prospectuses on the same source. "
            "UNIZULU has no 2027 entry -- source directly or fall back "
            "to its 2026 prospectus."
        ),
        "match_names": ["kzn-cao", "kzn cao", "kwazulu-natal cao", "kwazulu natal cao"],
    },
}


def find_multi_institution_document(display_name: str, source_id: str) -> str | None:
    haystack = _normalize(f"{display_name} {source_id}")
    for key, doc in MULTI_INSTITUTION_DOCUMENTS.items():
        if any(pattern in haystack for pattern in doc["match_names"]):
            return key
    return None
