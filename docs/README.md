# GeoDispatch AI Agent — Setup Guide

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



