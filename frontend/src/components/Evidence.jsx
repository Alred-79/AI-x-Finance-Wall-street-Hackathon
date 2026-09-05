import { useState } from 'react'
import { ArrowSquareOut, CaretDown, ChatCircleText, Globe, Info, Receipt } from '@phosphor-icons/react'
import { AUTHORITY, Button, Card, Tag, cx, formatDate } from './ui'

const TONE = { 5: 'info', 4: 'accent', 3: 'accent', 2: 'neutral', 1: 'signal', 0: 'neutral' }

const shortDate = (v) => (v ? formatDate(v, { day: 'numeric', month: 'short', year: 'numeric' }) : '')
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, '') } catch { return '' } }

/** Same fixed receipt label the backend produces (used for messages recorded before receipts existed). */
export function receiptLabel(e) {
  if (e.label) return e.label
  const auth = e.authority ?? (e.type === 'user' ? 5 : e.type === 'external' ? 0 : 2)
  const date = shortDate(e.date)
  if (e.type === 'user' || auth === 5) return `(confirmed by ${e.doc}${date ? `, ${date}` : ''})`
  if (e.type === 'external' || auth === 0) return `[public: ${host(e.url || e.excerpt) || e.doc || 'web'}]`
  if (e.type === 'template' || e.is_template || auth === 1) return `[${e.doc || 'document'} — template — not evidence]`
  return `[${e.doc || 'document'}${e.section ? ` ${e.section}` : ''}${date ? `, ${date}` : ''}]`
}

export function EvidenceItem({ e }) {
  const auth = e.authority ?? (e.type === 'user' ? 5 : e.type === 'external' ? 0 : 2)
  const isTemplate = e.type === 'template' || e.is_template
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
        <Tag tone={isTemplate ? 'signal' : TONE[auth] ?? 'neutral'}>{isTemplate ? 'template · not evidence' : AUTHORITY[auth] || e.type}</Tag>
        <span className="truncate">{e.doc}</span>
        {e.date ? <span className="text-faint">· {formatDate(e.date)}</span> : null}
      </div>
      <p className="mt-1 text-[14.5px]">{e.statement}</p>
      {e.excerpt && e.excerpt !== e.statement ? <p className="mt-1 text-[13px] italic text-faint">“{String(e.excerpt).slice(0, 240)}”</p> : null}
    </li>
  )
}

export function EvidenceList({ items, empty = 'No evidence yet.' }) {
  if (!items?.length) return <p className="py-3 text-[14px] text-muted">{empty}</p>
  return <ul className="divide-y divide-border">{items.map((e, i) => <EvidenceItem key={e.id || i} e={e} />)}</ul>
}

function ReceiptRow({ r }) {
  const [open, setOpen] = useState(false)
  const auth = r.authority ?? (r.type === 'user' ? 5 : r.type === 'external' ? 0 : 2)
  const isTemplate = r.type === 'template' || r.is_template || auth === 1
  const isWeb = r.type === 'external' || auth === 0
  const url = isWeb ? (r.url || r.excerpt) : ''
  const detail = r.excerpt && r.excerpt !== r.statement && !isWeb ? r.excerpt : ''
  return (
    <li>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 py-1.5 text-left text-[13px] hover:text-text" aria-expanded={open}>
        <Tag tone={isTemplate ? 'signal' : TONE[auth] ?? 'neutral'} className="shrink-0">{isTemplate ? 'template' : AUTHORITY[auth] || r.type}</Tag>
        <span className="min-w-0 flex-1 truncate text-text">{r.doc}{r.section ? <span className="text-muted"> {r.section}</span> : null}</span>
        {r.date ? <span className="shrink-0 text-faint tabular-nums">{shortDate(r.date)}</span> : null}
        <CaretDown className={cx('size-3 shrink-0 text-faint transition-transform', open && 'rotate-180')} weight="bold" />
      </button>
      {open ? (
        <div className="mb-2 ml-1 border-l-2 border-border pl-3 fade">
          <p className="text-[13.5px]">{r.statement}</p>
          {detail ? <p className="mt-1 text-[12.5px] italic text-faint">“{String(detail).slice(0, 320)}”</p> : null}
          {url ? <a href={url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-[12.5px] text-accent hover:underline">{host(url) || url} <ArrowSquareOut className="size-3" /></a> : null}
          <p className="mt-1 font-mono text-[11.5px] text-faint">{receiptLabel(r)}</p>
        </div>
      ) : null}
    </li>
  )
}

/** "Receipts · n" footer under a grounded reply: compact rows, click to expand the excerpt. */
export function Receipts({ items }) {
  const [open, setOpen] = useState(true)
  if (!items?.length) return null
  return (
    <div className="mt-2 border-t border-border pt-2">
      <button type="button" onClick={() => setOpen(!open)} className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-muted hover:text-text" aria-expanded={open}>
        <Receipt className="size-3.5" /> Receipts · {items.length}
        <CaretDown className={cx('size-3 text-faint transition-transform', open && 'rotate-180')} weight="bold" />
      </button>
      {open ? <ul className="mt-1 divide-y divide-border/60">{items.map((r, i) => <ReceiptRow key={r.id || i} r={r} />)}</ul> : null}
    </div>
  )
}

/** Shown when the knowledge base has nothing on the topic: says so, shows public sources (labelled), names who to ask. */
export function NoKnowledgeCard({ fallback = {}, onDraft }) {
  const topic = fallback.topic || 'this topic'
  const role = fallback.owner_role || 'CEO'
  const person = fallback.person
  const who = person ? `${person} (${role})` : role
  const sources = fallback.public_sources || []
  const draft = `Question for ${who}: what is our current practice for ${topic}? Please include any dates, owners or documents I can cite.`
  return (
    <Card className="mt-3 border-info/30 bg-info-soft/40 p-4">
      <div className="flex items-start gap-2.5">
        <Info className="mt-0.5 size-4 shrink-0 text-info" weight="fill" />
        <div className="min-w-0 flex-1">
          <p className="text-[14.5px] font-semibold tracking-[-0.01em]">Not in the knowledge base</p>
          <p className="mt-0.5 text-[13.5px] text-muted">The company documents hold nothing on <span className="text-text">{topic}</span>, so no conclusion is drawn from them — nothing above is a company fact unless it carries a receipt.</p>

          {sources.length ? (
            <div className="mt-3">
              <p className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-muted"><Globe className="size-3.5" /> Public web says <span className="font-normal text-faint">· public information, not company fact</span></p>
              <ul className="mt-1 space-y-1">
                {sources.map((s, i) => (
                  <li key={s.id || i} className="text-[13px]">
                    {s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">{s.title || host(s.url) || s.url} <ArrowSquareOut className="size-3" /></a> : <span>{s.title}</span>}
                    {s.snippet ? <span className="text-muted"> — {s.snippet}</span> : null}
                    <span className="ml-1 font-mono text-[11px] text-faint">{s.label || `[public: ${host(s.url)}]`}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
            <p className="inline-flex items-center gap-1.5 text-[13.5px]"><ChatCircleText className="size-4 text-muted" /> Ask: <span className="font-medium">{who}</span></p>
            {onDraft ? <Button variant="secondary" size="sm" onClick={() => onDraft(draft)}>Draft a question for {role}</Button> : null}
          </div>
        </div>
      </div>
    </Card>
  )
}
