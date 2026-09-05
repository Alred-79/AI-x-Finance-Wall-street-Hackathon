import { api } from '../lib/api'
import { Button, Card, Rows, Section, Spinner, Tag, cx } from '../components/ui'
import JobProgress from '../components/JobProgress'
import { useResource } from '../lib/cache'

const RATING_TONE = { Low: 'bg-accent text-inverse', Moderate: 'bg-signal text-inverse', High: 'bg-bad text-white', Critical: 'bg-bad text-white' }

export default function BuyerView({ status, actions, job, openQuestion }) {
  const deps = [status?.inherent_points, status?.counts, job?.state]
  const { data: sc, refreshing } = useResource('score', api.score, deps)
  const { data: excData } = useResource('exceptions', api.exceptions, deps)
  const exc = excData || []
  if (!sc) return <Spinner label="Computing the buyer's view" />
  const pct = sc.max_inherent_points ? Math.round((sc.inherent_points / sc.max_inherent_points) * 100) : 0

  return (
    <div className="mx-auto max-w-[760px] rise">
      <h1 className="display text-[24px] sm:text-[28px]">How the buyer will see this{refreshing ? <span className="ml-3 align-middle text-[13px] font-normal text-faint">updating…</span> : null}</h1>
      <p className="mt-1.5 text-[14.5px] text-muted">Computed with the customer's own workbook: their criticality table, risk points and escalation rules, applied to our current answers.</p>

      {job && job.kind === 'exceptions' ? <div className="mt-6"><JobProgress job={job} compact /></div> : null}

      <div className="mt-6 flex items-center gap-4 rounded-xl border border-border bg-surface p-4 avoid-break">
        <span className={cx('grid size-14 shrink-0 place-items-center rounded-lg text-[15px] font-bold tracking-[-0.03em]', RATING_TONE[sc.predicted_rating] || 'bg-surface-2')} aria-label={`Predicted rating ${sc.predicted_rating}`}>
          {sc.predicted_rating.slice(0, 3)}
        </span>
        <div className="min-w-0">
          <p className="truncate text-[17px] font-semibold tracking-[-0.015em]">Predicted rating: {sc.predicted_rating}</p>
          <p className="text-[14px] text-muted">{Math.round(sc.inherent_points)} of {Math.round(sc.max_inherent_points)} inherent risk points ({pct}%) · {sc.vendor_criticality} · {sc.escalations.length} predicted escalations</p>
        </div>
      </div>

      <Section title="Fix first" aside={<span className="text-[12.5px] text-faint">ranked by risk points removed per hour</span>}>
        <ul className="divide-y divide-border">
          {sc.fix_first.slice(0, 8).map((f) => (
            <li key={f.control} className="flex gap-3 py-3.5">
              <div className="min-w-0 flex-1">
                <p className="font-medium tracking-[-0.01em]">{f.action}</p>
                <p className="mt-0.5 text-[13.5px] text-muted">
                  ~{f.hours}h · removes {Math.round(f.points)} points · {f.qids.map((q) => <button key={q} type="button" onClick={() => openQuestion(q)} className="mr-1 text-accent hover:underline">Q{q}</button>)}
                </p>
              </div>
            </li>
          ))}
          {!sc.fix_first.length ? <li className="py-4 text-[14px] text-muted">Nothing to fix yet — index the documents first.</li> : null}
        </ul>
      </Section>

      <Section title="Predicted escalations" aside={<Button variant="secondary" size="sm" onClick={actions.exceptions} disabled={!!job || !sc.escalations.length}>Run buyer's-eye review</Button>}>
        <ul className="divide-y divide-border">
          {sc.escalations.map((e, i) => (
            <li key={i} className="flex gap-3 py-3">
              <Tag tone={e.kind === 'document' ? 'signal' : 'bad'} className="mt-0.5 shrink-0">{e.qid ? `Q${e.qid}` : 'Document'}</Tag>
              <div className="min-w-0">
                <p className="text-[14.5px]">{e.text}</p>
                <p className="text-[13px] text-muted">{e.reason}</p>
              </div>
            </li>
          ))}
          {!sc.escalations.length ? <li className="py-4 text-[14px] text-muted">No escalations predicted.</li> : null}
        </ul>
      </Section>

      {exc.length ? (
        <Section title="Exception request drafts" aside={<span className="text-[12.5px] text-faint">written only from evidence · exported to the workbook</span>}>
          <div className="space-y-3 pt-3">
            {exc.map((x) => (
              <Card key={x.qid} className="p-4 text-[14px]">
                <p className="font-medium"><span className="mr-2 text-faint">Q{x.qid}</span>{x.text}</p>
                <dl className="mt-3 space-y-2 text-muted">
                  <Row k="Justification" v={x.justification} />
                  <Row k="Mitigating controls" v={x.mitigating_controls} />
                  <Row k="Remediation plan" v={x.remediation_plan} />
                  <Row k="Evidence to attach" v={x.evidence_to_attach} />
                </dl>
              </Card>
            ))}
          </div>
        </Section>
      ) : null}

      <Section title="Documents the buyer asks for">
        <Rows rows={sc.documents.map((d) => ({ label: d.document, value: <><Tag tone={d.status === 'available' ? 'accent' : d.status === 'missing' ? 'bad' : 'signal'}>{d.status.replace('_', ' ')}</Tag><span className="ml-2 text-[13.5px] text-muted">{d.note}</span></> }))} />
      </Section>
    </div>
  )
}

const Row = ({ k, v }) => (
  <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-3"><dt className="shrink-0 text-faint sm:w-36">{k}</dt><dd className="min-w-0 flex-1 text-text">{v || '—'}</dd></div>
)
