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

Two more checks keep the agent from silently drifting away from the contract:
  * drift: contracts/examples/ai_{request,response}.json here are COPIES of the
    canonical files in ../contracts/examples (the contracts repo next to
    agent/). When that directory exists the copies must be byte-identical
    (fix with `sh contracts/sync.sh` from the directory holding both).
  * field sets: every Pydantic model's field names must equal the schema's
    "properties" keys and its required fields the schema's "required" list,
    so a field added on one side only (e.g. the old Go-only shelter_name)
    fails here instead of in production.
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

from models import (
    AgentRequest,
    AgentResponse,
    Coordinates,
    DeviceDecision,
    NetworkStatus,
    Shelter,
    TriagedDevice,
)

REQ_PATH = REPO_ROOT / "contracts" / "examples" / "ai_request.json"
RESP_PATH = REPO_ROOT / "contracts" / "examples" / "ai_response.json"
# Canonical contracts: the contracts repo checked out next to agent/ (dev tree
# and deploy layout). Absent in a standalone agent checkout.
CANON_DIR = REPO_ROOT.parent / "contracts" / "examples"

# (model, schema file, path from the schema root). Nested models are reached
# through the request/response properties that hold them, so a renamed
# property or a re-pointed $ref is caught too, not just a changed definition.
FIELD_SET_CHECKS = [
    (AgentRequest, REQ_PATH, ()),
    (TriagedDevice, REQ_PATH, ("devices", "items")),
    (Shelter, REQ_PATH, ("nearest_shelters", "items")),
    (Coordinates, REQ_PATH, ("nearest_shelters", "items", "location")),
    (NetworkStatus, REQ_PATH, ("network_status",)),
    (AgentResponse, RESP_PATH, ()),
    (DeviceDecision, RESP_PATH, ("decisions", "items")),
]

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


def check_drift():
    """Local contract copies must be byte-identical to ../contracts/examples.

    Returns True when consistent (or when there is no canonical dir to compare
    against — a standalone agent checkout — which is reported as SKIP).
    """
    if not CANON_DIR.is_dir():
        print(f"SKIP drift check: {CANON_DIR} not found (standalone agent checkout)")
        return True
    ok = True
    print(f"Drift vs canonical [{CANON_DIR}]")
    for local in (REQ_PATH, RESP_PATH):
        canon = CANON_DIR / local.name
        if not canon.exists():
            ok = False
            print(f"  FAIL {local.name}: canonical file {canon} is missing")
        elif not local.exists():
            ok = False
            print(f"  FAIL {local.name}: local copy {local} is missing (run: sh contracts/sync.sh)")
        elif local.read_bytes() != canon.read_bytes():
            ok = False
            print(f"  FAIL {local.name}: local copy differs from canonical (run: sh contracts/sync.sh)")
        else:
            print(f"  OK  {local.name} byte-identical to canonical")
    return ok


def resolve(doc, node):
    """Follow local "$ref": "#/..." pointers until a concrete schema node."""
    for _ in range(32):
        ref = node.get("$ref") if isinstance(node, dict) else None
        if ref is None:
            return node
        if not ref.startswith("#/"):
            raise ValueError(f"only local $ref supported, got {ref!r}")
        node = doc
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
    raise ValueError("$ref chain too deep (cycle?)")


def schema_node(doc, path):
    """Walk property names (and the array keyword "items") from the root."""
    node = resolve(doc, doc)
    for step in path:
        node = resolve(doc, node["items"] if step == "items" else node["properties"][step])
    return node


def check_field_sets():
    """Pydantic field names / required fields must equal the schema's."""
    ok = True
    docs = {}
    print("Field sets (Pydantic vs schema properties / required)")
    for model, path, steps in FIELD_SET_CHECKS:
        where = f"{path.name}:{'/'.join(steps) or '(root)'}"
        if not path.exists():
            print(f"  SKIP {model.__name__}: {path} not found — field sets NOT verified")
            continue
        try:
            doc = docs.setdefault(path, json.loads(path.read_text()))
            node = schema_node(doc, steps)
        except (KeyError, TypeError, ValueError) as e:
            ok = False
            print(f"  FAIL {model.__name__}: cannot resolve {where} ({e!r})")
            continue
        fields = {f.alias or name: f for name, f in model.model_fields.items()}
        names = set(fields)
        required = {name for name, f in fields.items() if f.is_required()}
        props = set(node.get("properties", {}))
        schema_req = set(node.get("required", []))
        problems = []
        if names != props:
            problems.append(f"fields only in Pydantic: {sorted(names - props)}, "
                            f"only in schema: {sorted(props - names)}")
        if required != schema_req:
            problems.append(f"required only in Pydantic: {sorted(required - schema_req)}, "
                            f"only in schema: {sorted(schema_req - required)}")
        # extra="forbid" is the Pydantic side of additionalProperties: false.
        if node.get("additionalProperties") is not False or model.model_config.get("extra") != "forbid":
            problems.append("schema additionalProperties must be false and model extra must be 'forbid'")
        if problems:
            ok = False
            print(f"  FAIL {model.__name__} vs {where}: " + "; ".join(problems))
        else:
            print(f"  OK  {model.__name__} == {where} ({len(names)} fields, {len(required)} required)")
    return ok


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

    ok = check_field_sets() and ok
    ok = check_drift() and ok

    print("\n" + ("ALL GOOD" if ok else "FAILURES ABOVE"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
