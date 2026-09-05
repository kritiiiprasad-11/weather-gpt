import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis } from 'recharts';

/** Renders a ClimateComparison: this period against its multi-year baseline. */
export default function ClimateCard({ data }) {
  if (!data) return null;
  const rows = (data.yearly || []).map((r) => ({ year: String(r.year), value: r.value }));
  const latest = rows.length ? rows[rows.length - 1].year : null;
  const wetter = data.anomaly > 0;
  const accent = wetter ? '#4FC3D9' : '#E3762A';

  return (
    <article className="animate-rise overflow-hidden rounded-lg border border-hairline bg-surface">
      <header className="px-4 pt-4">
        <h3 className="text-[15px] font-semibold leading-tight text-haze">
          {data.variable === 'rainfall' ? 'Rainfall' : 'Temperature'} · {data.period_label}
        </h3>
        <p className="mt-0.5 text-[12px] text-mute">{data.location?.name}</p>
      </header>

      <div className="flex items-end gap-6 px-4 pt-3">
        <div>
          <div className="tnum text-4xl font-semibold leading-none text-haze">
            {data.current_value}
            <span className="ml-1 text-base font-normal text-mute">{data.unit}</span>
          </div>
          <p className="mt-1 text-[11px] text-mute">this period</p>
        </div>
        <div className="pb-1">
          <div className="tnum text-xl font-medium leading-none" style={{ color: accent }}>
            {data.anomaly > 0 ? '+' : ''}
            {data.anomaly} {data.unit}
          </div>
          <p className="tnum mt-1 text-[11px] text-mute">
            {data.anomaly_pct > 0 ? '+' : ''}
            {data.anomaly_pct}% vs {data.baseline_years}-year normal ({data.baseline_value} {data.unit})
          </p>
        </div>
      </div>

      <div className="h-32 px-2 pt-3">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
            <XAxis
              dataKey="year"
              tick={{ fill: '#7C9DA8', fontSize: 10 }}
              axisLine={{ stroke: '#1E5468' }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <Tooltip
              cursor={{ fill: 'rgba(79,195,217,0.08)' }}
              contentStyle={{
                background: '#08222C',
                border: '1px solid #1E5468',
                borderRadius: 6,
                fontSize: 12,
                color: '#DCE7E7',
              }}
              formatter={(v) => [`${v} ${data.unit}`, data.variable]}
            />
            <ReferenceLine
              y={data.baseline_value}
              stroke="#7C9DA8"
              strokeDasharray="3 3"
              label={{ value: 'normal', fill: '#7C9DA8', fontSize: 10, position: 'left' }}
            />
            <Bar dataKey="value" radius={[2, 2, 0, 0]}>
              {rows.map((r) => (
                <Cell key={r.year} fill={r.year === latest ? accent : '#1E5468'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <p className="border-t border-hairline/60 px-4 py-3 text-[13px] leading-relaxed text-haze/90">
        {data.verdict}
      </p>
    </article>
  );
}
