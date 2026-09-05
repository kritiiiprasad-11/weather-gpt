import { AlertTriangle, CheckCircle2, Flame, Waves, Wind } from 'lucide-react';
import { sev } from '../severity';
import { t } from '../i18n';

const HAZARD_ICON = {
  flash_flood: Waves,
  cyclone: Wind,
  thunderstorm: Wind,
  heatwave: Flame,
  coldwave: Flame,
};

function formatWindow(from, to) {
  const f = new Date(from);
  const tt = new Date(to);
  const opts = { hour: '2-digit', minute: '2-digit' };
  return `${f.toLocaleTimeString([], opts)} → ${tt.toLocaleTimeString([], opts)}`;
}

/** `bundle` is the AlertBundle returned by /api/alerts. */
export default function AlertCard({ bundle, lang = 'en' }) {
  if (!bundle) return null;
  const alerts = bundle.alerts || [];

  if (alerts.length === 0) {
    const s = sev('green');
    return (
      <div
        className="animate-rise flex items-center gap-3 rounded-lg border border-hairline bg-surface px-4 py-3"
        style={{ borderLeft: `3px solid ${s.hex}` }}
      >
        <CheckCircle2 size={18} style={{ color: s.hex }} aria-hidden />
        <div>
          <p className="text-[14px] font-medium text-haze">{t(lang, 'noAlerts')}</p>
          <p className="text-[12px] text-mute">
            {bundle.location?.name} · flash flood, cyclone and heatwave thresholds all clear
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="animate-rise space-y-2">
      {alerts.map((a, i) => {
        const s = sev(a.severity);
        const Icon = HAZARD_ICON[a.hazard] || AlertTriangle;
        return (
          <article
            key={i}
            role="alert"
            className={`overflow-hidden rounded-lg border border-hairline bg-surface ${s.bg}`}
            style={{ borderLeft: `3px solid ${s.hex}` }}
          >
            <header className="flex items-center gap-2 px-4 pt-3">
              <Icon size={17} style={{ color: s.hex }} aria-hidden />
              <h3 className="text-[15px] font-semibold text-haze">{a.headline}</h3>
              <span
                className="ml-auto rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide"
                style={{ background: s.hex, color: '#08222C' }}
              >
                {s.label}
              </span>
            </header>

            <p className="px-4 pt-2 text-[13px] leading-relaxed text-haze/90">{a.detail}</p>

            <p
              className="mx-4 my-3 rounded border-l-2 px-3 py-2 text-[13px] leading-relaxed text-haze"
              style={{ borderColor: s.hex, background: 'rgba(255,255,255,0.04)' }}
            >
              {a.action}
            </p>

            <footer className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-hairline/60 px-4 py-2 text-[11px] text-mute">
              <span>{a.location?.name}</span>
              <span className="tnum">{formatWindow(a.valid_from, a.valid_to)}</span>
              <span className="tnum ml-auto">
                {Object.entries(a.triggered_by || {})
                  .map(([k, v]) => `${k.replace(/_/g, ' ')} ${typeof v === 'number' ? v.toFixed(1) : v}`)
                  .join(' · ')}
              </span>
            </footer>
          </article>
        );
      })}
    </div>
  );
}
