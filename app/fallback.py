from pydantic import BaseModel
from typing import List
from app.schemas.request import AgentRequest
from app.schemas.response import AgentResponse

class FallbackRequest(BaseModel):
    pass

def fallback(request: AgentRequest) -> AgentResponse:

    decisions: List[dict] = []

    for device in request.devices:
        start_decision: dict = {
        "phone": device.phone,
        "action": "none",
        "sms_message": "",
        "rescue_priority": 0,
        "zone_confirmed": device.zone,
        "zone_escalated": False,
        "confidence": 0.5,
        }
        if (device.zone == "red" and device.reachability_status == "CONNECTED_SMS"):
            start_decision["action"] = "sms"
            start_decision["sms_message"] = "Please evacuate immediately to the nearest shelter."
            start_decision["rescue_priority"] = 0
        elif (device.zone == "red" and device.reachability_status == "NOT_CONNECTED"):
            start_decision["action"] = "rescue_flag"
            start_decision["sms_message"] = ""
            start_decision["rescue_priority"] = 1
        start_decision["reasoning"] = (
            f"Rule-based fallback: {device.zone.value} zone, "
            f"{device.reachability_status.value}, action {start_decision['action']}."
        )
        decisions.append(start_decision)

    total_devices = len(request.devices)
    unreachable_devices = sum(d.reachability_status == "NOT_CONNECTED" for d in request.devices)
    reachable_devices = total_devices - unreachable_devices
    sms_actions = sum(d["action"] in ("sms", "both") for d in decisions)
    rescue_actions = sum(d["action"] in ("rescue_flag", "both") for d in decisions)
    gov_narrative : str= (
        f"{request.zone.value.capitalize()} zone: "
        f"{total_devices} device(s) processed. "
        f"{reachable_devices} reachable, "
        f"{unreachable_devices} unreachable. "
        f"SMS requested for {sms_actions} device(s). "
        f"Rescue requested for {rescue_actions} device(s)."
    )
    response = AgentResponse(
        event_id=request.event_id,
        zone=request.zone,
        decisions=decisions,
        gov_narrative=gov_narrative,
        request_qos=False,
        confidence=0.5,
    )
    return response
