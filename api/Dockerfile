# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer first, cached separately from source so a code-only change
# doesn't re-resolve/re-download the world.
COPY pyproject.toml uv.lock ./
COPY api/pyproject.toml api/README.md ./api/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --no-install-project --package coursefind-api

# Now the real source and the real (non-editable) install -- self-contained
# venv, no dangling editable path back to a source tree the runtime stage
# won't have.
COPY api/src ./api/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package coursefind-api


FROM python:3.12-slim AS runtime

RUN groupadd --gid 1000 app \
 && useradd --uid 1000 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv ./.venv

# Baked in at build time -- the CI pipeline's export step must produce this
# file before `docker build` runs. There is no boot-time fetch, on purpose:
# new data means a new image tag, not a live reload.
COPY --chown=app:app api/src/app/data/programmes.json ./data/programmes.json

ARG DATA_VERSION
ENV DATA_VERSION=${DATA_VERSION} \
    PROGRAMMES_DATA_PATH=/app/data/programmes.json \
    PATH="/app/.venv/bin:${PATH}"

USER 1000
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
