ARG PYTHON_IMAGE=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip pip install pip==26.2.2 \
    && pip install -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps . \
    && useradd --uid 10001 --create-home pipeline \
    && mkdir /state && chown pipeline:pipeline /state \
    && python -m pip uninstall -y pip setuptools wheel
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "pipefoundry.api:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
