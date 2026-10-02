from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime
from enum import Enum

class ZoneConfig(str, Enum):
    """Configuration for the danger zone a location falls in: red (highest) to green (safe)."""
    RED = "red"
    ORANGE = "orange"
    GREEN = "green"
class Action(str, Enum):
    """Actions that can be taken for a device based on its zone and status."""
    SMS = "sms"
    RESCUE_FLAG = "rescue_flag"
    BOTH = "both"
    NONE = "none"

class DeviceDecision(BaseModel):
    """A decision made for a single device, including the recommended shelter and any special instructions."""
    phone: str = Field(..., pattern=r"^\+[1-9]\d{1,14}$", description="The phone number of the device in E.164 format.")
    zone_escalated : bool = Field(..., description="Indicates if the device's zone has escalated to a more dangerous level.")
    zone_confirmed : ZoneConfig = Field(..., description="The confirmed zone for the device.")
    action: Action = Field(..., description="The recommended action for the device.")
    sms_message: str = Field(max_length=320, description="The SMS message to be sent to the device, if applicable.")
    rescue_priority: int = Field(..., ge=0, le=10, description="The priority for rescue operations, if applicable.")
    model_config = ConfigDict(extra="forbid")
    confidence : float = Field(..., ge=0.0, le=1.0, description="The confidence level of the decision, between 0 and 1.")
    reasoning: str = Field(..., description="Internal audit log — the AI's reasoning chain. Required.")
class AgentResponse(BaseModel):
    """The response from the agent, including decisions for each device and any relevant metadata."""
    event_id: str = Field(..., description="The unique identifier for the event.")
    model_config = ConfigDict(extra="forbid")
    zone: ZoneConfig = Field(..., description="The zone of the disaster.")
    decisions: List[DeviceDecision] = Field(..., min_length=1, description="A list of decisions made for each device.")
    gov_narrative: str = Field(min_length=1, description="A narrative or message from the government or authorities, if applicable.")
    request_qos: bool = Field(..., description="Indicates if the request is for Quality of Service (QoS) evaluation.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="The overall confidence level of the response, between 0 and 1.")

