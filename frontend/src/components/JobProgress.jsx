import { Check, CircleNotch } from '@phosphor-icons/react'
import { Card, Progress, cx } from './ui'

const INDEX_STAGES = [
  { key: 'parse', label: 'Reading documents' },
  { key: 'extract', label: 'Extracting claims' },
  { key: 'embed', label: 'Embedding for retrieval' },
  { key: 'conflicts', label: 'Checking for contradictions' },
  { key: 'derive', label: 'Deriving answers' },
  { key: 'score', label: "Scoring the buyer's view" },
]
const RESEARCH_STAGES = [
  { key: 'live_probe', label: 'Probing the public website' },
  { key: 'entity_facts', label: 'Looking up the company' },
  { key: 'public_pages', label: 'Finding security & privacy pages' },
  { key: 'attestations', label: 'Checking attestation claims' },
  { key: 'breach_history', label: 'Searching breach news' },
  { key: 'fourth_party', label: 'Watching subprocessors' },
  { key: 'summary', label: 'Compiling the reputational view' },
]

/** Derive a stepper model from the raw job event log. */
export function summarize(job) {
  const ev = job?.events || []
  const kind = job?.kind || job?.label || ''
  if (kind.startsWith('research')) {
    const seen = ev.filter((e) => e.ev === 'research').map((e) => e.mode)
    const current = seen[seen.length - 1]
    const idx = RESEARCH_STAGES.findIndex((s) => s.key === current)
    return { stages: RESEARCH_STAGES, current: job.state === 'done' ? RESEARCH_STAGES.length : Math.max(idx, 0), detail: current ? RESEARCH_STAGES[idx]?.label : 'Starting…', value: null, max: null }
  }
  if (kind === 'export' || (kind === 'generic' && job.steps)) {
    const stages = (job.steps || ['Working']).map((label) => ({ key: label, label }))
    const seen = ev.filter((e) => e.ev === 'stage').length
    return { stages, current: job.state === 'done' ? stages.length : Math.min(seen, stages.length - 1), detail: job.state === 'done' ? 'Done' : '', value: null, max: null }
  }
  if (kind === 'exceptions') {
    const stages = [{ key: 'score', label: 'Compute criticality & risk points' }, { key: 'draft', label: 'Draft exception requests from evidence' }]
    const seen = ev.filter((e) => e.ev === 'stage').length
    return { stages, current: job.state === 'done' ? 2 : Math.min(Math.max(seen - 1, 0), 1), detail: job.state === 'done' ? 'Done' : 'One draft per predicted escalation', value: null, max: null }
  }
  if (false) {
    const stages = [{ key: 'draft', label: 'Writing exception requests from evidence' }]
    return { stages, current: job.state === 'done' ? 1 : 0, detail: job.state === 'done' ? 'Done' : 'One draft per predicted escalation', value: null, max: null }
  }
  const parsed = ev.filter((e) => e.ev === 'parsed' || e.ev === 'skip').length
  const extracting = ev.find((e) => e.ev === 'extracting')
  const claimsEvents = ev.filter((e) => e.ev === 'claims')
  const claimsTotal = claimsEvents.length ? claimsEvents[claimsEvents.length - 1].total : 0
  const stage = [...ev].reverse().find((e) => e.ev === 'stage')?.stage
  const deriveTotal = ev.find((e) => e.ev === 'stage' && e.stage === 'derive')?.total || 66
  const derived = ev.filter((e) => e.ev === 'derived').length
  let current = 0, detail = 'Starting…', value = null, max = null
  const embedEv = [...ev].reverse().find((e) => e.ev === 'embedding')
  if (job.state === 'done') { current = INDEX_STAGES.length; detail = 'Done' }
  else if (stage === 'score') { current = 5; detail = 'Applying the buyer’s risk tables' }
  else if (stage === 'derive') { current = 4; detail = `${derived} of ${deriveTotal} questions`; value = derived; max = deriveTotal }
  else if (stage === 'conflicts') { current = 3; detail = 'Comparing policies, reports and records' }
  else if (stage === 'embed') { current = 2; detail = embedEv ? `${embedEv.claims ?? embedEv.chunks} of ${embedEv.of}` : 'Loading the embedding model'; value = embedEv ? (embedEv.claims ?? embedEv.chunks) : null; max = embedEv?.of ?? null }
  else if (extracting) { current = 1; detail = `${claimsEvents.length} of ${extracting.chunks} sections · ${claimsTotal} claims`; value = claimsEvents.length; max = extracting.chunks }
  else { current = 0; detail = parsed ? `${parsed} files` : 'Opening files…'; }
  return { stages: INDEX_STAGES, current, detail, value, max }
}

export default function JobProgress({ job, compact = false }) {
  if (!job) return null
  const { stages, current, detail, value, max } = summarize(job)
  const done = job.state === 'done'
  const failed = job.state === 'error'
  if (compact) {
    return (
      <div className="flex items-center gap-3 text-[13px] text-muted fade">
        {done ? <Check className="size-4 text-accent" weight="bold" /> : failed ? <span className="text-bad">✕</span> : <CircleNotch className="size-4 animate-spin text-accent" />}
        <span className="truncate">{failed ? job.error : `${job.label}${done ? ' complete' : ` · ${stages[current]?.label ?? ''}`}${detail && !done ? ` · ${detail}` : ''}`}</span>
      </div>
    )
  }
  return (
    <Card className="p-5 rise">
      <div className="flex items-center justify-between">
        <p className="text-[15px] font-semibold tracking-[-0.01em]">{job.label}</p>
        <span className="text-[13px] text-muted">{done ? 'Complete' : failed ? 'Failed' : detail}</span>
      </div>
      <Progress className="mt-3" value={value ?? (done ? 1 : current)} max={max ?? (done ? 1 : stages.length)} indeterminate={!done && value === null} />
      <ol className="mt-4 space-y-2">
        {stages.map((s, i) => {
          const state = done || i < current ? 'done' : i === current && !failed ? 'active' : 'todo'
          return (
            <li key={s.key} className={cx('flex items-center gap-3 text-[14px]', state === 'todo' && 'text-faint', state === 'active' && 'text-text', state === 'done' && 'text-muted')}>
              <span className="grid size-5 place-items-center">
                {state === 'done' ? <Check className="size-3.5 text-accent" weight="bold" /> : state === 'active' ? <CircleNotch className="size-3.5 animate-spin text-accent" /> : <span className="size-1.5 rounded-full bg-border-strong" />}
              </span>
              {s.label}
              {state === 'active' && detail ? <span className="ml-auto text-[12.5px] text-muted tabular-nums">{detail}</span> : null}
            </li>
          )
        })}
      </ol>
      {failed ? <p className="mt-3 text-[13.5px] text-bad">{job.error}</p> : null}
    </Card>
  )
}
