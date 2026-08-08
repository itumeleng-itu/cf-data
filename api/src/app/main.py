"""FastAPI qualify service. Data is loaded once at startup (validated via
Pydantic, then kept as plain dicts for the hot loop — see load_data) and
lives entirely in memory; a request does zero I/O."""

import json
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypedDict

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.evaluator import Failure, evaluate, subject_display_name
from app.qualify import select_score_threshold
from app.scoring import SCORERS
from app.subjects import Subject

_DEFAULT_DATA_PATH = Path(__file__).parent / "data" / "programmes.json"

PROGRAMMES: list[dict] = []
INSTITUTIONS: dict[str, dict] = {}


# --- load-time validation models (discarded after load) ---------------------

class _InstitutionModel(BaseModel):
    id: str
    name: str
    scoring_strategy: str
    scoring_config: dict = Field(default_factory=dict)


class _ProgrammeModel(BaseModel):
    institution_id: str
    academic_year: int
    qualification_code: str
    name: str
    faculty: str | None = None
    campus: list[str] = Field(default_factory=list)
    duration_years: float | None = None
    extended: bool = False
    requirements: dict
    selection_notes: list[str] = Field(default_factory=list)
    career_text: str | None = None
    source_doc: str | None = None
    source_page: int | None = None
    confidence: str = "extracted"


class _DataFile(BaseModel):
    institutions: list[_InstitutionModel]
    programmes: list[_ProgrammeModel]


def _data_path() -> Path:
    override = os.environ.get("PROGRAMMES_DATA_PATH")
    return Path(override) if override else _DEFAULT_DATA_PATH


def load_data(path: Path) -> tuple[list[dict], dict[str, dict]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    validated = _DataFile.model_validate(raw)
    programmes = [p.model_dump() for p in validated.programmes]
    institutions = {i.id: i.model_dump() for i in validated.institutions}
    return programmes, institutions


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global PROGRAMMES, INSTITUTIONS
    PROGRAMMES, INSTITUTIONS = load_data(_data_path())
    yield
    PROGRAMMES, INSTITUTIONS = [], {}


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def _add_data_headers(request: Request, call_next: Callable) -> Response:
    response = await call_next(request)
    response.headers["X-Data-Version"] = os.environ.get("DATA_VERSION", "unknown")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


# --- /v1/qualify --------------------------------------------------------------

_VALID_SUBJECTS = {s.value for s in Subject}


class SubjectMark(BaseModel):
    subject: str
    percentage: int = Field(ge=0, le=100)

    @field_validator("subject")
    @classmethod
    def _known_subject(cls, v: str) -> str:
        if v not in _VALID_SUBJECTS:
            raise ValueError(f"unknown subject '{v}'")
        return v


class QualifyRequest(BaseModel):
    subjects: list[SubjectMark] = Field(min_length=6, max_length=9)
    academic_year: int | None = None
    institutions: list[str] | None = None
    include_near_misses: bool = True


class FailureOut(BaseModel):
    kind: str
    message: str
    required_level: int | None
    actual_level: int | None


class ProgrammeResult(BaseModel):
    institution: str
    qualification_code: str
    name: str
    faculty: str | None
    campus: list[str]
    duration_years: float | None
    score_required: int | None
    score_actual: int
    margin: int | None
    selection_notes: list[str]
    failures: list[FailureOut] = Field(default_factory=list)


class QualifyResponse(BaseModel):
    scores: dict[str, int]
    qualified: list[ProgrammeResult]
    near_misses: list[ProgrammeResult]
    evaluated_count: int


# Plain-dict mirrors of the models above, used for the hot per-programme loop.
# Constructing a Pydantic model per programme (thousands per request) is the
# same "heavier to walk, heavier in RAM" cost the load-time validation avoids
# by discarding its models after load -- so the loop builds these instead and
# FastAPI's response_model validates the whole response exactly once, at the
# boundary, not once per programme.

class FailureDict(TypedDict):
    kind: str
    message: str
    required_level: int | None
    actual_level: int | None


class ProgrammeResultDict(TypedDict):
    institution: str
    qualification_code: str
    name: str
    faculty: str | None
    campus: list[str]
    duration_years: float | None
    score_required: int | None
    score_actual: int
    margin: int | None
    selection_notes: list[str]
    failures: list[FailureDict]


class QualifyResponseDict(TypedDict):
    scores: dict[str, int]
    qualified: list[ProgrammeResultDict]
    near_misses: list[ProgrammeResultDict]
    evaluated_count: int


def _evaluate_programme(programme: dict, marks: dict[str, int], achieved: int) -> ProgrammeResultDict:
    nsc = programme["requirements"]["nsc"]
    excluded = set(nsc.get("excluded_subjects") or [])

    required = select_score_threshold(nsc["score"], marks)

    failures: list[Failure] = []
    if required is None:
        # No score entry applies at all -- e.g. every threshold requires
        # either Mathematics or Mathematical Literacy and the learner has
        # neither. That's a failure, not a pass via some fallback threshold.
        required_names = [
            subject_display_name(e["requires_subject"])
            for e in nsc["score"] if e.get("requires_subject")
        ]
        message = f"Requires {' or '.join(required_names)} to determine eligibility for this programme"
        failures.append(Failure(kind="score", message=message, required=None, actual=achieved, subject=None))
    elif achieved < required:
        failures.append(Failure(
            kind="score",
            message=f"Requires an APS of {required}; you have {achieved}",
            required=required, actual=achieved, subject=None,
        ))
    failures.extend(evaluate(nsc["subjects"], marks, excluded))

    margin = achieved - required if required is not None else None
    return {
        "institution": programme["institution_id"],
        "qualification_code": programme["qualification_code"],
        "name": programme["name"],
        "faculty": programme.get("faculty"),
        "campus": programme.get("campus", []),
        "duration_years": programme.get("duration_years"),
        "score_required": required,
        "score_actual": achieved,
        "margin": margin,
        "selection_notes": programme.get("selection_notes", []),
        "failures": [
            {"kind": f.kind, "message": f.message, "required_level": f.required, "actual_level": f.actual}
            for f in failures
        ],
    }


def _run_qualify(request: QualifyRequest) -> QualifyResponseDict:
    marks = {s.subject: s.percentage for s in request.subjects}
    candidates = [
        p for p in PROGRAMMES
        if (request.academic_year is None or p["academic_year"] == request.academic_year)
        and (request.institutions is None or p["institution_id"] in request.institutions)
    ]

    scores: dict[str, int] = {}
    qualified: list[ProgrammeResultDict] = []
    near_misses: list[ProgrammeResultDict] = []

    for programme in candidates:
        institution_id = programme["institution_id"]
        if institution_id not in scores:
            strategy = INSTITUTIONS[institution_id]["scoring_strategy"]
            scores[institution_id] = SCORERS[strategy](marks)
        achieved = scores[institution_id]

        result = _evaluate_programme(programme, marks, achieved)
        if not result["failures"]:
            qualified.append(result)
        elif request.include_near_misses and len(result["failures"]) <= 2:
            near_misses.append(result)

    qualified.sort(key=lambda r: r["margin"] if r["margin"] is not None else 0, reverse=True)
    return {
        "scores": scores,
        "qualified": qualified,
        "near_misses": near_misses,
        "evaluated_count": len(candidates),
    }


@app.post("/v1/qualify", response_model=QualifyResponse)
def qualify(request: QualifyRequest) -> QualifyResponseDict:
    return _run_qualify(request)


# --- /v1/meta -------------------------------------------------------------------

class MetaResponse(BaseModel):
    data_version: str
    academic_years: list[int]
    institutions: dict[str, list[int]]
    programme_count: int


@app.get("/v1/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    years_by_institution: dict[str, set[int]] = {}
    for p in PROGRAMMES:
        years_by_institution.setdefault(p["institution_id"], set()).add(p["academic_year"])
    return MetaResponse(
        data_version=os.environ.get("DATA_VERSION", "unknown"),
        academic_years=sorted({p["academic_year"] for p in PROGRAMMES}),
        institutions={k: sorted(v) for k, v in years_by_institution.items()},
        programme_count=len(PROGRAMMES),
    )


# --- health/readiness -------------------------------------------------------------

@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    if not PROGRAMMES or not INSTITUTIONS:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}
