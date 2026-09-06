"""Central configuration. Every value can be overridden through the environment
or a .env file placed next to requirements.txt (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- app -------------------------------------------------------------
    APP_NAME: str = "WeatherGPT"
    DEBUG: bool = True
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Vercel gives every branch and every commit its own preview URL, so an
    # exact-match list is not enough. This regex covers them all.
    CORS_ORIGIN_REGEX: str = r"https://.*\.vercel\.app"

    # ---- LLM -------------------------------------------------------------
    # provider = gemini | openai | groq | ollama | none
    # Default is Groq running gpt-oss-120b - open weights, free tier, native
    # tool calling. If the key or the provider package is missing the app falls
    # back to the deterministic rule-based agent instead of crashing, so it
    # still runs end to end with nothing configured.
    LLM_PROVIDER: Literal["gemini", "openai", "groq", "ollama", "none"] = "groq"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    GROQ_API_KEY: str = ""
    # Groq retired llama-3.3-70b-versatile in June 2026. Current list:
    # https://console.groq.com/docs/models
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    # Fully local, open-weights. No key, no network egress.
    OLLAMA_MODEL: str = "llama3.1:8b"
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # ---- weather providers ----------------------------------------------
    # OpenWeatherMap is optional. When the key is absent the service falls back
    # to Open-Meteo, which is keyless and also serves the 1940+ archive used
    # for the multi-year climate baselines.
    OPENWEATHER_API_KEY: str = ""
    OPENWEATHER_BASE: str = "https://api.openweathermap.org"
    OPEN_METEO_FORECAST: str = "https://api.open-meteo.com/v1/forecast"
    OPEN_METEO_ARCHIVE: str = "https://archive-api.open-meteo.com/v1/archive"
    OPEN_METEO_GEOCODE: str = "https://geocoding-api.open-meteo.com/v1/search"
    HTTP_TIMEOUT: float = 20.0

    # ---- database --------------------------------------------------------
    # Leave empty to run without persistence.
    DATABASE_URL: str = ""
    DB_MIN_POOL: int = 1
    DB_MAX_POOL: int = 8

    # ---- alerting --------------------------------------------------------
    RAIN_FLASH_FLOOD_MM_HR: float = 100.0
    RAIN_WATCH_MM_HR: float = 40.0
    PRESSURE_DROP_HPA_3H: float = 5.0
    CYCLONE_WIND_KMH: float = 60.0
    STORM_WATCH_WIND_KMH: float = 40.0
    HEATWAVE_DEPARTURE_C: float = 4.5
    # Each poll re-runs the threshold checks, which touch the weather API.
    # 15 minutes is plenty for hazard warnings and keeps us well inside the
    # free provider's rate limit.
    ALERT_POLL_SECONDS: int = 900

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
