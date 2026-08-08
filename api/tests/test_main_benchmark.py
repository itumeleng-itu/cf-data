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
    for _ in range(15):
        start = time.perf_counter()
        result = main_module._run_qualify(request)
        best = min(best, time.perf_counter() - start)

    assert result["evaluated_count"] == 5000
    # Best-of-15, not a single sample or best-of-5: this budget was flaky for
    # three sub-phases in a row (56/61/65ms against 50ms), diagnosed rather
    # than papered over on 2026-08-08. Ruled out with direct evidence, not
    # assumed: extract/ coupling (grep found none), the local venv's heavier
    # dependency set (the SAME workload run inside a clean, isolated Docker
    # build showed the identical 45-70ms range -- a heavier venv would have
    # recovered to baseline there and didn't), an algorithmic regression
    # (cProfile's top-10-by-cumulative-time showed only evaluate()/
    # _evaluate_all()/_evaluate_subject() doing exactly the expected O(programmes)
    # work, nothing anomalous). Actual cause: this dev machine (an i7-8665U,
    # 4 cores/8 threads, 1.9GHz) was observed at 54% background load from
    # OneDrive sync, a browser, Docker Desktop's own overhead, and the coding
    # agent itself, all sharing the same cores the timed code runs on --
    # with GC disabled the best case dropped to 26.7ms (matching the
    # historical ~30-40ms baseline), but variance stayed huge (26.7-54.8ms)
    # even with GC off, confirming OS-scheduling contention/preemption, not
    # GC and not the code, as the dominant factor. Best-of-15 (up from 5)
    # substantially raises the odds of catching at least one unpreempted
    # sample without touching this threshold -- a 25-sample run found a
    # clean minimum of 39.5ms with a heavy tail up to 100ms, so more
    # attempts at finding the floor is the right lever, not a looser bound.
    assert best < 0.05, f"best of 15 qualify runs over 5000 programmes took {best * 1000:.1f}ms"
