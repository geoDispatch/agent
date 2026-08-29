# GeoDispatch AI Agent — Setup Guide

## Quick Start (new teammate)

A `Makefile` at the repo root wraps every command in this guide so you don't
have to memorize them. Fastest path from a fresh clone to a running server:

```bash
make setup     # create .venv + install deps, pull qwen2.5:3b, build the 3 geodispatch-* models
make run       # start the FastAPI server on http://localhost:8000
```

`make setup` already runs `make build-models`, so there's no separate build step.
On a low-RAM box (≤8 GB) also run `make ollama-config` **once** (needs sudo) to cap
Ollama to a single resident model — see the RAM constraint under Prerequisites.
Run `make help` to list every target (setup, run, health, the individual `test-*`
targets, cleanup). Quick sanity check after a change: `make test-quick`.

> Ollama must be running for `make setup`/`make run` (the Makefile checks and
> tells you if it isn't). If any step fails, fall back to the detailed manual
> steps below to debug one piece at a time — each `make` target just runs the
> documented command shown here.

Don't want to install Ollama and a virtualenv on your machine at all? There's a
containerized path that needs only Docker — one command, `docker compose up
--build`. See [Docker](#docker-alternative-to-the-manualmakefile-setup).

---

## What this is

GeoDispatch is a Python AI agent built for the **GSMA MENA Ignite Hackathon**. It triages disaster-response device batches (earthquake, flood, heatwave) by running each device through a **local LLM** (Ollama, `qwen2.5:3b` base with three hazard-specific system prompts) and returns a structured per-device decision — SMS, physical-rescue flag, both, or none — plus a government-facing summary. It exposes a single FastAPI endpoint, `POST /decide`, that takes one validated zone batch and returns validated decisions. Everything runs on-device: no cloud model calls, no data leaves the machine.

## Prerequisites

- **Python 3.10+** — the contract models use modern typing. (This box runs 3.14, but 3.10 is a safe minimum.)
- **Ollama** — install with:
  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  ```
- **~6 GB free RAM.** Each `geodispatch-*` model is ~1.9 GB. ⚠️ **Known constraint:** on a 7.6 GB machine, letting Ollama hold all three resident at once caused swap-thrashing. Cap it to one loaded model at a time (see Setup step 5).

## Setup

**1. Clone and enter the repo**
```bash
git clone <repo-url> agent
cd agent
```

**2. Create a virtualenv.** `.venv/` is gitignored (not committed) — make your own:
```bash
python3 -m venv .venv
source .venv/bin/activate          # then use plain `python`, `uvicorn`, ...
# or skip activation and call the venv binaries directly: .venv/bin/python ...
```

**3. Install dependencies**
```bash
pip install -r requirements.txt    # fastapi, uvicorn, pydantic v2, ollama
```

**4. Pull the base model**
```bash
ollama pull qwen2.5:3b
```

**5. Cap Ollama to one resident model.** ⚠️ Set `OLLAMA_MAX_LOADED_MODELS=1` unless you have **>8 GB free RAM** — with all three ~1.9 GB models resident on a 7.6 GB box we hit swap-thrashing. `export` alone does **not** affect a systemd-managed Ollama; use a service override:
```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=1"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
```
(If you run Ollama manually instead of via systemd, `export OLLAMA_MAX_LOADED_MODELS=1` in the shell that launches `ollama serve`.)

**6. Build the three hazard models** from their Modelfiles:
```bash
ollama create geodispatch-earthquake -f modelfiles/Modelfile.earthquake
ollama create geodispatch-flood      -f modelfiles/Modelfile.flood
ollama create geodispatch-heatwave   -f modelfiles/Modelfile.heatwave
```

**7. Verify** — `ollama list` should show the base model plus all three:
```
qwen2.5:3b
geodispatch-earthquake:latest
geodispatch-flood:latest
geodispatch-heatwave:latest
```

## Running the server

The FastAPI entrypoint is `main:app`. Ollama must be running first (systemd starts it on boot; otherwise `ollama serve`).
```bash
uvicorn main:app --host 0.0.0.0 --port 8000     # add --reload for dev
```
Confirm it's up (default port **8000**):
```bash
curl http://localhost:8000/health
# -> {"status":"ok"}
```
The triage endpoint is `POST /decide` — it takes one `AgentRequest` (a single zone batch) and returns an `AgentResponse`. Interactive docs at `http://localhost:8000/docs`.

## Testing it

Run all of these from the **repo root**. The three Ollama-backed ones need Ollama running and the models built (Setup steps 4–7). Use `.venv/bin/python` (or plain `python` with the venv activated).

- **`tests/validate_contract.py`** — validates the schemas against the locked contract examples. Fast; needs only pydantic, **no Ollama**.
  ```bash
  .venv/bin/python tests/validate_contract.py
  ```
- **`tests/test_quality.py`** — LLM output quality harness (10 multilingual cases). **Needs Ollama.**
  ```bash
  .venv/bin/python tests/test_quality.py
  ```
- **`tests/test_e2e.py`** — full end-to-end: builds 18 batches across all hazards/zones, POSTs each through the app, validates every response. **Needs Ollama.** ⏱️ Takes **~15–20 minutes** on modest hardware (last clean run averaged ~48 s/batch × 18 batches). This is expected — **it is not a hang.**
  ```bash
  .venv/bin/python tests/test_e2e.py
  ```
- **`tests/live_notconnected.py`** — targeted check for the `NOT_CONNECTED` reachability rule (unreachable devices must never get SMS/both; near → rescue_flag, far → none).
  ```bash
  .venv/bin/python tests/live_notconnected.py
  ```

## Docker (alternative to the manual/Makefile setup)

Prefer not to install Ollama, a virtualenv, and the models by hand? The repo
ships a two-service Compose stack that does all of it inside containers:

```bash
docker compose up --build
```

Then, from another terminal:

```bash
curl http://localhost:8000/health
# -> {"status":"ok"}

curl -sS -X POST http://localhost:8000/decide \
  -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json;print(json.dumps(json.load(open("contracts/examples/ai_request.json"))["examples"][0]))')"
```

That `/decide` takes ~2 minutes to return and is **not** hung — it's one cold
model load (see Known limitations). Verified against this stack, the earthquake
example above returns:

```json
{"event_id":"EQ-2024-001","zone":"red","decisions":[{"phone":"+212612345678",
"zone_confirmed":"red","zone_escalated":false,"action":"both","sms_message":
"Aftershocks expected. Leave the building and proceed to École Ibn Battouta for
shelter. Rescue has been alerted to your location.","rescue_priority":1,
"confidence":0.9,"reasoning":"Reachable by SMS (CONNECTED_SMS) in a red zone with
HIGH aftershock risk — send SMS AND flag rescue; dispatch first."}],
"gov_narrative":"1 of 1 devices in the red zone flagged for rescue; SMS
dispatched to 1.","request_qos":false,"confidence":0.9}
```

(`sms_message` and `reasoning` are model-generated, so their wording varies run to
run; the structure, `action`, `rescue_priority` and `confidence` are stable.)

⏱️ **The first run is slow, and it's almost entirely the download.** Inside the
container the `ollama` service pulls `qwen2.5:3b` (~1.9 GB) and then builds the
three `geodispatch-*` models, and the `app` service deliberately waits for all of
that before it starts. Budget **~20–40 minutes on a healthy link**; on a slow or
stalling one it can be far worse (see *First run stuck at N% forever* below).
Nothing is hung — watch progress with `docker compose logs -f ollama`.

**Every run after the first takes seconds.** The models live in a named volume
(`geodispatch-ollama-models`) and are neither re-downloaded nor rebuilt. Measured
on this box: `docker compose down` followed by `docker compose up -d --wait`
brought both services to `healthy` in **12 seconds**. Once warm, a
single-device `/decide` through the stack took **112 s** — the same
cold-model-load latency as the Makefile flow (see Known limitations); Docker adds
nothing measurable to it.

### What the two services are

| Service  | Image                   | Ports                                  | Role |
|----------|-------------------------|----------------------------------------|------|
| `ollama` | `ollama/ollama:0.32.15` | `11434` **internal only**              | Runs Ollama; pulls the base model and builds the three hazard models on startup |
| `app`    | built from `Dockerfile` | `8000` → **published to the host**     | The FastAPI app (`uvicorn main:app`) |

Only port **8000** is published. Ollama's `11434` is reachable from the `app`
container as `http://ollama:11434` but is *not* exposed to the host — the host
usually already runs its own Ollama on 11434 for the Makefile flow, and
publishing would clash with it. To inspect the containerized one:

```bash
docker compose exec ollama ollama list      # what's built in the volume
docker compose logs -f ollama               # startup / pull / build progress
```
(There's a commented-out `ports:` block in `docker-compose.yml` mapping host
`11435` if you really need to curl it directly while debugging.)

### Startup ordering is enforced, not hoped for

`app` declares `depends_on: ollama: condition: service_healthy`, and the
`ollama` healthcheck requires **two** things: the API answering *and* a readiness
marker that `docker/init-models.sh` writes only after all three
`geodispatch-*` models exist. Without the second condition Ollama would report
healthy the moment its port opened and the app's first `/decide` would 500
against a model that hadn't been built yet.

### Idempotent model provisioning

`docker/init-models.sh` is the `ollama` service's entrypoint. Every startup it
starts `ollama serve`, waits for the API, then:

- pulls `qwen2.5:3b` **only if** the volume doesn't already have it;
- builds each `geodispatch-*` model **only if** it's missing or its Modelfile
  changed (the script records a `sha256` of each Modelfile in the volume).

So re-running `docker compose up` never re-downloads or needlessly rebuilds, and
editing `modelfiles/Modelfile.flood` then restarting rebuilds **just** that
model. `modelfiles/` is bind-mounted read-only, which is what makes that loop
work without a rebuild of the app image. The experimental
`Modelfile.earthquake-test15b.txt` is deliberately **not** built (see
[MODELFILES.md](MODELFILES.md)).

### First run stuck at *N*% forever (slow link)? Seed the volume

`ollama pull` splits the 1.9 GB layer into 16 parts and retries stalled ones
indefinitely. On a link that keeps stalling you'll see the percentage climb, drop
back, and log `part N stalled; retrying` — it can effectively never finish. That
happened on this box (the pull sat around 9–33% for over an hour, with the
progress counter resetting).

If you already have `qwen2.5:3b` in a **host** Ollama (i.e. you ran `make setup`
before), copy it straight into the volume instead of downloading it twice:

```bash
docker compose stop ollama
docker run --rm \
  -v geodispatch-ollama-models:/dest \
  -v "$HOME/.ollama/models:/src:ro" \
  --entrypoint sh ollama/ollama:0.32.15 -c '
    rm -f /dest/models/blobs/*-partial*
    mkdir -p /dest/models/blobs /dest/models/manifests
    cp -a /src/blobs/. /dest/models/blobs/
    cp -a /src/manifests/. /dest/models/manifests/
    chown -R root:root /dest/models'
docker compose up -d --wait
```

Deleting the `*-partial*` files first matters — a half-written blob is what the
next pull would otherwise try to resume. The init script then reports
`base model qwen2.5:3b already present — skipping pull` and goes straight to
building the three models (~10 s total, no network). This is a shortcut for a bad
link, not a required step: on a decent connection plain `docker compose up
--build` needs nothing extra.

### RAM constraint applies here too

The compose file sets `OLLAMA_MAX_LOADED_MODELS=1` on the `ollama` service, for
exactly the reason documented in Setup step 5 and Known limitations: three
resident ~1.9 GB models on a 7.6 GB box caused swap-thrashing. In Docker it's
just an environment variable — **no `sudo`, no systemd override needed**, which
is the one setup step containerizing genuinely removes. `GEODISPATCH_OLLAMA_*`
timeout and in-flight knobs are set on the `app` service to the same defaults
the code uses; they're spelled out in `docker-compose.yml` so they're easy to
tune per box.

### Everyday commands

```bash
docker compose up --build          # start (rebuild app image if code changed)
docker compose up -d --wait        # start detached, return only when both are healthy
docker compose logs -f app         # app logs (per-request latency lines)
docker compose down                # stop; KEEPS the model volume
docker compose down -v             # stop and DELETE models (full re-download!)
docker compose exec app python -c "import httpx;print(httpx.get('http://ollama:11434/api/tags').json())"
```

`docker compose down` is the safe one — the named volume survives, so the next
`up` is a warm start. Only use `-v` if you actually want to re-pull ~1.9 GB.

The Docker path and the Makefile path are independent and can coexist: the app
reads `OLLAMA_HOST` (compose sets `http://ollama:11434`) and falls back to
`http://127.0.0.1:11434` when unset, so `make setup` / `make run` against a host
Ollama still work exactly as before.

## Known limitations

Be aware of these before filing them as bugs:

- **Latency is a hardware ceiling (~20–110 s/device), not a missing optimization.** Each device is one blocking model call and batch latency scales linearly with device count. Per-device **concurrency was tried and reverted**: setting `OLLAMA_NUM_PARALLEL=2` (to let Ollama process device calls in parallel) was **confirmed non-viable on this box** — free RAM collapsed to **~191 MB with ~5 GB of swap within seconds** (two ~1.9 GB model instances resident at once on a 7.6 GB machine). The async client (`ollama.AsyncClient` + `asyncio.gather`) is still in place and correct; it is simply **inert on this hardware** — same-model calls serialize server-side, so firing them concurrently doesn't overlap — and becomes a real win only on a box with more RAM/GPU. So the latency is a measured hardware limit, not an un-attempted improvement — don't file it as a bug.
- **No language/locale field** in the contract yet. SMS defaults to **bilingual Arabic + French**.
- **Broken Ollama install.** If `ollama run` fails with `llama-server binary not found`, your Ollama install is partial/broken. Reinstall via the official script (Prerequisites) — do **not** try to fix a source build by hand.

## Fault tolerance

The `/decide` pipeline is built to fail cleanly rather than hang or crash the process:

- **Ollama request timeout.** Every model call runs under an `httpx` timeout — **connect 5 s** (a down or restarting Ollama fails fast) and **read 240 s** (generous enough to clear a cold model load plus generation, which can take ~110 s). Without it, a hung Ollama would block `/decide` forever. Both are env-overridable:
  ```bash
  export GEODISPATCH_OLLAMA_CONNECT_TIMEOUT=5     # seconds, default 5
  export GEODISPATCH_OLLAMA_READ_TIMEOUT=240      # seconds, default 240
  ```
  When Ollama is down, times out, or returns unparseable output even after the one built-in retry, `/decide` returns a clean **500** (the full traceback is logged server-side only, never sent to the caller) and the app stays up for the next request.
- **Bounded in-flight calls.** `call_agent` sends at most `GEODISPATCH_OLLAMA_MAX_INFLIGHT` model calls at once (**default 1**, matching this box's serialized Ollama). This stops a large batch from parking many requests on open connections where they would trip the read timeout while queued behind each other — a 20-device batch fails that way otherwise. Raise it in lockstep with `OLLAMA_NUM_PARALLEL` on hardware that can actually parallelize.

**Robustness tests.** Run from the **repo root**, same conventions as the Testing section:

- **`tests/test_faults.py`** — fault injection: points the app at a dead port (connection refused) and at a black-hole port (accepts, never replies), confirming `/decide` returns a clean **500** — fast on refusal, via the read timeout on a hang (not an infinite hang) — and stays up for the next request. **No Ollama needed** (the point is that Ollama is broken/absent).
  ```bash
  .venv/bin/python tests/test_faults.py
  ```
- **`tests/test_semantic_garbage.py`** — schema-valid but semantically nonsensical input (empty/whitespace strings, contradictory reachability/zone/distance combos); confirms `call_agent` survives without crashing and still returns a valid `AgentResponse`. **Needs Ollama.**
  ```bash
  .venv/bin/python tests/test_semantic_garbage.py
  ```
- **`tests/test_concurrent.py`** — fires 3 overlapping `/decide` requests at a real uvicorn server; confirms the app stays stable under concurrent load with no cross-talk between requests (each response matches its own request). Stability test, **not** a speed test. **Needs Ollama.**
  ```bash
  .venv/bin/python tests/test_concurrent.py
  ```
- **`tests/test_max_devices.py`** — runs the schema-max **20-device** batch through `call_agent`; confirms nothing is truncated and all 20 phones reconcile 1:1 and in order. **Needs Ollama.** ⏱️ ~12 min (serialized), not a hang.
  ```bash
  .venv/bin/python tests/test_max_devices.py
  ```

## Troubleshooting

**`llama-server binary not found` (or `ollama run` errors immediately).**
Your Ollama runtime is incomplete. Reinstall with the official script and restart the service:
```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl restart ollama
```

**`address already in use` when starting Ollama.**
Ollama is *already* running as a systemd service — don't also launch `ollama serve` by hand. Check and use the running one:
```bash
systemctl status ollama      # is it already up?
ollama ps                    # what's loaded right now
```
Only run `ollama serve` manually if the service is stopped.

**Contract validation fails / "fixture not found".**
`tests/validate_contract.py` validates the **real** contract files at `contracts/examples/ai_request.json` and `contracts/examples/ai_response.json`. These are JSON Schema documents whose actual instances live in their top-level `examples[]` array (the test loads those). Make sure you have the real committed files — a placeholder/empty stub will fail validation.

**`/decide` returns HTTP 500 mid-run.**
Usually Ollama was restarted or ran out of memory while a request was in flight (see the RAM constraint above). Check `ollama ps` and `journalctl -u ollama --since "5 min ago"` before suspecting the app.



