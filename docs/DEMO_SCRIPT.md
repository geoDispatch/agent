# GeoDispatch — Demo Script (Python AI Agent)

*Read this out loud or paraphrase — it's a script, not a spec. Everything here is grounded in the real system (`docs/README.md`) and what was actually tested on 2026-08-23. No invented capabilities, no invented numbers.*

*Scope: my part is the **decision brain**. Teammates own the Go supervisor (batching, dispatch, dashboard) and the CAMARA network/QoS side — I flag those boundaries where they come up.*

---

## 30-second pitch

"When a disaster hits — earthquake, flood, heatwave — we suddenly know where thousands of phones are and how reachable each one is. That's raw data. It doesn't tell a rescue team what to *do*.

The GeoDispatch AI agent is the decision brain that turns that raw device-and-location data into concrete life-safety actions, one person at a time. For every device it decides: send an evacuation SMS, flag this person for physical rescue, do both, or do nothing — and when it flags a rescue, it says who to reach **first**. It runs entirely on a local model on this laptop — no cloud, no data leaving the machine — and hands each decision back to our Go supervisor to dispatch and to update the government dashboard."

One more line if they want it: "Think of it as ER triage, but for a whole disaster zone — automated, and in the language people actually speak."

---

## Live walkthrough

**1 · Start the service.** (Ollama is already running with the three models built.)

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
curl http://localhost:8000/health
# -> {"status":"ok"}
```

Say: "The agent is a single FastAPI endpoint. Health check is green — it's live."

**2 · Send a real request.** Either open the interactive docs at `http://localhost:8000/docs` and hit `POST /decide`, or curl the real committed contract example:

```bash
curl -s -X POST http://localhost:8000/decide \
  -H 'Content-Type: application/json' \
  -d @contracts/examples/ai_request.json
```

Say: "This is one **zone batch** — Go groups devices by zone and sends me one batch at a time, up to 20 devices. This one's a red-zone earthquake: magnitude 6.8, HIGH aftershock risk, network congestion HIGH."

**3 · Walk the response.** "I return one decision per device. To show both kinds of decision in one view, here's the contract's canonical two-device response (`contracts/examples/ai_response.json`) — same red-zone earthquake. These example files are validated on every run by `tests/validate_contract.py`, so this is the real shape, not a mock-up."

```json
{
  "event_id": "EQ-2024-001",
  "zone": "red",
  "decisions": [
    {
      "phone": "+212612345678",
      "zone_confirmed": "red",
      "zone_escalated": false,
      "action": "sms",
      "sms_message": "ALERTE: Séisme détecté. Évacuez vers École Ibn Battouta (1.2km nord). Évitez les bâtiments endommagés.",
      "rescue_priority": 0,
      "confidence": 0.87,
      "reasoning": "Device reachable via SMS, located in red zone. Standard evacuation SMS sent. Shelter 1.2km away, capacity available."
    },
    {
      "phone": "+212698765432",
      "zone_confirmed": "red",
      "zone_escalated": false,
      "action": "rescue_flag",
      "sms_message": "",
      "rescue_priority": 1,
      "confidence": 0.93,
      "reasoning": "Device NOT_CONNECTED. Location within 2km of epicenter. High collapse risk zone. Cannot reach via any channel — rescue dispatch required."
    }
  ],
  "gov_narrative": "Red zone: 2 devices processed. 1 reachable via SMS — evacuation message sent. 1 unreachable (NOT_CONNECTED) in high-collapse-risk area — rescue team dispatched. QoS boost requested to improve SMS delivery in congested area.",
  "request_qos": true,
  "confidence": 0.90
}
```

**Per-device fields, in plain terms:**

- **`phone`** — which person this decision is about.
- **`zone_confirmed` / `zone_escalated`** — the agent re-confirms the zone it was handed. If it judged the situation worse than that zone, `zone_escalated` flips to `true` and Go logs it for audit. Here it agreed — `false`.
- **`action`** — the actual instruction. Four values: `sms`, `rescue_flag`, `both`, `none`.
- **`sms_message`** — the exact text we'd send. Empty on purpose for a rescue-only device.
- **`rescue_priority`** — the dispatch order. "**`1` means send a team to this person first.** `0` means not flagged for rescue at all." So device 1 (priority 0) gets a text and no rescue; device 2 (priority 1) is top of the rescue queue.
- **`confidence`** — how sure the agent is about that one device (0.87 and 0.93 here).
- **`reasoning`** — an internal audit note. "This is for our logs — **never** sent to a survivor or shown on the public dashboard."

**The two decisions tell the whole story:**
- Device 1 (`+212612345678`) is reachable by SMS → `action: "sms"`, a real evacuation text pointing at a shelter 1.2 km away, `rescue_priority: 0`.
- Device 2 (`+212698765432`) is `NOT_CONNECTED` → `action: "rescue_flag"`, empty SMS, `rescue_priority: 1`. "We can't reach this phone at all and they're near the epicenter — so instead of texting into the void, we put them at the front of the rescue line."

**Batch-level fields:**
- **`gov_narrative`** — a plain-language situation line for the government dashboard. Counts only, no phone numbers. "This is the sentence an official actually reads."
- **`request_qos`** — a flag. "When a rescue is needed and network priority isn't already boosted, I ask Go to call the **CAMARA QoS** API to prioritize this zone's traffic. That's my teammate's part — I raise the flag, Go makes the call."
- **`confidence`** (top level, 0.90) — overall confidence across the batch.

Close with: "One call: one person gets a text, one gets a rescue team, the dashboard gets a summary, the network gets a boost request. That's the whole job."

---

## Technical talking points

*(pick what fits the room and the clock)*

**Three hazard-specific models, not one generic one.** Same base model (`qwen2.5:3b`, temperature 0.2 for determinism), but three separate system prompts: `geodispatch-earthquake`, `-flood`, `-heatwave`. The reasoning genuinely differs:
- **Earthquake** weighs aftershock and tsunami risk — either pushes someone up the rescue priority even if they're reachable.
- **Flood** weighs distance and evacuation timing — if someone's far with a flaky link, an SMS may arrive too late, so it leans toward rescue.
- **Heatwave** treats `severity` as a plain 0–10 danger scale, not a Richter magnitude.

"One prompt trying to caveat all three hazards gets muddy. Three focused prompts each stay sharp."

**Pydantic schema validation as a safety layer around the LLM.** "A language model is creative by nature; a dispatch system can't be — so the model is boxed in on both sides. Requests that don't match the contract are rejected by the framework *before my code runs* — an automatic **422**. Every response the model produces is validated against the strict `DeviceDecision` schema, and I force its decoder to emit JSON only. Bad or off-contract output gets exactly one retry; if it still fails, the request fails cleanly rather than shipping garbage downstream. The contract enforces correctness in **both** directions — the model literally cannot hand Go something Go can't parse."

**The `NOT_CONNECTED` rule — real teammate input, encoded into behavior.** "This came straight from Ilias on the network side: **SMS can't reliably reach a device that's `NOT_CONNECTED`.** That's a domain fact a language model wouldn't reliably infer, so it's a hard rule baked into all three models — if a device is `NOT_CONNECTED`, the action can only be `rescue_flag` or `none`, never SMS. And I tested it adversarially: max-danger earthquake, severity 8.2, tsunami risk on — exactly the context that would tempt the model to 'just text everyone.' A `NOT_CONNECTED` device close by (1.5 km) correctly becomes `rescue_flag`; too far (25 km) becomes `none`; reachable devices still get their SMS. That's `tests/live_notconnected.py`."

**Honest latency story.** "Full transparency: this is CPU-only dev hardware. One device is one blocking model call — roughly **20–110 seconds**, about **83s** on a cold model load — and a batch scales linearly. I confirmed that's a **hardware** ceiling, not a code bug: I tried real concurrency (set Ollama to run two model instances in parallel) and watched free memory collapse to about **191 MB with ~5 GB of swap within seconds** on this 7.6 GB box. I reverted it rather than risk the service thrashing mid-demo. The code itself is already async and concurrency-ready — the moment this runs on a box with more RAM or a GPU, that path lights up for free. I'd rather show you something slow and stable than fast and crashing."

**Fault tolerance is a feature — and it's tested, not assumed.** "I assumed things would break, so I tested the breakage. Every model call has a timeout — **5s to connect, 240s to read** — so a hung Ollama can't freeze the endpoint forever. If Ollama is down, times out, or returns something unparseable even after the retry, `/decide` returns a clean **HTTP 500 in seconds** and the service stays up for the very next request. The full error goes to my server log; the caller gets a short message, never a stack trace. That's `tests/test_faults.py`, and I ran it — connection-refused and a deliberately hung 'black-hole' server both behave exactly that way."

---

## If something breaks live

*Every scenario here maps to a failure I actually tested — I'm not guessing.*

**Ollama is slow / looks like it's hanging.** Stay calm — expected on this hardware. Say: "This is the CPU latency I mentioned — a cold load is ~80 seconds; the request is still running, not stuck. There's a hard 240-second read timeout behind it, so worst case it returns a clean error — it can't hang forever." Don't kill it; let it finish or let the timeout fire. *(Backed by `tests/test_faults.py`, black-hole case.)*

**Ollama actually died / connection refused.** Say: "Watch — the service doesn't crash." The endpoint returns a clean 500 within seconds (not a hang); fire the same request again and it's still answering. "That's the fault handling — the process survives a dead backend and is ready for the next request." *(Backed by `tests/test_faults.py`, dead-port case, fired twice.)*

**Malformed / weird input.** Two layers: if the JSON doesn't match the contract, they get an instant **422** with a clear validation error — "the schema doing its job before the model even runs." If the input is technically valid but nonsensical (empty strings, contradictory values), the agent still returns a well-formed, valid response — it survives garbage instead of crashing. *(Backed by `tests/test_semantic_garbage.py`.)*

**A request during a model switch.** We cap Ollama to one model in memory on this box, so switching hazard (earthquake → flood) reloads a model and adds a cold-load delay to that first request. Say: "First request after a hazard switch is the slow one — the model's loading. Same ~80s cold start, then it's warm." It doesn't fail; it's the cold-start tax, and if it ever exceeded the timeout it'd still return a clean 500, not hang. *(The concurrent test `tests/test_concurrent.py` fires earthquake + flood + heatwave at once — forcing exactly these swaps — and all three came back correct with no cross-talk and the server still up.)*

**Last resort.** The pairs in `contracts/examples/` are real, validated request/response files — I can walk those to show exactly what the system produces without depending on a live model call.

---

*Sources: `docs/README.md`, `docs/MODELFILES.md`, `contracts/examples/*.json`, `docs/CHANGELOG.md` (E2E latency log, 2026-08-23), and the test suite (`tests/test_faults.py`, `tests/test_semantic_garbage.py`, `tests/test_concurrent.py`, `tests/live_notconnected.py`).*
