import { useMemo, useState } from 'react'
import { Axis, Grid, LABEL_COL, PLOT_GUTTER, Readout, fmt, niceMax, seriesColor } from './shared'

/** Ordered parts of a whole per label. Series are sequential steps, darkest first; 2px surface gaps separate segments; only the data-end is rounded. */
export default function StackedBarChart({ spec }) {
  const { labels, series } = spec.data
  const [hover, setHover] = useState(null)
  const n = series.length
  const totals = useMemo(() => labels.map((_, r) => series.reduce((a, s) => a + (s.values[r] || 0), 0)), [labels, series])
  const max = useMemo(() => niceMax(Math.max(0, ...totals)), [totals])
  const maxRow = totals.indexOf(Math.max(...totals))

  return (
    <div>
      <ul className="space-y-1">
        {labels.map((label, r) => {
          const total = totals[r]
          const rowPct = (total / max) * 100
          const labelled = r === maxRow || hover?.row === r
          return (
            <li key={`${label}-${r}`} className="flex items-center gap-3">
              <span className={LABEL_COL} title={label}>{label}</span>
              <span className="relative h-5 flex-1">
                <span className={`absolute inset-y-0 left-0 ${PLOT_GUTTER}`}>
                  <Grid max={max} />
                  <span className="absolute inset-y-0 left-0 flex gap-[2px]" style={{ width: `${rowPct}%` }}>
                    {series.map((s, i) => {
                      const v = s.values[r] || 0
                      if (v <= 0) return null
                      const text = `${label} · ${s.name}: ${fmt(v)} of ${fmt(total)}${spec.unit ? ` ${spec.unit}` : ''}`
                      const key = `${r}:${i}`
                      return (
                        <span key={s.name} role="img" tabIndex={0} title={text} aria-label={text}
                          className="h-full min-w-[2px] cursor-default transition-opacity last:rounded-r-[4px] focus:outline-none"
                          style={{ width: `${(v / total) * 100}%`, background: seriesColor(i, n), opacity: hover && hover.key !== key ? 0.55 : 1 }}
                          onMouseEnter={() => setHover({ key, row: r, text })} onMouseLeave={() => setHover(null)} onFocus={() => setHover({ key, row: r, text })} onBlur={() => setHover(null)} />
                      )
                    })}
                  </span>
                  {labelled && total > 0 ? (
                    <span className="absolute top-1/2 -translate-y-1/2 whitespace-nowrap text-[12px] tabular-nums text-text" style={{ left: `calc(${rowPct}% + 6px)`, lineHeight: 1 }}>{fmt(total)}</span>
                  ) : null}
                </span>
              </span>
            </li>
          )
        })}
      </ul>
      <div className="flex gap-3">
        <span className={LABEL_COL} aria-hidden />
        <div className="relative flex-1"><div className={`absolute inset-y-0 left-0 ${PLOT_GUTTER}`}><Axis max={max} /></div><div className="h-5" /></div>
      </div>
      <Readout hover={hover?.text} hint="Hover a segment for the exact count." unit={spec.unit} />
    </div>
  )
}
