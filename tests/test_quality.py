#!/usr/bin/env python3
"""
test_quality.py — Qwen2.5 go/no-go harness for the GeoDispatch triage agent.

Feeds 10 synthetic TriagedDevice batches (earthquake / flood / heatwave,
mixing AR / FR / EN / code-switched AR-FR in the *government narrative and
context* fields — not victim free-text) to the real per-hazard GeoDispatch
models and checks that every response is valid JSON with the required decision
shape and an SMS that fits in a single 160-char message.

THIS HARNESS TESTS THE MODELFILES. It sends NO system message, exactly like
services/ollama.py::_decide_device, so the `SYSTEM` prompt baked into
modelfiles/Modelfile.<hazard> is what actually runs. It used to send its own
SYSTEM_PROMPT in messages[], which silently overrode the Modelfile SYSTEM
entirely — every result from that version was a verdict on the ad-hoc prompt in
this file, not on the shipped models. Do not reintroduce a system message here.

Each case is routed by its own `disaster_type` to the matching model
(geodispatch-earthquake / -flood / -heatwave), so hazard-specific prompt rules
are exercised too.

Decision shape the model must emit (and ONLY this):
    {
      "action":          "sms" | "rescue_flag" | "both" | "none",
      "sms_message":     str,      # "" is allowed when no SMS is sent
      "rescue_priority": int,      # 0=not flagged; 1=highest urgency (first)..10=lowest (last)
      "confidence":      float,    # 0..1
      "reasoning":       str
    }
(The Modelfiles also emit `phone`, `zone_confirmed` and `zone_escalated` per
models/schemas.py::DeviceDecision; extra fields are not failures here.)

Deps: `ollama` + Python stdlib only.
Run:  python3 test_quality.py
Env:  OLLAMA_MODEL   optional — pin ONE model for all 10 cases (e.g.
                     `qwen2.5:3b` to measure the bare base model). Unset is the
                     normal path: route per hazard. There is deliberately no
                     bare "qwen2.5" default; that tag is not pulled and 404s.
      OLLAMA_HOST    default: ollama lib default (localhost:11434)
      OLLAMA_JSON_FORMAT ("1"/"0", default "1" — use Ollama's JSON mode),
      NO_COLOR (disable ANSI colors).
"""

import json
import os
import sys

try:
    import ollama
except ImportError:
    sys.exit(
        "The 'ollama' library is not installed.\n"
        "  pip install ollama      (and make sure `ollama serve` is running)"
    )

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

# One model per hazard — the real shipped models, whose Modelfile SYSTEM prompt
# is the thing under test. Built by `make build-models`.
MODEL_BY_HAZARD = {
    "earthquake": "geodispatch-earthquake",
    "flood": "geodispatch-flood",
    "heatwave": "geodispatch-heatwave",
}
# Optional override: pin every case to ONE model (e.g. OLLAMA_MODEL=qwen2.5:3b to
# measure the bare base model). No default — routing per hazard is the norm.
MODEL_OVERRIDE = os.environ.get("OLLAMA_MODEL")
HOST = os.environ.get("OLLAMA_HOST")  # None -> ollama lib default (localhost:11434)
# JSON mode constrains Ollama's decoder to emit valid JSON. It's what you'd
# ship, so it's the default here; set OLLAMA_JSON_FORMAT=0 to instead test the
# model's raw prompt-following (JSON purely because the system prompt said so).
USE_JSON_FORMAT = os.environ.get("OLLAMA_JSON_FORMAT", "1") != "0"


def model_for(device):
    """The model that serves this device in production, or the pinned override."""
    if MODEL_OVERRIDE:
        return MODEL_OVERRIDE
    try:
        return MODEL_BY_HAZARD[device["disaster_type"]]
    except KeyError:
        raise SystemExit(
            f"no model mapped for disaster_type {device.get('disaster_type')!r} "
            f"(known: {sorted(MODEL_BY_HAZARD)})"
        )

SMS_LIMIT = 160  # single-segment GSM-7 SMS
UCS2_LIMIT = 70  # single-segment SMS once any non-Latin (e.g. Arabic) char appears
REQUIRED_FIELDS = ("action", "sms_message", "rescue_priority", "confidence", "reasoning")
VALID_ACTIONS = {"sms", "rescue_flag", "both", "none"}

# --------------------------------------------------------------------------- #
# Colors
# --------------------------------------------------------------------------- #

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def red(t):      return _c(t, "91")
def green(t):    return _c(t, "92")
def yellow(t):   return _c(t, "93")
def cyan(t):     return _c(t, "96")
def bold(t):     return _c(t, "1")
def bold_red(t): return _c(t, "1;91")

# --------------------------------------------------------------------------- #
# No system prompt, deliberately
# --------------------------------------------------------------------------- #
# This harness used to define a SYSTEM_PROMPT here and send it in messages[].
# An Ollama system message REPLACES the Modelfile's baked-in SYSTEM prompt, so
# that made the harness test this file's ad-hoc prompt instead of the shipped
# models — a green run said nothing about modelfiles/Modelfile.<hazard>. The
# production path (services/ollama.py::_decide_device) sends the device JSON as
# the only message and lets the Modelfile SYSTEM govern; this harness now does
# exactly the same. Do not add a system message back.

# --------------------------------------------------------------------------- #
# 10 synthetic TriagedDevice test cases
#   earthquake x4, flood x3, heatwave x3
#   languages: AR, FR, EN, and code-switched AR/FR in gov_narrative/context
# --------------------------------------------------------------------------- #

TEST_CASES = [
    {  # 1 — earthquake, AR, worst case
        "device_id": "EQ-AR-001",
        "disaster_type": "earthquake",
        "severity": "critical",
        "zone": "red",
        "reachability_status": "unreachable",
        "distance_km": 2.3,
        "network_congestion": "high",
        "gov_narrative": "نشرة رسمية: انهيار عدة مبانٍ في الحي القديم وفرق الإنقاذ لم تصل بعد.",
        "context": "احتمال وجود عالقين تحت الأنقاض.",
        "preferred_language": "ar",
    },
    {  # 2 — earthquake, code-switched AR/FR
        "device_id": "EQ-ARFR-002",
        "disaster_type": "earthquake",
        "severity": "high",
        "zone": "amber",
        "reachability_status": "intermittent",
        "distance_km": 8.0,
        "network_congestion": "moderate",
        "gov_narrative": "Bulletin: هزة ارتدادية متوقعة، évitez les bâtiments fissurés et restez dehors.",
        "context": "الكهرباء مقطوعة، réseau instable dans le secteur.",
        "preferred_language": "fr",
    },
    {  # 3 — flood, FR, unreachable + severe congestion
        "device_id": "FL-FR-003",
        "disaster_type": "flood",
        "severity": "critical",
        "zone": "red",
        "reachability_status": "unreachable",
        "distance_km": 15.0,
        "network_congestion": "severe",
        "gov_narrative": "Communiqué: crue soudaine de l'oued, plusieurs habitations submergées, route coupée.",
        "context": "Personnes signalées sur les toits.",
        "preferred_language": "fr",
    },
    {  # 4 — flood, EN, reachable / advisory
        "device_id": "FL-EN-004",
        "disaster_type": "flood",
        "severity": "moderate",
        "zone": "amber",
        "reachability_status": "reachable",
        "distance_km": 4.0,
        "network_congestion": "low",
        "gov_narrative": "Advisory: rising water in low-lying streets; move to higher ground.",
        "context": "Roads passable for now, water still rising.",
        "preferred_language": "en",
    },
    {  # 5 — heatwave, AR, vulnerable, reachable
        "device_id": "HW-AR-005",
        "disaster_type": "heatwave",
        "severity": "high",
        "zone": "amber",
        "reachability_status": "reachable",
        "distance_km": 1.0,
        "network_congestion": "low",
        "gov_narrative": "تحذير: موجة حر شديدة، درجات الحرارة تتجاوز 45 مئوية.",
        "context": "منطقة بها مسنون، ينصح بالترطيب وتجنب الشمس.",
        "preferred_language": "ar",
    },
    {  # 6 — heatwave, FR, green / low
        "device_id": "HW-FR-006",
        "disaster_type": "heatwave",
        "severity": "moderate",
        "zone": "green",
        "reachability_status": "reachable",
        "distance_km": 0.5,
        "network_congestion": "low",
        "gov_narrative": "Info: vigilance chaleur, hydratez-vous et limitez les efforts en après-midi.",
        "context": "Situation sous contrôle, pas de victime signalée.",
        "preferred_language": "fr",
    },
    {  # 7 — earthquake, EN, far / low risk
        "device_id": "EQ-EN-007",
        "disaster_type": "earthquake",
        "severity": "low",
        "zone": "green",
        "reachability_status": "reachable",
        "distance_km": 20.0,
        "network_congestion": "low",
        "gov_narrative": "Update: minor tremor felt, no structural damage reported in this district.",
        "context": "Residents advised to stay informed.",
        "preferred_language": "en",
    },
    {  # 8 — flood, code-switched AR/FR, both likely
        "device_id": "FL-ARFR-008",
        "disaster_type": "flood",
        "severity": "high",
        "zone": "red",
        "reachability_status": "intermittent",
        "distance_km": 6.0,
        "network_congestion": "high",
        "gov_narrative": "تنبيه: المياه ترتفع بسرعة، quittez le rez-de-chaussée immédiatement.",
        "context": "بعض الطرق مقطوعة، secours en route mais retardés.",
        "preferred_language": "fr",
    },
    {  # 9 — heatwave, AR/FR mix, unreachable / critical
        "device_id": "HW-ARFR-009",
        "disaster_type": "heatwave",
        "severity": "critical",
        "zone": "red",
        "reachability_status": "unreachable",
        "distance_km": 12.0,
        "network_congestion": "moderate",
        "gov_narrative": "حالة طوارئ: coupures d'eau généralisées et موجة حر قياسية منذ أيام.",
        "context": "مستشفى المنطقة مكتظ، cas de malaise signalés.",
        "preferred_language": "ar",
    },
    {  # 10 — earthquake, FR, reachable / advisory
        "device_id": "EQ-FR-010",
        "disaster_type": "earthquake",
        "severity": "moderate",
        "zone": "amber",
        "reachability_status": "reachable",
        "distance_km": 3.0,
        "network_congestion": "moderate",
        "gov_narrative": "Communiqué: secousse modérée, quelques fissures, inspectez avant de rentrer.",
        "context": "Répliques possibles dans les prochaines heures.",
        "preferred_language": "fr",
    },
]

# --------------------------------------------------------------------------- #
# Model call + response handling
# --------------------------------------------------------------------------- #


def call_model(client, device):
    """Return the model's raw text response for one device.

    Mirrors services/ollama.py::_decide_device exactly: the device JSON is the
    ONLY message, so the Modelfile's baked-in SYSTEM prompt is what governs.
    """
    resp = client.chat(
        model=model_for(device),
        messages=[
            {"role": "user", "content": json.dumps(device, ensure_ascii=False)},
        ],
        format="json" if USE_JSON_FORMAT else "",
        options={"temperature": 0},
    )
    return resp["message"]["content"]


def extract_json(raw):
    """
    Parse the model's response into a dict.

    Returns (obj, clean): obj is the parsed dict or None on failure; clean is
    True only if the raw text was already a bare JSON object (no fence/prose to
    strip). A False `clean` is a soft warning, not a failure.
    """
    text = raw.strip()
    try:
        return json.loads(text), True
    except (json.JSONDecodeError, TypeError):
        pass

    # Strip ```json ... ``` fences if present.
    if text.startswith("```"):
        inner = text[3:]
        if inner[:4].lower() == "json":
            inner = inner[4:]
        if "```" in inner:
            inner = inner[: inner.rindex("```")]
        text = inner.strip()

    # Fall back to the outermost {...} span.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1]), False
        except json.JSONDecodeError:
            return None, False
    return None, False


def evaluate(raw):
    """
    Validate one raw response against the go/no-go criteria.

    Returns (passed, obj, errors, warnings). `passed` is False if the response
    fails JSON parsing, omits a required field, or has an SMS > 160 chars.
    """
    errors, warnings = [], []

    obj, clean = extract_json(raw)
    if obj is None:
        return False, None, ["response is not valid JSON"], warnings
    if not isinstance(obj, dict):
        return False, None, [f"JSON root is {type(obj).__name__}, expected object"], warnings
    if not clean:
        warnings.append("JSON needed cleanup (fences/prose around it)")

    missing = [f for f in REQUIRED_FIELDS if f not in obj]
    if missing:
        errors.append("missing required field(s): " + ", ".join(missing))

    sms = obj.get("sms_message")
    if isinstance(sms, str):
        n = len(sms)
        if n > SMS_LIMIT:
            errors.append(f"SMS is {n} chars (> {SMS_LIMIT})")
        # Non-failing realism check: any non-Latin char forces UCS-2 SMS
        # encoding, which segments at 70 chars, not 160.
        elif any(ord(ch) > 127 for ch in sms) and n > UCS2_LIMIT:
            warnings.append(f"SMS is {n} chars; non-Latin text segments at {UCS2_LIMIT} (UCS-2)")
    elif "sms_message" in obj and sms is not None:
        errors.append(f"sms_message is {type(sms).__name__}, expected string")

    # Soft schema checks — surfaced, but don't flip the go/no-go verdict.
    action = obj.get("action")
    if action is not None and action not in VALID_ACTIONS:
        warnings.append(f"action {action!r} not in {sorted(VALID_ACTIONS)}")
    if action in ("sms", "both") and isinstance(sms, str) and sms.strip() == "":
        warnings.append(f"action is {action!r} but sms_message is empty")

    prio = obj.get("rescue_priority")
    if isinstance(prio, bool) or not isinstance(prio, (int, float)):
        if "rescue_priority" in obj:
            warnings.append("rescue_priority is not a number")
    elif not (0 <= prio <= 10):
        warnings.append(f"rescue_priority {prio} out of range 0-10")

    conf = obj.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        if "confidence" in obj:
            warnings.append("confidence is not a number")
    elif not (0 <= conf <= 1):
        warnings.append(f"confidence {conf} out of range 0-1")

    return len(errors) == 0, obj, errors, warnings

# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def print_case(i, device, raw, passed, obj, errors, warnings):
    print(bold(cyan(f"\n{'=' * 78}")))
    print(bold(cyan(f"[{i}/{len(TEST_CASES)}] {device['device_id']}  "
                     f"{device['disaster_type']}/{device['severity']}/{device['zone']}")))
    print(cyan("-" * 78))

    print(bold("INPUT:"))
    print(f"  model={model_for(device)}")
    print(f"  zone={device['zone']}  reachability={device['reachability_status']}  "
          f"distance_km={device['distance_km']}  congestion={device['network_congestion']}")
    print(f"  gov_narrative: {device['gov_narrative']}")
    print(f"  context:       {device['context']}")

    print(bold("\nMODEL OUTPUT:"))
    if obj is not None:
        action = obj.get("action")
        sms = obj.get("sms_message", "")
        sms_len = len(sms) if isinstance(sms, str) else "?"
        print(f"  action={action!r}  rescue_priority={obj.get('rescue_priority')}  "
              f"confidence={obj.get('confidence')}")
        print(f"  sms ({sms_len} chars): {sms!r}")
        print(f"  reasoning: {obj.get('reasoning')!r}")
    else:
        print("  " + red(repr(raw)))

    for w in warnings:
        print(yellow(f"  ⚠ warning: {w}"))
    for e in errors:
        print(bold_red(f"  ✗ FAIL: {e}"))

    print(green(bold("  ✓ PASS")) if passed else bold_red("  ✗ FAIL"))


def main():
    routing = (f"model={MODEL_OVERRIDE!r} (OLLAMA_MODEL override — every case)"
               if MODEL_OVERRIDE else
               "models=per-hazard " + "/".join(sorted(set(MODEL_BY_HAZARD.values()))))
    print(bold(f"GeoDispatch quality harness — {routing}  "
               f"json_format={'on' if USE_JSON_FORMAT else 'off'}  "
               f"cases={len(TEST_CASES)}"))
    print(bold("no system message: the Modelfile SYSTEM prompt is what is under test"))

    client = ollama.Client(host=HOST) if HOST else ollama.Client()

    # Pre-flight so a dead server fails once with a clear message, not 10 times.
    try:
        available = {m.model for m in client.list().models}
    except Exception as exc:  # noqa: BLE001 — surface any connection error clearly
        sys.exit(bold_red(
            f"\nCannot reach Ollama ({exc}).\n"
            "Start it with `ollama serve`, then `make build-models`."
        ))

    # Fail once, up front, if a model this run needs isn't built — otherwise
    # every case 404s separately and the summary blames the model's answers.
    needed = ({MODEL_OVERRIDE} if MODEL_OVERRIDE
              else {model_for(d) for d in TEST_CASES})
    missing_models = sorted(
        m for m in needed
        if m not in available and f"{m}:latest" not in available
    )
    if missing_models:
        sys.exit(bold_red(
            f"\nmodel(s) not found in Ollama: {', '.join(missing_models)}\n"
            "Build the per-hazard models with `make build-models`"
            + (f", or pull {MODEL_OVERRIDE!r}." if MODEL_OVERRIDE else ".")
        ))

    passed_count = 0
    failed_ids = []

    # Group by model, keeping each case's original 1-based number for the report.
    # This box runs OLLAMA_MAX_LOADED_MODELS=1, so every model switch is a cold
    # reload (~83 s). TEST_CASES alternates hazards, which would pay that ~9
    # times; hazard-major order pays it twice. Same cases, same checks.
    ordered = sorted(enumerate(TEST_CASES, 1), key=lambda pair: model_for(pair[1]))

    for i, device in ordered:
        try:
            raw = call_model(client, device)
        except Exception as exc:  # noqa: BLE001 — a failed call is a failed case
            print_case(i, device, f"<model call errored: {exc}>", False, None,
                       [f"model call raised {type(exc).__name__}: {exc}"], [])
            failed_ids.append(device["device_id"])
            continue

        passed, obj, errors, warnings = evaluate(raw)
        print_case(i, device, raw, passed, obj, errors, warnings)
        if passed:
            passed_count += 1
        else:
            failed_ids.append(device["device_id"])

    total = len(TEST_CASES)
    failed_count = total - passed_count
    print(bold(cyan(f"\n{'=' * 78}")))
    print(bold("SUMMARY"))
    print(f"  passed: {green(str(passed_count))} / {total}")
    line = f"  failed: {failed_count} / {total}"
    print(bold_red(line) if failed_count else line)
    if failed_ids:
        print("  failed cases: " + ", ".join(failed_ids))

    verdict = "GO ✓" if failed_count == 0 else "NO-GO ✗"
    subject = MODEL_OVERRIDE if MODEL_OVERRIDE else "the per-hazard Modelfiles"
    print(bold(green(f"\n{verdict}  — {subject} handled every case."))
          if failed_count == 0
          else bold_red(f"\n{verdict}  — {failed_count} case(s) failed; "
                        f"consider the OpenRouter fallback."))

    # Non-zero exit on any failure so this can gate CI / a go-no-go script.
    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
