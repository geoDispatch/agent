#!/usr/bin/env python3
"""Fault-injection test for /decide (Test #3): Ollama unreachable OR hung.

Two failure modes, neither of which needs a real Ollama:

  A. DEAD PORT (connection refused) — OLLAMA_HOST points at a closed port.
     httpx raises ConnectError fast; call_agent wraps it as AgentError; the
     route must return a clean 500. We fire TWICE to prove the FastAPI app
     stays up for the next request instead of crashing.

  B. BLACK HOLE (connect OK, never responds) — a tiny socket server accepts
     the TCP connection but never sends an HTTP reply. Without a read timeout
     this would hang /decide forever; with our timeout it must return 500
     within a few seconds. We also fire a second request afterward to prove
     the app survived the timeout.

Run: .venv/bin/python tests/test_faults.py   (from the repo root)
NO Ollama required — the whole point is that Ollama is broken/absent.
"""
from __future__ import annotations

import os
import pathlib
import socket
import sys
import threading
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_T = "2026-08-23T09:15:00Z"


def _request_body() -> dict:
    """One schema-valid single-device earthquake batch (as JSON-able dict)."""
    return {
        "event_id": "FAULT-TEST", "disaster_type": "earthquake", "severity": 7.5,
        "aftershock_risk": "HIGH", "tsunami_risk": False, "zone": "red",
        "batch_index": 0,
        "devices": [{
            "phone": "+212600000001", "latitude": 33.97, "longitude": -6.85,
            "location_radius_m": 50.0, "last_location_time": _T,
            "reachability_status": "CONNECTED_DATA", "last_status_time": _T,
            "zone": "red", "distance_km": 2.0,
        }],
        "nearest_shelters": [],
        "network_status": {
            "congestion_level": "HIGH", "sms_delivery_rate": 0.8,
            "qos_status": "inactive",
        },
    }


def _start_blackhole() -> tuple[socket.socket, int]:
    """A listener that accepts connections and then NEVER replies."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    port = srv.getsockname()[1]
    held: list[socket.socket] = []  # keep refs so sockets stay open

    def _loop() -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            held.append(conn)  # accepted, but we send nothing, ever

    threading.Thread(target=_loop, daemon=True).start()
    return srv, port


# <!-- APPEND-1 -->


def _fresh_client():
    """Build a TestClient AFTER env is set. main:app is imported lazily so the
    OLLAMA_* env vars we set below are the ones the app sees per request
    (ollama.AsyncClient reads OLLAMA_HOST at construction, inside call_agent)."""
    from fastapi.testclient import TestClient

    from main import app
    return TestClient(app, raise_server_exceptions=False)


def _post(client, body: dict) -> tuple[int, float]:
    started = time.perf_counter()
    resp = client.post("/decide", json=body)
    return resp.status_code, (time.perf_counter() - started)


def _check(label: str, status: int, elapsed: float, *, want_status: int,
           max_elapsed: float | None) -> bool:
    ok = status == want_status
    if max_elapsed is not None:
        ok = ok and elapsed <= max_elapsed
    bound = f" (<= {max_elapsed:.0f}s)" if max_elapsed is not None else ""
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: "
          f"status={status} (want {want_status}), took {elapsed:.1f}s{bound}",
          flush=True)
    return ok


def main() -> int:
    body = _request_body()
    fails = 0

    # ---- A. DEAD PORT (connection refused) --------------------------------- #
    print("A. Ollama DOWN — OLLAMA_HOST -> dead port 127.0.0.1:1 (refused)",
          flush=True)
    os.environ["OLLAMA_HOST"] = "http://127.0.0.1:1"
    os.environ["GEODISPATCH_OLLAMA_CONNECT_TIMEOUT"] = "2"
    os.environ["GEODISPATCH_OLLAMA_READ_TIMEOUT"] = "5"
    client = _fresh_client()
    s1, e1 = _post(client, body)
    fails += not _check("1st request -> clean 500", s1, e1,
                        want_status=500, max_elapsed=15)
    s2, e2 = _post(client, body)
    fails += not _check("2nd request -> app still up, clean 500", s2, e2,
                        want_status=500, max_elapsed=15)

    # ---- B. BLACK HOLE (connect OK, never responds -> must TIME OUT) ------- #
    print("\nB. Ollama HUNG — black-hole port (accepts, never replies)",
          flush=True)
    srv, port = _start_blackhole()
    os.environ["OLLAMA_HOST"] = f"http://127.0.0.1:{port}"
    os.environ["GEODISPATCH_OLLAMA_CONNECT_TIMEOUT"] = "2"
    os.environ["GEODISPATCH_OLLAMA_READ_TIMEOUT"] = "3"  # short so the test is fast
    client = _fresh_client()
    s3, e3 = _post(client, body)
    # Must return 500 AFTER ~read-timeout, and crucially NOT hang forever.
    ok3 = _check("hung request -> 500 via read timeout (not a hang)", s3, e3,
                 want_status=500, max_elapsed=20)
    # Prove the timeout actually fired (took at least ~the read timeout), i.e.
    # it wasn't an instant connect failure masquerading as success.
    timed_out = e3 >= 2.5
    print(f"  [{'PASS' if timed_out else 'FAIL'}] timeout genuinely fired: "
          f"elapsed {e3:.1f}s >= 2.5s", flush=True)
    fails += (not ok3) + (not timed_out)
    s4, e4 = _post(client, body)
    fails += not _check("post-timeout request -> app still up, 500", s4, e4,
                        want_status=500, max_elapsed=20)
    srv.close()

    print(f"\nRESULT: {'ALL PASS ✓' if fails == 0 else f'{fails} FAILURE(S) ✗'}",
          flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

