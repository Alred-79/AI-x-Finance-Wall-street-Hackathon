import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Printer } from '@phosphor-icons/react'
import './index.css'
import { Rows, Section, Spinner, StatusDot, StatusPill, Tag, cx } from './components/ui'
import { STATUS, formatDate } from './lib/format'

const RATING_TONE = { Low: 'bg-accent text-inverse', Moderate: 'bg-signal text-inverse', High: 'bg-bad text-white', Critical: 'bg-bad text-white' }

function Report() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => { fetch('/api/report').then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.statusText)))).then(setData).catch((e) => setErr(e.message)) }, [])
  if (err) return <p className="p-10 text-center text-bad">{err}</p>
  if (!data) return <Spinner label="Preparing the report" />
  const { vendor, generated_at, score, states, conflicts, reputational, open_items } = data
  const pct = score.max_inherent_points ? Math.round((score.inherent_points / score.max_inherent_points) * 100) : 0
  const byTopic = states.reduce((m, s) => { (m[s.topic] ||= []).push(s); return m }, {})
  const c = score.counts

  return (
    <div className="mx-auto max-w-[760px] px-5 py-10 sm:px-6 sm:py-14">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[13px] font-medium text-muted">Security review pre-flight</p>
          <h1 className="display mt-1 text-[30px] sm:text-[34px]">{vendor.legal_name} <span className="text-muted">· {vendor.brand}</span></h1>
          <p className="mt-2 text-[14px] text-muted">Generated {formatDate(generated_at, { dateStyle: 'long', timeStyle: 'short' })}. Every statement is traceable to a document, a record, an employee or a public source. Nothing is inferred.</p>
        </div>
        <button type="button" onClick={() => window.print()} className="no-print inline-flex h-10 items-center gap-2 rounded-[10px] border border-border-strong bg-surface px-4 text-[14px] font-medium hover:bg-surface-2"><Printer className="size-4" /> Print / save as PDF</button>
      </header>

      <div className="mt-8 flex items-center gap-4 rounded-xl border border-border bg-surface p-4 avoid-break">
        <span className={cx('grid size-14 shrink-0 place-items-center rounded-lg text-[15px] font-bold tracking-[-0.03em]', RATING_TONE[score.predicted_rating] || 'bg-surface-2')}>{score.predicted_rating.slice(0, 3)}</span>
        <div className="min-w-0">
          <p className="text-[17px] font-semibold tracking-[-0.015em]">Predicted buyer rating: {score.predicted_rating}</p>
          <p className="text-[14px] text-muted">{Math.round(score.inherent_points)} of {Math.round(score.max_inherent_points)} inherent risk points ({pct}%) · {score.vendor_criticality} · {score.escalations.length} predicted escalations</p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {Object.keys(STATUS).map((k) => (
          <div key={k} className="rounded-xl border border-border bg-surface px-3.5 py-3 avoid-break">
            <p className="flex items-center gap-2 text-[12px] text-muted"><StatusDot status={k} />{STATUS[k].short}</p>
            <p className="mt-1 text-[22px] font-semibold tabular-nums tracking-[-0.02em]">{c[k] ?? 0}</p>
          </div>
        ))}
      </div>

      <Section title="Fix first" aside={<span className="text-[12.5px] text-faint">risk points removed per hour</span>}>
        <ol className="divide-y divide-border">
          {score.fix_first.slice(0, 10).map((f, i) => (
            <li key={f.control} className="flex gap-3 py-3.5 avoid-break">
              <span className="w-5 shrink-0 text-[13px] text-faint tabular-nums">{i + 1}</span>
              <div className="min-w-0">
                <p className="font-medium tracking-[-0.01em]">{f.action}</p>
                <p className="mt-0.5 text-[13.5px] text-muted">~{f.hours}h · {Math.round(f.points)} points · Q{f.qids.join(', Q')}</p>
              </div>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Predicted escalations">
        <ul className="divide-y divide-border">
          {score.escalations.map((e, i) => (
            <li key={i} className="flex gap-3 py-3 avoid-break">
              <Tag tone={e.kind === 'document' ? 'signal' : 'bad'} className="mt-0.5 shrink-0">{e.qid ? `Q${e.qid}` : 'Document'}</Tag>
              <div className="min-w-0"><p className="text-[14.5px]">{e.text}</p><p className="text-[13px] text-muted">{e.reason}</p></div>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Requested documents">
        <Rows rows={score.documents.map((d) => ({ label: d.document, value: <><Tag tone={d.status === 'available' ? 'accent' : d.status === 'missing' ? 'bad' : 'signal'}>{d.status.replace('_', ' ')}</Tag><span className="ml-2 text-[13.5px] text-muted">{d.note}</span></> }))} />
      </Section>

      <Section title="Where sources disagree">
        <ul className="divide-y divide-border">
          {conflicts.map((k) => (
            <li key={k.id} className="py-3.5 avoid-break">
              <div className="flex items-center gap-2 text-[12.5px]"><Tag tone={k.status === 'resolved' ? 'accent' : 'bad'}>{k.status}</Tag><span className="text-faint">{k.severity}</span></div>
              <p className="mt-1.5 text-[14.5px]">{k.description}</p>
              <p className="mt-1 text-[13.5px] text-muted">{k.status === 'resolved' ? <>Resolved by {k.resolved_by}: {k.resolution_text}</> : <>To resolve: {k.question_to_ask}</>}</p>
            </li>
          ))}
          {!conflicts.length ? <li className="py-3 text-[14px] text-muted">No conflicts detected.</li> : null}
        </ul>
      </Section>

      {reputational?.fields ? (
        <Section title="What the buyer will find on the public web">
          <Rows rows={Object.entries(reputational.fields).map(([k, v]) => ({ label: k.replace(/_/g, ' '), value: v }))} />
          {reputational.discrepancies?.length ? (
            <ul className="mt-3 divide-y divide-border">
              {reputational.discrepancies.map((d, i) => <li key={i} className="py-3 text-[14px]"><span className="font-medium text-signal">Discrepancy.</span> {d.description} <span className="text-muted">To resolve: {d.question_to_ask}</span></li>)}
            </ul>
          ) : null}
        </Section>
      ) : null}

      <Section title="Open questions for the team">
        <ul className="divide-y divide-border">
          {open_items.slice(0, 15).map((it) => (
            <li key={it.qid} className="py-3 avoid-break">
              <p className="text-[14.5px]"><span className="mr-2 text-faint">Q{it.qid}</span>{it.question}</p>
              <p className="text-[13px] text-muted">{it.owner_role} · {it.why}</p>
            </li>
          ))}
        </ul>
      </Section>

      <div className="break-before" />
      <Section title="Answers by question">
        {Object.entries(byTopic).map(([topic, qs]) => (
          <div key={topic} className="mt-6 first:mt-2">
            <h3 className="text-[15px] font-semibold tracking-[-0.01em]">{topic}</h3>
            <ul className="divide-y divide-border">
              {qs.map((s) => (
                <li key={s.qid} className="py-3.5 avoid-break">
                  <div className="flex flex-wrap items-center gap-2"><span className="text-[13px] text-faint tabular-nums">Q{s.qid}</span><StatusPill status={s.status} /><span className="text-[12.5px] text-faint">confidence {Math.round((s.confidence || 0) * 100)}%</span></div>
                  <p className="mt-1.5 text-[14.5px] font-medium">{s.text}</p>
                  <p className="mt-1 text-[14px]">{s.answer}</p>
                  {s.comments ? <p className="mt-1 text-[13.5px] text-muted">{s.comments}</p> : null}
                  {s.evidence?.slice(0, 3).map((ev, i) => <p key={i} className="mt-1 text-[12.5px] text-faint">— {ev.doc}: “{(ev.excerpt || ev.statement || '').slice(0, 160)}”</p>)}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Section>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<StrictMode><Report /></StrictMode>)
