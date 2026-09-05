import { useEffect } from 'react';
import { Circle, CircleMarker, MapContainer, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import { sev } from '../severity';

/** Leaflet caches its container size. Without this, dragging the drawer
 *  leaves grey gaps and misaligned tiles. */
function ResizeAware() {
  const map = useMap();
  useEffect(() => {
    const container = map.getContainer();
    const ro = new ResizeObserver(() => map.invalidateSize({ animate: false }));
    ro.observe(container);
    return () => ro.disconnect();
  }, [map]);
  return null;
}

/** Keeps the viewport following the active location. */
function Recenter({ lat, lon }) {
  const map = useMap();
  useEffect(() => {
    if (lat != null && lon != null) map.setView([lat, lon], map.getZoom(), { animate: true });
  }, [lat, lon, map]);
  return null;
}

/** Tapping the map is the fastest way to ask about somewhere else. */
function ClickToMove({ onPick }) {
  useMapEvents({
    click(e) {
      onPick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

export default function MapPanel({ lat, lon, name, severity = 'green', radiusKm = 25, onPick }) {
  if (lat == null || lon == null) {
    return (
      <div className="grid h-full place-items-center px-6 text-center text-[13px] text-mute">
        Pick a location to see it on the map.
      </div>
    );
  }
  const s = sev(severity);

  return (
    <MapContainer
      center={[lat, lon]}
      zoom={9}
      className="map-drawer-canvas h-full w-full"
      scrollWheelZoom
      attributionControl
    >
      {/* OpenStreetMap tiles are keyless. CARTO's dark basemap now requires an
          API key and stamps "API KEY REQUIRED" across the tiles, so we darken
          OSM with a CSS filter instead (see .map-drawer-canvas in index.css). */}
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={19}
      />
      {/* Radar-style precipitation overlay. Needs an OpenWeatherMap key —
          set VITE_OWM_KEY to switch it on. */}
      {import.meta.env.VITE_OWM_KEY && (
        <TileLayer
          url={`https://tile.openweathermap.org/map/precipitation_new/{z}/{x}/{y}.png?appid=${import.meta.env.VITE_OWM_KEY}`}
          opacity={0.55}
        />
      )}

      <Circle
        center={[lat, lon]}
        radius={radiusKm * 1000}
        pathOptions={{ color: s.hex, fillColor: s.hex, fillOpacity: 0.12, weight: 1 }}
      />
      <CircleMarker
        center={[lat, lon]}
        radius={6}
        pathOptions={{ color: '#08222C', fillColor: s.hex, fillOpacity: 1, weight: 2 }}
      >
        <Tooltip direction="top" offset={[0, -8]}>
          {name || `${lat.toFixed(3)}, ${lon.toFixed(3)}`}
        </Tooltip>
      </CircleMarker>

      <Recenter lat={lat} lon={lon} />
      <ResizeAware />
      {onPick && <ClickToMove onPick={onPick} />}
    </MapContainer>
  );
}
