/* Shared chart primitives. Sequential single-hue only: every series is a step of the accent→surface ramp
   (the app's status colours fail categorical CVD checks, so they are never used as a series palette).
   Text always wears text tokens; identity comes from the swatch beside it, the legend, the tooltip and the table view. */

export const ramp = (t) => `color-mix(in oklab, var(--accent) ${Math.round(18 + 82 * t)}%, var(--surface))`

/** Ordered steps, darkest first (series 0 = the "best"/leading state). Spread over the ramp so neighbours stay apart. */
export const seriesColor = (i, n) => ramp(n <= 1 ? 1 : 1 - (i / (n - 1)) * 0.85)

export function fmt(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const n = Number(v)
  if (Number.isInteger(n)) return n.toLocaleString()
  return n.toLocaleString(undefined, { maximumFractionDigits: Math.abs(n) < 1 ? 2 : 1 })
}

/** Round the axis maximum up to a clean number (1 / 2 / 2.5 / 5 × 10^k). */
export function niceMax(max) {
  if (!(max > 0)) return 1
  const p = 10 ** Math.floor(Math.log10(max))
  const f = max / p
  const n = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10
  return n * p
}

/** Tick values for a nice maximum: always clean numbers (25 → 0,5,…,25; 10 → 0,2,…,10; 2 → 0,1,2; 1 → 0,1). */
export function ticks(max) {
  const divs = [5, 4, 2].find((d) => Number.isInteger(max / d)) || (Number.isInteger(max * 2 / 5) ? 5 : 1)
  return Array.from({ length: divs + 1 }, (_, i) => (max * i) / divs)
}

/** Hairline gridlines behind the bars — solid, one step off the surface, recessive. */
export function Grid({ max }) {
  return ticks(max).map((v) => <span key={v} aria-hidden className="absolute inset-y-0 w-px bg-border" style={{ left: `${(v / max) * 100}%`, opacity: v === 0 ? 1 : 0.7 }} />)
}

/** Tick labels under the plot; first left-aligned, last right-aligned, the rest centred on their line. The unit lives in the read-out, not on the axis. */
export function Axis({ max }) {
  const ts = ticks(max)
  const last = ts.length - 1
  // Every tick has a gridline; only 0, the max and alternating interior ticks get a label so neighbours never collide in a narrow card.
  const shown = ts.map((v, i) => i === 0 || i === last || (i % 2 === 0 && i <= last - 2))
  return (
    <div className="relative mt-1 h-4 text-[11px] tabular-nums text-faint" aria-hidden>
      {ts.map((v, i) => shown[i] ? (
        <span key={v} className="absolute top-0" style={{ left: `${(v / max) * 100}%`, transform: i === 0 ? 'none' : i === last ? 'translateX(-100%)' : 'translateX(-50%)' }}>{fmt(v)}</span>
      ) : null)}
    </div>
  )
}

export function Legend({ series }) {
  if (!series || series.length < 2) return null
  return (
    <ul className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted">
      {series.map((s, i) => (
        <li key={s.name} className="inline-flex items-center gap-1.5"><i className="inline-block size-2.5 shrink-0 rounded-[3px]" style={{ background: seriesColor(i, series.length) }} />{s.name}</li>
      ))}
    </ul>
  )
}

/** The hover read-out under a plot. Always paired with a `title` on the mark itself and with the table view, so it enhances, never gates. */
export function Readout({ hover, hint, unit }) {
  return (
    <p className="mt-1.5 flex min-h-[18px] items-baseline justify-between gap-3 text-[12.5px] text-muted">
      <span className="min-w-0 truncate">{hover || <span className="text-faint">{hint}</span>}</span>
      {unit ? <span className="shrink-0 text-[11.5px] text-faint">{unit}</span> : null}
    </p>
  )
}

/* Column widths shared by the bar charts: label column, then the plot with a right-hand gutter where the tip labels live. */
export const LABEL_COL = 'w-[38%] max-w-[170px] shrink-0 truncate text-[13px] text-muted'
export const PLOT_GUTTER = 'right-11'
