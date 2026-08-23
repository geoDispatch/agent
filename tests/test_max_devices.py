#!/usr/bin/env python3
"""Max-batch test (Test #4): the schema ceiling of 20 devices in one call.

AgentRequest allows devices min_length=1, max_length=20, but nothing had
actually run call_agent with 20 devices. This builds a full 20-device batch
(distinct E.164 phones), runs it through call_agent, and confirms:

  * no crash / no hang
  * exactly 20 decisions come back (nothing silently truncated)
  * decision phones line up 1:1 and IN ORDER with the request phones
    (the ordered reconciliation must hold at the ceiling too)
  * the whole thing is a schema-valid AgentResponse

SLOW: Ollama serializes same-model calls, so this is ~20 x single-device
latency (order of ~10 minutes on the CPU box). That is expected, not a hang.

Run: .venv/bin/python tests/test_max_devices.py   (from the repo root)
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from models.schemas import AgentRequest, AgentResponse
from services.ollama import call_agent

_T = "2026-08-23T09:15:00Z"
_N = 20


def _phone(i: int) -> str:
    # +2126000000NN, distinct per device, valid E.164.
    return f"+2126{i:08d}"


def _device(i: int) -> dict:
    reach = ["CONNECTED_DATA", "CONNECTED_SMS", "NOT_CONNECTED"][i % 3]
    return {
        "phone": _phone(i), "latitude": 33.97, "longitude": -6.85,
        "location_radius_m": 50.0, "last_location_time": _T,
        "reachability_status": reach, "last_status_time": _T,
        "zone": "red", "distance_km": 1.0 + i * 0.5,
    }


def _request() -> AgentRequest:
    return AgentRequest.model_validate({
        "event_id": "MAX-20", "disaster_type": "earthquake", "severity": 7.8,
        "aftershock_risk": "HIGH", "tsunami_risk": True, "zone": "red",
        "batch_index": 0,
        "devices": [_device(i) for i in range(_N)],
        "nearest_shelters": [{
            "name": "Stade Municipal", "address": "Ave Hassan II, Rabat",
            "location": {"latitude": 33.98, "longitude": -6.86},
            "distance_km": 1.1, "capacity": 500,
        }],
        "network_status": {
            "congestion_level": "CRITICAL", "sms_delivery_rate": 0.6,
            "qos_status": "inactive",
        },
    })


def main() -> int:
    req = _request()
    expected_phones = [d.phone for d in req.devices]
    print(f"running call_agent with {len(expected_phones)} devices "
          f"(serialized by Ollama; expect ~10 min)...", flush=True)

    started = time.perf_counter()
    try:
        resp = asyncio.run(call_agent(req))
    except Exception as exc:  # noqa: BLE001
        print(f"[CRASH] call_agent raised {type(exc).__name__}: {exc}", flush=True)
        return 1
    elapsed = time.perf_counter() - started

    got_phones = [d.phone for d in resp.decisions]
    checks = {
        "returned an AgentResponse": isinstance(resp, AgentResponse),
        "exactly 20 decisions (no truncation)": len(resp.decisions) == _N,
        "phones match 1:1 IN ORDER": got_phones == expected_phones,
        "response re-validates against schema": _revalidates(resp),
    }
    for label, ok in checks.items():
        print(f"[{'PASS' if ok else 'FAIL'}] {label}", flush=True)
    if got_phones != expected_phones:
        print(f"    expected {expected_phones}", flush=True)
        print(f"    got      {got_phones}", flush=True)

    fails = sum(1 for ok in checks.values() if not ok)
    print(f"\nelapsed {elapsed:.1f}s for {_N} devices "
          f"({elapsed / _N:.1f}s/device)", flush=True)
    print(f"VERDICT: {'ALL PASS ✓' if fails == 0 else f'{fails} FAILURE(S) ✗'}",
          flush=True)
    return 1 if fails else 0


def _revalidates(resp: AgentResponse) -> bool:
    try:
        AgentResponse.model_validate(resp.model_dump())
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    raise SystemExit(main())
