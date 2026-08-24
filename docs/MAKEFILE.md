# GeoDispatch — Makefile Guide

This documents every `make` target in the repo root `Makefile`. It exists so a
teammate can run the whole project without memorizing the manual commands in
`docs/README.md` — the Makefile is a shortcut layer on top of those, not a
replacement. If a `make` target fails, the manual steps in `docs/README.md`
are the fallback for debugging exactly where it broke.

Run all of these from the **repo root**.

---

## Setup targets

### `make help`
Lists every available target with a one-line description. This is the
default target — running plain `make` with no arguments does this.
```bash
make
# or
make help
```

### `make venv`
Creates `.venv/` and installs everything in `requirements.txt`
(fastapi, uvicorn, pydantic, ollama). Safe to re-run.
```bash
make venv
```

### `make pull-model`
Pulls the base model: `ollama pull qwen2.5:3b`. Needs Ollama installed and
running first.
```bash
make pull-model
```

### `make build-models`
Builds the three hazard-specific models from their Modelfiles:
`geodispatch-earthquake`, `geodispatch-flood`, `geodispatch-heatwave`.
Needs `pull-model` done first (they're all built `FROM qwen2.5:3b`).
```bash
make build-models
```

### `make setup`
Runs `venv` → `pull-model` → `build-models` in order — the full
"get started from absolute zero" path.
```bash
make setup
```

### `make ollama-config`
Applies the `OLLAMA_MAX_LOADED_MODELS=1` systemd override. **Needs `sudo`** —
the target prints a warning before it runs, since it edits a system service
file and restarts Ollama. Only relevant if Ollama is running as a systemd
service (see `docs/README.md` for the manual-process alternative).
```bash
make ollama-config
```

---

## Running the service

### `make run`
Starts the FastAPI app: `uvicorn main:app` on port 8000. Requires Ollama to
already be running with the models built (`make setup` done first).
```bash
make run
```

### `make health`
Curls `localhost:8000/health` and pretty-prints the result. Use this to
confirm the server (started via `make run` in another terminal) is actually
up before sending real requests.
```bash
make health
```

---

## Testing targets

Every target that needs Ollama checks first (e.g. `ollama list` or a curl to
`localhost:11434`) and prints a clear message telling you to start Ollama
before failing — rather than a raw "connection refused" error.

### `make test-quick`
The fast sanity pair: `validate_contract.py` + `live_notconnected.py`.
**~2-3 minutes.** Run this after any code change before committing.
```bash
make test-quick
```

### `make test-full`
The full confidence suite — all 8 test files, in the order documented in
`docs/TESTS.md`. Prints a warning before the slow ones (`test_e2e.py`,
`test_max_devices.py`) so a 15-20 minute or 10-12 minute pause isn't
mistaken for a hang. **~40-50 minutes total.** Run this before a demo or
before telling a teammate "it's ready."
```bash
make test-full
```

### Individual test targets
Run any single test file directly, without the others:

| Target | Runs |
|---|---|
| `make test-contract` | `validate_contract.py` |
| `make test-quality` | `test_quality.py` |
| `make test-notconnected` | `live_notconnected.py` |
| `make test-e2e` | `test_e2e.py` |
| `make test-faults` | `test_faults.py` |
| `make test-garbage` | `test_semantic_garbage.py` |
| `make test-concurrent` | `test_concurrent.py` |
| `make test-max` | `test_max_devices.py` |

```bash
make test-e2e   # example: just the end-to-end suite
```

See `docs/TESTS.md` for what each individual test actually checks and why
it exists.

---

## Cleanup

### `make clean`
Removes `__pycache__` directories. Safe — does **not** touch `.venv`.

### `make clean-venv`
Separately removes `.venv/`. Kept as its own target (not part of `make
clean`) so a plain `make clean` can never accidentally delete your virtual
environment.
```bash
make clean-venv
```

---

## Fastest path for a new teammate

```bash
make setup      # venv + pull base model + build the 3 hazard models
make run        # start the server (separate terminal / background)
make health     # confirm it's up
make test-quick # fast sanity check
```

If anything in `make setup` fails, fall back to the manual step-by-step in
`docs/README.md`'s Setup section to see exactly which step broke.