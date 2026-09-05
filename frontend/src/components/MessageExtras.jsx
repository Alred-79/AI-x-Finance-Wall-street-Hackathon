import { useState } from 'react'
import { Check, PushPin } from '@phosphor-icons/react'
import { api } from '../lib/api'
import { Button } from './ui'
import { Sources, VisualCard } from './charts/Chart'

/** Per-message extras rendered under an assistant reply: the charts the analyst proposed, each with "Add to dashboard". */
export default function MessageExtras({ m }) {
  const visuals = m?.meta?.visuals
  const [state, setState] = useState({}) // visual id → 'busy' | 'done' | { error }
  if (!Array.isArray(visuals) || !visuals.length) return null

  const add = async (v) => {
    setState((s) => ({ ...s, [v.id]: 'busy' }))
    try {
      await api.addDashboardItem({ spec: v, source: 'chat' })
      setState((s) => ({ ...s, [v.id]: 'done' }))
    } catch (e) {
      setState((s) => ({ ...s, [v.id]: { error: e.message || String(e) } }))
    }
  }

  return (
    <div className="mt-3 space-y-3">
      {visuals.map((v, i) => {
        const st = state[v.id ?? i]
        return (
          <VisualCard
            key={v.id ?? i}
            spec={v}
            footer={
              <>
                <Sources ids={v.source_ids} />
                <span className="flex items-center gap-2">
                  {st?.error ? <span className="text-[12.5px] text-bad">{st.error}</span> : null}
                  {st === 'done' ? (
                    <Button size="sm" variant="secondary" disabled className="!opacity-100 text-accent"><Check className="size-3.5" weight="bold" /> Added</Button>
                  ) : (
                    <Button size="sm" variant="secondary" loading={st === 'busy'} onClick={() => add({ ...v, id: v.id ?? `v${i + 1}` })}><PushPin className="size-3.5" /> Add to dashboard</Button>
                  )}
                </span>
              </>
            }
          />
        )
      })}
    </div>
  )
}
