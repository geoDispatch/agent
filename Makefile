# GeoDispatch — task runner
#
# Every target below maps to a command already documented in docs/README.md
# and docs/TEST.md. Nothing here is invented. New here? Run `make help`.
#
# Targets that talk to Ollama check it's up first and print a clear "start
# Ollama" message instead of failing with a raw connection-refused error.

VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip
PORT := 8000

.DEFAULT_GOAL := help
.PHONY: help setup venv pull-model build-models ollama-config run health \
        test-quick test-full test-contract test-quality test-notconnected \
        test-e2e test-faults test-garbage test-concurrent test-max \
        clean clean-venv check-ollama check-venv

help: ## Show this help (default target)
	@echo "GeoDispatch — available make targets:"
	@echo ""
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-22s %s\n", $$1, $$2}'
	@echo ""
	@echo "New teammate fastest path:  make setup && make run"
	@echo "Low-RAM box (<=8GB) also run once:  make ollama-config  (needs sudo)"

# ---------------------------------------------------------------------------
# Setup / getting started from zero
# ---------------------------------------------------------------------------

setup: ## Zero-to-ready: venv + pull-model + build-models (needs Ollama)
	@$(MAKE) venv
	@$(MAKE) pull-model
	@$(MAKE) build-models
	@echo ""
	@echo "Setup complete. Start the server with:  make run"

venv: ## Create .venv and install requirements.txt
	python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt

pull-model: check-ollama ## Pull the base model qwen2.5:3b (needs Ollama)
	ollama pull qwen2.5:3b

build-models: check-ollama ## Build the three geodispatch-* models from Modelfiles (needs Ollama)
	ollama create geodispatch-earthquake -f modelfiles/Modelfile.earthquake
	ollama create geodispatch-flood      -f modelfiles/Modelfile.flood
	ollama create geodispatch-heatwave   -f modelfiles/Modelfile.heatwave

ollama-config: ## Cap Ollama to 1 resident model via systemd override (needs sudo)
	@echo ">>> This uses sudo to write /etc/systemd/system/ollama.service.d/override.conf"
	@echo ">>> (OLLAMA_MAX_LOADED_MODELS=1) and restart ollama. You'll be prompted for your password."
	sudo mkdir -p /etc/systemd/system/ollama.service.d
	printf '[Service]\nEnvironment="OLLAMA_MAX_LOADED_MODELS=1"\n' | sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null
	sudo systemctl daemon-reload
	sudo systemctl restart ollama
	@echo ">>> Applied. Verify with:  systemctl show ollama -p Environment"

# ---------------------------------------------------------------------------
# Running the server
# ---------------------------------------------------------------------------

run: check-venv check-ollama ## Start the FastAPI server on port 8000 (needs Ollama)
	$(PY) -m uvicorn main:app --host 0.0.0.0 --port $(PORT)

health: ## Curl /health and pretty-print (needs the server running)
	@curl -sf http://localhost:$(PORT)/health >/dev/null 2>&1 || { \
		echo "ERROR: server not reachable at http://localhost:$(PORT)."; \
		echo "Start it first:  make run"; \
		exit 1; \
	}
	@curl -sf http://localhost:$(PORT)/health | python3 -m json.tool

# ---------------------------------------------------------------------------
# Tests  (order & runtimes per docs/TEST.md)
# ---------------------------------------------------------------------------

test-quick: check-venv check-ollama ## Fast sanity pair: contract + notconnected, ~2-3 min (needs Ollama)
	$(PY) tests/validate_contract.py
	$(PY) tests/live_notconnected.py

test-full: check-venv check-ollama ## Full confidence suite: all 8 tests in order, ~40-50 min (needs Ollama)
	$(PY) tests/validate_contract.py
	$(PY) tests/test_quality.py
	$(PY) tests/live_notconnected.py
	@echo ">>> NEXT: test_e2e.py runs 18 batches end-to-end — expect ~15-20 min. This is NOT a hang."
	$(PY) tests/test_e2e.py
	$(PY) tests/test_faults.py
	$(PY) tests/test_semantic_garbage.py
	$(PY) tests/test_concurrent.py
	@echo ">>> NEXT: test_max_devices.py runs a 20-device batch serialized — expect ~10-12 min. This is NOT a hang."
	$(PY) tests/test_max_devices.py

test-contract: check-venv ## validate_contract.py — schema vs locked contract (no Ollama)
	$(PY) tests/validate_contract.py

test-quality: check-venv check-ollama ## test_quality.py — LLM output quality, 10 cases (needs Ollama)
	$(PY) tests/test_quality.py

test-notconnected: check-venv check-ollama ## live_notconnected.py — NOT_CONNECTED reachability rule (needs Ollama)
	$(PY) tests/live_notconnected.py

test-e2e: check-venv check-ollama ## test_e2e.py — 18-batch end-to-end, SLOW ~15-20 min (needs Ollama)
	@echo ">>> test_e2e.py runs 18 batches end-to-end — expect ~15-20 min. This is NOT a hang."
	$(PY) tests/test_e2e.py

test-faults: check-venv ## test_faults.py — fault injection / clean 500s (no Ollama)
	$(PY) tests/test_faults.py

test-garbage: check-venv check-ollama ## test_semantic_garbage.py — nonsensical-but-valid input (needs Ollama)
	$(PY) tests/test_semantic_garbage.py

test-concurrent: check-venv check-ollama ## test_concurrent.py — 3 overlapping requests, stability (needs Ollama)
	$(PY) tests/test_concurrent.py

test-max: check-venv check-ollama ## test_max_devices.py — 20-device batch, SLOW ~10-12 min (needs Ollama)
	@echo ">>> test_max_devices.py runs a 20-device batch serialized — expect ~10-12 min. This is NOT a hang."
	$(PY) tests/test_max_devices.py

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Remove __pycache__ dirs (safe; keeps .venv)
	find . -path ./$(VENV) -prune -o -type d -name __pycache__ -exec rm -rf {} +
	@echo "Removed __pycache__ dirs. (Run 'make clean-venv' to also delete $(VENV).)"

clean-venv: ## Delete .venv (destructive)
	rm -rf $(VENV)
	@echo "Removed $(VENV). Recreate it with 'make venv' or 'make setup'."

# ---------------------------------------------------------------------------
# Internal guards (not shown in help)
# ---------------------------------------------------------------------------

check-ollama:
	@curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 || { \
		echo "ERROR: Ollama is not reachable at http://localhost:11434."; \
		echo "Start it first:  sudo systemctl start ollama    (or run: ollama serve)"; \
		echo "Then verify with:  ollama list"; \
		exit 1; \
	}

check-venv:
	@test -x $(PY) || { \
		echo "ERROR: $(PY) not found — the virtualenv isn't set up."; \
		echo "Create it first:  make venv    (or: make setup)"; \
		exit 1; \
	}
