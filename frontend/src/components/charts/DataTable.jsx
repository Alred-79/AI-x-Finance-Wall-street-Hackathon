import { fmt } from './shared'

/** The table twin of every chart — the WCAG-clean equivalent. Rows = labels, columns = series. */
export default function DataTable({ spec, firstColumn = '' }) {
  const { labels, series } = spec.data
  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="text-[11.5px] uppercase tracking-[0.04em] text-faint">
            <th className="py-1.5 pr-3 text-left font-semibold">{firstColumn}</th>
            {series.map((s) => <th key={s.name} className="py-1.5 pl-3 text-right font-semibold whitespace-nowrap">{s.name}{spec.unit && series.length === 1 ? <span className="ml-1 font-normal normal-case tracking-normal">({spec.unit})</span> : ''}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {labels.map((l, r) => (
            <tr key={`${l}-${r}`}>
              <td className="max-w-[260px] truncate py-1.5 pr-3" title={l}>{l}</td>
              {series.map((s) => <td key={s.name} className="py-1.5 pl-3 text-right tabular-nums">{fmt(s.values[r])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
