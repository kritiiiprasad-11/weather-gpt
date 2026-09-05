import {
  Droplets,
  Eye,
  Gauge,
  CloudRain,
  Thermometer,
  Wind,
  Cloud,
} from 'lucide-react';
import { t } from '../i18n';

const n = (v, d = 0) => (v === null || v === undefined ? '—' : Number(v).toFixed(d));

function Readout({ icon: Icon, label, value, unit }) {
  return (
    <div className="flex items-baseline gap-2 border-b border-hairline/60 py-2 last:border-0">
      <Icon size={14} className="shrink-0 self-center text-mute" aria-hidden />
      <span className="text-[13px] text-mute">{label}</span>
      <span className="tnum ml-auto text-[15px] font-medium text-haze">
        {value}
        <span className="ml-0.5 text-[11px] font-normal text-mute">{unit}</span>
      </span>
    </div>
  );
}

export default function WeatherCard({ data, lang = 'en' }) {
  if (!data) return null;
  const loc = data.location || {};
  const observed = data.observed_at ? new Date(data.observed_at) : null;

  return (
    <article className="animate-rise overflow-hidden rounded-lg border border-hairline bg-surface">
      <header className="flex items-start justify-between gap-4 px-4 pt-4">
        <div>
          <h3 className="text-[15px] font-semibold leading-tight text-haze">{loc.name}</h3>
          <p className="mt-0.5 text-[12px] text-mute">
            {data.condition || '—'}
            {loc.admin ? ` · ${loc.admin}` : ''}
          </p>
        </div>
        <div className="text-right">
          <div className="tnum text-readout font-semibold text-haze">
            {n(data.temperature_c)}
            <span className="align-top text-2xl text-signal">°</span>
          </div>
          {data.feels_like_c != null && (
            <p className="tnum -mt-1 text-[12px] text-mute">
              {t(lang, 'feelsLike')} {n(data.feels_like_c)}°C
            </p>
          )}
        </div>
      </header>

      <div className="grid gap-x-6 px-4 pb-3 pt-2 sm:grid-cols-2">
        <Readout icon={Droplets} label={t(lang, 'humidity')} value={n(data.humidity_pct)} unit="%" />
        <Readout
          icon={Wind}
          label={t(lang, 'wind')}
          value={`${n(data.wind_speed_kmh)}${data.wind_direction_cardinal ? ` ${data.wind_direction_cardinal}` : ''}`}
          unit=" km/h"
        />
        <Readout icon={CloudRain} label={t(lang, 'rain')} value={n(data.rainfall_mm_hr, 1)} unit=" mm/h" />
        <Readout
          icon={Gauge}
          label={t(lang, 'pressure')}
          value={`${n(data.pressure_hpa)}${
            data.pressure_change_3h_hpa != null
              ? ` (${data.pressure_change_3h_hpa > 0 ? '+' : ''}${n(data.pressure_change_3h_hpa, 1)}/3h)`
              : ''
          }`}
          unit=" hPa"
        />
        <Readout icon={Eye} label={t(lang, 'visibility')} value={n(data.visibility_km, 1)} unit=" km" />
        <Readout icon={Cloud} label={t(lang, 'cloud')} value={n(data.cloud_cover_pct)} unit="%" />
      </div>

      <footer className="flex items-center justify-between border-t border-hairline/60 px-4 py-2 text-[11px] text-mute">
        <span>
          {t(lang, 'updated')}{' '}
          {observed
            ? observed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            : '—'}
        </span>
        <span>{data.source}</span>
      </footer>
    </article>
  );
}

export { Readout, Thermometer };
