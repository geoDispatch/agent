# GeoDispatch — Test Suite Guide

This documents everything in `tests/`. The suite builds up in layers: first confirm
the wire contract is honored, then confirm the model produces reasonable output,
then confirm the whole pipeline works end-to-end, then confirm it survives things
going wrong. Each layer catches a different class of bug — a test passing at one
layer doesn't mean the next layer is fine.

Run everything from the **repo root**. `.venv/bin/python tests/<file>.py` (or plain
`python` with the venv activated). Files marked **Needs Ollama** require the
`geodispatch-*` models built and Ollama running (see `docs/README.md` Setup).

---

## 1. `validate_contract.py`
**Checks:** that `models/schemas.py` actually accepts the real, locked contract
JSON (`contracts/examples/ai_request.json` / `ai_response.json`) — not a fixture,
the real files the team agreed on.
**Why it exists:** an earlier version of this test validated against a fabricated
placeholder contract instead of the real one, and passed cleanly while being
meaningless. This test now loads the real `examples[]` array from each file and
fails loudly if those files are missing or don't match `AgentRequest`/`AgentResponse`.
**Needs Ollama:** No.
**Runtime:** instant.
```bash
.venv/bin/python tests/validate_contract.py
```

## 2. `test_quality.py`
**Checks:** sends 10 synthetic Arabic/French/English (including code-switched)
device batches to the real per-hazard models and checks that every response is
valid JSON matching the `DeviceDecision` shape, with an SMS that fits one
segment.
**Why it exists:** the original go/no-go harness — decides whether `qwen2.5:3b`
is good enough to use at all, before building anything on top of it.
**Tests the Modelfiles.** It sends no system message (an Ollama system message
would *replace* the Modelfile's baked-in `SYSTEM`), and routes each case to
`geodispatch-<its own disaster_type>`. It used to do neither, so every result
before 2026-08-30 was a verdict on an ad-hoc prompt in the test file rather than
on any shipped model.
**Scope limit:** its cases carry no `nearest_shelters`, so they exercise the
no-shelter SMS fallback, not shelter-name fidelity.
**Needs Ollama:** Yes — `make build-models` first.
**Runtime:** ~5-10 min (two cold model loads at ~83 s each on this box).
```bash
.venv/bin/python tests/test_quality.py
# or measure the bare base model instead of the shipped prompts:
OLLAMA_MODEL=qwen2.5:3b .venv/bin/python tests/test_quality.py
```

## 3. `live_notconnected.py`
**Checks:** that a device with `reachability_status: NOT_CONNECTED` only ever
gets `action: rescue_flag` (if close) or `action: none` (if far) — never `sms`
or `both`.
**Why it exists:** confirmed with a teammate (Ilias, network side) that SMS
delivery to an unconnected device isn't reliable enough to attempt. Earlier
versions of the model ignored this and sent SMS anyway, even under adversarial
conditions (max severity, tsunami risk). This test targets that exact failure
mode directly.
**Tests the Modelfiles.** It goes through `services.ollama.call_agent`, which
sends no system message, so the Modelfile's baked-in `SYSTEM` prompt is what
actually runs — and unlike `test_quality.py` its requests are real
`AgentRequest`s with `nearest_shelters` populated.
**Needs Ollama:** Yes.
**Runtime:** ~1-2 min.
```bash
.venv/bin/python tests/live_notconnected.py
```

## 4. `test_e2e.py`
**Checks:** builds 18 realistic batches spanning all three hazards, every zone
(red/orange/green), every `reachability_status`, and varying network conditions;
POSTs each through the real `/decide` endpoint (via FastAPI's TestClient); validates
every response against the schema; reports pass/fail and latency per batch.
**Why it exists:** this is the actual Week 1 exit criteria — proof the whole
pipeline (schema → prompt → model → schema) works end-to-end, not just that
individual pieces work in isolation.
**Needs Ollama:** Yes.
**Runtime:** ~15-20 min (batch latency scales with device count on CPU-only
hardware — this is expected, not a hang).
```bash
.venv/bin/python tests/test_e2e.py
```

## 5. `test_faults.py`
**Checks:** points the app at a dead port (connection refused) and a "black hole"
port (accepts the connection, never replies) and confirms `/decide` returns a
clean HTTP 500 — fast on refusal, via the read timeout on a hang — and that the
app stays up and answers the *next* request normally.
**Why it exists:** the Ollama client originally had no timeout at all
(`timeout=None`), so a hung Ollama would hang `/decide` forever with no way to
recover. This test exists to prove that failure mode is actually closed, not just
assumed fixed.
**Needs Ollama:** No (the point is testing what happens when Ollama-like
infrastructure is unavailable/broken).
**Runtime:** ~10-15 sec.
```bash
.venv/bin/python tests/test_faults.py
```

## 6. `test_semantic_garbage.py`
**Checks:** feeds input that's schema-valid but semantically strange — empty or
whitespace-only strings, absurd distances (e.g. 99999km), contradictory
zone/severity/reachability combinations — and confirms the pipeline still returns
a well-formed response instead of crashing.
**Why it exists:** Pydantic validation catches malformed *shape*, but says nothing
about nonsensical *values* within a valid shape. Real-world data (sensor glitches,
bad GPS fixes) will occasionally look like this — the system needs to survive it
gracefully, not necessarily "get it right."
**Needs Ollama:** Yes.
**Runtime:** ~2-3 min.
```bash
.venv/bin/python tests/test_semantic_garbage.py
```

## 7. `test_concurrent.py`
**Checks:** fires 3 overlapping `/decide` requests (different hazards, different
event IDs and phone numbers) at a real running uvicorn server simultaneously, and
confirms every response matches its own request with no data crossing between
them, and the server stays up afterward.
**Why it exists:** a real deployment may receive overlapping batches (e.g. Go
dispatching earthquake and flood zones at the same time). This is a **stability**
test, not a speed test — it does not assert anything about how fast the responses
come back, only that they don't get mixed up and nothing crashes.
**Needs Ollama:** Yes.
**Runtime:** varies with hardware (can be several minutes if hazard-switching
forces model reloads — see the latency note in `docs/README.md`).
```bash
.venv/bin/python tests/test_concurrent.py
```

## 8. `test_max_devices.py`
**Checks:** runs a full 20-device batch (the schema's maximum) through
`call_agent`, and confirms all 20 devices get a decision, in the correct order,
with no silent drops or truncation.
**Why it exists:** every other test uses 1-3 devices per batch. Nothing else
proves the system handles a genuinely large batch, which is the realistic
worst case Go could actually send.
**Needs Ollama:** Yes.
**Runtime:** ~10-12 min (serialized, one device at a time on this hardware — not
a hang).
```bash
.venv/bin/python tests/test_max_devices.py
```

---

## Not covered by `tests/` — shelter-name fidelity

Nothing in `tests/` checks that a non-empty `sms_message` names **this batch's
real shelter**. `test_quality.py`'s synthetic cases carry no `nearest_shelters` at
all, and `live_notconnected.py` asserts on `action` and SMS emptiness, not on the
message text. That gap was covered ad hoc on 2026-08-30 by a 6-case probe through
`services.ollama.call_agent` (one distinctive shelter name per case, all three
hazards) which found the name reproduced verbatim in only 3 of 6 cases and in
both clauses in 1 of 6 — see the "Known limitation" section of
`docs/MODELFILES.md` for the measurements and why it was not pursued further.

If you promote that probe into `tests/`, note the constraint that shaped it: on a
7.6 GB box with `OLLAMA_MAX_LOADED_MODELS=1`, a 6-case run spanning three hazards
gets OOM-killed. Run one hazard pair per invocation.

---

## Quick sanity check vs. full confidence run

**Quick check** (~2-3 min total) — enough to confirm nothing is obviously broken
after a code change:
```bash
.venv/bin/python tests/validate_contract.py
.venv/bin/python tests/live_notconnected.py
```

**Full confidence suite** (~40-50 min total) — run this before a demo or before
telling a teammate "it's ready":
```bash
.venv/bin/python tests/validate_contract.py
.venv/bin/python tests/test_quality.py
.venv/bin/python tests/live_notconnected.py
.venv/bin/python tests/test_e2e.py
.venv/bin/python tests/test_faults.py
.venv/bin/python tests/test_semantic_garbage.py
.venv/bin/python tests/test_concurrent.py
.venv/bin/python tests/test_max_devices.py
```