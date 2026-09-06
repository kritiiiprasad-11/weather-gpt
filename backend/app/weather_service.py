"""All outbound meteorological data access lives here.

Two providers are wired in:

* Open-Meteo  - keyless, gives hourly forecast + the 1940-onwards reanalysis
                archive that powers the multi-year climate baselines.
* OpenWeatherMap - used for current conditions when OPENWEATHER_API_KEY is set
                (closer to what IMD/OWM users expect for "right now" values).

Everything is normalised into the models in models.py so the agent, the alert
engine and the React client only ever see one shape.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from statistics import mean

import httpx

from .config import settings
from .models import (
    ClimateComparison,
    CurrentWeather,
    Forecast,
    ForecastPoint,
    Location,
)

log = logging.getLogger("weathergpt.weather")

# Process-local response cache: key -> (expires_at_monotonic, payload).
# _stale keeps the last good payload forever so a rate-limited request can fall
# back to slightly old data instead of failing outright.
_cache: dict[str, tuple[float, dict]] = {}
_stale: dict[str, dict] = {}
_CACHE_MAX = 512


def _prune_cache() -> None:
    """Drop expired entries, keeping the last good copy in _stale."""
    now = time.monotonic()
    for k, (expires, payload) in list(_cache.items()):
        _stale[k] = payload
        if expires <= now:
            _cache.pop(k, None)
    if len(_cache) > _CACHE_MAX:
        for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[: len(_cache) - _CACHE_MAX]:
            _cache.pop(k, None)
    if len(_stale) > _CACHE_MAX * 2:
        _stale.clear()


# How long each kind of answer stays fresh. Climate baselines are the big win:
# a ten-year average genuinely does not change during a demo.
TTL_GEOCODE = 24 * 3600
TTL_CURRENT = 300          # 5 minutes
TTL_FORECAST = 900         # 15 minutes
TTL_ARCHIVE = 24 * 3600    # reanalysis data lags by days

_CARDINALS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def degrees_to_cardinal(deg: float | None) -> str | None:
    if deg is None:
        return None
    return _CARDINALS[int((deg % 360) / 22.5 + 0.5) % 16]


class WeatherServiceError(RuntimeError):
    pass


class WeatherService:
    """Async client. One instance is created at app startup and shared."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=settings.HTTP_TIMEOUT,
            headers={"User-Agent": "WeatherGPT/1.0"},
        )

    async def shutdown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise WeatherServiceError("HTTP client not started")
        return self._client

    async def _get_json(self, url: str, params: dict, *, ttl: float = 0) -> dict:
        """GET with an in-process TTL cache and backoff on rate limits.

        Open-Meteo's keyless tier is metered per IP, and on shared hosting that
        IP is shared with strangers, so 429s happen through no fault of ours.
        Caching is the real fix: a ten-year climate baseline does not change
        between requests, and current conditions do not change every second.
        """
        key = None
        if ttl > 0:
            key = f"{url}?{sorted(params.items())}"
            hit = _cache.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]

        delay = 1.0
        last: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self.client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if key:
                    _cache[key] = (time.monotonic() + ttl, data)
                    _prune_cache()
                return data
            except httpx.HTTPStatusError as exc:
                last = exc
                if exc.response.status_code not in (429, 502, 503, 504):
                    raise
                if attempt == 2:
                    break
                retry_after = exc.response.headers.get("retry-after")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                log.warning("%s from %s, retrying in %.1fs", exc.response.status_code, url, wait)
                await asyncio.sleep(wait)
                delay *= 2
            except httpx.RequestError as exc:
                last = exc
                if attempt == 2:
                    break
                await asyncio.sleep(delay)
                delay *= 2

        # Out of retries. A stale cached value beats a hard failure.
        if key:
            stale = _stale.get(key)
            if stale is not None:
                log.warning("Serving stale data for %s after repeated failures", url)
                return stale
        raise WeatherServiceError(
            "The weather data provider is rate limiting us. Try again shortly."
        ) from last

    # ------------------------------------------------------------------
    # Geocoding
    # ------------------------------------------------------------------
    async def geocode(self, query: str, count: int = 1) -> list[Location]:
        data = await self._get_json(
            settings.OPEN_METEO_GEOCODE,
            {"name": query, "count": count, "language": "en", "format": "json"},
            ttl=TTL_GEOCODE,
        )
        out: list[Location] = []
        for r in data.get("results", []) or []:
            out.append(
                Location(
                    name=r["name"],
                    latitude=r["latitude"],
                    longitude=r["longitude"],
                    admin=r.get("admin1"),
                    country=r.get("country"),
                    timezone=r.get("timezone"),
                )
            )
        if not out:
            raise WeatherServiceError(f"No place found matching '{query}'")
        return out

    async def resolve(
        self,
        place: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> Location:
        """Place name wins; otherwise use the coordinates the browser gave us."""
        if place:
            return (await self.geocode(place))[0]
        if latitude is not None and longitude is not None:
            label = await self._reverse_label(latitude, longitude)
            return Location(name=label, latitude=latitude, longitude=longitude)
        raise WeatherServiceError("Provide either a place name or lat/lon.")

    async def _reverse_label(self, lat: float, lon: float) -> str:
        """Best-effort human label for a coordinate pair."""
        if settings.OPENWEATHER_API_KEY:
            try:
                data = await self._get_json(
                    f"{settings.OPENWEATHER_BASE}/geo/1.0/reverse",
                    {"lat": lat, "lon": lon, "limit": 1,
                     "appid": settings.OPENWEATHER_API_KEY},
                    ttl=TTL_GEOCODE,
                )
                if data:
                    st = data[0].get("state")
                    return f"{data[0]['name']}{', ' + st if st else ''}"
            except Exception:  # noqa: BLE001 - label is cosmetic
                pass
        return f"{lat:.3f}, {lon:.3f}"

    # ------------------------------------------------------------------
    # Current conditions
    # ------------------------------------------------------------------
    async def current(self, loc: Location) -> CurrentWeather:
        """Keyed provider first when available: its quota follows the key, not
        the IP address, which is what survives shared free hosting."""
        if settings.OPENWEATHER_API_KEY:
            try:
                return await self._current_owm(loc)
            except Exception as exc:  # noqa: BLE001
                log.warning("OpenWeatherMap current failed (%s), trying Open-Meteo", exc)
        return await self._current_open_meteo(loc)

    async def _current_owm(self, loc: Location) -> CurrentWeather:
        data = await self._get_json(
            f"{settings.OPENWEATHER_BASE}/data/2.5/weather",
            {
                "lat": loc.latitude,
                "lon": loc.longitude,
                "units": "metric",
                "appid": settings.OPENWEATHER_API_KEY,
            },
            ttl=TTL_CURRENT,
        )
        main = data.get("main", {})
        wind = data.get("wind", {})
        rain = data.get("rain", {}) or {}
        trend = await self.pressure_trend_3h(loc)
        deg = wind.get("deg")
        return CurrentWeather(
            location=loc,
            observed_at=datetime.fromtimestamp(data["dt"], tz=timezone.utc),
            temperature_c=main.get("temp"),
            feels_like_c=main.get("feels_like"),
            humidity_pct=main.get("humidity"),
            pressure_hpa=main.get("pressure"),
            pressure_change_3h_hpa=trend,
            wind_speed_kmh=round((wind.get("speed") or 0) * 3.6, 1),
            wind_gust_kmh=round((wind.get("gust") or 0) * 3.6, 1) or None,
            wind_direction_deg=deg,
            wind_direction_cardinal=degrees_to_cardinal(deg),
            rainfall_mm_hr=rain.get("1h", 0.0),
            cloud_cover_pct=(data.get("clouds") or {}).get("all"),
            visibility_km=(data.get("visibility") or 0) / 1000 or None,
            condition=(data.get("weather") or [{}])[0].get("description"),
            source="openweathermap",
        )

    async def _current_open_meteo(self, loc: Location) -> CurrentWeather:
        data = await self._get_json(
            settings.OPEN_METEO_FORECAST,
            {
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "current": (
                    "temperature_2m,relative_humidity_2m,apparent_temperature,"
                    "precipitation,rain,surface_pressure,cloud_cover,"
                    "wind_speed_10m,wind_direction_10m,wind_gusts_10m,weather_code"
                ),
                "hourly": "surface_pressure,precipitation,visibility",
                "past_hours": 24,
                "forecast_hours": 1,
                "timezone": "UTC",
                "wind_speed_unit": "kmh",
            },
            ttl=TTL_CURRENT,
        )
        cur = data.get("current", {})
        hourly = data.get("hourly", {})
        pressures = [p for p in (hourly.get("surface_pressure") or []) if p is not None]
        trend = None
        if len(pressures) >= 4:
            trend = round(pressures[-1] - pressures[-4], 1)
        rains = [r or 0 for r in (hourly.get("precipitation") or [])]
        rain24 = round(sum(rains[-24:]), 1) if rains else None
        vis = hourly.get("visibility") or []
        deg = cur.get("wind_direction_10m")
        return CurrentWeather(
            location=loc,
            observed_at=datetime.now(timezone.utc),
            temperature_c=cur.get("temperature_2m"),
            feels_like_c=cur.get("apparent_temperature"),
            humidity_pct=cur.get("relative_humidity_2m"),
            pressure_hpa=cur.get("surface_pressure"),
            pressure_change_3h_hpa=trend,
            wind_speed_kmh=cur.get("wind_speed_10m"),
            wind_gust_kmh=cur.get("wind_gusts_10m"),
            wind_direction_deg=deg,
            wind_direction_cardinal=degrees_to_cardinal(deg),
            rainfall_mm_hr=cur.get("precipitation"),
            rainfall_24h_mm=rain24,
            cloud_cover_pct=cur.get("cloud_cover"),
            visibility_km=round(vis[-1] / 1000, 1) if vis and vis[-1] else None,
            condition=WMO_CODES.get(cur.get("weather_code"), "Unknown"),
            source="open-meteo",
        )

    async def pressure_trend_3h(self, loc: Location) -> float | None:
        """hPa change over the last three hours. Negative = deepening low."""
        try:
            data = await self._get_json(
                settings.OPEN_METEO_FORECAST,
                {
                    "latitude": loc.latitude,
                    "longitude": loc.longitude,
                    "hourly": "surface_pressure",
                    "past_hours": 6,
                    "forecast_hours": 1,
                    "timezone": "UTC",
                },
                ttl=TTL_CURRENT,
            )
            vals = [p for p in data["hourly"]["surface_pressure"] if p is not None]
            if len(vals) >= 4:
                return round(vals[-1] - vals[-4], 1)
        except Exception:  # noqa: BLE001
            return None
        return None

    # ------------------------------------------------------------------
    # Forecast
    # ------------------------------------------------------------------
    async def forecast(self, loc: Location, hours: int = 48, days: int = 7) -> Forecast:
        """Open-Meteo first (richer fields), OpenWeatherMap as the fallback.

        Open-Meteo meters by IP, which is shared on free hosting, so on a
        rate-limited host the keyed provider is what keeps the app alive.
        """
        try:
            return await self._forecast_open_meteo(loc, hours, days)
        except WeatherServiceError:
            if not settings.OPENWEATHER_API_KEY:
                raise
            log.warning("Open-Meteo forecast unavailable, falling back to OpenWeatherMap")
            return await self._forecast_owm(loc, hours, days)

    async def _forecast_owm(self, loc: Location, hours: int, days: int) -> Forecast:
        """OWM's free 5-day/3-hour forecast, reshaped into our model."""
        data = await self._get_json(
            f"{settings.OPENWEATHER_BASE}/data/2.5/forecast",
            {
                "lat": loc.latitude,
                "lon": loc.longitude,
                "units": "metric",
                "appid": settings.OPENWEATHER_API_KEY,
            },
            ttl=TTL_FORECAST,
        )
        points: list[ForecastPoint] = []
        daily: dict[str, dict[str, float]] = {}
        for row in data.get("list", []):
            when = datetime.fromtimestamp(row["dt"], tz=timezone.utc)
            main = row.get("main", {})
            wind = row.get("wind", {})
            rain = (row.get("rain") or {}).get("3h", 0.0)
            points.append(
                ForecastPoint(
                    time=when,
                    temperature_c=main.get("temp"),
                    humidity_pct=main.get("humidity"),
                    pressure_hpa=main.get("pressure"),
                    wind_speed_kmh=round((wind.get("speed") or 0) * 3.6, 1),
                    wind_direction_deg=wind.get("deg"),
                    precipitation_mm=rain,
                    precipitation_probability_pct=round((row.get("pop") or 0) * 100),
                )
            )
            key = when.date().isoformat()
            d = daily.setdefault(key, {"max": -99.0, "min": 99.0, "rain": 0.0})
            d["max"] = max(d["max"], main.get("temp_max", main.get("temp", -99)))
            d["min"] = min(d["min"], main.get("temp_min", main.get("temp", 99)))
            d["rain"] += rain

        dates = sorted(daily)[:days]
        return Forecast(
            location=loc,
            hourly=points[:hours],
            daily_dates=dates,
            daily_max_c=[round(daily[d]["max"], 1) for d in dates],
            daily_min_c=[round(daily[d]["min"], 1) for d in dates],
            daily_rain_mm=[round(daily[d]["rain"], 1) for d in dates],
        )

    async def _forecast_open_meteo(self, loc: Location, hours: int, days: int) -> Forecast:
        data = await self._get_json(
            settings.OPEN_METEO_FORECAST,
            {
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "hourly": (
                    "temperature_2m,relative_humidity_2m,surface_pressure,"
                    "precipitation,precipitation_probability,"
                    "wind_speed_10m,wind_direction_10m"
                ),
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "forecast_days": min(days, 16),
                "timezone": "auto",
                "wind_speed_unit": "kmh",
            },
            ttl=TTL_FORECAST,
        )
        h = data.get("hourly", {})
        points: list[ForecastPoint] = []
        for i, t in enumerate(h.get("time", [])[:hours]):
            points.append(
                ForecastPoint(
                    time=datetime.fromisoformat(t),
                    temperature_c=_at(h, "temperature_2m", i),
                    humidity_pct=_at(h, "relative_humidity_2m", i),
                    pressure_hpa=_at(h, "surface_pressure", i),
                    wind_speed_kmh=_at(h, "wind_speed_10m", i),
                    wind_direction_deg=_at(h, "wind_direction_10m", i),
                    precipitation_mm=_at(h, "precipitation", i),
                    precipitation_probability_pct=_at(h, "precipitation_probability", i),
                )
            )
        d = data.get("daily", {})
        return Forecast(
            location=loc,
            hourly=points,
            daily_dates=d.get("time", []),
            daily_max_c=[v for v in d.get("temperature_2m_max", []) if v is not None],
            daily_min_c=[v for v in d.get("temperature_2m_min", []) if v is not None],
            daily_rain_mm=[v or 0 for v in d.get("precipitation_sum", [])],
        )

    # ------------------------------------------------------------------
    # Climate baselines
    # ------------------------------------------------------------------
    async def seasonal_normal_max_temp(self, loc: Location, years: int = 10) -> float | None:
        """Mean daily max for the current calendar week across N past years.

        This is the "regional seasonal average" the heatwave rule compares to.
        """
        today = datetime.now(timezone.utc).date()
        samples: list[float] = []
        # ~11 km grid. Climate normals do not vary meaningfully inside one
        # grid cell, and rounding makes nearby users share cache entries
        # instead of each triggering ten fresh archive requests.
        glat, glon = round(loc.latitude, 1), round(loc.longitude, 1)

        async def one_year(y: int) -> list[float]:
            start = today.replace(year=today.year - y) - timedelta(days=5)
            end = today.replace(year=today.year - y) + timedelta(days=5)
            data = await self._get_json(
                settings.OPEN_METEO_ARCHIVE,
                {
                    "latitude": glat,
                    "longitude": glon,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "daily": "temperature_2m_max",
                    "timezone": "auto",
                },
                ttl=TTL_ARCHIVE,
            )
            return [v for v in data["daily"]["temperature_2m_max"] if v is not None]

        try:
            results = await asyncio.gather(
                *[one_year(y) for y in range(1, years + 1)], return_exceptions=True
            )
        except Exception:  # noqa: BLE001 - no baseline just disables the rule
            log.warning("Seasonal normal unavailable; heatwave rule will be skipped")
            return None
        for r in results:
            if isinstance(r, list):
                samples.extend(r)
        return round(mean(samples), 1) if samples else None

    async def compare_climate(
        self,
        loc: Location,
        variable: str = "rainfall",
        month: int | None = None,
        years: int = 10,
    ) -> ClimateComparison:
        """Compare this month (or a named month) against an N-year baseline."""
        now = datetime.now(timezone.utc)
        month = month or now.month
        daily_var = "precipitation_sum" if variable == "rainfall" else "temperature_2m_mean"
        unit = "mm" if variable == "rainfall" else "°C"
        glat, glon = round(loc.latitude, 1), round(loc.longitude, 1)

        async def month_value(year: int) -> tuple[int, float] | None:
            start = datetime(year, month, 1).date()
            end_month = month % 12 + 1
            end_year = year + (1 if month == 12 else 0)
            end = (datetime(end_year, end_month, 1) - timedelta(days=1)).date()
            end = min(end, (now - timedelta(days=6)).date())
            if end < start:
                return None
            data = await self._get_json(
                settings.OPEN_METEO_ARCHIVE,
                {
                    "latitude": glat,
                    "longitude": glon,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "daily": daily_var,
                    "timezone": "auto",
                },
                ttl=TTL_ARCHIVE,
            )
            vals = [v for v in data["daily"][daily_var] if v is not None]
            if not vals:
                return None
            return year, round(sum(vals) if variable == "rainfall" else mean(vals), 1)

        target_year = now.year if month <= now.month else now.year - 1
        results = await asyncio.gather(
            *[month_value(target_year - k) for k in range(0, years + 1)],
            return_exceptions=True,
        )
        series = [r for r in results if isinstance(r, tuple)]
        if not series:
            raise WeatherServiceError("Archive returned no data for that period.")

        series.sort(key=lambda x: x[0], reverse=True)
        current_year, current_value = series[0]
        baseline_pairs = series[1:]
        if not baseline_pairs:
            raise WeatherServiceError("Not enough archive years for a baseline.")
        baseline = round(mean(v for _, v in baseline_pairs), 1)

        anomaly = round(current_value - baseline, 1)
        anomaly_pct = round((anomaly / baseline) * 100, 1) if baseline else 0.0
        direction = "above" if anomaly > 0 else "below"
        magnitude = (
            "sharply" if abs(anomaly_pct) > 40
            else "moderately" if abs(anomaly_pct) > 15
            else "slightly"
        )
        verdict = (
            f"{month_name(month)} {current_year} is {magnitude} {direction} the "
            f"{len(baseline_pairs)}-year normal "
            f"({current_value}{unit} vs {baseline}{unit})."
        )
        return ClimateComparison(
            location=loc,
            variable="rainfall" if variable == "rainfall" else "temperature",
            period_label=f"{month_name(month)} {current_year}",
            current_value=current_value,
            baseline_value=baseline,
            baseline_years=len(baseline_pairs),
            anomaly=anomaly,
            anomaly_pct=anomaly_pct,
            verdict=verdict,
            yearly=[{"year": float(y), "value": v} for y, v in sorted(series)],
            unit=unit,
        )


def _at(block: dict, key: str, i: int):
    arr = block.get(key) or []
    return arr[i] if i < len(arr) else None


def month_name(m: int) -> str:
    return [
        "January", "February", "March", "April", "May", "June", "July",
        "August", "September", "October", "November", "December",
    ][m - 1]


WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle",
    53: "Moderate drizzle", 55: "Dense drizzle", 61: "Light rain",
    63: "Moderate rain", 65: "Heavy rain", 66: "Freezing rain",
    67: "Heavy freezing rain", 71: "Light snow", 73: "Moderate snow",
    75: "Heavy snow", 80: "Light rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers", 95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

weather_service = WeatherService()
