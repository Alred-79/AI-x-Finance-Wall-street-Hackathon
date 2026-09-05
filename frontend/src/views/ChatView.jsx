import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { ArrowUp, Microphone, MicrophoneSlash, Sparkle } from '@phosphor-icons/react'
import { api, chatStream } from '../lib/api'
import { Button, Panel, Section, cx } from '../components/ui'
import ActivityTrail from '../components/ActivityTrail'
import { NoKnowledgeCard, Receipts } from '../components/Evidence'
import JobProgress from '../components/JobProgress'
import MessageExtras from '../components/MessageExtras'

const SUGGESTIONS = ['Is MFA enabled?', 'Who has production access?', 'Do we perform backups?', 'How would the buyer score us right now?', 'What should we cover next?']

export default function ChatView({ status, session, speaker, role, job, actions, refresh, openQuestion, pendingPrompt, clearPending }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [listening, setListening] = useState(false)
  const endRef = useRef(null)
  const recRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => { api.history(session).then(setMessages).catch(() => {}) }, [session])
  useEffect(() => { if (pendingPrompt && !busy) { const p = pendingPrompt; clearPending?.(); send(p) } }, [pendingPrompt]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages.length, busy])

  const patchLast = (fn) => setMessages((m) => { const c = [...m]; c[c.length - 1] = fn(c[c.length - 1]); return c })

  const send = async (text) => {
    const msg = (text ?? input).trim()
    if (!msg || busy) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', content: msg, meta: {} }, { role: 'assistant', content: '', meta: { events: [], live: true, status: 'Thinking…' } }])
    setBusy(true)
    try {
      const res = await chatStream({ session, message: msg, speaker: speaker || 'Employee', role }, (ev) => {
        if (ev.type === 'delta') patchLast((a) => ({ ...a, content: a.content + ev.text, meta: { ...a.meta, status: '' } }))
        else if (ev.type === 'reset') patchLast((a) => ({ ...a, content: '' }))
        else if (ev.type === 'status') patchLast((a) => ({ ...a, meta: { ...a.meta, status: ev.text } }))
        else if (ev.type === 'tool') patchLast((a) => ({ ...a, meta: { ...a.meta, events: [...(a.meta.events || []), { tool: ev.tool, args: ev.args, ok: ev.ok }] } }))
      })
      patchLast((a) => ({ ...a, content: res.reply, meta: { ...res, evidence: res.evidence, events: res.events, updated_qids: res.updated_qids, live: false, status: '' } }))
      if (res.updated_qids?.length) refresh()
    } catch (e) {
      patchLast((a) => ({ ...a, content: (a.content ? a.content + '\n\n' : '') + `Something went wrong: ${e.message || e}`, meta: { ...a.meta, live: false, status: '' } }))
    } finally { setBusy(false); inputRef.current?.focus() }
  }

  const toggleMic = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return alert('Speech recognition is not supported in this browser.')
    if (listening) { recRef.current?.stop(); setListening(false); return }
    const rec = new SR(); rec.lang = 'en-US'
    rec.onresult = (e) => { setListening(false); send(e.results[0][0].transcript) }
    rec.onerror = () => setListening(false); rec.onend = () => setListening(false)
    recRef.current = rec; rec.start(); setListening(true)
  }

  // "Draft a question for <role>" from the not-in-knowledge-base card: put the suggestion into the composer.
  const draftQuestion = (text) => {
    setInput(text)
    const el = inputRef.current
    if (el) { el.focus(); el.style.height = 'auto'; requestAnimationFrame(() => { el.style.height = `${Math.min(el.scrollHeight, 160)}px` }) }
  }

  const indexed = status?.indexed
  const c = status?.counts || {}

  return (
    <div className="mx-auto max-w-[760px] rise">
      {job ? <div className="mb-6"><JobProgress job={job} /></div> : null}


      {status && !messages.length && !job ? (
        <div className="mb-8">
          <h1 className="display text-[24px] sm:text-[28px]">What would you like to know?</h1>
          <p className="mt-2 text-[15px] text-muted">
            {indexed
              ? <>{c.VERIFIED ?? 0} answers are already verified from documents, {(c.PARTIAL ?? 0) + (c.UNKNOWN ?? 0)} need you, and {c.CONFLICT ?? 0} have sources that disagree. Ask anything, or let me pick what matters most.</>
              : <>Ask anything about the company's security posture. Answers carry receipts; where the documents are silent, I'll say so and tell you who to ask.</>}
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => <button key={s} type="button" onClick={() => send(s)} className="rounded-full border border-border px-3.5 py-1.5 text-[14px] text-muted transition-colors hover:border-border-strong hover:text-text">{s}</button>)}
          </div>
        </div>
      ) : null}

      <div className="space-y-6">
        {messages.map((m, i) => {
          const g = m.meta?.grounding
          // receipts from this turn; older messages (before receipts existed) fall back to the raw evidence list
          const receipts = g?.receipts?.length ? g.receipts : (m.meta?.evidence || [])
          return (
          <div key={i} className={cx('fade', m.role === 'user' ? 'flex justify-end' : '')}>
            {m.role === 'user' ? (
              <div className="max-w-[88%] rounded-2xl rounded-br-md bg-surface-2 px-4 py-2.5 text-[15px] sm:max-w-[80%]">{m.content}</div>
            ) : (
              <div className="max-w-full sm:max-w-[92%]">
                <ActivityTrail events={m.meta?.events} status={m.meta?.status} live={m.meta?.live} evidenceCount={receipts.length} />
                {m.content ? <div className={cx('md text-[15px]', m.meta?.live && 'caret')}><ReactMarkdown>{m.content}</ReactMarkdown></div> : null}
                {!m.meta?.live && g?.mode === 'no_knowledge' ? <NoKnowledgeCard fallback={g.fallback} onDraft={draftQuestion} /> : null}
                {!m.meta?.live && g?.mode === 'partial' ? <p className="mt-2 text-[12.5px] text-faint">Some statements above are not backed by a receipt.</p> : null}
                {!m.meta?.live && receipts.length ? <Receipts items={receipts} /> : null}
                {!m.meta?.live && m.meta?.updated_qids?.length ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {m.meta.updated_qids.map((q) => (
                      <button key={q} type="button" onClick={() => openQuestion(q)} className="rounded-full bg-accent-soft px-2.5 py-0.5 text-[12.5px] font-medium text-accent hover:bg-accent/25">Q{q} updated</button>
                    ))}
                  </div>
                ) : null}
                {!m.meta?.live ? <MessageExtras m={m} openQuestion={openQuestion} /> : null}
              </div>
            )}
          </div>
          )
        })}
        <div ref={endRef} />
      </div>

      {status || messages.length ? (
        <div className="sticky bottom-[calc(76px+env(safe-area-inset-bottom))] mt-8 sm:bottom-4">
          <div className="flex items-end gap-2 rounded-2xl border border-border bg-surface p-2 shadow-[0_12px_32px_-16px_rgba(0,0,0,0.5)]">
            <button type="button" onClick={() => send('What should we cover next? Ask me the single most important open question.')} disabled={busy} className="grid size-10 shrink-0 place-items-center rounded-xl text-muted hover:bg-text/7 hover:text-text disabled:opacity-40" title="Ask me the most important open question">
              <Sparkle className="size-[18px]" />
            </button>
            <textarea
              ref={inputRef}
              rows={1}
              className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2.5 text-[15px] outline-none placeholder:text-faint"
              placeholder={speaker ? `Ask or answer as ${speaker}…` : 'Ask or answer…'}
              value={input}
              onChange={(e) => { setInput(e.target.value); e.target.style.height = 'auto'; e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px` }}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
              disabled={busy}
            />
            <button type="button" onClick={toggleMic} className={cx('grid size-10 shrink-0 place-items-center rounded-xl hover:bg-text/7', listening ? 'text-bad' : 'text-muted hover:text-text')} title="Speak">
              {listening ? <MicrophoneSlash className="size-[18px]" /> : <Microphone className="size-[18px]" />}
            </button>
            <button type="button" onClick={() => send()} disabled={busy || !input.trim()} className="grid size-10 shrink-0 place-items-center rounded-xl bg-text text-bg disabled:opacity-30" aria-label="Send">
              <ArrowUp className="size-[18px]" weight="bold" />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
