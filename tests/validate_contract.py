#!/usr/bin/env python3
"""Validate the locked contract examples against models/schemas.py.

Run:  python3 tests/validate_contract.py   (from the repo root)
Exits non-zero on any failure, so it can gate CI / a go-no-go check.

contracts/examples/ai_request.json / ai_response.json are JSON Schema
documents ($schema, title, properties, definitions, ...), NOT instances — the
real payloads live in their top-level "examples" array. So we validate every
entry in examples[] (per-example pass/fail), not the schema envelope. If a file
is missing, this falls back to a contract-shaped fixture and says so LOUDLY — a
fallback pass does NOT prove the real payloads parse.
"""
import json
import pathlib
import sys

from pydantic import ValidationError

# This script lives in tests/ but imports the repo-root `models` package and
# reads contracts/examples/*.json at the repo root. Run as
# `python3 tests/validate_contract.py`, sys.path[0] is tests/, not the repo
# root — add the repo root (this file's parent's parent) before importing.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models import AgentRequest, AgentResponse, Shelter

REQ_PATH = REPO_ROOT / "contracts" / "examples" / "ai_request.json"
RESP_PATH = REPO_ROOT / "contracts" / "examples" / "ai_response.json"

REQ_FIXTURE = {
    "event_id": "evt-demo-001", "disaster_type": "earthquake", "severity": 8.2,
    "aftershock_risk": "HIGH", "tsunami_risk": False, "zone": "red", "batch_index": 0,
    "devices": [{
        "phone": "+212600000001", "latitude": 33.98, "longitude": -6.86,
        "location_radius_m": 25.0, "last_location_time": "2026-08-20T09:15:00Z",
        "reachability_status": "CONNECTED_SMS", "last_status_time": "2026-08-20T09:16:30Z",
        "zone": "red", "distance_km": 3.4,
    }],
    "nearest_shelters": [{
        "name": "Stade Municipal", "address": "Ave Hassan II, Rabat",
        "location": {"latitude": 33.98, "longitude": -6.86},
        "distance_km": 1.1, "capacity": 500,
    }],
    "network_status": {"congestion_level": "CRITICAL", "sms_delivery_rate": 0.63, "qos_status": "requested"},
}
RESP_FIXTURE = {
    "event_id": "evt-demo-001", "zone": "red",
    "decisions": [{
        "phone": "+212600000001", "zone_confirmed": "red", "zone_escalated": False,
        "action": "both", "sms_message": "Seisme: quittez le batiment, rejoignez le Stade Municipal (1.1km).",
        "rescue_priority": 1, "confidence": 0.9, "reasoning": "Red zone; SMS + rescue flag.",
    }],
    "gov_narrative": "1 device in red zone; SMS sent and rescue flagged.",
    "request_qos": True, "confidence": 0.87,
}


def load_examples(path, fixture):
    """Return (list_of_instances, source_label).

    The contract files are JSON Schema documents; the actual instances to
    validate live in their top-level "examples" array — return that list so the
    caller can validate every example. If the file exists but has no examples[]
    array, return the document itself (so it fails loudly rather than silently
    passing). If the file is missing, fall back to the contract-shaped fixture.
    """
    if path.exists():
        doc = json.loads(path.read_text())
        examples = doc.get("examples")
        if isinstance(examples, list) and examples:
            return examples, f"REAL FILE {path} (examples[0..{len(examples) - 1}])"
        return [doc], f"REAL FILE {path} (!! no examples[] array — validating document as-is)"
    return [fixture], f"FIXTURE (!! {path} not found — contract-shaped fallback)"


def main():
    print(f"pydantic import OK; python {sys.version.split()[0]}")
    ok = True

    req_examples, req_src = load_examples(REQ_PATH, REQ_FIXTURE)
    resp_examples, resp_src = load_examples(RESP_PATH, RESP_FIXTURE)

    print(f"AgentRequest   [{req_src}]  — {len(req_examples)} example(s)")
    for i, ex in enumerate(req_examples):
        try:
            r = AgentRequest.model_validate(ex)
            loc = r.nearest_shelters[0].location.model_dump() if r.nearest_shelters else "(no shelters)"
            print(f"  OK  example[{i}]  event_id={r.event_id!r}  devices={len(r.devices)}  shelter[0].location -> {loc}")
        except ValidationError as e:
            ok = False
            print(f"  FAIL example[{i}]\n{e}")

    print(f"AgentResponse  [{resp_src}]  — {len(resp_examples)} example(s)")
    for i, ex in enumerate(resp_examples):
        try:
            resp = AgentResponse.model_validate(ex)
            print(f"  OK  example[{i}]  event_id={resp.event_id!r}  decisions={len(resp.decisions)}  "
                  f"rescue_priority[0]={resp.decisions[0].rescue_priority} (1 = HIGHEST per contract)")
        except ValidationError as e:
            ok = False
            print(f"  FAIL example[{i}]\n{e}")

    # Prove the rename: new names accepted, old lat/lon rejected by extra="forbid".
    base = {"name": "S", "address": "A", "distance_km": 0.5, "capacity": 100}
    try:
        Shelter.model_validate({**base, "location": {"latitude": 33.98, "longitude": -6.86}})
        print("OK  Shelter accepts latitude/longitude")
    except ValidationError as e:
        ok = False
        print(f"FAIL Shelter rejected latitude/longitude\n{e}")
    try:
        Shelter.model_validate({**base, "location": {"lat": 33.98, "lon": -6.86}})
        ok = False
        print("FAIL old lat/lon was NOT rejected (extra='forbid' not working)")
    except ValidationError:
        print("OK  old lat/lon rejected (extra='forbid')")

    print("\n" + ("ALL GOOD" if ok else "FAILURES ABOVE"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
