from app.schemas.request import AgentRequest
from app.schemas.response import AgentResponse
from typing import Set

class SemanticValidationError(ValueError):
    pass
# validate event_id and zone_id in the response against the request

def ValidateEventId(AgentRequest, AgentResponse) -> None:
    if not AgentResponse.event_id or AgentResponse.event_id != AgentRequest.event_id:
        raise SemanticValidationError("Event ID is not valid.")

def ValidateZoneId(AgentRequest, AgentResponse) -> None:
    if not AgentResponse.zone or AgentResponse.zone != AgentRequest.zone:
        raise SemanticValidationError("Zone ID is not valid.")
def ValidateDeviceDecisions(AgentRequest, AgentResponse) -> None:
    if len(AgentResponse.decisions) != len(AgentRequest.devices):
        raise SemanticValidationError("Number of decisions does not match number of devices.")
    request_phones : Set[str] = {device.phone for device in AgentRequest.devices}
    response_phones : Set[str] = {decision.phone for decision in AgentResponse.decisions}
    if request_phones != response_phones:
        raise SemanticValidationError("Device phone numbers in the response do not match those in the request.")

def ValidateZoneEscalation(request: AgentRequest, response: AgentResponse) -> None:
    for request_device, response_decision in zip(request.devices, response.decisions):
        if request_device.zone != response_decision.zone_confirmed and not response_decision.zone_escalated:
            raise SemanticValidationError(
                f"Device {request_device.phone} is marked as escalated in the "
                "request but not in the response."
            )
        elif request_device.zone == response_decision.zone_confirmed and  response_decision.zone_escalated:
            raise SemanticValidationError(
                f"Device {request_device.phone} is marked as escalated in the "
                "request but not in the response."
            )
def ValidateActionConsistency(request: AgentRequest, response: AgentResponse) -> None:
    for response_decision in response.decisions:
        action = response_decision.action
        has_sms = bool(response_decision.sms_message)
        priority = response_decision.rescue_priority
        if action == "sms":
            invalid = not has_sms or priority != 0
        elif action == "rescue_flag":
            invalid = has_sms or priority <= 0
        elif action == "both":
            invalid = not has_sms or priority <= 0
        elif action == "none":
            invalid = has_sms
        else:
            invalid = False

        if invalid:
            raise SemanticValidationError(
                f"Device {response_decision.phone} has an invalid action response."
            )
def semantic_validator(request, response):
    ValidateEventId(request, response)
    ValidateZoneId(request, response)
    ValidateDeviceDecisions(request, response)
    ValidateZoneEscalation(request, response)
    ValidateActionConsistency(request, response)