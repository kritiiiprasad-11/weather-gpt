import { CloudRain, Droplets, Gauge, Wind } from 'lucide-react';
import { sev } from '../severity';
import { t } from '../i18n';

const n = (v, d = 0) => (v === null || v === undefined ? '—' : Number(v).toFixed(d));

/**
 * Always-visible instrument panel for the active location. On desktop it sits
 * in the left rail; on small screens it becomes a single horizontal strip.
 */
export default function ConditionsRail({ current, bundle, lang, loading }) {
  const s = sev(bundle?.overall_severity || 'green');
  const alerts = bundle?.alerts || [];

  if (loading || !current) {
    return (
      <div className="space-y-3 p-4">
        <div className="h-3 w-24 animate-breathe rounded bg-hairline" />
        <div className="h-12 w-28 animate-breathe rounded bg-hairline" />
        <div className="h-3 w-full animate-breathe rounded bg-hairline" />
      </div>
    );
  }

  return (
    <div className="flex flex-row items-center gap-5 overflow-x-auto p-4 lg:flex-col lg:items-stretch lg:gap-0 lg:overflow-visible">
      <div className="shrink-0">
        <p className="text-[11px] text-mute">{t(lang, 'conditions')}</p>
        <p className="mt-0.5 truncate text-[14px] font-semibold text-haze">
          {current.location?.name}
        </p>
        <div className="tnum mt-1 text-[42px] font-semibold leading-none text-haze lg:text-readout">
          {n(current.temperature_c)}
          <span className="align-top text-xl text-signal">°</span>
        </div>
        <p className="mt-1 text-[12px] text-mute">{current.condition}</p>
      </div>

      <dl className="flex shrink-0 gap-5 lg:mt-5 lg:flex-col lg:gap-0">
        {[
          [Droplets, t(lang, 'humidity'), n(current.humidity_pct), '%'],
          [Wind, t(lang, 'wind'), `${n(current.wind_speed_kmh)} ${current.wind_direction_cardinal || ''}`, 'km/h'],
          [CloudRain, t(lang, 'rain'), n(current.rainfall_mm_hr, 1), 'mm/h'],
          [Gauge, t(lang, 'pressure'), n(current.pressure_hpa), 'hPa'],
        ].map(([Icon, label, value, unit]) => (
          <div
            key={label}
            className="flex items-center gap-2 lg:border-b lg:border-hairline/60 lg:py-2.5"
          >
            <Icon size={13} className="text-mute" aria-hidden />
            <dt className="hidden text-[12px] text-mute lg:block">{label}</dt>
            <dd className="tnum text-[13px] font-medium text-haze lg:ml-auto">
              {value}
              <span className="ml-1 text-[10px] font-normal text-mute">{unit}</span>
            </dd>
          </div>
        ))}
      </dl>

      <div
        className="shrink-0 rounded-md border-l-2 px-3 py-2 lg:mt-5"
        style={{ borderColor: s.hex, background: `${s.hex}14` }}
      >
        <p className="text-[11px]" style={{ color: s.hex }}>
          {s.label}
        </p>
        <p className="mt-0.5 max-w-[220px] text-[13px] leading-snug text-haze">
          {alerts.length ? alerts[0].headline : t(lang, 'noAlerts')}
        </p>
        {alerts.length > 1 && (
          <p className="mt-1 text-[11px] text-mute">+{alerts.length - 1} more in force</p>
        )}
      </div>
    </div>
  );
}
