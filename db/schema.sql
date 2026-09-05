-- WeatherGPT — spatial + time-series schema
-- Postgres 14+ with PostGIS. TimescaleDB is optional but recommended.
--
--   createdb weathergpt
--   psql -d weathergpt -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb;   -- comment out if not installed
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- fuzzy place-name search

-- ---------------------------------------------------------------------------
-- Reference: places the system knows about
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS places (
    id            BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    admin1        TEXT,
    country       TEXT DEFAULT 'India',
    timezone      TEXT DEFAULT 'Asia/Kolkata',
    population    INTEGER,
    geom          GEOMETRY(Point, 4326) NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (name, admin1, country)
);
CREATE INDEX IF NOT EXISTS idx_places_geom ON places USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_places_name_trgm ON places USING GIN (name gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- Time series: every observation the API serves is logged here
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weather_observations (
    id                      BIGSERIAL,
    observed_at             TIMESTAMPTZ NOT NULL,
    place_name              TEXT,
    place_id                BIGINT REFERENCES places(id),
    geom                    GEOMETRY(Point, 4326) NOT NULL,
    temperature_c           DOUBLE PRECISION,
    humidity_pct            DOUBLE PRECISION,
    pressure_hpa            DOUBLE PRECISION,
    pressure_change_3h_hpa  DOUBLE PRECISION,
    wind_speed_kmh          DOUBLE PRECISION,
    wind_direction_deg      DOUBLE PRECISION,
    rainfall_mm_hr          DOUBLE PRECISION,
    cloud_cover_pct         DOUBLE PRECISION,
    visibility_km           DOUBLE PRECISION,
    condition               TEXT,
    source                  TEXT DEFAULT 'open-meteo',
    PRIMARY KEY (id, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_obs_geom ON weather_observations USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_obs_time ON weather_observations (observed_at DESC);

-- Turn it into a hypertable so retention and continuous aggregates work.
SELECT create_hypertable(
    'weather_observations', 'observed_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Daily rollup used by the climate-comparison endpoint as a local cache.
CREATE MATERIALIZED VIEW IF NOT EXISTS weather_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', observed_at) AS day,
    place_name,
    avg(temperature_c)  AS mean_temp_c,
    max(temperature_c)  AS max_temp_c,
    min(temperature_c)  AS min_temp_c,
    sum(rainfall_mm_hr) AS rain_mm,
    avg(pressure_hpa)   AS mean_pressure_hpa,
    max(wind_speed_kmh) AS max_wind_kmh
FROM weather_observations
GROUP BY day, place_name
WITH NO DATA;

SELECT add_continuous_aggregate_policy('weather_daily',
    start_offset => INTERVAL '30 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

-- Keep raw observations for two years, rollups forever.
SELECT add_retention_policy('weather_observations', INTERVAL '2 years',
                            if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- Multi-year climate normals (seed from IMD gridded data or the reanalysis API)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS climate_normals (
    id             BIGSERIAL PRIMARY KEY,
    geom           GEOMETRY(Point, 4326) NOT NULL,
    region_name    TEXT,
    month          SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    baseline_start SMALLINT NOT NULL,
    baseline_end   SMALLINT NOT NULL,
    normal_rain_mm      DOUBLE PRECISION,
    normal_max_temp_c   DOUBLE PRECISION,
    normal_min_temp_c   DOUBLE PRECISION,
    UNIQUE (region_name, month, baseline_start, baseline_end)
);
CREATE INDEX IF NOT EXISTS idx_normals_geom ON climate_normals USING GIST (geom);

-- ---------------------------------------------------------------------------
-- Warnings issued by the threshold engine
-- ---------------------------------------------------------------------------
CREATE TYPE alert_severity AS ENUM ('green', 'yellow', 'orange', 'red');
CREATE TYPE hazard_type AS ENUM
    ('flash_flood', 'cyclone', 'thunderstorm', 'heatwave', 'coldwave', 'none');

CREATE TABLE IF NOT EXISTS alert_events (
    id            BIGSERIAL PRIMARY KEY,
    hazard        hazard_type NOT NULL,
    severity      alert_severity NOT NULL,
    headline      TEXT NOT NULL,
    detail        TEXT,
    action        TEXT,
    triggered_by  JSONB DEFAULT '{}'::jsonb,
    valid_from    TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to      TIMESTAMPTZ NOT NULL,
    place_name    TEXT,
    geom          GEOMETRY(Point, 4326) NOT NULL,
    session_id    TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_alert_geom ON alert_events USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_alert_valid ON alert_events (valid_to DESC);
CREATE INDEX IF NOT EXISTS idx_alert_hazard ON alert_events (hazard, severity);

-- ---------------------------------------------------------------------------
-- User subscriptions: who gets pushed what, and where
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_subscriptions (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL,
    label           TEXT,
    geom            GEOMETRY(Point, 4326) NOT NULL,
    radius_m        INTEGER DEFAULT 25000,
    language        TEXT DEFAULT 'en',
    min_severity    alert_severity DEFAULT 'yellow',
    channel         TEXT DEFAULT 'websocket',  -- websocket | sms | push
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sub_geom ON alert_subscriptions USING GIST (geom);

-- Delivery log, so a warning is never sent twice for the same event.
CREATE TABLE IF NOT EXISTS alert_deliveries (
    id              BIGSERIAL PRIMARY KEY,
    subscription_id BIGINT REFERENCES alert_subscriptions(id) ON DELETE CASCADE,
    alert_id        BIGINT REFERENCES alert_events(id) ON DELETE CASCADE,
    delivered_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (subscription_id, alert_id)
);

-- ---------------------------------------------------------------------------
-- Conversation log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_messages (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    language    TEXT DEFAULT 'en',
    tools_used  TEXT[] DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages (session_id, created_at);

-- ---------------------------------------------------------------------------
-- Helper: which subscribers should be told about a given alert?
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION subscribers_for_alert(p_alert_id BIGINT)
RETURNS TABLE (subscription_id BIGINT, session_id TEXT, language TEXT) AS $$
    SELECT s.id, s.session_id, s.language
    FROM alert_subscriptions s
    JOIN alert_events a ON a.id = p_alert_id
    WHERE s.active
      AND ST_DWithin(s.geom::geography, a.geom::geography, s.radius_m)
      AND array_position(ARRAY['green','yellow','orange','red']::text[], a.severity::text)
          >= array_position(ARRAY['green','yellow','orange','red']::text[], s.min_severity::text)
      AND NOT EXISTS (
          SELECT 1 FROM alert_deliveries d
          WHERE d.subscription_id = s.id AND d.alert_id = p_alert_id
      );
$$ LANGUAGE sql STABLE;

-- ---------------------------------------------------------------------------
-- Seed a few reference points
-- ---------------------------------------------------------------------------
INSERT INTO places (name, admin1, geom) VALUES
    ('Mumbai',    'Maharashtra',   ST_SetSRID(ST_MakePoint(72.8777, 19.0760), 4326)),
    ('Pune',      'Maharashtra',   ST_SetSRID(ST_MakePoint(73.8567, 18.5204), 4326)),
    ('New Delhi', 'Delhi',         ST_SetSRID(ST_MakePoint(77.2090, 28.6139), 4326)),
    ('Chennai',   'Tamil Nadu',    ST_SetSRID(ST_MakePoint(80.2707, 13.0827), 4326)),
    ('Kolkata',   'West Bengal',   ST_SetSRID(ST_MakePoint(88.3639, 22.5726), 4326)),
    ('Guwahati',  'Assam',         ST_SetSRID(ST_MakePoint(91.7362, 26.1445), 4326)),
    ('Nashik',    'Maharashtra',   ST_SetSRID(ST_MakePoint(73.7898, 19.9975), 4326))
ON CONFLICT DO NOTHING;
