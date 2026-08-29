#!/bin/sh
# GeoDispatch — Ollama service entrypoint: serve + idempotent model provisioning.
#
# Replaces the official image's default `ollama serve` entrypoint. Sequence:
#
#   1. start `ollama serve` in the background
#   2. wait for its API to answer
#   3. pull qwen2.5:3b   -- only if absent from the volume
#   4. build the three geodispatch-* models -- only if absent OR their Modelfile
#      changed since the last build (sha256 recorded in the volume)
#   5. touch the readiness marker the container healthcheck looks for
#   6. hand the foreground back to `ollama serve` (exec-style wait) so the
#      container's lifetime == the server's lifetime
#
# Idempotent by construction: on a second `docker compose up` with a warm
# volume, steps 3 and 4 are pure no-ops (no re-download, no re-create) and the
# service is healthy in seconds. This is why the model volume exists.
#
# The marker in step 5 is what makes `depends_on: condition: service_healthy`
# meaningful for the app: without it ollama reports healthy the moment its HTTP
# port opens, and the app's first /decide would 500 against a model that has not
# been built yet.
set -eu

MODELFILE_DIR="${GEODISPATCH_MODELFILE_DIR:-/modelfiles}"
BASE_MODEL="${GEODISPATCH_BASE_MODEL:-qwen2.5:3b}"
READY_MARKER="${GEODISPATCH_READY_MARKER:-/tmp/geodispatch-models-ready}"
# Inside the mounted volume on purpose: it must outlive the container so a warm
# restart can tell "already built from this exact Modelfile" from "rebuild me".
STAMP_DIR="${GEODISPATCH_STAMP_DIR:-/root/.ollama/.geodispatch-build}"

log() { echo "[init-models] $*"; }

# Any earlier run's marker must not be trusted — this container has not
# finished provisioning yet.
rm -f "$READY_MARKER"

log "starting ollama serve (OLLAMA_MAX_LOADED_MODELS=${OLLAMA_MAX_LOADED_MODELS:-unset})"
ollama serve &
SERVE_PID=$!

# ---------------------------------------------------------------------------
# 2. Wait for the server to accept API calls before doing anything with it.
#    `ollama list` is a client->server round trip, so it succeeding proves the
#    HTTP API is really up (not just the process alive).
# ---------------------------------------------------------------------------
waited=0
until ollama list >/dev/null 2>&1; do
    # If serve died (bad env, port clash, corrupt volume), fail loudly now
    # instead of spinning for 60s and reporting a useless timeout.
    if ! kill -0 "$SERVE_PID" 2>/dev/null; then
        log "FATAL: 'ollama serve' exited during startup"
        wait "$SERVE_PID"
        exit 1
    fi
    waited=$((waited + 1))
    if [ "$waited" -gt 60 ]; then
        log "FATAL: ollama API did not come up within 60s"
        kill "$SERVE_PID" 2>/dev/null || true
        exit 1
    fi
    sleep 1
done
log "ollama API is up after ${waited}s"

# ---------------------------------------------------------------------------
# 3. Base model — pull only if the volume doesn't already have it.
#    `ollama list` output is matched on the exact tag; qwen2.5:3b and
#    qwen2.5:1.5b must not be confused for one another.
# ---------------------------------------------------------------------------
has_model() {
    # $1 = exact model reference as shown by `ollama list` (name column)
    ollama list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -qx "$1"
}

if has_model "$BASE_MODEL"; then
    log "base model $BASE_MODEL already present — skipping pull"
else
    log "pulling base model $BASE_MODEL (first run only; this is the slow step)"
    ollama pull "$BASE_MODEL"
    log "pulled $BASE_MODEL"
fi

# ---------------------------------------------------------------------------
# 4. The three hazard models. Rebuilt only when missing or when the Modelfile
#    changed — an `ollama create` off an already-pulled base is cheap (seconds,
#    no download) but not free, and skipping it keeps warm starts fast.
#
#    Only the three production Modelfiles are built. Modelfile.earthquake-test15b
#    .txt is deliberately excluded — docs/MODELFILES.md marks it experimental and
#    "must never serve /decide"; the glob-free explicit list keeps it that way.
# ---------------------------------------------------------------------------
mkdir -p "$STAMP_DIR"

build_if_needed() {
    tag="$1"
    modelfile="$MODELFILE_DIR/$2"

    if [ ! -f "$modelfile" ]; then
        log "FATAL: $modelfile not found (is ./modelfiles mounted?)"
        return 1
    fi

    stamp="$STAMP_DIR/$tag.sha256"
    current="$(sha256sum "$modelfile" | awk '{print $1}')"

    if has_model "$tag:latest" && [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$current" ]; then
        log "$tag already built from an unchanged $2 — skipping create"
        return 0
    fi

    log "building $tag from $2"
    ollama create "$tag" -f "$modelfile"
    echo "$current" > "$stamp"
    log "built $tag"
}

build_if_needed geodispatch-earthquake Modelfile.earthquake
build_if_needed geodispatch-flood      Modelfile.flood
build_if_needed geodispatch-heatwave   Modelfile.heatwave

# ---------------------------------------------------------------------------
# 5. Readiness marker — the healthcheck's second condition (see compose).
# ---------------------------------------------------------------------------
touch "$READY_MARKER"
log "provisioning complete — models ready:"
ollama list

# ---------------------------------------------------------------------------
# 6. Hand the foreground back to the server. `wait` propagates its exit code,
#    so if ollama dies the container dies (and compose can restart it) rather
#    than lingering as a healthy-looking husk.
# ---------------------------------------------------------------------------
wait "$SERVE_PID"
