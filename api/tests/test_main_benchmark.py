import time

import pytest

import app.main as main_module


def _synthetic_programme(i: int) -> dict:
    return {
        "institution_id": "uj",
        "academic_year": 2027,
        "qualification_code": f"SYN{i:05d}",
        "name": f"Synthetic Programme {i}",
        "faculty": "Synthetic",
        "campus": ["MAIN"],
        "duration_years": 3.0,
        "extended": False,
        "requirements": {
            "nsc": {
                "score": [{"min_score": 20 + (i % 20)}],
                "subjects": {
                    "kind": "all",
                    "rules": [
                        {"kind": "subject", "language": "english", "min_level": 4},
                        {"kind": "subject", "subject": "mathematics", "min_level": 4},
                    ],
                },
                "excluded_subjects": [],
            },
        },
        "selection_notes": [],
        "source_doc": None,
        "source_page": None,
        "confidence": "extracted",
    }


def test_qualify_over_5000_programmes_under_50ms(monkeypatch: pytest.MonkeyPatch) -> None:
    programmes = [_synthetic_programme(i) for i in range(5000)]
    monkeypatch.setattr(main_module, "PROGRAMMES", programmes)
    monkeypatch.setattr(main_module, "INSTITUTIONS", {
        "uj": {"id": "uj", "name": "UJ", "scoring_strategy": "aps_best6_excl_lo", "scoring_config": {}},
    })

    request = main_module.QualifyRequest(subjects=[
        {"subject": "english_hl", "percentage": 87},
        {"subject": "mathematics", "percentage": 88},
        {"subject": "life_orientation", "percentage": 88},
        {"subject": "geography", "percentage": 92},
        {"subject": "life_sciences", "percentage": 87},
        {"subject": "physical_sciences", "percentage": 73},
    ])

    main_module._run_qualify(request)  # warm-up: exclude first-call effects (dict resizing etc.) from the timing

    best = float("inf")
    for _ in range(5):
        start = time.perf_counter()
        result = main_module._run_qualify(request)
        best = min(best, time.perf_counter() - start)

    assert result["evaluated_count"] == 5000
    # Best-of-5, not a single sample: a lone wall-clock reading on a shared dev
    # machine is vulnerable to one-off GC/scheduler pauses unrelated to this
    # code's actual complexity; the minimum reflects what the algorithm can do.
    assert best < 0.05, f"best of 5 qualify runs over 5000 programmes took {best * 1000:.1f}ms"
