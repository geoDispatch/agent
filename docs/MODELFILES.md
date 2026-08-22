# GeoDispatch Modelfiles

Three Ollama Modelfiles wrap `qwen2.5` into one triage model per hazard:

| File                          | Model tag              | Hazard     |
|-------------------------------|------------------------|------------|
| `modelfiles/Modelfile.earthquake` | `geodispatch-earthquake` | earthquake |
| `modelfiles/Modelfile.flood`      | `geodispatch-flood`      | flood      |
| `modelfiles/Modelfile.heatwave`   | `geodispatch-heatwave`   | heatwave   |

Build them with:

```sh
ollama create geodispatch-earthquake -f modelfiles/Modelfile.earthquake
ollama create geodispatch-flood      -f modelfiles/Modelfile.flood
ollama create geodispatch-heatwave   -f modelfiles/Modelfile.heatwave
```

## Shared across all three

Every Modelfile is `FROM qwen2.5`, sets `PARAMETER temperature 0.2` (life-safety
structured output, not creative writing — low temperature for determinism), and
carries the same operative contract in its `SYSTEM` prompt:

- **Input is structured, not free text.** The model triages one `TriagedDevice`
  (JSON) at a time; `zone` was set by the upstream Go service and must never be
  invented.
- **Output is ONLY a JSON object** matching `DeviceDecision` in
  `models/schemas.py` — no prose, no markdown fences. Fields:
  `phone`, `zone_confirmed`, `zone_escalated`, `action`, `sms_message`,
  `rescue_priority`, `confidence`, `reasoning`.
- **`zone_confirmed`** echoes the incoming zone unless escalating; it may differ
  from the incoming zone ONLY when `zone_escalated` is `true`.
- **`action`**: `sms` = SMS only · `rescue_flag` = flag for physical rescue only
  · `both` = SMS + rescue · `none` = no action.
- **`sms_message`**: `""` when `action` is `rescue_flag` or `none`; otherwise
  actionable, calm, target < 160 chars, in the language of the device context.
- **`rescue_priority`** (matches `test_quality.py`'s wording, which is the
  authoritative direction): `0` = not flagged for rescue; for flagged devices
  `1` = highest urgency (dispatch FIRST) and `10` = lowest urgency among flagged
  devices (dispatch LAST). Lower the number toward 1 as danger rises.
- **`confidence`** 0–1; **`reasoning`** is one short internal audit sentence,
  never shown to users or sent via SMS.

The shared block is intentionally repeated verbatim inside each `SYSTEM` prompt
because the model only ever sees its own prompt — Ollama has no include
mechanism. This doc is the single source of truth for that block; edit it here
first, then propagate. Only the hazard rule below should differ between files.

### Open question — default SMS language

When a `TriagedDevice` carries no language hint, the prompts currently default
to **bilingual Arabic + French**. This is still under discussion with Ilias and
is flagged as a `# TODO(Ilias)` comment at the top of each Modelfile. Change it
in all three if the decision lands elsewhere.

## Hazard-specific (the only intended difference)

- **earthquake** — factor `aftershock_risk` and `tsunami_risk` into urgency;
  HIGH aftershock risk or any tsunami risk pushes `rescue_priority` toward 1 and
  favors `rescue_flag`/`both` over sms-only.
- **flood** — factor `distance_km` and `reachability_status` into evacuation
  timing; large distance and unreachable/intermittent links mean an SMS may
  arrive too late, so favor `rescue_flag`/`both` and a lower (more urgent)
  `rescue_priority`.
- **heatwave** — heatwave severity is NOT a Richter-style magnitude; treat
  `severity` as a general 0–10 danger scale (higher = more dangerous) when
  setting urgency.
