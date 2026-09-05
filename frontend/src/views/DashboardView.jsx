import { useCallback, useEffect, useState } from 'react'
import { ArrowClockwise, ChatCircleText, X } from '@phosphor-icons/react'
import { api } from '../lib/api'
import { Button, Panel, Spinner, Tag, formatDate } from '../components/ui'
import { Sources, VisualCard } from '../components/charts/Chart'

const PROMPT = 'How would the buyer score us right now?'

/** Saved charts. Cards with a live source are recomputed from the store on mount and whenever the data changes. */
export default function DashboardView({ status, job, startChat, embedded = false }) {
  const [items, setItems] = useState(null)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const refreshLive = useCallback(async (list) => {
    const live = (list || []).filter((i) => i.spec?.live_source)
    if (!live.length) return
    setRefreshing(true)
    await Promise.all(live.map((i) => api.dashboardLive(i.id)
      .then((fresh) => setItems((cur) => cur?.map((x) => (x.id === i.id ? { ...x, spec: fresh.spec } : x)) ?? cur))
      .catch(() => {})))
    setRefreshing(false)
  }, [])

  const load = useCallback(async () => {
    try {
      const d = await api.dashboard()
      setItems(d.items); setError('')
      refreshLive(d.items)
    } catch (e) { setError(e.message || String(e)) }
  }, [refreshLive])

  useEffect(() => { load() }, [load])
  // Data changed elsewhere (ingest finished, facts recorded): recompute the live cards.
  useEffect(() => { if (items) refreshLive(items) }, [status?.claims, status?.inherent_points, status?.counts?.VERIFIED, job?.state]) // eslint-disable-line react-hooks/exhaustive-deps

  const remove = async (id) => {
    const prev = items
    setItems((cur) => cur.filter((x) => x.id !== id))
    try { await api.removeDashboardItem(id) } catch (e) { setItems(prev); setError(e.message || String(e)) }
  }

  if (!items && !error) return <Spinner label="Loading the dashboard" />
  const hasLive = items?.some((i) => i.spec?.live_source)

  return (
    <div className="rise">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          {embedded ? <p className="text-[14.5px] text-muted">Charts you kept from the analyst's answers. Live cards recompute from the store each time you open this tab.</p> : (
            <>
              <h1 className="display text-[24px] sm:text-[28px]">Dashboard</h1>
              <p className="mt-1.5 text-[14.5px] text-muted">Charts you kept from the analyst's answers. Live cards recompute from the store each time you open this page.</p>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {hasLive ? <Button size="sm" variant="secondary" loading={refreshing} onClick={() => refreshLive(items)}><ArrowClockwise className="size-3.5" /> Refresh live cards</Button> : null}
          <Button size="sm" variant="secondary" onClick={() => startChat(PROMPT)}><ChatCircleText className="size-3.5" /> Ask the analyst</Button>
        </div>
      </div>

      {error ? <p className="mt-4 rounded-[10px] border border-bad/30 bg-bad-soft/40 px-4 py-2.5 text-[13.5px] text-bad">{error}</p> : null}

      {items && !items.length ? (
        <div className="mt-6">
          <Panel
            title="Nothing pinned yet"
            detail={`Ask the analyst something with numbers — '${PROMPT.replace(' right now', '')}' — and add the chart here.`}
            action={<Button variant="accent" onClick={() => startChat(PROMPT)}>Ask: {PROMPT}</Button>}
          />
        </div>
      ) : null}

      {items?.length ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((it) => (
            <VisualCard
              key={it.id}
              spec={it.spec}
              className="h-full"
              aside={
                <button type="button" onClick={() => remove(it.id)} className="-mr-1.5 -mt-1.5 grid size-8 shrink-0 place-items-center rounded-full text-faint hover:bg-text/7 hover:text-text" aria-label="Remove from dashboard" title="Remove from dashboard">
                  <X className="size-4" />
                </button>
              }
              footer={
                <>
                  <span className="flex items-center gap-2 text-[12px] text-faint">
                    Added {formatDate(it.created_at, { dateStyle: 'medium', timeStyle: 'short' })}
                    {it.spec?.live_source ? <Tag tone="accent" className="normal-case">live</Tag> : null}
                  </span>
                  <Sources ids={it.spec?.source_ids} />
                </>
              }
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}
