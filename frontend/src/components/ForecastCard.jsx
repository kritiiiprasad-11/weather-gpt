import { CloudRain } from 'lucide-react';

const day = (iso) =>
  new Date(iso).toLocaleDateString([], { weekday: 'short', day: 'numeric' });

export default function ForecastCard({ data }) {
  if (!data?.daily_dates?.length) return null;
  const rows = data.daily_dates.map((d, i) => ({
    date: d,
    max: data.daily_max_c[i],
    min: data.daily_min_c[i],
    rain: data.daily_rain_mm[i] ?? 0,
  }));
  const lo = Math.min(...rows.map((r) => r.min));
  const hi = Math.max(...rows.map((r) => r.max));
  const span = Math.max(hi - lo, 1);

  return (
    <article className="animate-rise overflow-hidden rounded-lg border border-hairline bg-surface">
      <header className="border-b border-hairline/60 px-4 py-3">
        <h3 className="text-[15px] font-semibold leading-tight text-haze">
          {rows.length}-day outlook
        </h3>
        <p className="text-[12px] text-mute">{data.location?.name}</p>
      </header>

      <ul>
        {rows.map((r) => (
          <li key={r.date} className="flex items-center gap-3 px-4 py-2.5">
            <span className="w-16 shrink-0 text-[13px] text-haze/90">{day(r.date)}</span>

            {/* Temperature range drawn as a positioned bar, not a chart. */}
            <span className="tnum w-8 text-right text-[12px] text-mute">{Math.round(r.min)}°</span>
            <span className="relative h-1 flex-1 rounded-full bg-hairline/70">
              <span
                className="absolute h-1 rounded-full bg-gradient-to-r from-signal to-orange"
                style={{
                  left: `${((r.min - lo) / span) * 100}%`,
                  width: `${((r.max - r.min) / span) * 100}%`,
                }}
              />
            </span>
            <span className="tnum w-8 text-[12px] font-medium text-haze">{Math.round(r.max)}°</span>

            <span className="tnum flex w-16 items-center justify-end gap-1 text-[12px] text-mute">
              {r.rain > 0 && <CloudRain size={12} aria-hidden />}
              {r.rain > 0 ? `${r.rain.toFixed(1)} mm` : '—'}
            </span>
          </li>
        ))}
      </ul>
    </article>
  );
}
