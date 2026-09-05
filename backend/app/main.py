"""FastAPI entrypoint.

Run:  uvicorn app.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import db
from .advisories import build_for_location
from .agent import get_agent
from .alerts import evaluate_location
from .config import settings
from .models import (
    AlertBundle,
    ChatRequest,
    ChatResponse,
    ClimateComparison,
    CurrentWeather,
    Forecast,
    Location,
    SectorAdvisory,
)
from .weather_service import WeatherServiceError, weather_service

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("weathergpt")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await weather_service.startup()
    await db.startup()
    log.info("WeatherGPT up. LLM provider=%s, persistence=%s",
             settings.LLM_PROVIDER, db.connected())
    yield
    await db.shutdown()
    await weather_service.shutdown()


app = FastAPI(
    title="WeatherGPT API",
    version="1.0.0",
    description="Conversational weather, warnings and climate analytics.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _resolve(place: str | None, lat: float | None, lon: float | None) -> Location:
    try:
        return await weather_service.resolve(place=place, latitude=lat, longitude=lon)
    except WeatherServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Health & geocoding
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
        "llm_provider": settings.LLM_PROVIDER,
        "active_agent": type(get_agent()).__name__,
        "weather_source": "openweathermap" if settings.OPENWEATHER_API_KEY else "open-meteo",
        "persistence": db.connected(),
    }


@app.get("/api/geocode", response_model=list[Location])
async def geocode(q: str = Query(min_length=2), limit: int = 5) -> list[Location]:
    try:
        return await weather_service.geocode(q, count=limit)
    except WeatherServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 1. Real-time weather
# ---------------------------------------------------------------------------
@app.get("/api/weather/current", response_model=CurrentWeather)
async def current_weather(
    lat: float | None = None, lon: float | None = None, place: str | None = None
) -> CurrentWeather:
    loc = await _resolve(place, lat, lon)
    obs = await weather_service.current(loc)
    asyncio.create_task(db.log_observation(obs))
    return obs


@app.get("/api/weather/forecast", response_model=Forecast)
async def forecast(
    lat: float | None = None, lon: float | None = None,
    place: str | None = None, days: int = Query(3, ge=1, le=7),
) -> Forecast:
    loc = await _resolve(place, lat, lon)
    return await weather_service.forecast(loc, hours=days * 24, days=days)


# ---------------------------------------------------------------------------
# 2. Early warnings
# ---------------------------------------------------------------------------
@app.get("/api/alerts", response_model=AlertBundle)
async def alerts(
    lat: float | None = None, lon: float | None = None,
    place: str | None = None, session_id: str | None = None,
) -> AlertBundle:
    loc = await _resolve(place, lat, lon)
    bundle = await evaluate_location(loc)
    asyncio.create_task(db.log_alerts(bundle, session_id))
    return bundle


@app.get("/api/alerts/nearby")
async def alerts_nearby(lat: float, lon: float, radius_km: float = 50) -> list[dict]:
    """Recent warnings around a point, straight out of PostGIS."""
    return await db.alerts_near(lat, lon, radius_km)


@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket) -> None:
    """Push threshold checks for a subscribed point.

    Client sends: {"lat": 19.07, "lon": 72.87}  (resend any time to move)
    Server pushes an AlertBundle immediately and then every ALERT_POLL_SECONDS.
    """
    await ws.accept()
    lat: float | None = None
    lon: float | None = None

    async def pump() -> None:
        while True:
            if lat is not None and lon is not None:
                try:
                    loc = await weather_service.resolve(latitude=lat, longitude=lon)
                    bundle = await evaluate_location(loc)
                    await ws.send_text(bundle.model_dump_json())
                    await db.log_alerts(bundle)
                except Exception as exc:  # noqa: BLE001
                    await ws.send_text(json.dumps({"error": str(exc)}))
            await asyncio.sleep(settings.ALERT_POLL_SECONDS)

    task = asyncio.create_task(pump())
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            lat, lon = msg.get("lat"), msg.get("lon")
            if lat is not None and lon is not None:
                loc = await weather_service.resolve(latitude=lat, longitude=lon)
                await ws.send_text((await evaluate_location(loc)).model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()


# ---------------------------------------------------------------------------
# 3. Sector advisories
# ---------------------------------------------------------------------------
@app.get("/api/advisory", response_model=SectorAdvisory)
async def advisory(
    sector: str = Query(pattern="^(agriculture|urban_transport|aviation|marine)$"),
    lat: float | None = None, lon: float | None = None, place: str | None = None,
) -> SectorAdvisory:
    loc = await _resolve(place, lat, lon)
    return await build_for_location(loc, sector)


# ---------------------------------------------------------------------------
# 4. Historical climate
# ---------------------------------------------------------------------------
@app.get("/api/climate/compare", response_model=ClimateComparison)
async def climate_compare(
    lat: float | None = None, lon: float | None = None, place: str | None = None,
    variable: str = Query("rainfall", pattern="^(rainfall|temperature)$"),
    month: int | None = Query(None, ge=1, le=12),
    years: int = Query(10, ge=2, le=30),
) -> ClimateComparison:
    loc = await _resolve(place, lat, lon)
    try:
        return await weather_service.compare_climate(loc, variable, month, years)
    except WeatherServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 5. Chat
# ---------------------------------------------------------------------------
@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Non-streaming variant. Handy for curl and for mobile clients."""
    agent = get_agent()
    reply, cards, tools = "", [], []
    async for event in agent.stream(req):
        if event["type"] == "token":
            reply += event["text"]
        elif event["type"] == "card":
            cards.append(event["card"])
        elif event["type"] == "done":
            tools = event.get("tools_used", [])
    await db.log_chat(req.session_id, "user", req.message, req.language)
    await db.log_chat(req.session_id, "assistant", reply, req.language, tools)
    return ChatResponse(reply=reply, cards=cards, tools_used=tools, language=req.language)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Server-sent events. Each line is `data: {json}\\n\\n`."""
    agent = get_agent()

    async def gen():
        collected, tools = "", []
        try:
            async for event in agent.stream(req):
                if event["type"] == "token":
                    collected += event["text"]
                if event["type"] == "done":
                    tools = event.get("tools_used", [])
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # noqa: BLE001
            log.exception("chat stream failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        finally:
            await db.log_chat(req.session_id, "user", req.message, req.language)
            await db.log_chat(req.session_id, "assistant", collected, req.language, tools)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Voice: server-side transcription fallback
# ---------------------------------------------------------------------------
@app.post("/api/voice/transcribe")
async def transcribe(file: UploadFile, language: str = "en") -> dict:
    """Server-side speech-to-text for browsers without the Web Speech API
    (Firefox, and most in-app webviews).

    Enable by installing faster-whisper:  pip install faster-whisper
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail=("Server-side STT is not installed. Run "
                    "`pip install faster-whisper`, or use the browser Web Speech API."),
        ) from exc

    import tempfile

    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(data)
        path = tmp.name

    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, info = model.transcribe(path, language=None if language == "auto" else language)
    text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "language": info.language}
