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

- **Latency (CPU-only).** Each device is one blocking model call, run in series, so a single decision takes **~20–110 s** (cold model load is the slow end) and batch latency scales linearly with device count. This is a known **Week 2** item (per-device concurrency / batching) — not a bug to report.
- **No language/locale field** in the contract yet. SMS defaults to **bilingual Arabic + French**.
- **Broken Ollama install.** If `ollama run` fails with `llama-server binary not found`, your Ollama install is partial/broken. Reinstall via the official script (Prerequisites) — do **not** try to fix a source build by hand.

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



