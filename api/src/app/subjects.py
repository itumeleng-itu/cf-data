"""The full list of matric (NSC) subjects the app knows about, plus the
level-conversion table South African universities use.

In plain terms: every South African university judges an applicant's
matric certificate using two building blocks —
  1. which SUBJECTS the learner took (e.g. Mathematics, Physical Sciences)
  2. what LEVEL (1-7) they achieved in each, converted from a percentage.

This file defines both: the fixed list of subject names (Subject) and the
percentage-to-level conversion table every institution uses (defined by
the Department of Basic Education, not invented here).

Frozen taxonomy. Never rename members — add only. These keys appear in
the database, the API contract and the frontend."""

from enum import StrEnum


class Subject(StrEnum):
    """Every matric subject the system recognises, as a fixed code (e.g.
    "mathematics"). Home Language / First Additional Language pairs
    exist for each official South African language (e.g. english_hl vs
    english_fal) because a learner only takes one of the two, at a
    different difficulty level."""
    ENGLISH_HL = "english_hl";           ENGLISH_FAL = "english_fal"
    AFRIKAANS_HL = "afrikaans_hl";       AFRIKAANS_FAL = "afrikaans_fal"
    ISIZULU_HL = "isizulu_hl";           ISIZULU_FAL = "isizulu_fal"
    ISIXHOSA_HL = "isixhosa_hl";         ISIXHOSA_FAL = "isixhosa_fal"
    SEPEDI_HL = "sepedi_hl";             SEPEDI_FAL = "sepedi_fal"
    SESOTHO_HL = "sesotho_hl";           SESOTHO_FAL = "sesotho_fal"
    SETSWANA_HL = "setswana_hl";         SETSWANA_FAL = "setswana_fal"
    XITSONGA_HL = "xitsonga_hl";         XITSONGA_FAL = "xitsonga_fal"
    SISWATI_HL = "siswati_hl";           SISWATI_FAL = "siswati_fal"
    TSHIVENDA_HL = "tshivenda_hl";       TSHIVENDA_FAL = "tshivenda_fal"
    ISINDEBELE_HL = "isindebele_hl";     ISINDEBELE_FAL = "isindebele_fal"

    MATHEMATICS = "mathematics"
    MATHEMATICAL_LITERACY = "mathematical_literacy"
    TECHNICAL_MATHEMATICS = "technical_mathematics"

    PHYSICAL_SCIENCES = "physical_sciences"
    TECHNICAL_SCIENCES = "technical_sciences"
    LIFE_SCIENCES = "life_sciences"
    LIFE_ORIENTATION = "life_orientation"

    ACCOUNTING = "accounting"
    BUSINESS_STUDIES = "business_studies"
    ECONOMICS = "economics"
    GEOGRAPHY = "geography"
    HISTORY = "history"
    TOURISM = "tourism"
    CONSUMER_STUDIES = "consumer_studies"
    VISUAL_ARTS = "visual_arts"
    DRAMATIC_ARTS = "dramatic_arts"
    MUSIC = "music"
    DESIGN = "design"
    INFORMATION_TECHNOLOGY = "information_technology"
    COMPUTER_APPLICATIONS_TECHNOLOGY = "computer_applications_technology"
    ENGINEERING_GRAPHICS_AND_DESIGN = "engineering_graphics_and_design"
    AGRICULTURAL_SCIENCES = "agricultural_sciences"
    HOSPITALITY_STUDIES = "hospitality_studies"
    RELIGION_STUDIES = "religion_studies"


# Groups the Home Language / First Additional Language version of each
# language together, so the rest of the app can ask "did they meet the
# English requirement?" without caring which of the two variants the
# learner actually wrote.
LANGUAGE_FAMILIES: dict[str, tuple[str, str]] = {
    "english": ("english_hl", "english_fal"),
    "afrikaans": ("afrikaans_hl", "afrikaans_fal"),
    "isizulu": ("isizulu_hl", "isizulu_fal"),
    "isixhosa": ("isixhosa_hl", "isixhosa_fal"),
    "sepedi": ("sepedi_hl", "sepedi_fal"),
    "sesotho": ("sesotho_hl", "sesotho_fal"),
    "setswana": ("setswana_hl", "setswana_fal"),
    "xitsonga": ("xitsonga_hl", "xitsonga_fal"),
    "siswati": ("siswati_hl", "siswati_fal"),
    "tshivenda": ("tshivenda_hl", "tshivenda_fal"),
    "isindebele": ("isindebele_hl", "isindebele_fal"),
}


def percentage_to_level(pct: int) -> int:
    """Converts a raw matric mark (0-100%) into the official NSC
    "achievement level" (1-7) that universities actually use for
    admission. For example, 85% becomes level 7 (the top band), and 45%
    becomes level 3. This mirrors the exact bands published on every
    South African matric certificate."""
    if not 0 <= pct <= 100:
        raise ValueError(f"percentage out of range 0-100: {pct}")
    if pct >= 80:
        return 7
    if pct >= 70:
        return 6
    if pct >= 60:
        return 5
    if pct >= 50:
        return 4
    if pct >= 40:
        return 3
    if pct >= 30:
        return 2
    return 1
