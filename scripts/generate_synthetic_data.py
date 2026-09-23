#!/usr/bin/env python3
"""Generate synthetic (AgentRequest, AgentResponse) training data for fine-tuning.

This script reimplements the EXACT deterministic earthquake-triage rules from the
Go mock agent (a.go) in Python, generates realistic synthetic request batches, runs
them through the reimplemented rules to produce responses, validates every pair
against the real Pydantic models in app/schemas/, and writes the pairs to
data/dataset.jsonl in ChatML format for fine-tuning Qwen2.5-1.5B-Instruct.

Run:
    python scripts/generate_synthetic_data.py
"""
import argparse
import json
import os
import random
import re
import sys
from datetime import datetime, timedelta

# --- Make the project's Pydantic models importable -------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pydantic import ValidationError  # noqa: E402
from app.schemas.request import AgentRequest  # noqa: E402
from app.schemas.response import AgentResponse  # noqa: E402

# --- Defaults --------------------------------------------------------------------
DEFAULT_NUM = 5000
DEFAULT_SEED = 1337
DEFAULT_OUT = os.path.join(PROJECT_ROOT, "data", "dataset.jsonl")

SYSTEM_PROMPT = (
    "You are an emergency disaster triage agent. Output valid JSON strictly "
    "conforming to the response schema."
)

# =================================================================================
# 1. Faithful re-implementation of the Go rule logic (a.go)
# =================================================================================
MAX_SHELTER_RUNES = 120  # matches maxShelterRunes in a.go

# Exact zone table from a.go `rules`.
ZONE_RULES = {
    "red": {
        "reachable": "both",
        "unreachable": "rescue_flag",
        "rescue_priority": 1,
        "confidence": 0.99,
        "alert": "EARTHQUAKE ALERT (red zone): evacuate now, avoid damaged buildings and lifts.",
    },
    "orange": {
        "reachable": "both",
        "unreachable": "rescue_flag",
        "rescue_priority": 2,
        "confidence": 0.92,
        "alert": "EARTHQUAKE WARNING (orange zone): move to open ground away from damaged buildings.",
    },
    "green": {
        "reachable": "sms",
        "unreachable": "none",
        "rescue_priority": 0,
        "confidence": 0.75,
        "alert": "EARTHQUAKE NOTICE (green zone): low risk here. Expect aftershocks and follow official guidance.",
    },
}

REACHABLE_STATUSES = {"CONNECTED_DATA", "CONNECTED_SMS"}
E164 = re.compile(r"^\+[1-9]\d{1,14}$")


def truncate_runes(s: str, n: int) -> str:
    """Port of truncateRunes in a.go: keep <= n code points, else n-1 + ellipsis."""
    if len(s) <= n:
        return s
    return s[: n - 1] + "\u2026"


def sms_text(rule: dict, tsunami_risk: bool, nearest_shelters) -> str:
    """Port of smsText in a.go: alert + optional tsunami + shelter/fallback line."""
    parts = [rule["alert"]]
    if tsunami_risk:
        parts.append(" Tsunami risk: move away from the coast.")
    if nearest_shelters and (nearest_shelters[0]["name"] or "").strip() != "":
        name = truncate_runes(nearest_shelters[0]["name"].strip(), MAX_SHELTER_RUNES)
        parts.append(" Nearest shelter: " + name + ".")
    else:
        parts.append(" Follow local authority instructions.")
    return "".join(parts)


def decide(req: dict) -> dict:
    """Port of decide() in a.go. Applies the fixed rules to one earthquake batch.

    Mirrors the Go validation so faithful bad input raises loudly rather than
    silently producing a wrong response.
    """
    if req["disaster_type"] != "earthquake":
        raise ValueError("unsupported disaster_type for mock agent")
    zone = req["zone"]
    if zone not in ZONE_RULES:
        raise ValueError("invalid zone: must be red, orange or green")
    rule = ZONE_RULES[zone]
    devices = req["devices"]
    if not (1 <= len(devices) <= 20):
        raise ValueError("invalid batch size: devices must hold 1..20 entries")

    seen = set()
    decisions = []
    reachable = sms = rescue = 0
    for i, d in enumerate(devices):
        if not E164.match(d["phone"]):
            raise ValueError(f"devices/{i}/phone is not E.164")
        if d["phone"] in seen:
            raise ValueError(f"devices/{i}/phone is duplicated")
        if d["zone"] != zone:
            raise ValueError(f"devices/{i}/zone differs from zone")
        seen.add(d["phone"])

        status = d["reachability_status"]
        if status in REACHABLE_STATUSES:
            action = rule["reachable"]
            reachable += 1
        elif status == "NOT_CONNECTED":
            action = rule["unreachable"]
        else:
            raise ValueError(f"devices/{i}/reachability_status is unknown")

        dec = {
            "phone": d["phone"],
            "zone_confirmed": zone,
            "zone_escalated": False,
            "action": action,
            "sms_message": "",
            "rescue_priority": 0,
            "confidence": rule["confidence"],
            "reasoning": f"mock rule: {zone} zone, {status}, action {action}",
        }
        if action in ("sms", "both"):
            dec["sms_message"] = sms_text(
                rule, bool(req.get("tsunami_risk")), req.get("nearest_shelters")
            )
            sms += 1
        if action in ("rescue_flag", "both"):
            dec["rescue_priority"] = rule["rescue_priority"]
            rescue += 1
        decisions.append(dec)

    n = len(decisions)
    unreachable = n - reachable
    return {
        "event_id": req["event_id"],
        "zone": zone,
        "decisions": decisions,
        "gov_narrative": (
            f"Mock agent (development tool), {zone} zone batch {req['batch_index']}: "
            f"{n} device(s), {reachable} reachable, {unreachable} unreachable. "
            f"SMS requested for {sms}, rescue requested for {rescue}."
        ),
        "request_qos": zone != "green" and reachable > 0,
        "confidence": rule["confidence"],
    }


# =================================================================================
# 2. Synthetic (but clearly fake) data generation
# =================================================================================
ZONES = ["red", "orange", "green"]
AFTERSHOCK_RISKS = ["LOW", "MEDIUM", "HIGH"]
CONGESTION_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"]
QOS_STATUSES = ["inactive", "requested", "active", "failed"]
REACHABLE_CHOICES = ["CONNECTED_DATA", "CONNECTED_SMS"]

# Country calling codes used only to shape fake-but-valid E.164 numbers.
COUNTRY_CODES = ["212", "1", "33", "44", "49", "81", "91", "61", "55", "39", "34", "82"]

# Fake, generic place names/addresses (no real PII, no real addresses).
SHELTER_NAMES = [
    "Centre d'Accueil Al-Manar", "Gymnase Municipal Nord", "Ecole Primaire Les Oliviers",
    "Salle Omnisports Riad", "Complexe Sportif El Fath", "Lycee Ibn Sina",
    "Stade Communal Sud", "Halle des Sports Zenith", "Centre Culturel Al-Andalous",
    "Maison des Jeunes Al Amal", "Refuge Municipal Bab Chark", "Gymnase Al Wahda",
    "Centre Sportif Les Cedres", "Salle Polyvalente Ennour", "Ecole Al Fajr",
]
SHELTER_STREETS = [
    "Rue 12, Quartier Nord", "Avenue des Palmiers, Secteur 4", "Boulevard Al Massira",
    "Rue des Ecoles, Zone 3", "Avenue Al Wahda, Hay Salam", "Rue Ibn Rochd, Secteur 7",
    "Boulevard de l'Unite, Zone Est", "Rue 45, Cite El Amal", "Avenue Moulay Youssef",
]
# One deliberately long name (> 120 chars) to exercise the SMS truncation branch.
LONG_SHELTER_NAME = (
    "Centre Regional Temporaire d'Hebergement d'Urgence pour Populations Sinistrees "
    "du Secteur Metropolitain Nord-Est et Communes Rurales Avoisinantes (Annexe Provisoire)"
)


def make_phone(used: set) -> str:
    r"""A valid, unique-within-batch E.164 number matching ^\+[1-9]\d{1,14}$."""
    while True:
        cc = random.choice(COUNTRY_CODES)
        total = random.randint(10, 13)  # total digit count after '+'
        sub_len = max(1, total - len(cc))
        subscriber = "".join(random.choice("0123456789") for _ in range(sub_len))
        phone = "+" + cc + subscriber
        if E164.match(phone) and phone not in used:
            used.add(phone)
            return phone


def iso_time(base: datetime) -> str:
    """A fake RFC3339 UTC timestamp shortly before `base`."""
    t = base - timedelta(seconds=random.randint(0, 6 * 3600))
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_shelter(base_lat: float, base_lon: float) -> dict:
    r = random.random()
    if r < 0.03:
        name = "   "               # whitespace-only -> triggers the fallback SMS line
    elif r < 0.10:
        name = LONG_SHELTER_NAME    # > 120 chars -> triggers truncation
    else:
        name = random.choice(SHELTER_NAMES)
    return {
        "name": name,
        "address": random.choice(SHELTER_STREETS),
        "location": {
            "latitude": round(base_lat + random.uniform(-0.05, 0.05), 6),
            "longitude": round(base_lon + random.uniform(-0.05, 0.05), 6),
        },
        "distance_km": round(random.uniform(0.2, 8.0), 2),
        "capacity": random.randint(0, 1200),
    }


def make_request(idx: int, zone: str) -> dict:
    base_time = datetime(2026, 9, 23, 10, 0, 0)
    region = random.choice(["MA", "JP", "CL", "TR", "ID", "IT", "MX", "US"])
    base_lat = round(random.uniform(-55.0, 60.0), 6)
    base_lon = round(random.uniform(-120.0, 145.0), 6)

    # Severity loosely correlated with zone for realism (still schema-valid 0..10).
    if zone == "red":
        severity = round(random.uniform(6.0, 8.6), 1)
    elif zone == "orange":
        severity = round(random.uniform(4.5, 6.5), 1)
    else:
        severity = round(random.uniform(3.0, 5.0), 1)

    # Batch-level reachable probability -> varies the reachable/unreachable ratio.
    # Beta(2,1) skews toward higher values (more reachable on average) while still
    # occasionally producing low-reachability catastrophic batches.
    reach_p = random.betavariate(2, 1)
    n_devices = random.randint(1, 20)
    used_phones = set()
    devices = []
    for _ in range(n_devices):
        if random.random() < reach_p:
            status = random.choice(REACHABLE_CHOICES)
        else:
            status = "NOT_CONNECTED"
        devices.append({
            "phone": make_phone(used_phones),
            "latitude": round(base_lat + random.uniform(-0.1, 0.1), 6),
            "longitude": round(base_lon + random.uniform(-0.1, 0.1), 6),
            "location_radius_m": round(random.uniform(5.0, 2000.0), 1),
            "last_location_time": iso_time(base_time),
            "reachability_status": status,
            "last_status_time": iso_time(base_time),
            "zone": zone,
            "distance_km": round(random.uniform(0.0, 30.0), 2),
        })

    # Include batches with zero, one, two and three shelters.
    n_shelters = random.choices([0, 1, 2, 3], weights=[15, 35, 30, 20])[0]
    shelters = [make_shelter(base_lat, base_lon) for _ in range(n_shelters)]

    return {
        "event_id": f"EQ-2026-{region}-{idx:04d}",
        "disaster_type": "earthquake",
        "severity": severity,
        "aftershock_risk": random.choice(AFTERSHOCK_RISKS),
        "tsunami_risk": random.random() < 0.3,
        "zone": zone,
        "batch_index": random.randint(0, 40),
        "devices": devices,
        "nearest_shelters": shelters,
        "network_status": {
            "congestion_level": random.choice(CONGESTION_LEVELS),
            "sms_delivery_rate": round(random.uniform(0.0, 1.0), 2),
            "qos_status": random.choice(QOS_STATUSES),
        },
    }


# =================================================================================
# 3. Orchestration: generate, validate, write ChatML JSONL, summarize
# =================================================================================
def compact(obj: dict) -> str:
    """Compact JSON string (no extra whitespace), UTF-8 preserved."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic ChatML dataset.")
    parser.add_argument("--num", type=int, default=DEFAULT_NUM, help="number of examples")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output .jsonl path")
    args = parser.parse_args()

    random.seed(args.seed)

    # Roughly-balanced, shuffled list of zones across all examples.
    zone_plan = [ZONES[i % 3] for i in range(args.num)]
    random.shuffle(zone_plan)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    zone_counts = {z: 0 for z in ZONES}
    action_counts = {"sms": 0, "rescue_flag": 0, "both": 0, "none": 0}
    congestion_counts = {c: 0 for c in CONGESTION_LEVELS}
    shelter_count_hist = {0: 0, 1: 0, 2: 0, 3: 0}
    tsunami_true = 0
    failed = 0
    written = 0

    with open(args.out, "w", encoding="utf-8") as fh:
        for idx, zone in enumerate(zone_plan):
            req = make_request(idx, zone)
            resp = decide(req)

            # Validate EVERY pair against the real Pydantic models before writing.
            try:
                AgentRequest(**req)
                AgentResponse(**resp)
            except ValidationError as exc:
                failed += 1
                print(
                    f"SCHEMA VALIDATION FAILED for example {idx} (zone={zone}):",
                    file=sys.stderr,
                )
                print(exc, file=sys.stderr)
                print("request=" + compact(req), file=sys.stderr)
                print("response=" + compact(resp), file=sys.stderr)
                continue  # never write bad data

            line = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": compact(req)},
                    {"role": "assistant", "content": compact(resp)},
                ]
            }
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
            written += 1

            zone_counts[zone] += 1
            congestion_counts[req["network_status"]["congestion_level"]] += 1
            shelter_count_hist[len(req["nearest_shelters"])] += 1
            if req["tsunami_risk"]:
                tsunami_true += 1
            for d in resp["decisions"]:
                action_counts[d["action"]] += 1

    # ---- Summary ----
    print("=" * 60)
    print(f"Synthetic dataset written to: {args.out}")
    print(f"Total examples generated (written): {written}")
    print(f"Failed schema validation: {failed}")
    print("-" * 60)
    print("Zone distribution (examples):")
    for z in ZONES:
        print(f"  {z:<7}: {zone_counts[z]}")
    print("Action distribution (across all device decisions):")
    for a, c in action_counts.items():
        print(f"  {a:<12}: {c}")
    print("Network congestion_level coverage (examples):")
    for c in CONGESTION_LEVELS:
        print(f"  {c:<9}: {congestion_counts[c]}")
    print("nearest_shelters count distribution (examples):")
    for k in (0, 1, 2, 3):
        print(f"  {k} shelter(s): {shelter_count_hist[k]}")
    print(f"tsunami_risk=true examples: {tsunami_true}")
    print("=" * 60)

    if failed:
        raise RuntimeError(
            f"{failed} generated pair(s) failed schema validation - see errors "
            "above. No bad data was written, but the run is not clean."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

