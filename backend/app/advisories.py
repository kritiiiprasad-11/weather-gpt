"""Sector advisories derived from the same observation + forecast pair.

Each sector reads different variables out of the forecast: a farmer cares about
the 72-hour rain total before spraying, a dispatcher cares about visibility and
waterlogging, a pilot cares about crosswind and cloud base, a fishing crew cares
about wind fetch and gusts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    AdvisoryItem,
    CurrentWeather,
    Forecast,
    Location,
    SectorAdvisory,
    Severity,
)
from .weather_service import weather_service


def _rain_next(fc: Forecast, hours: int) -> float:
    return round(sum(p.precipitation_mm or 0 for p in fc.hourly[:hours]), 1)


def _max_wind(fc: Forecast, hours: int) -> float:
    return round(max([p.wind_speed_kmh or 0 for p in fc.hourly[:hours]] or [0]), 1)


def _cloud_base_m(temp_c: float | None, rh: float | None) -> float | None:
    """Espy's approximation: base ≈ 125 m per °C of dewpoint depression."""
    if temp_c is None or rh is None or rh <= 0:
        return None
    dew = temp_c - ((100 - rh) / 5.0)
    return max(round((temp_c - dew) * 125), 0)


def build(sector: str, cur: CurrentWeather, fc: Forecast) -> SectorAdvisory:
    loc: Location = cur.location
    now = datetime.now(timezone.utc)
    rain24 = _rain_next(fc, 24)
    rain72 = _rain_next(fc, 72)
    wind12 = _max_wind(fc, 12)
    items: list[AdvisoryItem] = []
    metrics: dict = {
        "rain_next_24h_mm": rain24,
        "rain_next_72h_mm": rain72,
        "peak_wind_12h_kmh": wind12,
        "humidity_pct": cur.humidity_pct,
        "temperature_c": cur.temperature_c,
    }

    if sector == "agriculture":
        headline = f"{rain72:.0f} mm of rain expected over the next three days"
        if rain24 < 2:
            items.append(AdvisoryItem(
                title="Irrigation",
                guidance=("Little to no rain in the next 24 hours. Irrigate early morning "
                          "or after 17:00 to cut evaporation losses."),
                severity=Severity.YELLOW))
        elif rain24 > 40:
            items.append(AdvisoryItem(
                title="Skip irrigation and open drains",
                guidance=(f"{rain24:.0f} mm expected in 24 hours. Stop scheduled irrigation "
                          "and clear field drains so standing water does not choke roots."),
                severity=Severity.ORANGE))
        else:
            items.append(AdvisoryItem(
                title="Irrigation",
                guidance=f"{rain24:.0f} mm of natural rainfall covers most crop demand today.",
                severity=Severity.GREEN))

        spray_ok = rain24 < 5 and wind12 < 15
        items.append(AdvisoryItem(
            title="Spraying window",
            guidance=("Conditions suit spraying: dry spell with light wind. Finish before "
                      "midday heat." if spray_ok else
                      f"Hold off spraying — {rain24:.0f} mm rain and gusts to {wind12:.0f} km/h "
                      "will wash off or drift the chemical."),
            severity=Severity.GREEN if spray_ok else Severity.ORANGE))

        if (cur.humidity_pct or 0) > 85 and 18 <= (cur.temperature_c or 0) <= 30:
            items.append(AdvisoryItem(
                title="Fungal disease risk",
                guidance=("Humidity above 85% with mild temperatures favours blight and "
                          "downy mildew. Scout fields and plan a preventive spray in the "
                          "next dry window."),
                severity=Severity.ORANGE))
        if rain72 > 100:
            items.append(AdvisoryItem(
                title="Harvest and storage",
                guidance=("Bring harvested produce under cover and raise stacks off the "
                          "ground before the wet spell."),
                severity=Severity.RED))

    elif sector == "urban_transport":
        headline = "Road conditions and flood risk"
        vis = cur.visibility_km
        if rain24 > 60:
            items.append(AdvisoryItem(
                title="Waterlogging likely",
                guidance=(f"{rain24:.0f} mm forecast in 24 hours. Expect standing water at "
                          "underpasses and drains backing up. Add 40-60 minutes to commutes."),
                severity=Severity.RED))
        elif rain24 > 20:
            items.append(AdvisoryItem(
                title="Wet roads",
                guidance="Slow down, double your following distance, and use low beams.",
                severity=Severity.YELLOW))
        else:
            items.append(AdvisoryItem(
                title="Roads",
                guidance="No rain-related disruption expected on the main corridors.",
                severity=Severity.GREEN))
        if vis is not None and vis < 1:
            items.append(AdvisoryItem(
                title="Low visibility",
                guidance=f"Visibility down to {vis:.1f} km. Use fog lamps and avoid overtaking.",
                severity=Severity.RED))
        if wind12 > 50:
            items.append(AdvisoryItem(
                title="High-sided vehicles",
                guidance=(f"Gusts to {wind12:.0f} km/h. Trucks and two-wheelers should avoid "
                          "flyovers and open stretches."),
                severity=Severity.ORANGE))
        metrics["visibility_km"] = vis

    elif sector == "aviation":
        base = _cloud_base_m(cur.temperature_c, cur.humidity_pct)
        headline = "Terminal area conditions"
        metrics["cloud_base_m"] = base
        metrics["visibility_km"] = cur.visibility_km
        metrics["wind_direction_deg"] = cur.wind_direction_deg
        if base is not None:
            items.append(AdvisoryItem(
                title="Cloud base",
                guidance=(f"Estimated base near {base} m AGL "
                          f"({'IMC likely, expect approach delays' if base < 300 else 'VMC likely'})."),
                severity=Severity.RED if base < 150 else
                         Severity.ORANGE if base < 300 else Severity.GREEN))
        if cur.visibility_km is not None:
            items.append(AdvisoryItem(
                title="Visibility",
                guidance=f"{cur.visibility_km:.1f} km reported. "
                         + ("Below CAT-I minima at many Indian fields."
                            if cur.visibility_km < 1.5 else "Above standard approach minima."),
                severity=Severity.RED if cur.visibility_km < 1.5 else Severity.GREEN))
        shear = wind12 - (cur.wind_speed_kmh or 0)
        items.append(AdvisoryItem(
            title="Wind and shear",
            guidance=(f"Surface wind {cur.wind_speed_kmh or 0:.0f} km/h from "
                      f"{cur.wind_direction_cardinal or '—'}, peaking at {wind12:.0f} km/h. "
                      + ("Marked low-level shear risk on final approach."
                         if shear > 25 else "Shear risk low.")),
            severity=Severity.ORANGE if shear > 25 else Severity.GREEN))

    elif sector == "marine":
        headline = "Sea state and fishing advisory"
        # Rough sea-state estimate from sustained wind (Beaufort-ish mapping).
        wave = round(0.0025 * (wind12 ** 1.6), 1)
        metrics["est_wave_height_m"] = wave
        if wind12 > 60:
            sev, note = Severity.RED, "Do not venture into the sea."
        elif wind12 > 40:
            sev, note = Severity.ORANGE, "Small craft should return to harbour."
        elif wind12 > 25:
            sev, note = Severity.YELLOW, "Moderate sea. Experienced crews only."
        else:
            sev, note = Severity.GREEN, "Sea conditions are workable."
        items.append(AdvisoryItem(
            title="Sea state",
            guidance=f"Winds to {wind12:.0f} km/h, estimated significant wave height {wave} m. {note}",
            severity=sev))
        items.append(AdvisoryItem(
            title="Visibility at sea",
            guidance=(f"{cur.visibility_km:.1f} km. Keep radar and AIS on."
                      if cur.visibility_km else "Visibility data unavailable; navigate with caution."),
            severity=Severity.YELLOW if (cur.visibility_km or 10) < 3 else Severity.GREEN))
    else:
        headline = "General advisory"
        items.append(AdvisoryItem(
            title="Overview",
            guidance=f"{cur.condition or 'Current conditions'} at {cur.temperature_c:.0f} °C.",
            severity=Severity.GREEN))

    return SectorAdvisory(
        location=loc,
        sector=sector,  # type: ignore[arg-type]
        issued_at=now,
        headline=headline,
        items=items,
        metrics=metrics,
    )


async def build_for_location(loc: Location, sector: str) -> SectorAdvisory:
    cur = await weather_service.current(loc)
    fc = await weather_service.forecast(loc, hours=72, days=4)
    return build(sector, cur, fc)
