"""Hand-verified ground truth for classification validation. Each set of
page numbers was checked by manually counting programme-table pages
against the real prospectus PDF -- never invented, only recorded from
direct observation. Shared between tests/test_classify.py's real-PDF
integration test and scripts/classify_report.py so the two never drift
apart into disagreeing about what "correct" means.
"""

UJ_2027_TABLE_PAGES: frozenset[int] = frozenset({
    # 50 removed 2026-08-02: confirmed a phantom entry, swept in by the
    # original page-range inference (the 40-51 CBE block) rather than
    # actually observed. Page 50 is NASCA / Amended Senior Certificate
    # narrative (alternative admission routes for adult learners) -- no
    # qualification codes, no programme rows.
    32, 33, 34, 37, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 51,
    54, 55, 60, 61, 62, 63, 66, 67, 68, 69, 70, 74, 75, 76, 82,
    86, 87, 88, 89, 90, 91, 92, 93, 94, 95,
})

# Verified 2026-08-02 by reading the full text of all 15 pages of
# universities/2027/cput.pdf directly, not inferred from classification
# output. Only 2 of 15 pages are genuine per-programme requirement tables
# (DEPARTMENT/QUALIFICATION/APS SCORE/METHOD header row, one row per
# programme); the rest is subject-combination career guidance, front
# matter, or the APS-methodology page. Thin, but real -- page 50's earlier
# removal from UJ_2027_TABLE_PAGES is exactly why a small directly-verified
# set is trusted here over a larger inferred one.
CPUT_2027_TABLE_PAGES: frozenset[int] = frozenset({7, 15})
