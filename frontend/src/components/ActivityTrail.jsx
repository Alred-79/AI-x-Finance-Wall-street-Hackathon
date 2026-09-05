import { useState } from 'react'
import { CaretDown, Check, CircleNotch, FileMagnifyingGlass, Globe, ListChecks, NotePencil, Scales, ShieldCheck, WarningDiamond } from '@phosphor-icons/react'
import { cx } from './ui'

const META = {
  search_evidence: { Icon: FileMagnifyingGlass, text: (a) => `Searched company documents for “${a?.query ?? ''}”` },
  get_question: { Icon: ListChecks, text: (a) => `Read the current state of Q${String(a?.qid ?? '').replace(/^Q/, '')}` },
  find_questions: { Icon: ListChecks, text: (a) => `Looked for questions about “${a?.keyword ?? ''}”` },
  list_open_items: { Icon: ListChecks, text: () => 'Prioritised the open questions' },
  list_conflicts: { Icon: WarningDiamond, text: () => 'Checked open conflicts' },
  record_user_fact: { Icon: NotePencil, text: (a) => `Recorded your statement: ${a?.attribute?.replace(/_/g, ' ') ?? 'fact'} = ${a?.value ?? ''}` },
  resolve_conflict: { Icon: Check, text: () => 'Marked the conflict resolved' },
  web_research: { Icon: Globe, text: (a) => `Researched the public web (${a?.mode ?? 'all'})` },
  get_score: { Icon: Scales, text: () => "Computed the buyer's-eye score" },
  who_to_ask: { Icon: ShieldCheck, text: (a) => `Worked out who owns ${(a?.controls || []).map((c) => c.replace(/_/g, ' ')).join(', ') || 'this'}` },
  get_metrics: { Icon: Scales, text: (a) => `Gathered the numbers for ${a?.name?.replace(/_/g, ' ') ?? 'the chart'}` },
  propose_visual: { Icon: Scales, text: (a) => `Drew a chart: ${a?.title ?? ''}` },
}

/** Live while streaming (every step visible), collapsed to one line once the turn is done. */
export default function ActivityTrail({ events = [], status, live, evidenceCount = 0 }) {
  const [open, setOpen] = useState(false)
  if (!events.length && !status) return null
  const rows = events.map((e, i) => {
    const m = META[e.tool] || { Icon: ShieldCheck, text: () => e.tool.replace(/_/g, ' ') }
    return (
      <li key={i} className={cx('flex items-start gap-2.5 text-[13px]', e.ok === false ? 'text-bad' : 'text-muted')}>
        <m.Icon className="mt-[3px] size-3.5 shrink-0" />
        <span className="min-w-0 break-words">{m.text(e.args)}</span>
      </li>
    )
  })
  if (live) {
    return (
      <ul className="mb-3 space-y-1.5 fade">
        {rows}
        {status ? (
          <li className="flex items-center gap-2.5 text-[13px] text-text">
            <CircleNotch className="size-3.5 shrink-0 animate-spin text-accent" />
            <span>{status}</span>
          </li>
        ) : null}
      </ul>
    )
  }
  const summary = `${events.length} step${events.length === 1 ? '' : 's'}${evidenceCount ? ` · ${evidenceCount} evidence item${evidenceCount === 1 ? '' : 's'}` : ''}`
  return (
    <div className="mt-3 border-t border-border pt-2">
      <button type="button" onClick={() => setOpen(!open)} className="inline-flex items-center gap-1.5 text-[12.5px] text-faint hover:text-text">
        <CaretDown className={cx('size-3 transition-transform', open && 'rotate-180')} weight="bold" /> {summary}
      </button>
      {open ? <ul className="mt-2 space-y-1.5">{rows}</ul> : null}
    </div>
  )
}
