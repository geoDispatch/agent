import json
import sys
from pathlib import Path

import httpx

# Make the project root importable when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import OLLAMA_URL, OLLAMA_MODEL
from app.schemas.response import AgentResponse


request_data = {
    "event_id": "TEST-001",
    "disaster_type": "earthquake",
    "severity": 6.8,
    "aftershock_risk": "HIGH",
    "tsunami_risk": False,
    "zone": "red",
    "batch_index": 1,
    "devices": [
        {
            "phone": "+212600000000",
            "latitude": 31.6,
            "longitude": -8.0,
            "location_radius_m": 100,
            "last_location_time": "2026-09-23T10:00:00Z",
            "reachability_status": "CONNECTED_SMS",
            "last_status_time": "2026-09-23T10:01:00Z",
            "zone": "red",
            "distance_km": 2.1,
        }
    ],
    "nearest_shelters": [
        {
            "name": "Test Shelter",
            "address": "Test Address",
            "location": {
                "latitude": 31.61,
                "longitude": -8.01,
            },
            "distance_km": 1.2,
            "capacity": 500,
        }
    ],
    "network_status": {
        "congestion_level": "HIGH",
        "sms_delivery_rate": 0.5,
        "qos_status": "active",
    },
}

request_json = json.dumps(request_data)


payload_without_format = {
    "model": OLLAMA_MODEL,
    "messages": [
        {
            "role": "user",
            "content": request_json,
        }
    ],
    "stream": False,
}


payload_with_format = {
    "model": OLLAMA_MODEL,
    "messages": [
        {
            "role": "user",
            "content": request_json,
        }
    ],
    "stream": False,
    "format": AgentResponse.model_json_schema(),
}


def run_test(name, payload):
    response = httpx.post(
        f"{OLLAMA_URL}/api/chat",
        json=payload,
        timeout=60,
    )

    response.raise_for_status()

    content = response.json()["message"]["content"]

    print("\n==============================")
    print(name)
    print("==============================")
    print(content)


run_test("TEST A — WITHOUT FORMAT", payload_without_format)
run_test("TEST B — WITH FORMAT", payload_with_format)
