import { useMemo, useState } from 'react'
import { Axis, Grid, LABEL_COL, PLOT_GUTTER, Readout, fmt, niceMax, seriesColor } from './shared'

/** Horizontal bars, one row per label; 1–3 series stack as thin bars inside the row. Bars ≤ 24px, 4px rounded data-end, square baseline. */
export default function BarChart({ spec }) {
  const { labels, series } = spec.data
  const [hover, setHover] = useState(null)
  const n = series.length
  const max = useMemo(() => niceMax(Math.max(0, ...series.flatMap((s) => s.values))), [series])
  // Selective direct labels: only the largest bar of the chart gets a number at its tip; hover and the table carry the rest.
  const maxKey = useMemo(() => {
    let best = { v: -Infinity, key: null }
    series.forEach((s, i) => s.values.forEach((v, r) => { if (v > best.v) best = { v, key: `${r}:${i}` } }))
    return best.key
  }, [series])
  const barH = n === 1 ? 20 : n === 2 ? 9 : 6

  return (
    <div>
      <ul className="space-y-1">
        {labels.map((label, r) => (
          <li key={`${label}-${r}`} className="flex items-center gap-3">
            <span className={LABEL_COL} title={label}>{label}</span>
            <span className="relative flex-1" style={{ height: n === 1 ? 20 : n * barH + (n - 1) * 2 }}>
              <span className={`absolute inset-y-0 left-0 ${PLOT_GUTTER}`}>
                <Grid max={max} />
                {series.map((s, i) => {
                  const v = s.values[r]
                  const pct = Math.max(0, Math.min(100, (v / max) * 100))
                  const key = `${r}:${i}`
                  const text = `${label} · ${s.name}: ${fmt(v)}${spec.unit ? ` ${spec.unit}` : ''}`
                  const labelled = maxKey === key || hover?.key === key
                  return (
                    <span key={s.name} className="absolute inset-x-0" style={{ top: i * (barH + 2), height: barH }}>
                      {/* hit target is the whole row band, wider than the mark */}
                      <span className="absolute -inset-y-[3px] left-0 z-[1] cursor-default" style={{ width: `calc(${pct}% + 12px)` }} title={text} aria-label={text} role="img"
                        onMouseEnter={() => setHover({ key, text })} onMouseLeave={() => setHover(null)} onFocus={() => setHover({ key, text })} onBlur={() => setHover(null)} tabIndex={0} />
                      <span className="absolute inset-y-0 left-0 rounded-r-[4px] transition-[width] duration-500" style={{ width: v > 0 ? `max(2px, ${pct}%)` : 0, background: seriesColor(i, n), opacity: hover && hover.key !== key ? 0.55 : 1 }} />
                      {labelled && v > 0 ? (
                        <span className="absolute top-1/2 -translate-y-1/2 whitespace-nowrap text-[12px] tabular-nums text-text" style={{ left: `calc(${pct}% + 6px)`, lineHeight: 1 }}>{fmt(v)}</span>
                      ) : null}
                    </span>
                  )
                })}
              </span>
            </span>
          </li>
        ))}
      </ul>
      <div className="flex gap-3">
        <span className={LABEL_COL} aria-hidden />
        <div className="relative flex-1"><div className={`absolute inset-y-0 left-0 ${PLOT_GUTTER}`}><Axis max={max} /></div><div className="h-5" /></div>
      </div>
      <Readout hover={hover?.text} hint="Hover a bar for the exact value." unit={spec.unit} />
    </div>
  )
}
