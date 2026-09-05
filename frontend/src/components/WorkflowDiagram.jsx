import { useState } from 'react'
import { ArrowRight, ArrowUUpLeft, Check, CircleNotch } from '@phosphor-icons/react'
import { cx } from './ui'

/**
 * Component-based flow: one node per step with its live value from the store, SVG arrows between them,
 * a loop-back for guided workflows, and a "how this is deduced" panel for the selected node.
 * `current` (index) lights the node that is running; `done` marks a finished run.
 */
export default function WorkflowDiagram({ diagram, current = -1, running = false }) {
  const [sel, setSel] = useState(0)
  if (!diagram?.nodes?.length) return null
  const { nodes, kind, outcome } = diagram
  const selected = nodes[Math.min(sel, nodes.length - 1)]

  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-stretch gap-y-3">
        {nodes.map((n, i) => {
          const state = running ? (i < current ? 'done' : i === current ? 'active' : 'todo') : n.done ? 'done' : 'idle'
          return (
            <div key={n.id} className="flex items-stretch">
              <button
                type="button"
                onClick={() => setSel(i)}
                className={cx(
                  'relative flex min-w-[112px] flex-col justify-between rounded-[10px] border px-3 py-2 text-left transition-colors',
                  sel === i ? 'border-accent bg-accent-soft/40' : 'border-border bg-surface hover:border-border-strong',
                  state === 'todo' && 'opacity-60',
                )}
                aria-pressed={sel === i}
              >
                <span className="flex items-center gap-1.5 text-[11.5px] font-medium uppercase tracking-[0.04em] text-faint">
                  {state === 'active' ? <CircleNotch className="size-3 animate-spin text-accent" /> : state === 'done' ? <Check className="size-3 text-accent" weight="bold" /> : null}
                  {n.label}
                </span>
                <span className="mt-1 text-[18px] font-semibold tabular-nums tracking-[-0.02em]">{n.value ?? '—'}</span>
                {n.unit ? <span className="text-[11.5px] text-muted truncate max-w-[160px]" title={n.unit}>{n.unit}</span> : null}
              </button>
              {i < nodes.length - 1 ? <Connector kind={kind} index={i} total={nodes.length} /> : null}
            </div>
          )
        })}
        {kind === 'loop' ? (
          <div className="flex items-center pl-2 text-faint" title="Repeats until nothing is open">
            <ArrowUUpLeft className="size-4" /><span className="ml-1 text-[11.5px]">repeat</span>
          </div>
        ) : null}
      </div>

      <div className="mt-3 rounded-[10px] border border-border bg-surface-2/60 px-3.5 py-3">
        <p className="text-[11.5px] font-semibold uppercase tracking-[0.04em] text-faint">How “{selected.label}” is deduced</p>
        <p className="mt-1 text-[13.5px] text-muted">{selected.how || 'A fixed step with no derived value.'}</p>
      </div>
      {outcome ? <p className="mt-2 text-[13px] text-muted"><span className="font-medium text-text">Outcome:</span> {outcome}</p> : null}
    </div>
  )
}

/** SVG arrow between two nodes; the fan layout draws a short tick for the parallel checks. */
function Connector({ kind, index, total }) {
  const parallel = kind === 'fan' && index < total - 2
  return (
    <svg width="26" height="100%" viewBox="0 0 26 40" preserveAspectRatio="none" className="shrink-0 self-center text-border-strong" aria-hidden="true" style={{ height: 40 }}>
      {parallel ? (
        <path d="M2 20 H24" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 3" fill="none" />
      ) : (
        <>
          <path d="M2 20 H18" stroke="currentColor" strokeWidth="1.5" fill="none" />
          <path d="M14 15 L20 20 L14 25" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
    </svg>
  )
}

export { ArrowRight }
