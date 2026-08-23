"""User-turn prompt builder for EARTHQUAKE zone batches.

The Modelfile's baked-in SYSTEM prompt (modelfiles/Modelfile.earthquake) already
defines the output format, the DeviceDecision schema, and the triage rules. This
module ONLY serializes one AgentRequest (a single zone batch) into a compact,
line-oriented block that a 3B model can parse reliably — no format/rule text is
repeated here.

Kept structurally parallel with prompts/flood.py and prompts/heatwave.py; the
only intended difference is the EARTHQUAKE-specific event fields
(aftershock_risk, tsunami_risk).
"""

from models.schemas import AgentRequest


def build_prompt(request: AgentRequest) -> str:
    """Serialize one earthquake zone batch into the user-turn prompt text."""
    lines: list[str] = []

    # Event / batch context — one field per line.
    lines.append(f"disaster_type: {request.disaster_type}")
    lines.append(f"severity: {request.severity}")
    lines.append(f"zone: {request.zone}")
    lines.append(f"batch_index: {request.batch_index}")

    # EARTHQUAKE-specific event fields (the only intended divergence from the
    # flood/heatwave builders).
    lines.append(f"aftershock_risk: {request.aftershock_risk}")
    lines.append(f"tsunami_risk: {str(request.tsunami_risk).lower()}")

    # One block per device — every device in the batch is emitted, never dropped.
    lines.append("")
    lines.append(f"devices ({len(request.devices)}):")
    for i, device in enumerate(request.devices, 1):
        lines.append(f"- device {i}:")
        lines.append(f"    phone: {device.phone}")
        lines.append(f"    reachability_status: {device.reachability_status}")
        lines.append(f"    distance_km: {device.distance_km}")
        lines.append(f"    zone: {device.zone}")

    # Nearest shelters — skip the block entirely when the list is empty.
    if request.nearest_shelters:
        lines.append("")
        lines.append(f"nearest_shelters ({len(request.nearest_shelters)}):")
        for shelter in request.nearest_shelters:
            lines.append(f"- {shelter.name} ({shelter.distance_km} km)")

    # Network status — affects SMS deliverability.
    lines.append("")
    lines.append("network_status:")
    lines.append(f"    congestion_level: {request.network_status.congestion_level}")
    lines.append(f"    sms_delivery_rate: {request.network_status.sms_delivery_rate}")

    return "\n".join(lines)
