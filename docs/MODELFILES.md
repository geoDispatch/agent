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

`modelfiles/` also holds one **experimental** file that is deliberately *not*
part of that build — see [Experimental](#experimental--not-for-production) at the
bottom.

## Shared across all three

Every Modelfile is `FROM qwen2.5:3b`, sets `PARAMETER temperature 0.2`
(life-safety structured output, not creative writing — low temperature for
determinism) and `PARAMETER num_predict 220` (hard cap on generated tokens), and
carries the same operative contract in its `SYSTEM` prompt:

- **Input is structured, not free text.** The model triages one `TriagedDevice`
  (JSON) at a time; `zone` was set by the upstream Go service and must never be
  invented.
- **Output is ONLY a JSON object** matching `DeviceDecision` in
  `models/schemas.py` — no prose, no markdown fences. Fields, **in this order**:
  `phone`, `zone_confirmed`, `zone_escalated`, `action`, `sms_message`,
  `rescue_priority`, `confidence`, `reasoning`. The order is load-bearing:
  reordering it (putting `reasoning` first) made the model drop `phone`
  entirely and fail schema validation. Keep `phone` first.
- **`zone_confirmed`** echoes the incoming zone unless escalating; it may differ
  from the incoming zone ONLY when `zone_escalated` is `true`.
- **`action`**: `sms` = SMS only · `rescue_flag` = flag for physical rescue only
  · `both` = SMS + rescue · `none` = no action.
- **`sms_message` — empty-first check.** `""` when `action` is `rescue_flag` or
  `none`, and the SMS LANGUAGE rule then does not apply at all; otherwise
  actionable, calm, under 160 chars. This ordering matters: stating the
  bilingual mandate first made the model write a bilingual SMS on
  `rescue_flag` decisions, which must carry no text.
- **`rescue_priority`** (matches `test_quality.py`'s wording, which is the
  authoritative direction): `0` = not flagged for rescue; for flagged devices
  `1` = highest urgency (dispatch FIRST) and `10` = lowest urgency among flagged
  devices (dispatch LAST). Lower the number toward 1 as danger rises.
- **`confidence`** 0–1; **`reasoning`** is one short internal audit sentence in
  English, never shown to users or sent via SMS, quoting this device's own
  `reachability_status` and `distance_km`.
- **NOT_CONNECTED hard rule.** `reachability_status: NOT_CONNECTED` forces
  `rescue_flag` or `none`, never `sms`/`both`, regardless of severity. The split
  is a numeric threshold on the **device's own** `distance_km`: `<= 10` km →
  `rescue_flag`, `> 10` km → `none`. The prompt names concrete numbers on both
  sides (1.5/3.4/8.0 vs 15.0/25.0/40.0) and explicitly tells the model to ignore
  the `distance_km` inside `nearest_shelters` — without both of those, the model
  read the shelter's distance and inverted the practicality logic.

### SMS shape and the bilingual mandate

Non-empty `sms_message` must contain **both Arabic script and French in the same
message**. Three rules in the prompt carry this, and each exists because of a
measured failure:

- **SMS LANGUAGE** — an absolute both-scripts mandate that names the failure
  modes seen in real output: Arabic-only, French-only, English-only, and
  Chinese-only.
- **SMS SHAPE** — the message is described as an ordered sequence in prose:
  Arabic imperative verb → shelter name → `الآن`, then ` / `, then French
  imperative verb → the same shelter name → `maintenant`. Three literal Arabic
  openers are given (`اذهبوا إلى`, `توجهوا إلى`, `أخلوا إلى`) because a negative
  guard ("do not start with `/go`") *produced* `/go` output, while naming the
  allowed openers stopped it.
- **SMS SHELTER NAME** — copy the `name` of the nearest `nearest_shelters` entry
  character for character into **both** clauses; if the list is empty or missing,
  write `أقرب ملجأ` / `l'abri le plus proche`. The fallback is required: the
  synthetic cases in `test_quality.py` have no `nearest_shelters`, and a bracketed
  slot pattern leaked `[shelter_name]` straight into `sms_message`.

  This rule needs the **prompt builders** to cooperate, and until 2026-08-30 they
  did not. `prompts/*.py` rendered each shelter as a bare bullet
  (`- Centre Culturel Tazi (1.1 km)`), so the rule's phrase "copy the `name`
  field" pointed at a field the model never saw. Result: 4 of 6 probe cases
  translated or transliterated the name instead of copying it
  (`Complexe Sportif Zerktouni` → `Complexe Sportif زرتكوني`,
  `Salle Omnisports Ghandi` → `ساحة الألعاب الجامعية غاندي`), and the French
  clause fell back to `l'abri le plus proche` in **6 of 6** — the only literal
  French shelter wording anywhere in the prompt, so it won by default. The
  builders now emit `- name: <name> (<km> km)`, and the WITH-branch says the name
  is written twice and explicitly forbids the generic phrase when a shelter is
  present. If you ever change that bullet format, change the rule's wording in
  all three Modelfiles to match — they are one mechanism, not two.

### No examples, deliberately

The prompts contain **no finished sample decision and no finished sample SMS**.
Both were tried and both shipped verbatim: three worked JSON decisions were
copied word-for-word (sometimes pairing one situation's `reasoning` with a
different situation's `action`), and a single fake shelter name in a "shape
guide" was emitted by 8 of 8 probe runs. The three common situations are instead
*described* in prose, under a banner stating that no copyable example exists and
that reusing any phrase from the descriptions is a failure.

A related lesson for anyone editing these prompts: on a 3B model, **negative
constraints reliably backfire** and any concrete sample text gets shipped as-is.
Prefer positive, enumerated framing, and re-measure after every edit — several
"obvious" clarifications here caused outright regressions (a full DECISION
PROCEDURE rewrite scored 0/4 and brought Chinese output back).

### Generation cap — `num_predict 220`

`reasoning` is internal-only, so it never needs to be long, but `sms_message` is
now mandatorily bilingual and Arabic costs roughly a token per character, so a
full decision generates more tokens than it used to. `PARAMETER num_predict` was
raised 150 → 220 alongside the bilingual mandate so an AR+FR message plus
`reasoning` cannot run past the JSON close and produce unparseable output. It is
a ceiling, not a target: typical calls already stop below it via EOS, so median
latency is unchanged; the cap's job is to bound the worst case so a rare ramble
can't inflate `/decide` latency.

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
  favors `rescue_flag`/`both` over sms-only (the NOT_CONNECTED hard rule still
  wins).
- **flood** — rising water compresses the evacuation window, so a *reachable*
  device far from safety warrants `both` with a low (urgent) `rescue_priority`.
  Phrased around reachable devices on purpose: the older wording ("large distance
  and unreachable links … favor `rescue_flag`/`both`") competed with the
  NOT_CONNECTED hard rule and pulled unreachable devices toward `both`.
- **heatwave** — heatwave severity is NOT a Richter-style magnitude; treat
  `severity` as a general 0–10 danger scale (higher = more dangerous) when
  setting urgency.

## Verifying a prompt change

Both live harnesses now exercise these Modelfiles, because neither sends a system
message — an Ollama system message *replaces* the baked-in `SYSTEM` prompt, so
sending one silently tests the harness's own prompt instead.

- `tests/live_notconnected.py` — goes through `services.ollama.call_agent`, the
  same path `/decide` uses. Targets the NOT_CONNECTED hard rule.
- `tests/test_quality.py` — 10 AR/FR/EN/code-switched cases, each routed to
  `geodispatch-<its own disaster_type>`. Structural: valid JSON, required fields,
  SMS length. Its synthetic cases carry **no `nearest_shelters`**, so they
  exercise the no-shelter fallback, not shelter-name fidelity — cover that with a
  real `AgentRequest` through `call_agent`.

`test_quality.py` was broken for exactly this reason until 2026-08-30: it defined
its own 46-line `SYSTEM_PROMPT`, sent it in `messages[]`, and pinned a single
hardcoded `OLLAMA_MODEL` default of `qwen2.5` (a tag that is not pulled — it
404s). Every result it produced was a verdict on that ad-hoc prompt, not on any
shipped model, and its prompt also disagreed with the contract (it used
`reachable | intermittent | unreachable` where the schema uses
`CONNECTED_DATA | CONNECTED_SMS | NOT_CONNECTED`, and it stated the
`rescue_priority` direction backwards). `OLLAMA_MODEL` is now an optional
override for pinning one model — set `OLLAMA_MODEL=qwen2.5:3b` to measure the
bare base model instead of the shipped prompts.

If you add a harness, send the device payload as the only message.

## Known limitation — shelter-name fidelity (3B, as shipped 2026-08-30)

**qwen2.5:3b does not reliably copy a Latin shelter name into an Arabic
sentence.** Measured on the 6-case shelter probe (real `AgentRequest`s through
`call_agent`, one distinctive name per case, all three hazards):

| | before the `name:` label | after |
|---|---|---|
| name copied verbatim at least once | 2/6 | **3/6** |
| name in **both** clauses (what the rule asks for) | 0/6 | **1/6** |

Everything else on that probe is clean 6/6: single Arabic opener with no joined
menu, no `/go` or ASCII gloss, no bracketed placeholder, no copied example
phrasing, no Chinese, genuinely bilingual, one line, one slash, under 160 chars.

The failure is always the same shape — the name is **translated or
transliterated into Arabic script** rather than copied:

- `Complexe Sportif Zerktouni` → `ملجأ زركوني`
- `Salle Omnisports Ghandi` → `ساحة الملعب غاندي`
- `Dar Chabab Anfa` → `دار الشبب أونفا`

And when the Arabic clause does carry the name, the French clause usually still
says `l'abri le plus proche` despite the rule now forbidding it there.

Two fixes were applied and both helped without regressing anything else: the
prompt builders label the field (`- name: <name> (<km> km)`), and the WITH-branch
tells the model to write the name twice and never to use the generic phrase when
a shelter is provided. The residual failure is a **model-capability limit, not a
prompt bug** — this is a 3B model asked to hold Latin orthography intact inside
Arabic generation, and the transliteration is the natural thing for it to do.
Further prompt edits were deliberately stopped here: three prior "obvious"
tightenings each introduced a new failure mode (`/go`, bracketed slots, a joined
opener menu), so the risk of a fourth outweighed the remaining upside.

One artifact this round did introduce, in the single both-clause case: an Arabic
`الآن` landed *after* the French clause
(`اتوجهوا إلى Centre Culturel Tazi/Rejoignez Centre Culturel Tazi الآن`),
which the SMS SHAPE rule puts before the slash. Cosmetic, not measured as a
failure by any check. The long-standing `اتوجهوا` artifact also persists — a
spurious prefixed alif on `توجهوا`, present in every message all night.

**Operational impact:** a recipient may get a shelter named in Arabic
transliteration instead of the sign they will actually read on the building. The
message stays actionable — correct language pair, correct urgency, plausible
name — but the name is not guaranteed to match the shelter registry. Anything
downstream that needs the exact shelter identity should read
`nearest_shelters[0].name` from the request, **not** parse `sms_message`.

Two options if this needs to be airtight later, both out of scope for the 3B
constraint: post-process `sms_message` to substitute the real name in (a template
join, no model involved), or move to a larger model. The first is cheap and
deterministic and is the recommended next step.

## Experimental — not for production

| File | Model tag | Base |
|------|-----------|------|
| `modelfiles/Modelfile.earthquake-test15b.txt` | `geodispatch-earthquake-test15b` | `qwen2.5:1.5b` |

A 1.5B twin of `Modelfile.earthquake`, kept only to measure what the 3B base
costs in latency (Week 2 perf item). The `.txt` extension and the header banner
mark it as out-of-band: it is **not** in `make build-models` and must never
serve `/decide`.

Its `SYSTEM` prompt, `temperature`, and `num_predict` are byte-for-byte copies of
`Modelfile.earthquake` — the `FROM` line is the only intended difference — so a
measured behaviour gap is attributable to base model size alone. If
`Modelfile.earthquake`'s `SYSTEM` prompt changes, either mirror it here or delete
this file once the size question is settled.
