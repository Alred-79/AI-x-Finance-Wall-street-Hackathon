import { useState } from 'react'
import { ChartBarHorizontal, Table } from '@phosphor-icons/react'
import { Card, cx } from '../ui'
import { Legend } from './shared'
import BarChart from './BarChart'
import StackedBarChart from './StackedBarChart'
import StatTile from './StatTile'
import DataTable from './DataTable'

const RENDER = { bar: BarChart, stacked_bar: StackedBarChart, stat: StatTile, table: DataTable }

/** Renders a visual spec by kind, with a legend for ≥2 series and a table-view toggle on every chart. */
export default function Chart({ spec }) {
  const [table, setTable] = useState(false)
  const Body = RENDER[spec?.kind]
  if (!Body || !spec?.data?.series?.length) return <p className="text-[13px] text-muted">This chart could not be rendered.</p>
  const toggleable = spec.kind !== 'table'
  const showTable = table || spec.kind === 'table'
  return (
    <div>
      {(toggleable || spec.data.series.length > 1) ? (
        <div className="mb-2 flex items-start justify-between gap-3">
          <div className="min-w-0">{!showTable && spec.kind !== 'stat' ? <Legend series={spec.data.series} /> : null}</div>
          {toggleable ? (
            <button type="button" onClick={() => setTable(!table)} className="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[12px] text-faint hover:bg-text/7 hover:text-text" aria-pressed={table} title={table ? 'Show as chart' : 'Show as table'}>
              {table ? <ChartBarHorizontal className="size-3.5" /> : <Table className="size-3.5" />}{table ? 'Chart' : 'Table'}
            </button>
          ) : null}
        </div>
      ) : null}
      {showTable ? <DataTable spec={spec} /> : <Body spec={spec} />}
    </div>
  )
}

/** Card chrome shared by the chat reply and the dashboard: title, one-sentence description, the chart, optional header aside and footer. */
export function VisualCard({ spec, aside, footer, className }) {
  return (
    <Card className={cx('flex flex-col p-4', className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[14.5px] font-semibold tracking-[-0.01em]">{spec.title}</h3>
          {spec.description ? <p className="mt-0.5 text-[13px] text-muted">{spec.description}</p> : null}
        </div>
        {aside}
      </div>
      <div className="mt-3 flex-1"><Chart spec={spec} /></div>
      {footer ? <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">{footer}</div> : null}
    </Card>
  )
}

const SOURCE_NAME = { get_score: "buyer's-eye score", get_metrics: 'live metrics', search_evidence: 'document search', get_question: 'question state', list_open_items: 'open items', web_research: 'public web' }

export function Sources({ ids }) {
  if (!ids?.length) return <span />
  return (
    <span className="text-[12px] text-faint">
      Sources: {ids.map((id) => SOURCE_NAME[id] || id).join(' · ')}
    </span>
  )
}
