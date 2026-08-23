#!/usr/bin/env python3
"""
test_quality.py — Qwen2.5 go/no-go harness for the GeoDispatch triage agent.

Feeds 10 synthetic TriagedDevice batches (earthquake / flood / heatwave,
mixing AR / FR / EN / code-switched AR-FR in the *government narrative and
context* fields — not victim free-text) to a local Ollama qwen2.5 model and
checks that every response is valid JSON with the required decision shape and
an SMS that fits in a single 160-char message.

Decision shape the model must emit (and ONLY this):
    {
      "action":          "sms" | "rescue_flag" | "both" | "none",
      "sms_message":     str,      # "" is allowed when no SMS is sent
      "rescue_priority": int,      # 0=not flagged; 1=highest urgency (first)..10=lowest (last)
      "confidence":      float,    # 0..1
      "reasoning":       str
    }

Deps: `ollama` + Python stdlib only.
Run:  python3 test_quality.py
Env:  OLLAMA_MODEL (default "qwen2.5"), OLLAMA_HOST (default lib default),
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

MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5")
HOST = os.environ.get("OLLAMA_HOST")  # None -> ollama lib default (localhost:11434)
# JSON mode constrains Ollama's decoder to emit valid JSON. It's what you'd
# ship, so it's the default here; set OLLAMA_JSON_FORMAT=0 to instead test the
# model's raw prompt-following (JSON purely because the system prompt said so).
USE_JSON_FORMAT = os.environ.get("OLLAMA_JSON_FORMAT", "1") != "0"

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
# System prompt
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """\
You are the decision core of GeoDispatch, a disaster-response triage agent.

You receive ONE TriagedDevice as JSON. Its zone was already classified by an
upstream service. Fields:
  disaster_type      earthquake | flood | heatwave
  severity           low | moderate | high | critical
  zone               red (most affected) | amber | green (least affected)
  reachability_status  reachable | intermittent | unreachable  (cellular link)
  distance_km        distance from the device to the nearest response team
  network_congestion low | moderate | high | severe  (SMS delivery reliability)
  gov_narrative      official situation text (may be Arabic, French, English,
                     or code-switched Arabic/French)
  context            extra situational context, same languages
  preferred_language optional hint for the SMS language

Decide what to do for this device and reply with ONLY a JSON object, no prose,
no markdown fences:
  {
    "action": "sms" | "rescue_flag" | "both" | "none",
    "sms_message": string,
    "rescue_priority": integer 0-10,
    "confidence": number 0-1,
    "reasoning": string
  }

Rules:
- action:
    "sms"         send an SMS only (device reachable, self-help/advice helps).
    "rescue_flag" flag for physical rescue only (no reliable SMS path, or SMS
                  alone is insufficient).
    "both"        send an SMS AND flag for rescue.
    "none"        no action warranted (low risk, green zone, no need).
- sms_message: <= 160 characters, actionable and calm. Write it in the language
  of gov_narrative/context (use preferred_language if given). If action is
  "rescue_flag" or "none", set it to "".
- rescue_priority: 0 = NOT flagged for rescue. For flagged devices the scale is
  INVERTED: 1 = highest urgency (dispatch FIRST), 10 = lowest urgency among
  flagged devices (dispatch LAST). LOWER the number toward 1 for critical
  severity, red zone, unreachable status, and short distance_km — a
  life-threatening, unreachable device in the red zone is 1 or 2, never 8-10.
- If reachability is unreachable or network_congestion is severe, prefer
  rescue_flag/both over sms-only, since the SMS may never arrive.
- confidence: your certainty in this decision, 0-1.
- reasoning: one short sentence (English is fine).
Output the JSON object and nothing else."""

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
    """Return the model's raw text response for one device."""
    resp = client.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
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
    print(bold(f"GeoDispatch quality harness — model={MODEL!r}  "
               f"json_format={'on' if USE_JSON_FORMAT else 'off'}  "
               f"cases={len(TEST_CASES)}"))

    client = ollama.Client(host=HOST) if HOST else ollama.Client()

    # Pre-flight so a dead server fails once with a clear message, not 10 times.
    try:
        client.list()
    except Exception as exc:  # noqa: BLE001 — surface any connection error clearly
        sys.exit(bold_red(
            f"\nCannot reach Ollama ({exc}).\n"
            "Start it with `ollama serve` and pull the model: "
            f"`ollama pull {MODEL}`."
        ))

    passed_count = 0
    failed_ids = []

    for i, device in enumerate(TEST_CASES, 1):
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
    print(bold(green(f"\n{verdict}  — Qwen2.5 handled every case."
                     if failed_count == 0 else "")) if failed_count == 0
          else bold_red(f"\n{verdict}  — {failed_count} case(s) failed; "
                        f"consider the OpenRouter fallback."))

    # Non-zero exit on any failure so this can gate CI / a go-no-go script.
    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
