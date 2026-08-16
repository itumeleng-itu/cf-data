"""This is the CourseFind API — the web service a learner's browser (or
another app) actually talks to. Its whole job, in one sentence: take a
learner's matric subject marks and tell them which university programmes
they qualify for, and why (or why not).

How it works, in plain terms:
  1. On startup, it reads the full list of programmes and their
     requirements from a JSON file into memory once (see load_data).
  2. When a request comes in to /v1/qualify, it checks that learner's
     marks against every programme in memory and returns three things:
     their calculated score at each university, the programmes they
     qualify for, and "near misses" (programmes they're close to
     qualifying for, with the specific reasons why not).
  3. Because everything lives in memory (no database calls per request),
     answering a request is very fast.

The actual admission-rules logic (does this learner meet THIS
requirement?) lives in evaluator.py, qualify.py and scoring.py — this
file is the web layer: routes, request/response shapes, and wiring.

Data is loaded once at startup (validated via Pydantic, then kept as
plain dicts for the hot loop — see load_data) and lives entirely in
memory; a request does zero I/O."""

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

# The entire dataset, held in memory for the lifetime of the running
# server. Empty until the app finishes starting up (see lifespan below).
PROGRAMMES: list[dict] = []
INSTITUTIONS: dict[str, dict] = {}


# --- load-time validation models (discarded after load) ---------------------
# These three classes describe the exact SHAPE the programmes.json data file
# must have. They're only used once, at startup, to check the file isn't
# corrupt or missing fields -- after that check passes, the data is converted
# to plain dictionaries (see load_data) because plain dicts are faster to
# work with than these validation objects when checking thousands of
# programmes per request.

class _InstitutionModel(BaseModel):
    """One university: its id, display name, and which scoring formula
    (see scoring.py) it uses to calculate APS."""
    id: str
    name: str
    scoring_strategy: str
    scoring_config: dict = Field(default_factory=dict)


class _ProgrammeModel(BaseModel):
    """One degree/diploma programme at one university: its code, name,
    and admission requirements (the "requirements" field holds the rule
    tree that evaluator.py checks a learner's marks against)."""
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
    """The whole programmes.json file: every institution plus every
    programme, all in one place."""
    institutions: list[_InstitutionModel]
    programmes: list[_ProgrammeModel]


def _data_path() -> Path:
    """Where to load the programme data from. Defaults to the bundled
    data/programmes.json file, but can be pointed elsewhere via the
    PROGRAMMES_DATA_PATH environment variable (handy for testing)."""
    override = os.environ.get("PROGRAMMES_DATA_PATH")
    return Path(override) if override else _DEFAULT_DATA_PATH


def load_data(path: Path) -> tuple[list[dict], dict[str, dict]]:
    """Reads the data file, checks it matches the expected shape (see the
    models above), then converts it to plain lists/dicts for speed.
    Called once when the server starts."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    validated = _DataFile.model_validate(raw)
    programmes = [p.model_dump() for p in validated.programmes]
    institutions = {i.id: i.model_dump() for i in validated.institutions}
    return programmes, institutions


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Runs once when the server starts (loads all the programme data
    into memory) and once when it shuts down (clears it). FastAPI calls
    this automatically -- it's not called directly anywhere else."""
    global PROGRAMMES, INSTITUTIONS
    PROGRAMMES, INSTITUTIONS = load_data(_data_path())
    yield
    PROGRAMMES, INSTITUTIONS = [], {}


# The actual web application. Every route below (@app.get / @app.post) is
# attached to this one object.
app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def _add_data_headers(request: Request, call_next: Callable) -> Response:
    """Runs on every single request/response, regardless of which route
    handled it. Stamps two extra HTTP headers on the reply: which version
    of the programme data answered this request (useful for debugging),
    and a caching hint telling browsers/CDNs they can reuse the response
    for an hour."""
    response = await call_next(request)
    response.headers["X-Data-Version"] = os.environ.get("DATA_VERSION", "unknown")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


# --- /v1/qualify --------------------------------------------------------------
# This is the main endpoint: a learner sends their subject marks, and gets
# back which programmes they qualify for. Everything below builds up to
# the qualify() function near the bottom of this section.

_VALID_SUBJECTS = {s.value for s in Subject}


class SubjectMark(BaseModel):
    """One subject and the percentage the learner achieved in it, as sent
    in the request body -- e.g. {"subject": "mathematics", "percentage": 72}."""
    subject: str
    percentage: int = Field(ge=0, le=100)

    @field_validator("subject")
    @classmethod
    def _known_subject(cls, v: str) -> str:
        """Rejects the request early if it names a subject that isn't in
        our fixed subject list (see subjects.py) -- e.g. a typo -- rather
        than silently ignoring it."""
        if v not in _VALID_SUBJECTS:
            raise ValueError(f"unknown subject '{v}'")
        return v


class QualifyRequest(BaseModel):
    """The shape of a request to POST /v1/qualify: the learner's marks
    (6-9 subjects, matching how many subjects a real NSC certificate has),
    optionally narrowed to a specific academic year or a specific list of
    universities, and whether to include "near miss" programmes."""
    subjects: list[SubjectMark] = Field(min_length=6, max_length=9)
    academic_year: int | None = None
    institutions: list[str] | None = None
    include_near_misses: bool = True


class FailureOut(BaseModel):
    """One reason a learner doesn't qualify for a programme, formatted
    for the API response (mirrors evaluator.Failure)."""
    kind: str
    message: str
    required_level: int | None
    actual_level: int | None


class ProgrammeResult(BaseModel):
    """One programme's result for this learner: whether they qualify
    (empty failures list) or don't (failures explain exactly why), plus
    the programme's own details (name, campus, duration, etc.)."""
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
    """The full shape of what /v1/qualify sends back: the learner's
    calculated score at each university, the list of programmes they
    qualify for, the list of "near miss" programmes, and how many
    programmes were checked in total."""
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
# (These TypedDicts have no behaviour of their own -- they just describe, for
# readability and type-checking, what shape each plain dict must have.)

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
    """Checks ONE programme against a learner's marks: does their score
    meet the required APS, AND do they meet every subject requirement?
    Combines both checks into a single result the learner can read,
    including a plain-English reason for each thing they're missing."""
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
    """The main "check every programme" loop: for each candidate
    programme (optionally narrowed by year/university), calculates the
    learner's score at that institution (caching it, since a university
    usually offers many programmes and the score only needs computing
    once per university), then sorts the results into "qualified" and
    "near miss" (close, but missing 1-2 things) buckets."""
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
    """POST /v1/qualify — the endpoint the frontend calls when a learner
    submits their marks. Takes a QualifyRequest (their subjects and
    marks), returns a QualifyResponse (what they qualify for). All the
    actual work happens in _run_qualify above; this function is just the
    route FastAPI dispatches to."""
    return _run_qualify(request)


# --- /v1/meta -------------------------------------------------------------------
# A small "about the data" endpoint -- lets the frontend show things like
# "which years and universities are currently covered?" without having to
# fetch every programme.

class MetaResponse(BaseModel):
    """Summary info about the currently-loaded dataset: which data
    version is live, which academic years exist, which years each
    university has data for, and the total programme count."""
    data_version: str
    academic_years: list[int]
    institutions: dict[str, list[int]]
    programme_count: int


@app.get("/v1/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    """GET /v1/meta — returns a snapshot of what data is currently
    loaded, mostly for the frontend to display "last updated" / "which
    universities are covered" style information."""
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
# These two endpoints aren't for learners -- they're for infrastructure
# (Kubernetes, load balancers) to check "is this server OK to send traffic
# to?" See k8s/deployment.yaml for how they're used.

@app.get("/healthz")
def healthz() -> dict[str, str]:
    """"Is the process alive at all?" -- always returns ok as long as the
    server can respond to a request. Doesn't check whether data has
    finished loading; see readyz for that."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    """"Is the server ready to actually serve real requests?" -- fails
    (503) until the startup data load has finished. Kubernetes uses this
    to avoid sending traffic to a pod that's still starting up."""
    if not PROGRAMMES or not INSTITUTIONS:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}
