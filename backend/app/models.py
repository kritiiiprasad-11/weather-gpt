"""Pydantic contracts shared by the REST layer, the agent tools and the UI."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Geography
# --------------------------------------------------------------------------
class Location(BaseModel):
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    admin: str | None = None
    country: str | None = None
    timezone: str | None = None


# --------------------------------------------------------------------------
# Observations
# --------------------------------------------------------------------------
class CurrentWeather(BaseModel):
    location: Location
    observed_at: datetime
    temperature_c: float
    feels_like_c: float | None = None
    humidity_pct: float | None = None
    pressure_hpa: float | None = None
    pressure_change_3h_hpa: float | None = None
    wind_speed_kmh: float | None = None
    wind_gust_kmh: float | None = None
    wind_direction_deg: float | None = None
    wind_direction_cardinal: str | None = None
    rainfall_mm_hr: float | None = None
    rainfall_24h_mm: float | None = None
    cloud_cover_pct: float | None = None
    visibility_km: float | None = None
    condition: str | None = None
    source: str = "open-meteo"


class ForecastPoint(BaseModel):
    time: datetime
    temperature_c: float | None = None
    humidity_pct: float | None = None
    pressure_hpa: float | None = None
    wind_speed_kmh: float | None = None
    wind_direction_deg: float | None = None
    precipitation_mm: float | None = None
    precipitation_probability_pct: float | None = None


class Forecast(BaseModel):
    location: Location
    hourly: list[ForecastPoint] = []
    daily_max_c: list[float] = []
    daily_min_c: list[float] = []
    daily_rain_mm: list[float] = []
    daily_dates: list[str] = []


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------
class Severity(str, Enum):
    GREEN = "green"      # no action
    YELLOW = "yellow"    # be updated / watch
    ORANGE = "orange"    # be prepared
    RED = "red"          # take action


class HazardType(str, Enum):
    FLASH_FLOOD = "flash_flood"
    CYCLONE = "cyclone"
    THUNDERSTORM = "thunderstorm"
    HEATWAVE = "heatwave"
    COLDWAVE = "coldwave"
    NONE = "none"


class Alert(BaseModel):
    hazard: HazardType
    severity: Severity
    headline: str
    detail: str
    action: str
    triggered_by: dict[str, Any] = {}
    valid_from: datetime
    valid_to: datetime
    location: Location


class AlertBundle(BaseModel):
    location: Location
    evaluated_at: datetime
    overall_severity: Severity
    alerts: list[Alert] = []


# --------------------------------------------------------------------------
# Sector advisories
# --------------------------------------------------------------------------
Sector = Literal["agriculture", "urban_transport", "aviation", "marine"]


class AdvisoryItem(BaseModel):
    title: str
    guidance: str
    severity: Severity = Severity.GREEN


class SectorAdvisory(BaseModel):
    location: Location
    sector: Sector
    issued_at: datetime
    headline: str
    items: list[AdvisoryItem] = []
    metrics: dict[str, Any] = {}


# --------------------------------------------------------------------------
# Climate analytics
# --------------------------------------------------------------------------
class ClimateComparison(BaseModel):
    location: Location
    variable: Literal["rainfall", "temperature"]
    period_label: str
    current_value: float
    baseline_value: float
    baseline_years: int
    anomaly: float
    anomaly_pct: float
    verdict: str
    yearly: list[dict[str, float]] = []
    unit: str


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------
class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []
    latitude: float | None = None
    longitude: float | None = None
    place: str | None = None
    language: str = "en"
    session_id: str | None = None


class ChatCard(BaseModel):
    """A structured payload the React client renders inside the chat stream."""

    type: Literal["weather", "alert", "advisory", "climate", "forecast"]
    data: dict[str, Any]


class ChatResponse(BaseModel):
    reply: str
    cards: list[ChatCard] = []
    tools_used: list[str] = []
    language: str = "en"
