import { useEffect, useMemo, useState } from 'react'
import { ArrowSquareOut, WarningDiamond } from '@phosphor-icons/react'
import { api } from '../lib/api'
import { AUTHORITY, Button, Panel, Rows, Section, Spinner, Tag, cx } from '../components/ui'
import { STATUS, STATUS_ORDER } from '../lib/format'
import JobProgress from '../components/JobProgress'
import DashboardView from './DashboardView'
import { useResource } from '../lib/cache'

const TABS = [['dashboard', 'Dashboard'], ['overview', 'Overview'], ['coverage', 'Evidence map'], ['conflicts', 'Contradictions'], ['documents', 'Documents'], ['web', 'Public web']]
const TIER_COLS = ['record', 'attestation', 'policy', 'template', 'employee', 'public']
const TIER_LABEL = { record: 'Records', attestation: 'Attestation', policy: 'Policies', template: 'Templates', employee: 'Employees', public: 'Public web' }
const GROUP_LABEL = { access: 'Access', authentication: 'Authentication', resilience: 'Resilience', vulnerability: 'Vulnerability', people: 'People', governance: 'Governance', incident: 'Incident & network', data: 'Data & privacy', other: 'Other' }

/* Sequential single-hue ramp (accent → surface). Steps are monotone in lightness on both themes. */
const ramp = (t) => `color-mix(in oklab, var(--accent) ${Math.round(18 + 82 * t)}%, var(--surface))`
const STATUS_RAMP = { VERIFIED: 1, CONFIRMED_BY_USER: 0.78, PARTIAL: 0.5, CONFLICT: 0.3, UNKNOWN: 0.12 }

export default function DataView({ status, job, actions, openQuestion, startChat }) {
  const [tab, setTab] = useState(() => localStorage.getItem('dataTab') || 'dashboard')
  useEffect(() => { localStorage.setItem('dataTab', tab) }, [tab])
  const { data, refreshing } = useResource('overview', api.overview, [status?.claims, status?.counts, job?.state])
  if (!data) return <Spinner label="Reading the store" />
  const empty = !data.counts.claims

  return (
    <div className="rise">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="display text-[24px] sm:text-[28px]">Company data</h1>
          <p className="mt-1.5 text-[14.5px] text-muted">
            Everything the analyst knows, by source and by control. Stored in {data.dialect === 'postgres' ? `Postgres${data.pgvector ? ' with pgvector' : ''}` : 'SQLite'} · {data.counts.embeddings} vectors for retrieval.{refreshing ? <span className="ml-2 text-faint">· updating…</span> : null}
          </p>
        </div>
      </div>

      <div className="mt-5 -mx-4 flex gap-1 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        {TABS.map(([k, label]) => (
          <button key={k} type="button" onClick={() => setTab(k)} className={cx('shrink-0 rounded-full px-3 py-1.5 text-[13.5px] font-medium transition-colors', tab === k ? 'bg-surface-2 text-text' : 'text-muted hover:text-text')}>{label}</button>
        ))}
      </div>

      {job && job.state === 'running' && job.kind === 'index' ? <div className="mt-6"><JobProgress job={job} /></div> : null}
      {empty && !job ? <div className="mt-6"><Panel title="Nothing indexed yet" detail="Run the ingest workflow once; the result is stored and reused on every start." action={<Button variant="accent" onClick={() => actions.workflow('ingest', 'Ingest company documents', 'index')} disabled={!status?.keys?.openrouter}>Run ingest</Button>} /></div> : null}

      {tab === 'dashboard' && <div className="mt-6"><DashboardView status={status} job={job} startChat={startChat} embedded /></div>}
      {tab === 'overview' && <Overview data={data} />}
      {tab === 'coverage' && <Coverage data={data} openQuestion={openQuestion} />}
      {tab === 'conflicts' && <Conflicts data={data} openQuestion={openQuestion} />}
      {tab === 'documents' && <Documents docs={data.documents} />}
      {tab === 'web' && <PublicWeb status={status} job={job} actions={actions} />}
    </div>
  )
}

/* ---------------------------------------------------------------- overview */
function Overview({ data }) {
  const c = data.counts
  const openConflicts = data.conflicts.filter((k) => k.status === 'open').length
  const tiles = [
    ['Documents', c.documents], ['Claims extracted', c.claims], ['Retrieval vectors', c.embeddings],
    ['Employee statements', c.user_statements], ['Public findings', c.external_findings], ['Open contradictions', openConflicts],
  ]
  const maxTier = Math.max(1, ...data.tiers.map((t) => t.claims))
  const topics = Object.entries(data.topics)
  return (
    <>
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {tiles.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-border bg-surface px-3.5 py-3">
            <p className="text-[12px] text-muted">{label}</p>
            <p className="mt-0.5 text-[22px] font-semibold tabular-nums tracking-[-0.02em]">{value}</p>
          </div>
        ))}
      </div>

      <Section title="Claims by source tier" aside={<span className="text-[12.5px] text-faint">higher tiers win a contradiction</span>}>
        <ul className="pt-2">
          {data.tiers.map((t) => (
            <li key={t.label} className="group flex items-center gap-3 py-1.5" title={`${t.claims} claims from ${t.documents || '—'} ${t.label} source${t.documents === 1 ? '' : 's'}`}>
              <span className="w-24 shrink-0 text-[13px] text-muted sm:w-28">{TIER_LABEL[t.label]}</span>
              <span className="relative h-5 flex-1">
                <span className="absolute inset-y-0 left-0 rounded-r-[4px] transition-[width] duration-500" style={{ width: `${Math.max(t.claims ? 2 : 0, (t.claims / maxTier) * 100)}%`, background: ramp(1) }} />
              </span>
              <span className="w-10 shrink-0 text-right text-[13px] tabular-nums">{t.claims}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Questionnaire status by topic" aside={<Legend />}>
        <ul className="pt-2">
          {topics.map(([topic, t]) => (
            <li key={topic} className="flex items-center gap-3 py-1.5">
              <span className="w-24 shrink-0 truncate text-[13px] text-muted sm:w-44" title={topic}>{topic}</span>
              <span className="flex h-5 flex-1 gap-[2px]">
                {STATUS_ORDER.filter((s) => t[s]).map((s) => (
                  <span key={s} className="h-full first:rounded-l-[4px] last:rounded-r-[4px]" style={{ width: `${(t[s] / t.total) * 100}%`, background: ramp(STATUS_RAMP[s]) }} title={`${STATUS[s].label}: ${t[s]} of ${t.total}`} />
                ))}
              </span>
              <span className="w-10 shrink-0 text-right text-[13px] tabular-nums text-muted">{t.total}</span>
            </li>
          ))}
        </ul>
      </Section>
    </>
  )
}

function Legend() {
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted">
      {STATUS_ORDER.map((s) => <span key={s} className="inline-flex items-center gap-1.5"><i className="inline-block size-2.5 rounded-[3px]" style={{ background: ramp(STATUS_RAMP[s]) }} />{STATUS[s].short}</span>)}
    </span>
  )
}

/* ---------------------------------------------------------------- coverage heatmap */
function Coverage({ data, openQuestion }) {
  const [hover, setHover] = useState(null)
  const rows = data.coverage
  const max = useMemo(() => Math.max(1, ...rows.flatMap((r) => TIER_COLS.map((t) => r.tiers[t] || 0))), [rows])
  const groups = useMemo(() => rows.reduce((m, r) => { (m[r.group] ||= []).push(r); return m }, {}), [rows])
  return (
    <Section title="Evidence map" aside={<span className="text-[12.5px] text-faint">claims per control and source tier · darker = more</span>} className="mt-6">
      <p className="mt-2 text-[13.5px] text-muted">A control with nothing in the record, attestation or policy columns can only be answered by you. A warning marks controls where sources contradict each other.</p>
      <div className="-mx-4 mt-3 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <table className="w-full min-w-[640px] border-separate border-spacing-y-[2px] text-[13px]">
          <thead>
            <tr className="text-[11.5px] uppercase tracking-[0.04em] text-faint">
              <th className="w-[260px] py-1 text-left font-semibold">Control</th>
              {TIER_COLS.map((t) => <th key={t} className="w-16 py-1 text-center font-semibold">{TIER_LABEL[t]}</th>)}
              <th className="w-10" />
            </tr>
          </thead>
          <tbody>
            {Object.entries(groups).map(([g, rs]) => (
              <GroupRows key={g} label={GROUP_LABEL[g] || g} rows={rs} max={max} hover={hover} setHover={setHover} openQuestion={openQuestion} />
            ))}
          </tbody>
        </table>
      </div>
      {hover ? <p className="mt-2 text-[12.5px] text-muted">{hover}</p> : <p className="mt-2 text-[12.5px] text-faint">Hover a cell for the exact count; click a control to open its first question.</p>}
    </Section>
  )
}

function GroupRows({ label, rows, max, hover, setHover, openQuestion }) {
  return (
    <>
      <tr><td colSpan={TIER_COLS.length + 2} className="pt-3 text-[12px] font-semibold text-muted">{label}</td></tr>
      {rows.map((r) => (
        <tr key={r.control} className="group">
          <td className="py-0">
            <button type="button" onClick={() => r.questions[0] && openQuestion(r.questions[0])} className="flex w-full items-center gap-2 truncate py-1 text-left hover:text-accent" title={`${r.name} · Q${r.questions.join(', Q')}`}>
              <span className="truncate">{r.name}</span>
            </button>
          </td>
          {TIER_COLS.map((t) => {
            const v = r.tiers[t] || 0
            const s = v ? 0.15 + 0.85 * Math.sqrt(v / max) : 0
            return (
              <td key={t} className="p-0 px-[1px]">
                <div className="h-7 rounded-[4px] transition-transform hover:scale-[1.06]" style={{ background: v ? ramp(s) : 'var(--surface-2)' }}
                  onMouseEnter={() => setHover(`${r.name} · ${TIER_LABEL[t]}: ${v} claim${v === 1 ? '' : 's'}`)} onMouseLeave={() => setHover(null)}
                  aria-label={`${r.name} ${TIER_LABEL[t]} ${v}`} />
              </td>
            )
          })}
          <td className="text-center">{r.open_conflicts ? <WarningDiamond className="mx-auto size-4 text-bad" weight="fill" aria-label={`${r.open_conflicts} open conflicts`} /> : null}</td>
        </tr>
      ))}
    </>
  )
}

/* ---------------------------------------------------------------- conflicts */
function Conflicts({ data, openQuestion }) {
  const items = data.conflicts
  if (!items.length) return <p className="mt-8 text-[14.5px] text-muted">No contradictions detected yet.</p>
  return (
    <Section title={`Contradictions (${items.filter((k) => k.status === 'open').length} open)`} className="mt-6">
      <ul className="divide-y divide-border">
        {items.map((k) => (
          <li key={k.id} className="py-5">
            <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
              <Tag tone={k.status === 'resolved' ? 'accent' : 'bad'}>{k.status}</Tag>
              <span className="text-faint">{k.severity} · {k.attribute.replace(/_/g, ' ')}</span>
              {k.controls.map((c) => <Tag key={c}>{c.replace(/_/g, ' ')}</Tag>)}
            </div>
            <p className="mt-2 text-[14.5px]">{k.description}</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {k.claims.slice(0, 4).map((c) => (
                <div key={c.id} className="rounded-[10px] border border-border bg-surface p-3">
                  <p className="text-[12px] text-muted"><Tag tone={c.is_template ? 'signal' : c.authority >= 4 ? 'accent' : 'neutral'}>{c.is_template ? 'template' : AUTHORITY[c.authority]}</Tag> <span className="ml-1">{c.doc}</span>{c.observed_at ? ` · ${c.observed_at}` : ''}</p>
                  <p className="mt-1.5 text-[13.5px]">{c.statement}</p>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[13.5px] text-muted">{k.status === 'resolved' ? <>Resolved by {k.resolved_by}: {k.resolution_text}</> : <>To resolve: {k.question_to_ask}</>}</p>
          </li>
        ))}
      </ul>
    </Section>
  )
}

/* ---------------------------------------------------------------- documents */
const GROUP = { 4: 'Records — what actually happens', 3: 'Attestations — audited at a point in time', 2: 'Policies & contracts — what should happen', 1: 'Templates — not evidence', 0: 'Questionnaire' }
function Documents({ docs }) {
  const groups = [4, 3, 2, 1, 0].map((a) => [a, docs.filter((d) => (d.is_template ? 1 : d.authority) === a)]).filter(([, l]) => l.length)
  return groups.map(([a, list]) => (
    <Section key={a} title={GROUP[a]}>
      <ul className="divide-y divide-border">
        {list.map((d) => (
          <li key={d.id} className="py-3">
            <div className="flex flex-wrap items-center gap-2">
              <Tag tone={a >= 3 ? 'accent' : a === 1 ? 'signal' : 'neutral'}>{AUTHORITY[a]}</Tag>
              <p className="min-w-0 truncate font-medium tracking-[-0.01em]">{d.name}</p>
              <span className="ml-auto text-[12.5px] text-faint tabular-nums">{d.n_claims} claims · {d.effective_date || 'undated'}</span>
            </div>
          </li>
        ))}
      </ul>
    </Section>
  ))
}

/* ---------------------------------------------------------------- public web */
function PublicWeb({ status, job, actions }) {
  const { data } = useResource('reputational', api.reputational, [status?.last_research, job?.state])
  if (!data) return <Spinner label="Loading" />
  const running = job && job.state === 'running' && job.kind === 'research'
  const f = data.summary?.fields || {}
  return (
    <>
      {running ? <div className="mt-6"><JobProgress job={job} /></div> : null}
      {!data.summary && !running ? (
        <div className="mt-6"><Panel title="Not researched yet" detail="Seven checks via Tavily; fills the Reputational Assessment tab of the buyer's workbook." action={<Button variant="accent" onClick={() => actions.workflow('research', 'Outside-in research', 'research')} disabled={!status?.keys?.tavily}>Run outside-in research</Button>} /></div>
      ) : null}
      {data.summary ? (
        <>
          <Section title="Reputational assessment"><Rows rows={Object.entries(f).map(([k, v]) => ({ label: k.replace(/_/g, ' '), value: v }))} /></Section>
          {data.summary.discrepancies?.length ? (
            <Section title="Public web disagrees with our documents">
              <ul className="divide-y divide-border">{data.summary.discrepancies.map((d, i) => <li key={i} className="py-3.5"><p className="text-[14.5px]">{d.description}</p><p className="mt-1 text-[13.5px] text-muted">To resolve: {d.question_to_ask}</p></li>)}</ul>
            </Section>
          ) : null}
        </>
      ) : null}
      {data.findings.length ? (
        <Section title={`Public findings (${data.findings.length})`}>
          <ul className="divide-y divide-border">
            {data.findings.map((x) => (
              <li key={x.id} className="py-3">
                <div className="flex items-center gap-2 text-[13px]"><Tag>{x.kind.replace('_', ' ')}</Tag>{x.url.startsWith('http') ? <a className="inline-flex items-center gap-1 truncate text-accent hover:underline" href={x.url} target="_blank" rel="noreferrer">{x.title || x.url}<ArrowSquareOut className="size-3 shrink-0" /></a> : <span className="text-muted">{x.title}</span>}</div>
                <p className="mt-1 text-[13.5px] text-muted">{x.snippet?.slice(0, 220)}</p>
                {x.note ? <p className="mt-1 text-[13px] text-signal">{x.note}</p> : null}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </>
  )
}
