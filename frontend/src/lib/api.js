const J = async (r) => {
  if (!r.ok) {
    let msg = r.statusText
    try { msg = (await r.json()).detail || msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  return r.json()
}
const get = (u) => fetch(u).then(J)
const post = (u, body) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then(J)

export const api = {
  status: () => get('/api/status'),
  prism: () => get('/api/prism'),
  run: () => post('/api/run'),
  research: (mode = 'all') => post(`/api/research?mode=${encodeURIComponent(mode)}`),
  job: (id) => get(`/api/jobs/${id}`),
  questions: () => get('/api/questions'),
  question: (qid) => get(`/api/questions/${qid}`),
  conflicts: () => get('/api/conflicts'),
  resolve: (id, body) => post(`/api/conflicts/${id}/resolve`, body),
  openItems: (role) => get(`/api/open-items${role ? `?role=${encodeURIComponent(role)}` : ''}`),
  score: () => get('/api/score'),
  draftExceptions: () => post('/api/score/exceptions'),
  exceptions: () => get('/api/score/exceptions'),
  reputational: () => get('/api/reputational'),
  documents: () => get('/api/documents'),
  facts: () => get('/api/facts'),
  chat: (body) => post('/api/chat', body),
  history: (session) => get(`/api/chat/${session}`),
  upload: (files) => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    return fetch('/api/upload', { method: 'POST', body: fd }).then(J)
  },
  reset: () => post('/api/reset?keep_statements=true'),
  overview: () => get('/api/data/overview'),
  workflows: () => get('/api/workflows'),
  startWorkflow: (key) => post(`/api/workflows/${key}/start`),
  // dashboards (query-driven charts)
  dashboard: () => get('/api/dashboard'),
  addDashboardItem: (body) => post('/api/dashboard/items', body),
  removeDashboardItem: (id) => fetch(`/api/dashboard/items/${id}`, { method: 'DELETE' }).then(J),
  dashboardLive: (id) => get(`/api/dashboard/items/${id}/live`),
  reorderDashboard: (ids) => post('/api/dashboard/reorder', { ids }),
  dashboardMetrics: (name) => get(`/api/dashboard/metrics/${encodeURIComponent(name)}`),
}

/** Stream a chat turn. onEvent receives {type: status|tool|delta|reset|done|error, ...}. Resolves with the done event. */
export async function chatStream(body, onEvent) {
  const r = await fetch('/api/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!r.ok || !r.body) {
    let msg = r.statusText
    try { msg = (await r.json()).detail || msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  let done = null
  for (;;) {
    const { value, done: eof } = await reader.read()
    if (eof) break
    buf += dec.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const frame = buf.slice(0, idx); buf = buf.slice(idx + 2)
      const line = frame.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      let ev
      try { ev = JSON.parse(line.slice(6)) } catch { continue }
      onEvent?.(ev)
      if (ev.type === 'done') done = ev
      if (ev.type === 'error') throw new Error(ev.text)
    }
  }
  if (!done) throw new Error('stream ended without a reply')
  return done
}

export function pollJob(id, onEvent, interval = 1200) {
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const j = await api.job(id)
        onEvent?.(j)
        if (j.state === 'done') return resolve(j)
        if (j.state === 'error') return reject(new Error(j.error))
        setTimeout(tick, interval)
      } catch (e) { reject(e) }
    }
    tick()
  })
}

export const STATUS_LABEL = {
  VERIFIED: 'Verified from documents',
  CONFIRMED_BY_USER: 'Confirmed by employee',
  PARTIAL: 'Partial',
  CONFLICT: 'Conflict',
  UNKNOWN: 'Unknown',
}
export const STATUS_ORDER = ['VERIFIED', 'CONFIRMED_BY_USER', 'PARTIAL', 'CONFLICT', 'UNKNOWN']
