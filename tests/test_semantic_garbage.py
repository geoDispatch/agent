#!/usr/bin/env python3
"""Semantic-garbage test (Tests #1 & #2): schema-VALID but nonsensical input.

FastAPI/Pydantic already reject schema violations with 422 (that path is not
touched here). This checks the *other* class of bad input — payloads that pass
the schema but make no real-world sense — and confirms services.ollama.call_agent
does not crash on them and still returns a schema-valid AgentResponse:

  #1 Empty / whitespace-only strings where the schema allows any string
     (event_id="", shelter name="   ", address="").
  #2 Technically-valid enum/number combos that are nonsensical together
     (NOT_CONNECTED at 0 km in a green zone; CONNECTED_DATA 99999 km away;
      severity 0.0 WITH tsunami_risk=True and aftershock HIGH).

We assert only that it does NOT crash and returns a valid AgentResponse — per
the ask, these are not to be rejected, just survived. Needs Ollama + models.

Run: .venv/bin/python tests/test_semantic_garbage.py   (from the repo root)
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models.schemas import AgentRequest, AgentResponse
from services.ollama import call_agent

_T = "2026-08-23T09:15:00Z"


def _device(reach: str, zone: str, dist: float) -> dict:
    return {
        "phone": "+212600000001", "latitude": 33.97, "longitude": -6.85,
        "location_radius_m": 50.0, "last_location_time": _T,
        "reachability_status": reach, "last_status_time": _T,
        "zone": zone, "distance_km": dist,
    }


# <!-- APPEND-1 -->


def _req(eid: str, *, device: dict, severity: float, tsunami: bool,
         aftershock: str, zone: str, shelters: list) -> AgentRequest:
    return AgentRequest.model_validate({
        "event_id": eid, "disaster_type": "earthquake", "severity": severity,
        "aftershock_risk": aftershock, "tsunami_risk": tsunami, "zone": zone,
        "batch_index": 0, "devices": [device], "nearest_shelters": shelters,
        "network_status": {
            "congestion_level": "HIGH", "sms_delivery_rate": 0.8,
            "qos_status": "inactive",
        },
    })


# Each case is schema-valid (it constructs) but semantically garbage.
CASES = [
    # #1 empty event_id + whitespace-only shelter name/address
    ("#1 empty event_id + whitespace shelter strings", _req(
        "", device=_device("CONNECTED_DATA", "red", 2.0), severity=7.0,
        tsunami=False, aftershock="MEDIUM", zone="red",
        shelters=[{
            "name": "   ", "address": "",
            "location": {"latitude": 33.98, "longitude": -6.86},
            "distance_km": 1.0, "capacity": 100,
        }])),
    # #2 NOT_CONNECTED but 0 km away in a GREEN (safe) zone — contradictory
    ("#2 NOT_CONNECTED @ 0km in green zone", _req(
        "GARBAGE-NC-0", device=_device("NOT_CONNECTED", "green", 0.0),
        severity=3.0, tsunami=False, aftershock="LOW", zone="green",
        shelters=[])),
    # #2 CONNECTED_DATA but absurdly far (99999 km) — schema has no upper bound
    ("#2 CONNECTED_DATA @ 99999km", _req(
        "GARBAGE-FAR", device=_device("CONNECTED_DATA", "orange", 99999.0),
        severity=5.0, tsunami=False, aftershock="MEDIUM", zone="orange",
        shelters=[])),
    # #2 severity 0.0 but tsunami=True and aftershock HIGH — self-contradictory
    ("#2 severity 0.0 + tsunami=True + aftershock HIGH", _req(
        "GARBAGE-CTX", device=_device("CONNECTED_SMS", "red", 4.0),
        severity=0.0, tsunami=True, aftershock="HIGH", zone="red",
        shelters=[])),
]


def main() -> int:
    fails = 0
    for label, req in CASES:
        try:
            resp = asyncio.run(call_agent(req))
        except Exception as exc:  # noqa: BLE001 - this is the crash we're hunting
            fails += 1
            print(f"[CRASH] {label}: {type(exc).__name__}: {exc}", flush=True)
            continue
        # Did not crash. Confirm we got a genuinely valid AgentResponse back.
        valid = isinstance(resp, AgentResponse)
        try:
            AgentResponse.model_validate(resp.model_dump())
        except Exception as exc:  # noqa: BLE001
            valid = False
            print(f"    (revalidation failed: {exc})", flush=True)
        d = resp.decisions[0]
        fails += not valid
        print(f"[{'PASS' if valid else 'FAIL'}] {label}", flush=True)
        print(f"    -> action={d.action!r} prio={d.rescue_priority} "
              f"conf={resp.confidence} phones_ok={[x.phone for x in resp.decisions] == [dev.phone for dev in req.devices]}",
              flush=True)
    print(f"\nRESULT: {len(CASES) - fails}/{len(CASES)} survived without crashing",
          flush=True)
    print(f"VERDICT: {'ALL PASS ✓' if fails == 0 else f'{fails} FAILURE(S) ✗'}",
          flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

