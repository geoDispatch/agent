from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class Status(str, Enum):
    """Network congestion level, from low load up to critical saturation."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class QosStatus(str, Enum):
    """Quality-of-Service state of a prioritized network slice for a device."""
    INACTIVE = "inactive"
    REQUESTED = "requested"
    ACTIVE = "active"
    FAILED = "failed"


class ReachabilityStatus(str, Enum):
    """How a device can currently be reached: full data, SMS only, or offline."""
    CONNECTED_DATA = "CONNECTED_DATA"
    CONNECTED_SMS = "CONNECTED_SMS"
    NOT_CONNECTED = "NOT_CONNECTED"


class Zone(str, Enum):
    """Danger zone a location falls in: red (highest) to green (safe)."""
    RED = "red"
    ORANGE = "orange"
    GREEN = "green"


class DisasterType(str, Enum):
    """The kind of disaster event being handled."""
    FLOOD = "flood"
    EARTHQUAKE = "earthquake"
    HEATWAVE = "heatwave"


class AftershockRisk(str, Enum):
    """Likelihood of further aftershocks following an earthquake."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Coordinates(BaseModel):
    """A geographic point (latitude/longitude) with validated bounds."""
    latitude: float = Field(..., ge=-90, le=90, description="Latitude in degrees, must be between -90 and 90.")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude in degrees, must be between -180 and 180.")


class NetworkStatus(BaseModel):
    """Snapshot of network health: congestion, QoS state, and SMS delivery rate."""
    congestion_level: Status = Field(..., description="The status of the network.")
    qos_status: QosStatus = Field(..., description="The QoS status of the network.")
    sms_delivery_rate: Optional[float] = Field(None, ge=0.0, le=1.0, description="The fraction of successfully delivered SMS messages (0..1).")


class TriagedDevice(BaseModel):
    """A single citizen device that has been located and triaged during a disaster."""
    phone: str = Field(..., pattern=r"^\+[1-9]\d{1,14}$", description="The phone number of the device in E.164 format.")
    latitude: float = Field(..., ge=-90, le=90, description="Latitude in degrees, must be between -90 and 90.")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude in degrees, must be between -180 and 180.")
    location_radius_m: Optional[float] = Field(None, ge=0.0, description="The radius in meters around the location.")
    last_location_time: Optional[datetime] = Field(None, description="The last time the location was updated.")
    reachability_status: ReachabilityStatus = Field(..., description="The reachability status of the device.")
    last_status_time: Optional[datetime] = Field(None, description="The last time the device was reachable.")
    zone: Zone = Field(..., description="The zone to which the device belongs.")
    distance_km: Optional[float] = Field(None, ge=0.0, description="The distance in kilometers.")


class Shelter(BaseModel):
    """A nearby shelter a device can be directed to, with capacity and location."""
    name: str = Field(..., description="The name of the shelter.")
    address: str = Field(..., description="The address of the shelter.")
    capacity: Optional[int] = Field(None, ge=0, description="The capacity of the shelter.")
    location: Coordinates = Field(..., description="The geographical coordinates of the shelter.")
    distance_km: Optional[float] = Field(None, ge=0.0, description="The distance in kilometers to the shelter.")


class AgentRequest(BaseModel):
    """Top-level request the agent receives: one disaster event, a batch of triaged
    devices, the nearest shelters, and current network status to decide from."""
    event_id: str = Field(..., description="The unique identifier for the event.")
    disaster_type: DisasterType = Field(..., description="The type of disaster.")
    severity: Optional[float] = Field(None, ge=0.0, le=10.0, description="Richter magnitude (earthquake) or equivalent severity scale, between 0 and 10.")
    aftershock_risk: Optional[AftershockRisk] = Field(None, description="The risk of aftershocks.")
    tsunami_risk: Optional[bool] = Field(None, description="Indicates if there is a tsunami risk.")
    zone: Zone = Field(..., description="The zone of the disaster.")
    batch_index: int = Field(..., ge=0, description="The index of the batch of requests.")
    devices: List[TriagedDevice] = Field(..., min_length=0, max_length=20, description="A list of triaged devices.")
    nearest_shelters: Optional[List[Shelter]] = Field(None, min_length=0, max_length=3, description="A list of the nearest shelters.")
    network_status: NetworkStatus = Field(..., description="The status of the network.")
