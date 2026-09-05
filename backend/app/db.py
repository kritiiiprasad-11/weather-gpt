"""Optional PostGIS / TimescaleDB persistence.

If DATABASE_URL is empty every function becomes a no-op, so the API runs fine
without a database while you are still building. Schema lives in db/schema.sql.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .config import settings
from .models import AlertBundle, CurrentWeather

log = logging.getLogger("weathergpt.db")

try:  # asyncpg is optional at import time
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

_pool: Any = None


def enabled() -> bool:
    """A database was configured (not necessarily reachable)."""
    return bool(settings.DATABASE_URL) and asyncpg is not None


def connected() -> bool:
    """A pool is actually open. This is what /api/health should report."""
    return _pool is not None


async def startup() -> None:
    global _pool
    if not enabled():
        log.info("DATABASE_URL not set - running without persistence.")
        return
    try:
        _pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=settings.DB_MIN_POOL,
            max_size=settings.DB_MAX_POOL,
        )
        log.info("Postgres pool ready.")
    except Exception as exc:  # noqa: BLE001
        log.warning("Postgres unavailable (%s). Continuing without persistence.", exc)
        _pool = None


async def shutdown() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def log_observation(obs: CurrentWeather) -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as con:
            await con.execute(
                """
                INSERT INTO weather_observations (
                    observed_at, place_name, geom, temperature_c, humidity_pct,
                    pressure_hpa, pressure_change_3h_hpa, wind_speed_kmh,
                    wind_direction_deg, rainfall_mm_hr, cloud_cover_pct,
                    visibility_km, condition, source
                ) VALUES ($1,$2, ST_SetSRID(ST_MakePoint($3,$4),4326),
                          $5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                """,
                obs.observed_at, obs.location.name,
                obs.location.longitude, obs.location.latitude,
                obs.temperature_c, obs.humidity_pct, obs.pressure_hpa,
                obs.pressure_change_3h_hpa, obs.wind_speed_kmh,
                obs.wind_direction_deg, obs.rainfall_mm_hr,
                obs.cloud_cover_pct, obs.visibility_km, obs.condition, obs.source,
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("log_observation skipped: %s", exc)


async def log_alerts(bundle: AlertBundle, session_id: str | None = None) -> None:
    if not _pool or not bundle.alerts:
        return
    try:
        async with _pool.acquire() as con:
            for a in bundle.alerts:
                await con.execute(
                    """
                    INSERT INTO alert_events (
                        hazard, severity, headline, detail, action, triggered_by,
                        valid_from, valid_to, place_name, geom, session_id
                    ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,
                              ST_SetSRID(ST_MakePoint($10,$11),4326),$12)
                    """,
                    a.hazard.value, a.severity.value, a.headline, a.detail, a.action,
                    json.dumps(a.triggered_by), a.valid_from, a.valid_to,
                    a.location.name, a.location.longitude, a.location.latitude,
                    session_id,
                )
    except Exception as exc:  # noqa: BLE001
        log.debug("log_alerts skipped: %s", exc)


async def log_chat(session_id: str | None, role: str, content: str,
                   language: str, tools: list[str] | None = None) -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as con:
            await con.execute(
                """INSERT INTO chat_messages (session_id, role, content, language, tools_used)
                   VALUES ($1,$2,$3,$4,$5)""",
                session_id, role, content, language, tools or [],
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("log_chat skipped: %s", exc)


async def alerts_near(lat: float, lon: float, radius_km: float = 50) -> list[dict]:
    """Alerts issued in the last 12 hours within `radius_km` — the spatial query
    that justifies PostGIS being in the stack."""
    if not _pool:
        return []
    async with _pool.acquire() as con:
        rows = await con.fetch(
            """
            SELECT hazard, severity, headline, detail, action, valid_from, valid_to,
                   place_name,
                   ST_Distance(geom::geography,
                               ST_SetSRID(ST_MakePoint($1,$2),4326)::geography)/1000
                     AS distance_km
            FROM alert_events
            WHERE valid_to > now() - interval '12 hours'
              AND ST_DWithin(geom::geography,
                             ST_SetSRID(ST_MakePoint($1,$2),4326)::geography, $3)
            ORDER BY valid_from DESC
            LIMIT 50
            """,
            lon, lat, radius_km * 1000,
        )
    return [dict(r) for r in rows]
