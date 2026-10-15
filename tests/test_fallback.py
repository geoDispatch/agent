import pytest

from app.fallback import fallback
from app.schemas.request import AgentRequest
from app.schemas.response import AgentResponse
from app.validators.semantic import semantic_validator


def phone(i):
    return f"+2126000000{i:02d}"


def device(i, zone, reachability_status):
    return {
        "phone": phone(i),
        "latitude": 31.63,
        "longitude": -8.0,
        "reachability_status": reachability_status,
        "zone": zone,
    }


def make_request(devices, zone="red"):
    return AgentRequest(
        event_id="EQ-2024-001",
        disaster_type="earthquake",
        severity=6.8,
        zone=zone,
        batch_index=0,
        devices=devices,
        network_status={"congestion_level": "HIGH", "qos_status": "active"},
    )


# 8 devices so every narrative count is distinct:
# 8 total, 5 reachable, 3 unreachable, 4 SMS, 2 rescue.
MIXED_DEVICES = [
    device(0, "red", "CONNECTED_SMS"),
    device(1, "red", "CONNECTED_SMS"),
    device(2, "red", "CONNECTED_SMS"),
    device(3, "red", "CONNECTED_SMS"),
    device(4, "red", "NOT_CONNECTED"),
    device(5, "red", "NOT_CONNECTED"),
    device(6, "green", "CONNECTED_DATA"),
    device(7, "green", "NOT_CONNECTED"),
]


def test_red_connected_sms_gets_sms():
    response = fallback(make_request([device(0, "red", "CONNECTED_SMS")]))

    assert isinstance(response, AgentResponse)
    decision = response.decisions[0]
    assert decision.phone == phone(0)
    assert decision.action == "sms"
    assert decision.sms_message
    assert decision.rescue_priority == 0
    assert decision.zone_confirmed == "red"
    assert decision.zone_escalated is False


def test_red_not_connected_gets_rescue_flag():
    response = fallback(make_request([device(0, "red", "NOT_CONNECTED")]))

    decision = response.decisions[0]
    assert decision.action == "rescue_flag"
    assert decision.sms_message == ""
    assert decision.rescue_priority > 0
    assert decision.zone_confirmed == "red"
    assert decision.zone_escalated is False


def test_safe_device_gets_no_action():
    response = fallback(make_request([device(0, "green", "CONNECTED_DATA")], zone="green"))

    decision = response.decisions[0]
    assert decision.action == "none"
    assert decision.sms_message == ""
    assert decision.rescue_priority == 0
    assert decision.zone_confirmed == "green"
    assert decision.zone_escalated is False


def test_multiple_devices_get_one_decision_each_in_order():
    response = fallback(make_request(MIXED_DEVICES))

    assert [d.phone for d in response.decisions] == [phone(i) for i in range(8)]
    assert [d.action for d in response.decisions] == [
        "sms", "sms", "sms", "sms", "rescue_flag", "rescue_flag", "none", "none",
    ]


def test_gov_narrative_counts():
    narrative = fallback(make_request(MIXED_DEVICES)).gov_narrative

    assert narrative.startswith("Red zone: ")
    assert "8 device(s) processed" in narrative
    assert "5 reachable" in narrative
    assert "3 unreachable" in narrative
    assert "SMS requested for 4 device(s)" in narrative
    assert "Rescue requested for 2 device(s)" in narrative


@pytest.mark.parametrize(
    "request_obj",
    [
        make_request([device(0, "red", "CONNECTED_SMS")]),
        make_request([device(0, "red", "NOT_CONNECTED")]),
        make_request([device(0, "green", "CONNECTED_DATA")], zone="green"),
        make_request(MIXED_DEVICES),
    ],
    ids=["red-sms", "red-not-connected", "safe", "mixed"],
)
def test_fallback_response_passes_semantic_validator(request_obj):
    response = fallback(request_obj)

    assert response.event_id == request_obj.event_id
    assert response.zone == request_obj.zone
    semantic_validator(request_obj, response)
