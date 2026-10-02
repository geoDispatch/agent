from app.schemas.request import AgentRequest
from app.schemas.response import AgentResponse

class SemanticValidationError(ValueError):
    pass

def validate_phones(request_devices, response_decisions):
    """
    Every request device must have exactly one response decision.
    """
    request_phones = {device.phone for device in request_devices}
    response_phones = [decision.phone for decision in response_decisions]
    # Check duplicates first
    if len(response_phones) != len(set(response_phones)):
        return False

    return request_phones == set(response_phones)

def validate_device_zones(request_devices, response_decisions):
    """
    Compare every device with the response decision
    belonging to the same phone.
    """

    decisions_by_phone: dict[str, AgentResponse] = {
        decision.phone: decision for decision in response_decisions
    }

    for device in request_devices:
        decision : AgentResponse | None = decisions_by_phone.get(device.phone)
        if decision is None:
            return False

        request_zone = device.zone.value
        response_zone = decision.zone_confirmed.value
        # Zone changed but AI says it did NOT escalate
        if request_zone != response_zone and not decision.zone_escalated:
            return False
        # AI says zone escalated but zone did not change
        if request_zone == response_zone and decision.zone_escalated:
            return False
    return True

def semantic_validator( request: AgentRequest,response: AgentResponse)-> bool:
    """
    Validate that AgentResponse logically corresponds
    to the original AgentRequest.
    """
    # 1. Event ID must match
    if response.event_id != request.event_id:
        raise SemanticValidationError(
            f"Event ID mismatch: "
            f"{response.event_id} != {request.event_id}"
        )
    # 2. Batch zone must match
    if response.zone.value != request.zone.value:
        raise SemanticValidationError(
            f"Zone mismatch: "
            f"{response.zone.value} != {request.zone.value}"
        )
    # 3. Same number of devices and decisions
    if len(response.decisions) != len(request.devices):
        raise SemanticValidationError(
            "Number of decisions does not match number of devices."
        )
    # 4. Decisions cannot be empty
    if len(response.decisions) == 0:
        raise SemanticValidationError(
            "Decisions list cannot be empty."
        )
    # 5. Phones must match exactly
    if not validate_phones(request.devices,response.decisions):
        raise SemanticValidationError(
            "Response phone numbers do not match request devices."
        )
    # 6. Check each device zone
    if not validate_device_zones(request.devices, response.decisions):
        raise SemanticValidationError(
            "Device zone validation failed."
        )
    return True