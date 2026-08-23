#!/usr/bin/env python3
"""Validate the locked contract examples against models/schemas.py.

Run:  python3 validate_contract.py
Exits non-zero on any failure, so it can gate CI / a go-no-go check.

If contracts/examples/ai_request.json / ai_response.json exist, they are
validated directly. If they are missing, this falls back to a contract-shaped
fixture (using the coords from the contract example) and says so LOUDLY — a
fallback pass does NOT prove the real payloads parse.
"""
import json
import pathlib
import sys

from pydantic import ValidationError

from models import AgentRequest, AgentResponse, Shelter

REQ_PATH = pathlib.Path("contracts/examples/ai_request.json")
RESP_PATH = pathlib.Path("contracts/examples/ai_response.json")

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


def load(path, fixture):
    if path.exists():
        return json.loads(path.read_text()), f"REAL FILE {path}"
    return fixture, f"FIXTURE (!! {path} not found — contract-shaped fallback)"


def main():
    print(f"pydantic import OK; python {sys.version.split()[0]}")
    ok = True

    req_data, req_src = load(REQ_PATH, REQ_FIXTURE)
    resp_data, resp_src = load(RESP_PATH, RESP_FIXTURE)

    try:
        r = AgentRequest.model_validate(req_data)
        print(f"OK  AgentRequest   [{req_src}]")
        print(f"    shelter.location -> {r.nearest_shelters[0].location.model_dump()}")
    except ValidationError as e:
        ok = False
        print(f"FAIL AgentRequest  [{req_src}]\n{e}")

    try:
        resp = AgentResponse.model_validate(resp_data)
        print(f"OK  AgentResponse  [{resp_src}]")
        print(f"    rescue_priority = {resp.decisions[0].rescue_priority} (1 = HIGHEST per contract)")
    except ValidationError as e:
        ok = False
        print(f"FAIL AgentResponse [{resp_src}]\n{e}")

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
