import { useEffect, useMemo, useRef, useState } from 'react'
import { CaretDown } from '@phosphor-icons/react'
import { api } from '../lib/api'
import { Button, Card, Confidence, Input, STATUS, STATUS_ORDER, StatusDot, StatusPill, Tag, cx } from '../components/ui'
import { EvidenceList } from '../components/Evidence'

export default function QuestionnaireView({ questions, status, focusQid, speaker, role, refresh, actions, job }) {
  const [filter, setFilter] = useState(null)
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(focusQid)
  const rowRefs = useRef({})

  useEffect(() => { if (focusQid) { setOpen(focusQid); setTimeout(() => rowRefs.current[focusQid]?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50) } }, [focusQid])

  const counts = useMemo(() => questions.reduce((a, q) => ({ ...a, [q.status]: (a[q.status] || 0) + 1 }), {}), [questions])
  const groups = useMemo(() => {
    const g = new Map()
    for (const q of questions) {
      if (filter && q.status !== filter) continue
      if (search && !`${q.qid} ${q.text} ${q.topic}`.toLowerCase().includes(search.toLowerCase())) continue
      if (!g.has(q.topic)) g.set(q.topic, [])
      g.get(q.topic).push(q)
    }
    return [...g.entries()]
  }, [questions, filter, search])

  return (
    <div className="rise">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="display text-[24px] sm:text-[28px]">Questionnaire</h1>
          <p className="mt-1.5 text-[14.5px] text-muted">{questions.length} questions · every answer carries its evidence and a confidence score.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a href="/api/export/workbook"><Button size="sm">Export workbook</Button></a>
        </div>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-2">
        {STATUS_ORDER.map((s) => (
          <button key={s} type="button" onClick={() => setFilter(filter === s ? null : s)} className={cx('inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[13px] transition-colors', filter === s ? 'border-border-strong bg-surface-2 text-text' : 'border-border text-muted hover:text-text')}>
            <StatusDot status={s} /> {STATUS[s].short} <span className="tabular-nums text-faint">{counts[s] || 0}</span>
          </button>
        ))}
        <Input className="h-9 w-full text-[14px] sm:ml-auto sm:max-w-[260px]" placeholder="Search questions" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {groups.map(([topic, qs]) => (
        <section key={topic} className="mt-8">
          <h2 className="border-b border-border pb-2 text-[12.5px] font-semibold uppercase tracking-[0.04em] text-faint">{topic}</h2>
          <ul className="divide-y divide-border">
            {qs.map((q) => (
              <li key={q.qid} ref={(el) => { rowRefs.current[q.qid] = el }}>
                <button type="button" onClick={() => setOpen(open === q.qid ? null : q.qid)} className="flex w-full items-start gap-3 py-3.5 text-left">
                  <StatusDot status={q.status} className="mt-2" />
                  <div className="min-w-0 flex-1">
                    <p className="text-[15px] tracking-[-0.01em]"><span className="mr-2 text-faint tabular-nums">{q.qid}</span>{q.text}</p>
                    {q.status !== 'UNKNOWN' && q.answer ? <p className="mt-0.5 truncate text-[13.5px] text-muted">{q.answer}</p> : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-3 pt-0.5">
                    {q.criticality ? <Tag className="hidden md:inline-flex">{q.criticality.split(' ')[0]}</Tag> : null}
                    <Confidence value={q.confidence} className="hidden sm:inline-flex" />
                    <CaretDown className={cx('size-3.5 text-faint transition-transform', open === q.qid && 'rotate-180')} weight="bold" />
                  </div>
                </button>
                {open === q.qid ? <QuestionDetail q={q} speaker={speaker} role={role} onChanged={refresh} /> : null}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {!groups.length ? <p className="mt-10 text-center text-[14.5px] text-muted">Nothing matches.</p> : null}
    </div>
  )
}

function QuestionDetail({ q, speaker, role, onChanged }) {
  const [full, setFull] = useState(null)
  const [resolution, setResolution] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => { setFull(null); api.question(q.qid).then(setFull).catch(() => {}) }, [q.qid, q.updated_at])
  const conflicts = full?.conflicts || []
  const slots = Object.entries(q.open_slots || {})
  return (
    <Card className="mb-4 p-4 fade sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={q.status} />
        <Confidence value={q.confidence} />
        <span className="text-[12.5px] text-faint">· owner {q.owner_role}{q.inherent_pts ? ` · ${q.inherent_pts} inherent risk points to the buyer` : ''}</span>
      </div>

      <Block title="Vendor response"><p className="text-[15px]">{q.answer || '—'}</p></Block>
      {q.comments ? <Block title="Comments / clarification"><p className="text-[14.5px] text-muted">{q.comments}</p></Block> : null}

      {slots.length ? (
        <Block title="Still needed from you">
          <div className="flex flex-wrap gap-1.5">{slots.map(([k]) => <Tag key={k} tone="signal">{q.slots?.[k] || k}</Tag>)}</div>
          {q.next_question ? <p className="mt-2 text-[13.5px] text-muted">The analyst would ask: “{q.next_question}”</p> : null}
        </Block>
      ) : null}

      {conflicts.length ? (
        <Block title="Sources disagree">
          {conflicts.map((c) => (
            <div key={c.id} className="mt-2 rounded-[10px] border border-bad/30 bg-bad-soft/30 p-3.5 first:mt-0">
              <p className="text-[14.5px]">{c.description}</p>
              <p className="mt-1.5 text-[13.5px] text-muted">To resolve: {c.question_to_ask}</p>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <Input className="h-10 text-[14px]" placeholder="Your answer (recorded under your name)" value={resolution} onChange={(e) => setResolution(e.target.value)} />
                <Button size="sm" className="h-10 sm:shrink-0" loading={saving} disabled={!resolution.trim()} onClick={async () => { setSaving(true); try { await api.resolve(c.id, { resolution, speaker: speaker || 'Employee', role }); setResolution(''); await onChanged?.() } finally { setSaving(false) } }}>Resolve</Button>
              </div>
            </div>
          ))}
        </Block>
      ) : null}

      <Block title={`Evidence (${q.evidence?.length || 0})`}><EvidenceList items={q.evidence} empty="No evidence in the documents. This answer has to come from you." /></Block>

      {full?.statements?.length ? (
        <Block title="What employees said">
          <ul className="divide-y divide-border">
            {full.statements.map((s) => (
              <li key={s.id} className="py-2 text-[14px] first:pt-0 last:pb-0">
                <span className="font-medium text-info">{s.speaker}</span> <span className="text-faint">({s.role}) · {String(s.created_at).slice(0, 16).replace('T', ' ')}</span>
                <p className="text-muted">{s.statement}{s.supersedes ? <span className="text-faint"> — supersedes an earlier statement</span> : null}</p>
              </li>
            ))}
          </ul>
        </Block>
      ) : null}
    </Card>
  )
}

function Block({ title, children }) {
  return (
    <div className="mt-5">
      <p className="mb-1.5 text-[12px] font-semibold uppercase tracking-[0.04em] text-faint">{title}</p>
      {children}
    </div>
  )
}
