import { Plane, Ship, Sprout, TrafficCone } from 'lucide-react';
import { sev } from '../severity';

const SECTOR = {
  agriculture: { icon: Sprout, name: 'Agriculture' },
  urban_transport: { icon: TrafficCone, name: 'Travel and transport' },
  aviation: { icon: Plane, name: 'Aviation' },
  marine: { icon: Ship, name: 'Marine' },
};

export default function AdvisoryCard({ data }) {
  if (!data) return null;
  const meta = SECTOR[data.sector] || SECTOR.agriculture;
  const Icon = meta.icon;

  return (
    <article className="animate-rise overflow-hidden rounded-lg border border-hairline bg-surface">
      <header className="flex items-center gap-2 border-b border-hairline/60 px-4 py-3">
        <Icon size={17} className="text-signal" aria-hidden />
        <div>
          <h3 className="text-[15px] font-semibold leading-tight text-haze">{meta.name}</h3>
          <p className="text-[12px] text-mute">
            {data.headline} · {data.location?.name}
          </p>
        </div>
      </header>

      <ul className="divide-y divide-hairline/60">
        {(data.items || []).map((item, i) => {
          const s = sev(item.severity);
          return (
            <li key={i} className="flex gap-3 px-4 py-3">
              <span
                className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                style={{ background: s.hex }}
                aria-label={s.label}
              />
              <div>
                <p className="text-[13px] font-medium text-haze">{item.title}</p>
                <p className="mt-0.5 text-[13px] leading-relaxed text-haze/80">{item.guidance}</p>
              </div>
            </li>
          );
        })}
      </ul>

      {data.metrics && (
        <footer className="flex flex-wrap gap-x-4 gap-y-1 border-t border-hairline/60 px-4 py-2 text-[11px] text-mute">
          {Object.entries(data.metrics)
            .filter(([, v]) => v !== null && v !== undefined)
            .map(([k, v]) => (
              <span key={k} className="tnum">
                {k.replace(/_/g, ' ')} {typeof v === 'number' ? Number(v).toFixed(1) : String(v)}
              </span>
            ))}
        </footer>
      )}
    </article>
  );
}
