import copy

import pytest

from app.schemas.request import AgentRequest
from app.schemas.response import AgentResponse
from app.validators.semantic import (
    SemanticValidationError,
    ValidateActionConsistency,
    ValidateDeviceDecisions,
    ValidateEventId,
    ValidateZoneEscalation,
    ValidateZoneId,
)


PHONE_A = "+212612345678"
PHONE_B = "+212698765432"
ALL_VALIDATORS = [
    ValidateEventId,
    ValidateZoneId,
    ValidateDeviceDecisions,
    ValidateZoneEscalation,
    ValidateActionConsistency,
]


def device(phone):
    return {
        "phone": phone,
        "latitude": 31.63,
        "longitude": -8.0,
        "reachability_status": "CONNECTED_DATA",
        "zone": "red",
    }


def decision(phone, action, sms_message, rescue_priority):
    return {
        "phone": phone,
        "zone_escalated": False,
        "zone_confirmed": "red",
        "action": action,
        "sms_message": sms_message,
        "rescue_priority": rescue_priority,
        "confidence": 0.9,
        "reasoning": "test",
    }


@pytest.fixture
def request_data():
    return {
        "event_id": "EQ-2024-001",
        "disaster_type": "earthquake",
        "severity": 6.8,
        "zone": "red",
        "batch_index": 0,
        "devices": [device(PHONE_A), device(PHONE_B)],
        "network_status": {"congestion_level": "HIGH", "qos_status": "active"},
    }


@pytest.fixture
def response_data():
    return {
        "event_id": "EQ-2024-001",
        "zone": "red",
        "decisions": [
            decision(PHONE_A, "sms", "Go to the nearest shelter.", 0),
            decision(PHONE_B, "rescue_flag", "", 5),
        ],
        "gov_narrative": "Earthquake in red zone.",
        "request_qos": True,
        "confidence": 0.9,
    }


def validate(validator, request_data, response_data):
    validator(AgentRequest(**request_data), AgentResponse(**response_data))


@pytest.mark.parametrize("validator", ALL_VALIDATORS)
def test_valid_response_passes(validator, request_data, response_data):
    validate(validator, request_data, response_data)


def test_wrong_event_id_fails(request_data, response_data):
    response_data["event_id"] = "EQ-2024-999"
    with pytest.raises(SemanticValidationError):
        validate(ValidateEventId, request_data, response_data)


def test_wrong_zone_fails(request_data, response_data):
    response_data["zone"] = "orange"
    with pytest.raises(SemanticValidationError):
        validate(ValidateZoneId, request_data, response_data)


def test_decisions_count_mismatch_fails(request_data, response_data):
    # The extra decision reuses a known phone, so the phone sets still match.
    response_data["decisions"].append(copy.deepcopy(response_data["decisions"][0]))
    with pytest.raises(SemanticValidationError):
        validate(ValidateDeviceDecisions, request_data, response_data)


def test_unknown_phone_fails(request_data, response_data):
    response_data["decisions"][1]["phone"] = "+212600000000"
    with pytest.raises(SemanticValidationError):
        validate(ValidateDeviceDecisions, request_data, response_data)


def test_duplicate_phone_fails(request_data, response_data):
    response_data["decisions"][1]["phone"] = PHONE_A
    with pytest.raises(SemanticValidationError):
        validate(ValidateDeviceDecisions, request_data, response_data)


def test_zone_changed_without_escalation_fails(request_data, response_data):
    request_data["devices"][0]["zone"] = "orange"
    with pytest.raises(SemanticValidationError):
        validate(ValidateZoneEscalation, request_data, response_data)


def test_same_zone_with_escalation_fails(request_data, response_data):
    response_data["decisions"][0]["zone_escalated"] = True
    with pytest.raises(SemanticValidationError):
        validate(ValidateZoneEscalation, request_data, response_data)


def test_both_without_sms_fails(request_data, response_data):
    response_data["decisions"][0] = decision(PHONE_A, "both", "", 5)
    with pytest.raises(SemanticValidationError):
        validate(ValidateActionConsistency, request_data, response_data)


def test_both_with_zero_priority_fails(request_data, response_data):
    response_data["decisions"][0] = decision(PHONE_A, "both", "Help is coming.", 0)
    with pytest.raises(SemanticValidationError):
        validate(ValidateActionConsistency, request_data, response_data)


def test_none_with_sms_fails(request_data, response_data):
    response_data["decisions"][0] = decision(PHONE_A, "none", "Stay safe.", 0)
    with pytest.raises(SemanticValidationError):
        validate(ValidateActionConsistency, request_data, response_data)
