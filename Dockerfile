# GeoDispatch AI agent — FastAPI app image.
#
# This image contains ONLY the Python app. Ollama and the geodispatch-* models
# live in the separate `ollama` service (see docker-compose.yml) so that model
# weights sit in a named volume and survive `docker compose down`.
#
# Base: python:3.14-slim — 3.14 matches the interpreter this project is
# developed and tested on (docs/README.md "Prerequisites" states 3.10+ as the
# floor; pinning the tested version avoids a "works on my box" gap), and -slim
# keeps the image small since we need no compilers (all four deps ship wheels).
FROM python:3.14-slim

# PYTHONDONTWRITEBYTECODE: no .pyc litter in a layer that is thrown away anyway.
# PYTHONUNBUFFERED: uvicorn/logging output reaches `docker compose logs` live
# instead of sitting in a pipe buffer — matters when watching a slow /decide.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, in their own layer: requirements.txt changes far less often
# than the app code, so edits to routes/ or prompts/ reuse this cached layer.
# --retries/--timeout because a flaky network shouldn't fail a whole build.
COPY requirements.txt ./
RUN pip install --retries 10 --timeout 60 -r requirements.txt

# App code. Copied as explicit paths (not `COPY . .`) so nothing unexpected —
# tests/, docs/, contracts/ — ends up in the runtime image.
COPY main.py ./
COPY routes/ ./routes/
COPY services/ ./services/
COPY models/ ./models/
COPY prompts/ ./prompts/

# Run as a non-root user: the app only ever reads its own code and makes
# outbound HTTP calls to the ollama service, so it needs no write access.
RUN useradd --create-home --uid 10001 geodispatch \
    && chown -R geodispatch:geodispatch /app
USER geodispatch

# Where the app looks for Ollama. Overridden in docker-compose.yml to
# http://ollama:11434; the code's own default stays localhost so the non-Docker
# Makefile flow is unchanged (see services/ollama.py::_ollama_host).
ENV OLLAMA_HOST=http://ollama:11434

EXPOSE 8000

# Liveness for `depends_on`/`--wait`. python -c instead of curl: the slim image
# ships no curl and adding one just for a healthcheck is 10 MB of nothing.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

# Same command docs/README.md documents for the manual flow.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
