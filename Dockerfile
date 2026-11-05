ARG BUILDER_IMAGE=cgr.dev/chainguard/python:latest-dev@sha256:95d8cc85fad8acc8ebad357e1972f2a975c498a65406cd9b00bb2233371a94a2
ARG RUNTIME_IMAGE=cgr.dev/chainguard/python:latest@sha256:bf06e09413bec94d6489f0be783b8f9349339907b89e0f759d190d0b95ab2d8f
FROM ${BUILDER_IMAGE} AS build
USER 0
WORKDIR /app
COPY requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install pip==26.2.2 \
    && PYYAML_FORCE_LIBYAML=0 /opt/venv/bin/python -m pip install \
       --only-binary=:all: --no-binary=pyyaml -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip /opt/venv/bin/python -m pip install --no-deps . \
    && mkdir /state && chown 10001:10001 /state \
    && /opt/venv/bin/python -m pip uninstall -y pip setuptools wheel

FROM ${BUILDER_IMAGE} AS verify
USER 0
WORKDIR /verification
COPY --from=build /opt/venv /opt/venv
COPY requirements-ci.lock ./
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install \
    --no-deps --target=/test-tools -r requirements-ci.lock
COPY src/ ./src/
COPY tests/ ./tests/
COPY scripts/ ./scripts/
COPY examples/ ./examples/
COPY docs/ ./docs/
COPY pyproject.toml Dockerfile requirements*.lock ./
ENV PYTHONPATH=/test-tools PATH=/opt/venv/bin:/usr/bin \
    PYTHONDONTWRITEBYTECODE=1 PIPEFOUNDRY_STATE_DIR=/tmp/build-gate
RUN python scripts/build_gate.py --output=/verification/build-receipt.json

FROM ${RUNTIME_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:/usr/bin \
    PIPEFOUNDRY_STATE_DIR=/state
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build --chown=10001:10001 /state /state
COPY --from=verify /verification/build-receipt.json /app/build-receipt.json
USER 10001:10001
EXPOSE 8080
ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "pipefoundry.api:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--limit-concurrency", "64", "--backlog", "128", "--timeout-keep-alive", "5", "--h11-max-incomplete-event-size", "16384"]
