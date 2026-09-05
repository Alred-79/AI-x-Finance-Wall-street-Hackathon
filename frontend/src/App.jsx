import { useCallback, useEffect, useRef, useState } from 'react'
import { ChatCircleText, ClipboardText, Database, Download, FileText, FlowArrow, Moon, Scales, Sun } from '@phosphor-icons/react'
import { api, pollJob } from './lib/api'
import { prefetch, readCache, writeCache } from './lib/cache'
import { toggleTheme } from './lib/theme'
import { Tag, cx } from './components/ui'
import JobProgress, { summarize } from './components/JobProgress'
import ChatView from './views/ChatView'
import QuestionnaireView from './views/QuestionnaireView'
import BuyerView from './views/BuyerView'
import WorkflowsView from './views/WorkflowsView'
import DataView from './views/DataView'

const uid = () => Math.random().toString(36).slice(2, 10)
// [key, short label for the mobile tab bar, icon, long label for the desktop nav, show in the mobile tab bar]
const NAV = [
  ['chat', 'Analyst', ChatCircleText, 'Analyst', true],
  ['questions', 'Questions', ClipboardText, 'Questionnaire', true],
  ['workflows', 'Workflows', FlowArrow, 'Workflows', true],
  ['data', 'Data', Database, 'Data', true],
  ['buyer', 'Buyer', Scales, "Buyer's view", true],
]

export default function App() {
  const [view, setView] = useState(() => localStorage.getItem('view') || 'chat')
  const [status, setStatus] = useState(() => readCache('status') ?? null)
  const [questions, setQuestions] = useState(() => readCache('questions') ?? [])
  const [job, setJob] = useState(null)
  const [error, setError] = useState('')
  const [focusQid, setFocusQid] = useState(null)
  const [pendingPrompt, setPendingPrompt] = useState(null)
  const [speaker, setSpeaker] = useState(() => localStorage.getItem('speaker') || '')
  const [role, setRole] = useState(() => localStorage.getItem('role') || 'CTO')
  const [session] = useState(() => localStorage.getItem('session') || (() => { const s = uid(); localStorage.setItem('session', s); return s })())
  const timer = useRef(null)

  useEffect(() => { localStorage.setItem('view', view); window.scrollTo({ top: 0 }) }, [view])
  useEffect(() => { localStorage.setItem('speaker', speaker) }, [speaker])
  useEffect(() => { localStorage.setItem('role', role) }, [role])

  const refresh = useCallback(async () => {
    try {
      const [s, q] = await Promise.all([api.status(), api.questions()])
      writeCache('status', s); writeCache('questions', q)
      setStatus(s); setQuestions(q); setError('')
    } catch (e) { setError(e.message || String(e)) }
  }, [])
  useEffect(() => { refresh(); timer.current = setInterval(refresh, 20000); return () => clearInterval(timer.current) }, [refresh])
  // Warm the other views once the shell is up, one request at a time, so switching tabs is instant.
  useEffect(() => {
    if (!status) return
    const t = setTimeout(() => prefetch([['workflows', api.workflows], ['overview', api.overview], ['open_items', () => api.openItems()], ['score', api.score], ['exceptions', api.exceptions], ['reputational', api.reputational]]), 800)
    return () => clearTimeout(t)
  }, [status?.indexed]) // eslint-disable-line react-hooks/exhaustive-deps
  // A job started server-side (auto-index on first start, or from another tab) is adopted here so progress is visible.
  useEffect(() => {
    const running = status?.jobs?.[0]
    if (running && !job) {
      const label = running.kind === 'workflow:ingest' ? 'Ingesting company documents' : running.kind.replace('workflow:', '').replace(/_/g, ' ')
      const kind = running.kind.includes('ingest') || running.kind === 'index' ? 'index' : running.kind.includes('research') ? 'research' : running.kind.includes('buyer') ? 'exceptions' : 'generic'
      setJob({ id: running.id, label, kind, workflow: running.kind.replace('workflow:', ''), events: [], state: 'running', adopted: true })
      pollJob(running.id, (jj) => setJob((p) => (p && p.id === running.id ? { ...p, events: jj.events, state: jj.state } : p)), 1000)
        .then(() => { setJob((p) => (p ? { ...p, state: 'done' } : p)); refresh(); setTimeout(() => setJob((p) => (p?.id === running.id ? null : p)), 6000) })
        .catch((e) => { setError(e.message); setJob(null) })
    }
  }, [status?.jobs, job, refresh])

  const runJob = useCallback(async (starter, label, kind, extra = {}) => {
    setError('')
    try {
      const j = await starter()
      const id = j.id || j.job?.id
      setJob({ id, label, kind, ...extra, events: [], state: 'running' })
      let lastDerived = 0
      await pollJob(id, (jj) => {
        setJob({ id, label, kind, ...extra, events: jj.events, state: jj.state })
        const derived = jj.events.filter((e) => e.ev === 'derived').length
        if (derived - lastDerived >= 6) { lastDerived = derived; refresh() }
      }, 1000)
      setJob((p) => ({ ...p, state: 'done' }))
      await refresh()
      setTimeout(() => setJob((p) => (p?.id === id ? null : p)), 6000)
    } catch (e) {
      setError(e.message || String(e))
      setJob((p) => (p ? { ...p, state: 'error', error: e.message } : null))
      setTimeout(() => setJob(null), 8000)
    }
  }, [refresh])

  const openQuestion = useCallback((qid) => { setFocusQid(qid); setView('questions') }, [])
  const startChat = useCallback((prompt) => { setPendingPrompt(prompt); setView('chat') }, [])
  const actions = {
    workflow: (key, label, kind, steps) => runJob(() => api.startWorkflow(key), label || key, kind || 'generic', { workflow: key, steps }),
    upload: (files) => runJob(() => api.upload(files), 'Ingesting new files', 'index', { workflow: 'ingest' }),
    exceptions: () => runJob(() => api.startWorkflow('buyer_review'), "Buyer's-eye review", 'exceptions', { workflow: 'buyer_review' }),
  }
  const common = { status, questions, refresh, job, actions, speaker, role, openQuestion, startChat }
  const iconBtn = 'grid size-9 place-items-center rounded-full text-muted hover:bg-text/7 hover:text-text'
  const progress = job && job.state === 'running' ? summarize(job) : null
  const progressPct = progress ? (progress.max ? Math.round((progress.value / progress.max) * 100) : Math.round(((progress.current + 0.5) / progress.stages.length) * 100)) : 0

  return (
    // Bottom padding reserves room for the mobile tab bar (plus the home indicator); none is needed from `sm` up.
    <div className="min-h-screen pb-[calc(64px+env(safe-area-inset-bottom))] sm:pb-0">
      <header className="sticky top-0 z-40 border-b border-border bg-bg/80 backdrop-blur-xl">
        <div className="mx-auto flex h-13 w-full max-w-[1040px] items-center gap-2 px-4 sm:px-6">
          <button type="button" onClick={() => setView('chat')} className="mr-1 inline-flex items-center gap-2.5 font-semibold tracking-[-0.01em] sm:mr-3">
            <img src="/mascot.png" alt="" className="size-7 rounded-lg object-cover" width="28" height="28" />
            Security Analyst
          </button>
          <nav className="hidden items-center gap-1 sm:flex" aria-label="Primary">
            {NAV.map(([k, , , long]) => (
              <button key={k} type="button" onClick={() => setView(k)} className={cx('rounded-full px-3 py-1.5 text-[14px] font-medium transition-colors hover:bg-text/7 hover:text-text', view === k ? 'text-text' : 'text-muted')}>
                {long}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-0.5 sm:gap-1">
            {job ? <div className="mr-2 hidden max-w-[320px] lg:block"><JobProgress job={job} compact /></div> : null}
            <Identity speaker={speaker} setSpeaker={setSpeaker} role={role} setRole={setRole} />
            <a href="/api/export/workbook" className={iconBtn} title="Download the completed workbook (.xlsx)"><Download className="size-4" weight="bold" /></a>
            <a href="/report" target="_blank" rel="noreferrer" className={iconBtn} title="Open the printable report"><FileText className="size-4" weight="bold" /></a>
            <button type="button" onClick={toggleTheme} className={iconBtn} aria-label="Toggle colour theme">
              <Sun className="size-4 [html[data-theme=light]_&]:hidden" weight="bold" />
              <Moon className="hidden size-4 [html[data-theme=light]_&]:block" weight="bold" />
            </button>
          </div>
        </div>
        {/* Thin progress line so a running job stays visible on every screen size, even where the compact stepper is hidden. */}
        {progress ? (
          <div className="h-0.5 w-full bg-surface-2">
            <div className={cx('h-full bg-accent transition-[width] duration-500', progress.value === null && 'shimmer')} style={{ width: `${progressPct}%` }} />
          </div>
        ) : null}
      </header>

      <main className="mx-auto w-full max-w-[1040px] px-4 py-6 sm:px-6 sm:py-8">
        {error ? <p className="mb-4 rounded-[10px] border border-bad/30 bg-bad-soft/40 px-4 py-2.5 text-[13.5px] text-bad">{error}</p> : null}
        {view === 'chat' && <ChatView {...common} session={session} pendingPrompt={pendingPrompt} clearPending={() => setPendingPrompt(null)} goTo={setView} />}
        {view === 'questions' && <QuestionnaireView {...common} focusQid={focusQid} />}
        {view === 'workflows' && <WorkflowsView {...common} />}
        {view === 'data' && <DataView {...common} />}
        {view === 'buyer' && <BuyerView {...common} />}
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-bg/92 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl sm:hidden" aria-label="Primary">
        {NAV.filter((n) => n[4]).map(([k, label, Icon]) => (
          <button key={k} type="button" onClick={() => setView(k)} className={cx('flex flex-1 flex-col items-center gap-1 pb-2 pt-2.5 text-[11px] font-medium', view === k ? 'text-accent' : 'text-muted')}>
            <Icon className="size-[22px]" weight={view === k ? 'fill' : 'regular'} />{label}
          </button>
        ))}
      </nav>
    </div>
  )
}

function Identity({ speaker, setSpeaker, role, setRole }) {
  const [open, setOpen] = useState(!speaker)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const close = (e) => { if (e.key === 'Escape' || (e.type === 'mousedown' && ref.current && !ref.current.contains(e.target))) setOpen(false) }
    document.addEventListener('mousedown', close); document.addEventListener('keydown', close)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close) }
  }, [open])
  const initials = (speaker || '?').trim().split(/\s+/).map((p) => p[0]).join('').slice(0, 2).toUpperCase()
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(!open)} className="inline-flex h-9 items-center gap-2 rounded-full px-1 text-[14px] font-medium hover:bg-text/7 md:pr-2.5" title="Who is answering? Statements are attributed to you.">
        <span className="grid size-7 place-items-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent">{initials}</span>
        <span className="hidden md:inline">{speaker || 'Who are you?'}</span>
        <Tag className="hidden md:inline-flex">{role}</Tag>
      </button>
      {open ? (
        // Full-width sheet under the header on phones; anchored popover from `sm` up.
        <div className="fixed inset-x-4 top-16 z-50 rounded-xl border border-border bg-surface p-4 shadow-[0_12px_32px_-12px_rgba(0,0,0,0.45)] rise sm:absolute sm:inset-x-auto sm:right-0 sm:top-11 sm:w-72">
          <p className="text-[13px] text-muted">Your answers are recorded under this name, so the analyst can say who confirmed what.</p>
          <label className="mt-3 block text-[13px] font-medium">Name
            <input autoFocus className="mt-1 h-10 w-full rounded-[10px] border border-border bg-bg px-3 text-[14px] outline-none focus:border-accent" value={speaker} onChange={(e) => setSpeaker(e.target.value)} placeholder="e.g. Sahil" />
          </label>
          <label className="mt-3 block text-[13px] font-medium">Role
            <select className="mt-1 h-10 w-full rounded-[10px] border border-border bg-bg px-3 text-[14px] outline-none focus:border-accent" value={role} onChange={(e) => setRole(e.target.value)}>
              {['CTO', 'CEO', 'CBO', 'Security Lead', 'Engineer', 'Other'].map((r) => <option key={r}>{r}</option>)}
            </select>
          </label>
          <button type="button" onClick={() => setOpen(false)} className="mt-4 h-10 w-full rounded-[10px] bg-text text-[14px] font-medium text-bg">Done</button>
        </div>
      ) : null}
    </div>
  )
}
