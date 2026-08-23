#!/usr/bin/env python3
"""test_e2e.py — Week 1 exit-criteria end-to-end test for POST /decide.

Builds ~18 synthetic AgentRequest batches spanning all three hazards and every
structured dimension the contract exposes (zone red/orange/green,
reachability_status all three values, congestion LOW..CRITICAL/UNKNOWN, QoS
inactive/active/requested/failed), validates each through AgentRequest, POSTs
each to the FastAPI app via TestClient (no live uvicorn needed), validates every
2xx response through AgentResponse, records pass/fail + latency, appends any
failure / notable edge case to docs/CHANGELOG.md, and prints a final summary.

Note on "languages": the AgentRequest contract carries no free-text / narrative
field, so — unlike test_quality.py, which put AR/FR/EN text in gov_narrative /
context — we cannot inject a language via the input. SMS language is decided by
the model's baked-in default (bilingual AR+FR). This test therefore exercises
every STRUCTURED dimension the contract exposes; language coverage lives in
test_quality.py.

Run:  .venv/bin/python test_e2e.py
"""
from __future__ import annotations

import datetime as dt
import pathlib
import statistics
import time
from collections import defaultdict

from fastapi.testclient import TestClient
from pydantic import ValidationError

from main import app
from models.schemas import AgentRequest, AgentResponse

CHANGELOG = pathlib.Path("docs/CHANGELOG.md")
TODAY = dt.date.today().isoformat()
_T = "2026-08-23T09:15:00Z"     # fixed timestamps (contract needs date-time; value is inert)


def _device(phone: str, reach: str, zone: str, dist: float) -> dict:
    return {
        "phone": phone, "latitude": 33.97, "longitude": -6.85,
        "location_radius_m": 50.0, "last_location_time": _T,
        "reachability_status": reach, "last_status_time": _T,
        "zone": zone, "distance_km": dist,
    }


def _shelter(name: str, dist: float, cap: int = 300) -> dict:
    return {
        "name": name, "address": "Ave Hassan II, Rabat",
        "location": {"latitude": 33.98, "longitude": -6.86},
        "distance_km": dist, "capacity": cap,
    }


_ALL_SHELTERS = [_shelter("École Ibn Battouta", 1.2), _shelter("Complexe Sportif Al Amal", 2.1)]

# PLACEHOLDER_SPECS
# Each spec: (event_id, hazard, severity, zone, aftershock_risk, tsunami_risk,
#             congestion_level, sms_delivery_rate, qos_status,
#             [(reachability_status, distance_km), ...], n_shelters)
# device.zone is set to the batch zone (Go sets it upstream; matching is valid).
SPECS = [
    # ---- earthquake (aftershock + tsunami vary here) ----
    ("EQ-2026-01", "earthquake", 7.2, "red",    "HIGH",   True,  "HIGH",     0.55, "inactive",
     [("NOT_CONNECTED", 2.1), ("CONNECTED_SMS", 3.4)], 2),
    ("EQ-2026-02", "earthquake", 5.5, "orange", "MEDIUM", False, "MEDIUM",   0.80, "active",
     [("CONNECTED_DATA", 8.0)], 2),
    ("EQ-2026-03", "earthquake", 3.1, "green",  "LOW",    False, "LOW",      0.95, "inactive",
     [("CONNECTED_DATA", 18.0)], 1),
    ("EQ-2026-04", "earthquake", 8.4, "red",    "HIGH",   True,  "CRITICAL", 0.40, "requested",
     [("NOT_CONNECTED", 1.2), ("NOT_CONNECTED", 0.8), ("CONNECTED_SMS", 2.5)], 2),
    ("EQ-2026-05", "earthquake", 6.0, "orange", "MEDIUM", False, "UNKNOWN",  0.65, "inactive",
     [("CONNECTED_SMS", 5.0), ("NOT_CONNECTED", 6.3)], 0),
    ("EQ-2026-06", "earthquake", 4.0, "green",  "LOW",    False, "LOW",      0.90, "active",
     [("CONNECTED_DATA", 12.0)], 1),
    # ---- flood (aftershock/tsunami inert but contract-required) ----
    ("FL-2026-07", "flood", 8.0, "red",    "LOW", False, "CRITICAL", 0.45, "inactive",
     [("NOT_CONNECTED", 15.0), ("CONNECTED_SMS", 4.0)], 2),
    ("FL-2026-08", "flood", 5.0, "orange", "LOW", False, "HIGH",     0.60, "requested",
     [("CONNECTED_SMS", 6.0)], 1),
    ("FL-2026-09", "flood", 2.5, "green",  "LOW", False, "LOW",      0.96, "inactive",
     [("CONNECTED_DATA", 20.0)], 1),
    ("FL-2026-10", "flood", 7.5, "red",    "LOW", False, "HIGH",     0.50, "active",
     [("NOT_CONNECTED", 9.0), ("NOT_CONNECTED", 11.0)], 2),
    ("FL-2026-11", "flood", 4.5, "orange", "LOW", False, "MEDIUM",   0.72, "inactive",
     [("CONNECTED_DATA", 7.0), ("CONNECTED_SMS", 3.5), ("NOT_CONNECTED", 8.2)], 1),
    ("FL-2026-12", "flood", 3.0, "green",  "LOW", False, "UNKNOWN",  0.88, "failed",
     [("CONNECTED_DATA", 14.0)], 0),
    # ---- heatwave (severity is a 0-10 danger scale, not Richter) ----
    ("HW-2026-13", "heatwave", 9.0, "red",    "LOW", False, "MEDIUM",   0.70, "inactive",
     [("NOT_CONNECTED", 12.0), ("CONNECTED_SMS", 1.0)], 2),
    ("HW-2026-14", "heatwave", 6.0, "orange", "LOW", False, "LOW",      0.92, "active",
     [("CONNECTED_DATA", 2.0)], 1),
    ("HW-2026-15", "heatwave", 3.5, "green",  "LOW", False, "LOW",      0.97, "inactive",
     [("CONNECTED_DATA", 0.5)], 1),
    ("HW-2026-16", "heatwave", 8.5, "red",    "LOW", False, "HIGH",     0.58, "requested",
     [("NOT_CONNECTED", 5.0), ("CONNECTED_SMS", 1.5), ("CONNECTED_DATA", 0.9)], 2),
    ("HW-2026-17", "heatwave", 5.5, "orange", "LOW", False, "CRITICAL", 0.48, "inactive",
     [("CONNECTED_SMS", 4.0), ("NOT_CONNECTED", 6.0)], 0),
    ("HW-2026-18", "heatwave", 2.0, "green",  "LOW", False, "LOW",      0.95, "failed",
     [("CONNECTED_DATA", 1.2)], 1),
]


def build_requests() -> list[tuple[str, dict]]:
    """Turn each spec into a JSON-ready AgentRequest payload dict."""
    out: list[tuple[str, dict]] = []
    for i, (eid, hazard, sev, zone, af, ts, cong, rate, qos, devs, nshelt) in enumerate(SPECS, 1):
        devices = [
            _device(f"+2126{i:03d}{j:03d}", reach, zone, dist)
            for j, (reach, dist) in enumerate(devs, 1)
        ]
        payload = {
            "event_id": eid, "disaster_type": hazard, "severity": sev,
            "aftershock_risk": af, "tsunami_risk": ts, "zone": zone, "batch_index": 0,
            "devices": devices, "nearest_shelters": _ALL_SHELTERS[:nshelt],
            "network_status": {"congestion_level": cong, "sms_delivery_rate": rate, "qos_status": qos},
        }
        out.append((eid, payload))
    return out


# RUN_PLACEHOLDER
def _semantic_edges(payload: dict, response: AgentResponse) -> list[str]:
    """Cheap sanity checks on a valid response — surfaced as notable edge cases."""
    notes: list[str] = []
    for d in response.decisions:
        if d.action in ("sms", "both") and not d.sms_message.strip():
            notes.append(f"{d.action} action with empty sms_message")
        if d.action in ("rescue_flag", "none") and d.sms_message.strip():
            notes.append(f"{d.action} action but sms_message is non-empty")
        if d.zone_confirmed != payload["zone"] and not d.zone_escalated:
            notes.append("zone_confirmed differs from request zone without zone_escalated")
    reach = {dev["reachability_status"] for dev in payload["devices"]}
    if payload["zone"] == "red" and "NOT_CONNECTED" in reach:
        flagged = any(d.action in ("rescue_flag", "both") for d in response.decisions)
        if not flagged:
            notes.append("red zone with NOT_CONNECTED device but nothing flagged for rescue")
    return notes


def append_changelog(rows: list[tuple[str, str, str, str]], summary_note: str) -> None:
    """Append failure / edge rows + a summary row to docs/CHANGELOG.md."""
    text = CHANGELOG.read_text() if CHANGELOG.exists() else ""
    lines: list[str] = []
    if "## E2E test log" not in text:
        lines.append("# GeoDispatch Changelog\n")
        lines.append("## E2E test log\n")
        lines.append("| Date | Input summary | What happened | How handled |")
        lines.append("|------|---------------|---------------|-------------|")
    for date, inp, happened, handled in rows:
        lines.append(f"| {date} | {inp} | {happened} | {handled} |")
    lines.append(f"| {TODAY} | test_e2e run ({len(SPECS)} batches) | {summary_note} | "
                 "Logged; Week 2 to investigate concurrent per-device calls or batching |")
    block = ("\n" if text and not text.endswith("\n") else "") + "\n".join(lines) + "\n"
    CHANGELOG.write_text(text + block)


# MAIN_PLACEHOLDER
def main() -> int:
    client = TestClient(app, raise_server_exceptions=False)
    requests = build_requests()

    results = []          # dicts: eid, hazard, zone, reach(set), status, ok(bool), latency_ms, error, notes
    changelog_rows = []   # (date, input summary, what happened, how handled)

    for eid, payload in requests:
        hazard, zone = payload["disaster_type"], payload["zone"]
        reach = sorted({d["reachability_status"] for d in payload["devices"]})
        ndev = len(payload["devices"])
        summary = f"{hazard}/{zone}/{ndev}dev/reach={'+'.join(r.split('_')[-1] for r in reach)}"
        rec = {"eid": eid, "hazard": hazard, "zone": zone, "reach": reach,
               "ndev": ndev, "ok": False, "status": "", "latency_ms": 0.0, "notes": []}

        # 1. validate the request through AgentRequest before using it
        try:
            AgentRequest.model_validate(payload)
        except ValidationError as exc:
            rec["status"] = "REQUEST_INVALID"
            rec["notes"].append(str(exc).splitlines()[0])
            changelog_rows.append((TODAY, f"{eid} {summary}", "request failed AgentRequest validation",
                                   "Test bug: fix synthetic input (not a /decide defect)"))
            results.append(rec); print(f"[{eid}] REQUEST_INVALID", flush=True); continue

        # 2. POST to /decide, measure latency. TestClient uses an in-process ASGI
        # transport (no socket), so there is no network read timeout to trip on a
        # slow model call; we still guard against any client-side error.
        t0 = time.perf_counter()
        try:
            resp = client.post("/decide", json=payload)
        except Exception as exc:  # noqa: BLE001 — a client-side failure is a failed batch
            rec["latency_ms"] = (time.perf_counter() - t0) * 1000
            rec["status"] = "POST_ERROR"
            rec["notes"].append(f"{type(exc).__name__}: {exc}")
            changelog_rows.append((TODAY, f"{eid} {summary}", f"client POST raised {type(exc).__name__}",
                                   "Test-harness/client error; re-run before Week 2 sign-off"))
            results.append(rec); print(f"[{eid}] POST_ERROR ({rec['latency_ms']:.0f}ms)", flush=True); continue
        rec["latency_ms"] = (time.perf_counter() - t0) * 1000

        if resp.status_code != 200:
            rec["status"] = f"HTTP_{resp.status_code}"
            body = resp.text[:160].replace("\n", " ")
            rec["notes"].append(body)
            changelog_rows.append((TODAY, f"{eid} {summary}", f"HTTP {resp.status_code}: {body}",
                                   "500s return a clean message; investigate server log"))
            results.append(rec); print(f"[{eid}] {rec['status']} ({rec['latency_ms']:.0f}ms)", flush=True); continue

        # 3. validate the response through AgentResponse
        try:
            ar = AgentResponse.model_validate(resp.json())
        except ValidationError as exc:
            rec["status"] = "RESPONSE_INVALID"
            rec["notes"].append(str(exc).splitlines()[0])
            changelog_rows.append((TODAY, f"{eid} {summary}", "response failed AgentResponse validation",
                                   "Contract breach — model output shape must be fixed before Week 2"))
            results.append(rec); print(f"[{eid}] RESPONSE_INVALID ({rec['latency_ms']:.0f}ms)", flush=True); continue

        rec["ok"] = True
        rec["status"] = "PASS"
        rec["notes"] = _semantic_edges(payload, ar)
        for note in rec["notes"]:
            changelog_rows.append((TODAY, f"{eid} {summary}", f"edge case: {note}",
                                   "Response still schema-valid; noted for review"))
        print(f"[{eid}] PASS ({rec['latency_ms']:.0f}ms)"
              + (f"  ⚠ {'; '.join(rec['notes'])}" if rec["notes"] else ""), flush=True)
        results.append(rec)

    return _report(results, changelog_rows)


# REPORT_PLACEHOLDER
def _report(results: list[dict], changelog_rows: list[tuple[str, str, str, str]]) -> int:
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    posted = [r for r in results if r["latency_ms"] > 0]
    posted_latencies = [r["latency_ms"] for r in posted]
    avg_ms = statistics.mean(posted_latencies) if posted_latencies else 0.0
    max_ms = max(posted_latencies) if posted_latencies else 0.0
    posted_devices = sum(r["ndev"] for r in posted)
    per_dev_ms = (sum(posted_latencies) / posted_devices) if posted_devices else 0.0

    # failure attribution by hazard and by reachability_status (rate = fails/total seen)
    hz_total, hz_fail = defaultdict(int), defaultdict(int)
    re_total, re_fail = defaultdict(int), defaultdict(int)
    for r in results:
        hz_total[r["hazard"]] += 1
        if not r["ok"]:
            hz_fail[r["hazard"]] += 1
        for rs in r["reach"]:
            re_total[rs] += 1
            if not r["ok"]:
                re_fail[rs] += 1

    summary_note = (
        f"{passed}/{total} passed; batch latency avg {avg_ms / 1000:.0f}s, max {max_ms / 1000:.0f}s; "
        f"~{per_dev_ms / 1000:.0f}s per device over {posted_devices} device calls. "
        "KNOWN LATENCY RISK: /decide makes one blocking model call per device on CPU, so batch "
        "latency scales linearly with device count — Week 2 must investigate concurrent per-device "
        "calls or batching."
    )
    append_changelog(changelog_rows, summary_note)

    print("\n" + "=" * 70)
    print("E2E SUMMARY — Week 1 exit criteria (/decide across hazards)")
    print("=" * 70)
    print(f"  passed          : {passed}/{total}")
    print(f"  avg latency     : {avg_ms:.0f} ms  (over {len(posted_latencies)} POSTed)")
    print(f"  max latency     : {max_ms:.0f} ms")
    print(f"  per-device avg  : {per_dev_ms:.0f} ms  (over {posted_devices} device calls)")
    print("  failures by hazard:")
    for hz in sorted(hz_total):
        print(f"      {hz:<10} {hz_fail[hz]}/{hz_total[hz]} failed")
    print("  failures by reachability_status:")
    for rs in sorted(re_total):
        print(f"      {rs:<15} {re_fail[rs]}/{re_total[rs]} failed")

    worst_hz = max(hz_fail, key=lambda k: hz_fail[k] / hz_total[k], default=None) if any(hz_fail.values()) else None
    worst_re = max(re_fail, key=lambda k: re_fail[k] / re_total[k], default=None) if any(re_fail.values()) else None
    if worst_hz or worst_re:
        print("  worst combination(s):")
        if worst_hz:
            print(f"      hazard   -> {worst_hz} ({hz_fail[worst_hz]}/{hz_total[worst_hz]})")
        if worst_re:
            print(f"      reachability -> {worst_re} ({re_fail[worst_re]}/{re_total[worst_re]})")
    else:
        print("  worst combination: none — no failures across any hazard/reachability")

    edge_count = sum(len(r["notes"]) for r in results if r["ok"])
    print(f"  notable edge cases logged to {CHANGELOG}: {edge_count}")
    print(f"  verdict         : {'GO ✓' if passed == total else 'NO-GO ✗'}")
    print("=" * 70)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())




