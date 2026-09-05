import { ArrowRight, CircleNotch } from '@phosphor-icons/react'
import { api } from '../lib/api'
import { useResource } from '../lib/cache'
import { STATUS, STATUS_ORDER, STATUS_RAMP, ramp, shortTopic } from '../lib/format'
import { Tag, cx } from './ui'

const RATING_TONE = { Low: 'text-accent', Moderate: 'text-signal', High: 'text-bad', Critical: 'text-bad' }

/**
 * Posture at a glance: the Analyst home when no conversation is open.
 * Every tile is a question waiting to be asked — clicking pre-fills and sends it.
 */
export default function Posture({ status, ask, openQuestion, goTo }) {
  const deps = [status?.counts, status?.inherent_points, status?.last_run]
  const { data: overview } = useResource('overview', api.overview, deps)
  const { data: items } = useResource('open_items', () => api.openItems(), deps)
  const { data: wf } = useResource('workflows', api.workflows, deps)
  const rating = status?.predicted_rating
  const ratio = status?.max_inherent_points ? status.inherent_points / status.max_inherent_points : 0
  const topics = overview ? Object.entries(overview.topics) : []

  return (
    <div className="grid gap-4 sm:grid-cols-5">
      {/* rating meter */}
      <button type="button" onClick={() => ask('How would the buyer score us right now, and what would move the rating most?')}
        className="group rounded-xl border border-border bg-surface p-4 text-left transition-colors hover:border-border-strong sm:col-span-2" title="Ask the analyst about the buyer's score">
        <p className="text-[12.5px] font-semibold uppercase tracking-[0.04em] text-faint">Predicted buyer rating</p>
        <p className={cx('display mt-1 text-[34px]', RATING_TONE[rating] || 'text-text')}>{rating || '—'}</p>
        <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-surface-2" aria-label={`${Math.round(ratio * 100)}% of the maximum inherent risk points`}>
          <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${Math.round(ratio * 100)}%`, background: ramp(1) }} />
        </div>
        <p className="mt-2 text-[13px] text-muted tabular-nums">
          {status?.inherent_points != null ? `${Math.round(status.inherent_points)} of ${Math.round(status.max_inherent_points)} inherent points` : 'Not scored yet'}
          {status?.escalations ? ` · ${status.escalations} escalations` : ''}{status?.vendor_criticality ? ` · ${status.vendor_criticality.split(':')[0]}` : ''}
        </p>
        <Counts counts={status?.counts} />
      </button>

      {/* status by topic heat strip */}
      <div className="rounded-xl border border-border bg-surface p-4 sm:col-span-3">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-[12.5px] font-semibold uppercase tracking-[0.04em] text-faint">Status by topic</p>
          <span className="hidden items-center gap-2 text-[11.5px] text-muted sm:flex">
            {STATUS_ORDER.map((s) => <span key={s} className="inline-flex items-center gap-1"><i className="inline-block size-2 rounded-[2px]" style={{ background: ramp(STATUS_RAMP[s]) }} />{STATUS[s].short}</span>)}
          </span>
        </div>
        {topics.length ? (
          <ul className="mt-3 grid gap-x-5 gap-y-1.5 sm:grid-cols-2">
            {topics.map(([topic, t]) => (
              <li key={topic}>
                <button type="button" onClick={() => ask(`Where do we stand on ${topic.toLowerCase()}? What is verified, what is still open, and what would you ask me first?`)}
                  className="group flex w-full items-center gap-2.5 rounded-md px-1 py-0.5 text-left hover:bg-text/5" title={`${topic}: ${STATUS_ORDER.filter((s) => t[s]).map((s) => `${t[s]} ${STATUS[s].short.toLowerCase()}`).join(', ')}`}>
                  <span className="w-[108px] shrink-0 truncate text-[12.5px] text-muted group-hover:text-text">{shortTopic(topic)}</span>
                  <span className="flex h-2.5 flex-1 gap-[2px]">
                    {STATUS_ORDER.filter((s) => t[s]).map((s) => <span key={s} className="h-full first:rounded-l-[3px] last:rounded-r-[3px]" style={{ width: `${(t[s] / t.total) * 100}%`, background: ramp(STATUS_RAMP[s]) }} />)}
                  </span>
                  <span className="w-5 shrink-0 text-right text-[11.5px] tabular-nums text-faint">{t.total}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : <Loading />}
      </div>

      {/* top open items */}
      <div className="rounded-xl border border-border bg-surface p-4 sm:col-span-3">
        <div className="flex items-baseline justify-between">
          <p className="text-[12.5px] font-semibold uppercase tracking-[0.04em] text-faint">Ask me first</p>
          <button type="button" onClick={() => goTo('questions')} className="text-[12.5px] text-muted hover:text-text">all questions</button>
        </div>
        {items ? (
          <ul className="mt-2 divide-y divide-border">
            {items.slice(0, 3).map((it) => (
              <li key={it.qid}>
                <button type="button" onClick={() => ask(`Let's answer Q${it.qid}. ${it.question}`)} className="group flex w-full items-start gap-3 py-2.5 text-left">
                  <span className="mt-0.5 shrink-0 text-[12px] tabular-nums text-faint">Q{it.qid}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] group-hover:text-accent">{it.text}</span>
                    <span className="block text-[12.5px] text-muted">{it.status === 'CONFLICT' ? 'sources disagree' : it.status === 'UNKNOWN' ? 'nothing in the documents' : 'partly answered'} · {it.owner_role}{it.priority ? ` · priority ${Math.round(it.priority)}` : ''}</span>
                  </span>
                  <ArrowRight className="mt-1 size-3.5 shrink-0 text-faint group-hover:text-accent" />
                </button>
              </li>
            ))}
            {!items.length ? <li className="py-3 text-[14px] text-muted">Nothing open — every question has an answer with evidence.</li> : null}
          </ul>
        ) : <Loading />}
      </div>

      {/* workflow outcomes */}
      <div className="rounded-xl border border-border bg-surface p-4 sm:col-span-2">
        <div className="flex items-baseline justify-between">
          <p className="text-[12.5px] font-semibold uppercase tracking-[0.04em] text-faint">Workflows</p>
          <button type="button" onClick={() => goTo('workflows')} className="text-[12.5px] text-muted hover:text-text">open</button>
        </div>
        {wf ? (
          <ul className="mt-2 space-y-2">
            {wf.workflows.map((w) => {
              const ran = w.last_run || (w.diagram?.outcome && !/not (run|exported) yet/i.test(w.diagram.outcome) && w.diagram.nodes?.some((n) => n.done))
              return (
                <li key={w.key}>
                  <button type="button" onClick={() => goTo('workflows')} className="group flex w-full items-start gap-2 text-left">
                    <i className={cx('mt-[7px] size-1.5 shrink-0 rounded-full', ran ? 'bg-accent' : 'bg-border-strong')} />
                    <span className="min-w-0">
                      <span className="block text-[13.5px] group-hover:text-text">{w.title}</span>
                      <span className="block truncate text-[12px] text-faint">{w.diagram?.outcome || 'Not run yet'}</span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        ) : <Loading />}
      </div>
    </div>
  )
}

function Counts({ counts }) {
  if (!counts) return null
  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {STATUS_ORDER.map((s) => counts[s] ? <Tag key={s} tone={STATUS[s].tone}>{counts[s]} {STATUS[s].short.toLowerCase()}</Tag> : null)}
    </div>
  )
}

const Loading = () => <p className="mt-3 flex items-center gap-2 text-[13px] text-faint"><CircleNotch className="size-3.5 animate-spin" /> loading</p>
