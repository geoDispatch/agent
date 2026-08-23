#!/usr/bin/env python3
"""Live check of the NOT_CONNECTED HARD RULE against the real earthquake model.

Runs four single-device batches through services.ollama.call_agent (the real
inference path, one blocking model call per device) on the geodispatch-earthquake
model, under MAXIMALLY adversarial event context (red zone, severity 8.2, HIGH
aftershock, tsunami=true, CRITICAL congestion) so the reachability rule is tested
against everything that used to override it:

  1. NOT_CONNECTED @ 1.5 km  -> expect rescue_flag (close enough to dispatch)
  2. NOT_CONNECTED @ 25 km   -> expect none        (too far to dispatch)
  3. CONNECTED_SMS  @ 3.4 km -> expect sms/both    (reachable; "both" must survive)
  4. CONNECTED_DATA @ 3.4 km -> expect sms/both    (reachable; "both" must survive)

Run: .venv/bin/python tests/live_notconnected.py   (from the repo root)
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models.schemas import AgentRequest
from services.ollama import call_agent

_T = "2026-08-23T09:15:00Z"


def _device(reach: str, dist: float, zone: str = "red") -> dict:
    return {
        "phone": "+212600000001", "latitude": 33.97, "longitude": -6.85,
        "location_radius_m": 50.0, "last_location_time": _T,
        "reachability_status": reach, "last_status_time": _T,
        "zone": zone, "distance_km": dist,
    }


def _req(eid: str, reach: str, dist: float) -> AgentRequest:
    """Max-danger earthquake batch — the context that used to force 'both'."""
    return AgentRequest.model_validate({
        "event_id": eid, "disaster_type": "earthquake", "severity": 8.2,
        "aftershock_risk": "HIGH", "tsunami_risk": True, "zone": "red", "batch_index": 0,
        "devices": [_device(reach, dist)],
        "nearest_shelters": [{
            "name": "Stade Municipal", "address": "Ave Hassan II, Rabat",
            "location": {"latitude": 33.98, "longitude": -6.86},
            "distance_km": 1.1, "capacity": 500,
        }],
        "network_status": {"congestion_level": "CRITICAL", "sms_delivery_rate": 0.6, "qos_status": "inactive"},
    })


# (label, request, allowed_actions)
CASES = [
    ("NOT_CONNECTED @ 1.5km red (max danger)", _req("LIVE-NC-1p5", "NOT_CONNECTED", 1.5), {"rescue_flag"}),
    ("NOT_CONNECTED @ 25km  red (max danger)", _req("LIVE-NC-25", "NOT_CONNECTED", 25.0), {"none"}),
    ("CONNECTED_SMS  @ 3.4km red (reachable)", _req("LIVE-SMS", "CONNECTED_SMS", 3.4), {"sms", "both"}),
    ("CONNECTED_DATA @ 3.4km red (reachable)", _req("LIVE-DATA", "CONNECTED_DATA", 3.4), {"sms", "both"}),
]


def main() -> int:
    fails = 0
    for label, req, allowed in CASES:
        d = asyncio.run(call_agent(req)).decisions[0]
        # For NOT_CONNECTED, the rule also requires an empty sms_message.
        nc = req.devices[0].reachability_status == "NOT_CONNECTED"
        action_ok = d.action in allowed
        sms_ok = (not nc) or d.sms_message == ""
        case_ok = action_ok and sms_ok
        fails += not case_ok
        print(f"[{'PASS' if case_ok else 'FAIL'}] {label}", flush=True)
        print(f"    action={d.action!r}  rescue_priority={d.rescue_priority}  "
              f"sms_len={len(d.sms_message)}  sms={d.sms_message!r}", flush=True)
        print(f"    reasoning={d.reasoning!r}", flush=True)
        print(f"    expected action in {sorted(allowed)}"
              + ("  + empty sms (NOT_CONNECTED)" if nc else ""), flush=True)
        print(flush=True)
    passed = len(CASES) - fails
    print(f"RESULT: {passed}/{len(CASES)} checks passed", flush=True)
    print(f"VERDICT: {'ALL PASS ✓' if fails == 0 else f'{fails} FAILURE(S) ✗'}", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
