"""User-turn prompt builder for FLOOD zone batches.

The Modelfile's baked-in SYSTEM prompt (modelfiles/Modelfile.flood) already
defines the output format, the DeviceDecision schema, and the triage rules. This
module ONLY serializes one AgentRequest (a single zone batch) into a compact,
line-oriented block that a 3B model can parse reliably — no format/rule text is
repeated here.

Kept structurally parallel with prompts/earthquake.py and prompts/heatwave.py;
flood has no hazard-specific event fields, so it omits the earthquake-only
aftershock_risk / tsunami_risk lines.
"""

from models.schemas import AgentRequest


def build_prompt(request: AgentRequest) -> str:
    """Serialize one flood zone batch into the user-turn prompt text."""
    lines: list[str] = []

    # Event / batch context — one field per line.
    lines.append(f"disaster_type: {request.disaster_type}")
    lines.append(f"severity: {request.severity}")
    lines.append(f"zone: {request.zone}")
    lines.append(f"batch_index: {request.batch_index}")

    # (No flood-specific event fields — the earthquake builder adds
    # aftershock_risk / tsunami_risk here.)

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
    # The "name:" label is load-bearing, not decoration: the Modelfile's SMS
    # SHELTER NAME rule says to copy "the name field of the nearest entry", and
    # with a bare bullet the model had no field by that name to copy from. It
    # translated or transliterated the name instead (Salle Omnisports Ghandi
    # -> "ساحة الألعاب الجامعية غاندي") in 4 of 6 probe cases on 2026-08-30.
    if request.nearest_shelters:
        lines.append("")
        lines.append(f"nearest_shelters ({len(request.nearest_shelters)}):")
        for shelter in request.nearest_shelters:
            lines.append(f"- name: {shelter.name} ({shelter.distance_km} km)")

    # Network status — affects SMS deliverability.
    lines.append("")
    lines.append("network_status:")
    lines.append(f"    congestion_level: {request.network_status.congestion_level}")
    lines.append(f"    sms_delivery_rate: {request.network_status.sms_delivery_rate}")

    return "\n".join(lines)
