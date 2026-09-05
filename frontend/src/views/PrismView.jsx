import { useEffect, useState } from 'react'
import { ShieldCheck, Waveform } from '@phosphor-icons/react'
import { api } from '../lib/api'
import { Panel, Section, Spinner, Tag, cx } from '../components/ui'

const PHASE_LABEL = {
  derive: 'Answer derivation',
  guardrail: 'Guardrail override',
  conflict_judge: 'Contradiction judging',
  claim_extraction: 'Claim extraction',
  exception_draft: 'Exception drafting',
  outside_in_research: 'Public-web research',
  llm: 'Model call',
}

const rel = (t) => {
  const s = Math.max(0, Math.round(Date.now() / 1000 - t))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  return `${Math.round(s / 3600)}h ago`
}

export default function PrismView({ status }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    let alive = true
    const tick = () => api.prism().then((d) => alive && setData(d)).catch((e) => alive && setErr(e.message))
    tick()
    const t = setInterval(tick, 5000)
    return () => { alive = false; clearInterval(t) }
  }, [status?.claims])

  if (err) return <Panel title="PRISM status unavailable" detail={err} />
  if (!data) return <Spinner label="Reading PRISM" />

  const c = data.counters || {}
  const overrides = (data.recent || []).filter((r) => r.kind === 'overrides')
  const tiles = [
    ['Model calls traced', c.traces || 0],
    ['Guardrail overrides', c.overrides || 0],
    ['Turns evaluated', c.trajectories || 0],
    ['Failed sends', c.failed || 0],
  ]

  return (
    <div className="rise">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="display text-[24px] sm:text-[28px]">PRISM</h1>
          <p className="mt-1.5 max-w-2xl text-[14.5px] text-muted">
            Every model call, every agent turn, and — the one that matters — every time the engine overruled the
            model because the evidence did not support what it wanted to say.
          </p>
        </div>
        <Tag tone={data.configured ? 'signal' : 'neutral'}>
          {data.configured ? 'Connected' : 'Not configured'}
        </Tag>
      </div>

      {!data.configured ? (
        <div className="mt-6">
          <Panel
            title="PRISM credentials not set"
            detail="Set PRISMTRACE_API_KEY and PRISMTRACE_PROJECT_ID in .env to stream traces. Overrides are still counted locally and shown below, so the guardrail is auditable either way."
          />
        </div>
      ) : null}

      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-border bg-surface px-3.5 py-3">
            <p className="text-[12px] text-muted">{label}</p>
            <p className="mt-0.5 text-[22px] font-semibold tabular-nums tracking-[-0.02em]">{value}</p>
          </div>
        ))}
      </div>

      <Section
        title={`Guardrail overrides (${overrides.length})`}
        aside={<span className="text-[12.5px] text-faint">the model overreached; the engine did not let it through</span>}
      >
        {overrides.length ? (
          <ul className="divide-y divide-border rounded-xl border border-border bg-surface">
            {overrides.map((o, i) => (
              <li key={i} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <ShieldCheck className="size-4 shrink-0 text-signal" />
                  <span className="text-[14px] font-medium">Q{o.qid}</span>
                  <Tag tone="bad">model said &ldquo;{o.model_answer}&rdquo;</Tag>
                  <span className="text-faint">&rarr;</span>
                  <Tag tone="signal">recorded as {o.final_status}</Tag>
                  <span className="ml-auto text-[12px] text-faint">{rel(o.at)}</span>
                </div>
                <ul className="mt-1.5 space-y-0.5 pl-6">
                  {(o.reasons || []).map((r, j) => (
                    <li key={j} className="text-[13.5px] text-muted">{r}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-6 text-center text-[14px] text-muted">
            No overrides recorded yet. Run the pipeline, or ask the analyst something the documents do not cover.
          </p>
        )}
      </Section>

      <Section title="Recent traces">
        {data.recent?.length ? (
          <ul className="divide-y divide-border rounded-xl border border-border bg-surface text-[13.5px]">
            {data.recent.slice(0, 20).map((r, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2">
                <Waveform className={cx('size-3.5 shrink-0', r.kind === 'failed' ? 'text-bad' : 'text-faint')} />
                <span className="font-medium">{PHASE_LABEL[r.phase] || r.phase || r.kind}</span>
                {r.qid ? <span className="text-muted">Q{r.qid}</span> : null}
                {r.model ? <span className="text-faint">{r.model}</span> : null}
                {r.latency_ms ? <span className="text-faint tabular-nums">{r.latency_ms}ms</span> : null}
                {r.reason ? <span className="text-faint">{r.reason}</span> : null}
                <span className="ml-auto text-[12px] text-faint">{rel(r.at)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-6 text-center text-[14px] text-muted">Nothing traced yet this session.</p>
        )}
      </Section>

      <Section title="Agent turns submitted for evaluation">
        {data.trajectories?.length ? (
          <ul className="divide-y divide-border rounded-xl border border-border bg-surface text-[13.5px]">
            {data.trajectories.map((t, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2">
                <Tag tone={t.mode === 'grounded' ? 'signal' : t.mode === 'no_knowledge' ? 'bad' : 'neutral'}>{t.mode}</Tag>
                <span className="text-muted">{t.tools?.length || 0} tool calls</span>
                <span className="text-muted">{t.receipts} receipts</span>
                {t.uncited ? <span className="text-bad">{t.uncited} uncited</span> : null}
                <span className="ml-auto text-[12px] text-faint">{rel(t.at)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-6 text-center text-[14px] text-muted">No agent turns yet. Ask the analyst a question.</p>
        )}
      </Section>
    </div>
  )
}
