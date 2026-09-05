import { fmt, ramp } from './shared'

/** Hero number: the first label/value is the figure; further pairs are context. Proportional figures (no tabular-nums) at display size. */
export default function StatTile({ spec }) {
  const { labels, series } = spec.data
  const values = series[0]?.values || []
  const hero = values[0]
  const context = labels.slice(1).map((l, i) => ({ label: l, value: values[i + 1] }))
  // A "… of N" pair (Answered / Total, Inherent / Maximum) earns a thin meter; the track is a lighter step of the same ramp.
  const denom = context[0]?.value
  const meter = context.length >= 1 && denom > 0 && hero >= 0 && hero <= denom && /max|total|of|possible|out/i.test(context[0].label) ? hero / denom : null
  return (
    <div>
      <p className="text-[13px] text-muted">{labels[0]}</p>
      <p className="mt-0.5 text-[40px] font-semibold leading-none tracking-[-0.03em]">
        {fmt(hero)}{spec.unit ? <span className="ml-1.5 text-[15px] font-normal tracking-normal text-muted">{spec.unit}</span> : null}
      </p>
      {meter !== null ? (
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full" style={{ background: ramp(0.12) }} role="img" aria-label={`${fmt(hero)} of ${fmt(denom)}`} title={`${fmt(hero)} of ${fmt(denom)} (${Math.round(meter * 100)}%)`}>
          <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${Math.round(meter * 100)}%`, background: ramp(1) }} />
        </div>
      ) : null}
      {context.length ? (
        <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
          {context.map((c) => (
            <div key={c.label}>
              <dt className="text-[12px] text-faint">{c.label}</dt>
              <dd className="text-[14.5px] font-medium">{fmt(c.value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  )
}
