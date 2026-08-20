"""Wire contract for the GeoDispatch AI triage agent.

These Pydantic v2 models are the *locked* schema exchanged with the Go service.
Field names, enum values, and constraints mirror the JSON Schema contract 1:1 —
do not rename or add fields. Every model forbids unknown keys, matching the
contract's ``additionalProperties: false``.

Flow (one zone batch at a time):
    Go     --POST /decide-->   Python   :  AgentRequest
    Python --response------->  Go       :  AgentResponse
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Enums — Literal types, exact values from the contract (case-sensitive).
# --------------------------------------------------------------------------- #

DisasterType = Literal["earthquake", "flood", "heatwave"]
AftershockRisk = Literal["LOW", "MEDIUM", "HIGH"]
Zone = Literal["red", "orange", "green"]
ReachabilityStatus = Literal["CONNECTED_DATA", "CONNECTED_SMS", "NOT_CONNECTED"]
CongestionLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"]
QoSStatus = Literal["inactive", "requested", "active", "failed"]
Action = Literal["sms", "rescue_flag", "both", "none"]

# E.164 phone number, e.g. +14155552671 (leading '+', no leading 0, 2–15 digits).
E164_PATTERN = r"^\+[1-9]\d{1,14}$"


class StrictModel(BaseModel):
    """Base model: reject any field not declared in the contract."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Request side  (Go -> Python)
# --------------------------------------------------------------------------- #


class Coordinates(StrictModel):
    # Field names are latitude/longitude to match the contract (NOT lat/lon);
    # extra="forbid" would reject the real payloads otherwise. Bounds are the
    # universal lat/lon ranges (see note in TriagedDevice).
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class TriagedDevice(StrictModel):
    phone: str = Field(..., pattern=E164_PATTERN)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    location_radius_m: float = Field(..., ge=0)
    last_location_time: datetime
    reachability_status: ReachabilityStatus
    last_status_time: datetime
    # zone is ALWAYS set by the Go side, never by the AI.
    zone: Zone
    distance_km: float = Field(..., ge=0)


class Shelter(StrictModel):
    name: str
    address: str
    location: Coordinates
    distance_km: float = Field(..., ge=0)
    capacity: int = Field(..., ge=0)


class NetworkStatus(StrictModel):
    congestion_level: CongestionLevel
    sms_delivery_rate: float = Field(..., ge=0.0, le=1.0)
    qos_status: QoSStatus


class AgentRequest(StrictModel):
    """Go calculates zones. AI decides actions. Never reversed."""

    event_id: str
    disaster_type: DisasterType
    severity: float = Field(..., ge=0, le=10)
    aftershock_risk: AftershockRisk
    tsunami_risk: bool
    zone: Zone
    batch_index: int = Field(..., ge=0)
    devices: list[TriagedDevice] = Field(..., min_length=1, max_length=20)
    nearest_shelters: list[Shelter] = Field(..., min_length=0, max_length=3)
    network_status: NetworkStatus


# --------------------------------------------------------------------------- #
# Response side  (Python -> Go)
# --------------------------------------------------------------------------- #


class DeviceDecision(StrictModel):
    # phone must match a phone from the request (cross-checked in agent logic).
    phone: str = Field(..., pattern=E164_PATTERN)
    # zone_confirmed may differ from the incoming zone ONLY if zone_escalated is True.
    zone_confirmed: Zone
    zone_escalated: bool
    action: Action
    # "" when action is "rescue_flag" or "none"; aim < 160 for a single SMS segment.
    sms_message: str = Field(..., max_length=320)
    # CONTRACT DIRECTION: 0 = not flagged; 1 = HIGHEST urgency; urgency DECREASES
    # as the number rises toward 10 (higher number = dispatched LATER).
    # !! MISMATCH: test_quality.py's system prompt tells the model "10 = most
    # urgent" — the OPPOSITE direction. Fix that prompt before shipping, or Go
    # receives inverted priorities. Schema range (0-10) is correct either way.
    rescue_priority: int = Field(..., ge=0, le=10)
    confidence: float = Field(..., ge=0.0, le=1.0)
    # Internal audit log ONLY — never shown to end users or sent via SMS.
    reasoning: str


class AgentResponse(StrictModel):
    """Go calculates zones. AI decides actions. Never reversed."""

    event_id: str  # must echo the request's event_id
    zone: Zone  # must echo the request's zone
    decisions: list[DeviceDecision] = Field(..., min_length=1)
    gov_narrative: str = Field(..., min_length=1)  # no PII; shown to gov officials
    request_qos: bool
    confidence: float = Field(..., ge=0.0, le=1.0)


__all__ = [
    # enums
    "DisasterType",
    "AftershockRisk",
    "Zone",
    "ReachabilityStatus",
    "CongestionLevel",
    "QoSStatus",
    "Action",
    # helpers
    "E164_PATTERN",
    "StrictModel",
    # request side
    "Coordinates",
    "TriagedDevice",
    "Shelter",
    "NetworkStatus",
    "AgentRequest",
    # response side
    "DeviceDecision",
    "AgentResponse",
]
