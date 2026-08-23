#!/usr/bin/env python3
"""Concurrent-load test (Test #5): 3 overlapping POST /decide requests.

This is about the FastAPI APP staying stable under overlapping requests (the
"Go sends 3 batches at once" demo scenario), NOT about speed — Ollama still
serializes same-model work under the hood, so wall-clock ~= sum, and that's
fine. We spin up a REAL uvicorn server (not TestClient) and fire 3 requests
truly concurrently with httpx + asyncio.gather.

Pass criteria:
  * all 3 return HTTP 200 (app didn't crash / drop a request under overlap)
  * each response echoes ITS OWN event_id and device phone — no cross-talk
    between concurrent requests (the real concurrency-safety risk)
  * server /health still OK afterward (process stayed up)

Needs Ollama + models. Wall time ~= 3x single-device latency (serialized).

Run: .venv/bin/python tests/test_concurrent_decide.py   (from the repo root)
"""
from __future__ import annotations

import asyncio
import pathlib
import subprocess
import sys
import time

import httpx

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_T = "2026-08-23T09:15:00Z"
_PORT = 8123
_BASE = f"http://127.0.0.1:{_PORT}"


def _body(eid: str, phone: str, disaster: str) -> dict:
    return {
        "event_id": eid, "disaster_type": disaster, "severity": 6.5,
        "aftershock_risk": "MEDIUM", "tsunami_risk": False, "zone": "orange",
        "batch_index": 0,
        "devices": [{
            "phone": phone, "latitude": 33.97, "longitude": -6.85,
            "location_radius_m": 50.0, "last_location_time": _T,
            "reachability_status": "CONNECTED_DATA", "last_status_time": _T,
            "zone": "orange", "distance_km": 3.0,
        }],
        "nearest_shelters": [],
        "network_status": {
            "congestion_level": "MEDIUM", "sms_delivery_rate": 0.9,
            "qos_status": "inactive",
        },
    }


# <!-- APPEND-1 -->

# 3 distinct requests: distinct event_ids AND distinct phones, so any
# cross-talk between concurrent requests shows up as a mismatch.
REQUESTS = [
    _body("CONC-A", "+212600000001", "earthquake"),
    _body("CONC-B", "+212600000002", "flood"),
    _body("CONC-C", "+212600000003", "heatwave"),
]


def _wait_health(proc: subprocess.Popen, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False  # server died on startup
        try:
            r = httpx.get(f"{_BASE}/health", timeout=2.0)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


async def _fire_all() -> list:
    # Read timeout must clear the SERIALIZED total for all 3 devices, since
    # Ollama processes them one at a time behind the app.
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5, read=300, write=10, pool=5)) as c:
        started = time.perf_counter()
        results = await asyncio.gather(
            *(c.post(f"{_BASE}/decide", json=b) for b in REQUESTS),
            return_exceptions=True,
        )
        return results, time.perf_counter() - started


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(_PORT),
         "--log-level", "warning"],
        cwd=str(REPO_ROOT),
    )
    fails = 0
    try:
        if not _wait_health(proc):
            print("[FAIL] uvicorn did not come up healthy", flush=True)
            return 1
        print(f"server up on {_BASE}; firing {len(REQUESTS)} concurrent /decide "
              f"requests...", flush=True)

        results, wall = asyncio.run(_fire_all())
        expected = {b["event_id"]: b["devices"][0]["phone"] for b in REQUESTS}
        got_ids = []
        for i, res in enumerate(results):
            if isinstance(res, BaseException):
                fails += 1
                print(f"[FAIL] request {i} raised {type(res).__name__}: {res}",
                      flush=True)
                continue
            if res.status_code != 200:
                fails += 1
                print(f"[FAIL] request {i} -> HTTP {res.status_code}: {res.text[:200]}",
                      flush=True)
                continue
            data = res.json()
            eid = data["event_id"]
            got_ids.append(eid)
            phone = data["decisions"][0]["phone"]
            match = expected.get(eid) == phone and len(data["decisions"]) == 1
            fails += not match
            print(f"[{'PASS' if match else 'FAIL'}] {eid}: HTTP 200, "
                  f"phone={phone} (want {expected.get(eid)}), "
                  f"action={data['decisions'][0]['action']!r}", flush=True)

        no_crosstalk = sorted(got_ids) == sorted(expected)
        print(f"[{'PASS' if no_crosstalk else 'FAIL'}] all event_ids present, "
              f"no cross-talk: got {sorted(got_ids)}", flush=True)
        fails += not no_crosstalk

        # Process still alive and answering after the concurrent burst?
        alive = proc.poll() is None and _wait_health(proc, timeout=5.0)
        print(f"[{'PASS' if alive else 'FAIL'}] server still up after burst",
              flush=True)
        fails += not alive
        print(f"\nwall time for 3 concurrent (Ollama serializes): {wall:.1f}s",
              flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f"VERDICT: {'ALL PASS ✓' if fails == 0 else f'{fails} FAILURE(S) ✗'}",
          flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

