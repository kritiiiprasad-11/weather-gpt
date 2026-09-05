"""Extreme weather early warning engine.

Rules follow the problem statement, with an added "watch" tier below each
"warning" tier so the UI has something useful to show before a hazard is
already on top of the user. Thresholds are in config.py, not hard-coded here,
so a state disaster authority can retune them without touching logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import settings
from .models import (
    Alert,
    AlertBundle,
    CurrentWeather,
    Forecast,
    HazardType,
    Location,
    Severity,
)
from .weather_service import weather_service

_ORDER = {Severity.GREEN: 0, Severity.YELLOW: 1, Severity.ORANGE: 2, Severity.RED: 3}


def _peak_hourly_rain(fc: Forecast, hours: int = 12) -> float:
    vals = [p.precipitation_mm or 0 for p in fc.hourly[:hours]]
    return max(vals) if vals else 0.0


def _peak_wind(fc: Forecast, hours: int = 12) -> float:
    vals = [p.wind_speed_kmh or 0 for p in fc.hourly[:hours]]
    return max(vals) if vals else 0.0


def _forecast_pressure_drop(fc: Forecast, hours: int = 12) -> float:
    """Largest 3-hour fall found in the next `hours` of forecast pressure."""
    p = [x.pressure_hpa for x in fc.hourly[:hours] if x.pressure_hpa is not None]
    worst = 0.0
    for i in range(3, len(p)):
        worst = min(worst, p[i] - p[i - 3])
    return worst  # negative number


def evaluate(
    current: CurrentWeather,
    forecast: Forecast,
    seasonal_normal_max_c: float | None,
) -> AlertBundle:
    now = datetime.now(timezone.utc)
    loc: Location = current.location
    alerts: list[Alert] = []

    # ---------------------------------------------------------------- flood
    obs_rain = current.rainfall_mm_hr or 0.0
    fc_rain = _peak_hourly_rain(forecast)
    rain_rate = max(obs_rain, fc_rain)
    if rain_rate > settings.RAIN_FLASH_FLOOD_MM_HR:
        alerts.append(
            Alert(
                hazard=HazardType.FLASH_FLOOD,
                severity=Severity.RED,
                headline="Flash flood warning",
                detail=(
                    f"Rainfall rate of {rain_rate:.0f} mm/hr crosses the "
                    f"{settings.RAIN_FLASH_FLOOD_MM_HR:.0f} mm/hr flash flood threshold. "
                    "Streams, underpasses and low-lying colonies can flood within minutes."
                ),
                action=(
                    "Move to higher ground now. Do not cross flowing water on foot or by "
                    "vehicle. Cut power at the mains if water enters the building."
                ),
                triggered_by={"rain_mm_hr": rain_rate,
                              "threshold": settings.RAIN_FLASH_FLOOD_MM_HR},
                valid_from=now,
                valid_to=now + timedelta(hours=6),
                location=loc,
            )
        )
    elif rain_rate > settings.RAIN_WATCH_MM_HR:
        alerts.append(
            Alert(
                hazard=HazardType.FLASH_FLOOD,
                severity=Severity.ORANGE,
                headline="Heavy rainfall watch",
                detail=(
                    f"Peak rainfall of {rain_rate:.0f} mm/hr expected. Urban waterlogging "
                    "and slow traffic are likely, especially at known low points."
                ),
                action="Delay non-essential travel. Clear drains and roof outlets.",
                triggered_by={"rain_mm_hr": rain_rate,
                              "threshold": settings.RAIN_WATCH_MM_HR},
                valid_from=now,
                valid_to=now + timedelta(hours=12),
                location=loc,
            )
        )

    # -------------------------------------------------------------- cyclone
    obs_drop = current.pressure_change_3h_hpa or 0.0
    fc_drop = _forecast_pressure_drop(forecast)
    drop = min(obs_drop, fc_drop)                 # most negative
    wind = max(current.wind_speed_kmh or 0.0, _peak_wind(forecast))
    if abs(drop) > settings.PRESSURE_DROP_HPA_3H and wind > settings.CYCLONE_WIND_KMH:
        alerts.append(
            Alert(
                hazard=HazardType.CYCLONE,
                severity=Severity.RED,
                headline="Cyclone / severe storm warning",
                detail=(
                    f"Pressure falling {abs(drop):.1f} hPa in 3 hours with winds reaching "
                    f"{wind:.0f} km/h. That combination marks a rapidly deepening system."
                ),
                action=(
                    "Secure loose roofing, hoardings and boats. Stay indoors away from "
                    "windows. Fishermen should not put out to sea."
                ),
                triggered_by={"pressure_drop_hpa_3h": drop, "wind_kmh": wind},
                valid_from=now,
                valid_to=now + timedelta(hours=24),
                location=loc,
            )
        )
    elif wind > settings.STORM_WATCH_WIND_KMH or abs(drop) > settings.PRESSURE_DROP_HPA_3H:
        alerts.append(
            Alert(
                hazard=HazardType.THUNDERSTORM,
                severity=Severity.YELLOW,
                headline="Squall / gusty wind watch",
                detail=(
                    f"Winds up to {wind:.0f} km/h with a 3-hour pressure change of "
                    f"{drop:.1f} hPa. Short-lived squalls are possible."
                ),
                action="Park away from trees and hoardings. Unplug sensitive equipment.",
                triggered_by={"pressure_drop_hpa_3h": drop, "wind_kmh": wind},
                valid_from=now,
                valid_to=now + timedelta(hours=12),
                location=loc,
            )
        )

    # ------------------------------------------------------------- heatwave
    tmax = max(forecast.daily_max_c[:1] or [current.temperature_c or 0])
    if seasonal_normal_max_c is not None:
        departure = round(tmax - seasonal_normal_max_c, 1)
        if departure > settings.HEATWAVE_DEPARTURE_C + 2:
            sev, label = Severity.RED, "Severe heatwave warning"
        elif departure > settings.HEATWAVE_DEPARTURE_C:
            sev, label = Severity.ORANGE, "Heatwave warning"
        elif departure > settings.HEATWAVE_DEPARTURE_C - 2:
            sev, label = Severity.YELLOW, "Hot day watch"
        else:
            sev = None
            label = ""
        if sev:
            alerts.append(
                Alert(
                    hazard=HazardType.HEATWAVE,
                    severity=sev,
                    headline=label,
                    detail=(
                        f"Maximum of {tmax:.1f} °C runs {departure:+.1f} °C against the "
                        f"local seasonal normal of {seasonal_normal_max_c:.1f} °C."
                    ),
                    action=(
                        "Avoid outdoor work between 12:00 and 16:00. Drink water every "
                        "20 minutes. Check on elderly neighbours and outdoor workers."
                    ),
                    triggered_by={
                        "tmax_c": tmax,
                        "seasonal_normal_c": seasonal_normal_max_c,
                        "departure_c": departure,
                    },
                    valid_from=now,
                    valid_to=now + timedelta(hours=24),
                    location=loc,
                )
            )

    overall = max((a.severity for a in alerts), key=lambda s: _ORDER[s], default=Severity.GREEN)
    return AlertBundle(
        location=loc, evaluated_at=now, overall_severity=overall, alerts=alerts
    )


async def evaluate_location(loc: Location) -> AlertBundle:
    """Convenience wrapper that fetches everything the rules need."""
    current = await weather_service.current(loc)
    forecast = await weather_service.forecast(loc, hours=24, days=3)
    normal = await weather_service.seasonal_normal_max_temp(loc, years=10)
    return evaluate(current, forecast, normal)
