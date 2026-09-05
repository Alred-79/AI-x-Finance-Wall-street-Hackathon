import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Play, UploadSimple } from '@phosphor-icons/react'
import { api } from '../lib/api'
import { Button, Card, Spinner, Tag, cx, formatDate } from '../components/ui'
import { summarize } from '../components/JobProgress'
import WorkflowDiagram from '../components/WorkflowDiagram'

const KIND = { ingest: 'index', research: 'research', buyer_review: 'exceptions', export: 'export' }

export default function WorkflowsView({ status, job, actions, startChat }) {
  const [data, setData] = useState(null)
  const fileRef = useRef(null)
  useEffect(() => { api.workflows().then(setData).catch(() => {}) }, [job?.state, status?.counts])
  if (!data) return <Spinner label="Loading workflows" />

  const start = async (w) => {
    if (w.kind === 'chat') {
      const r = await api.startWorkflow(w.key)
      startChat(r.prompt)
      return
    }
    actions.workflow(w.key, w.title, KIND[w.key] || 'generic', w.steps)
  }

  return (
    <div className="rise">
      <h1 className="display text-[24px] sm:text-[28px]">Workflows</h1>
      <p className="mt-1.5 max-w-[680px] text-[14.5px] text-muted">Each workflow is a fixed sequence of steps. The numbers on the nodes are live from the store — what each step produced last time — and clicking a node explains how that result is deduced. Progress streams back step by step; nothing runs silently.</p>

      <div className="mt-6 grid gap-4">
        {data.workflows.map((w) => {
          const running = job && job.state === 'running' && job.workflow === w.key
          const prog = running ? summarize({ ...job, kind: KIND[w.key] || 'generic', steps: w.steps }) : null
          return (
            <Card key={w.key} className={cx('flex flex-col p-5', running && 'border-accent/40')}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[16px] font-semibold tracking-[-0.015em]">{w.title}</p>
                  <p className="mt-1 text-[13.5px] text-muted">{w.summary}</p>
                </div>
                <Tag tone={w.kind === 'chat' ? 'info' : 'neutral'}>{w.kind === 'chat' ? 'guided chat' : 'background'}</Tag>
              </div>

              <WorkflowDiagram diagram={w.diagram} current={prog ? Math.min(prog.current, (w.diagram?.nodes?.length || 1) - 1) : -1} running={!!running} />
              {running && prog?.detail ? <p className="mt-2 text-[12.5px] text-muted tabular-nums">{prog.detail}</p> : null}

              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4">
                {w.key === 'ingest' ? (
                  <>
                    <Button size="sm" variant="secondary" onClick={() => fileRef.current?.click()} disabled={!!job || !w.available}><UploadSimple className="size-4" /> Add files</Button>
                    <input ref={fileRef} type="file" multiple className="hidden" onChange={(e) => { if (e.target.files?.length) actions.upload(Array.from(e.target.files)); e.target.value = '' }} />
                    <Button size="sm" onClick={() => start(w)} disabled={!!job || !w.available} loading={running}><Play className="size-3.5" weight="fill" /> {status?.indexed ? 'Re-run on datasets/' : 'Run'}</Button>
                  </>
                ) : (
                  <Button size="sm" onClick={() => start(w)} disabled={(!!job && w.kind !== 'chat') || !w.available} loading={running}>
                    {w.kind === 'chat' ? <ArrowRight className="size-3.5" weight="bold" /> : <Play className="size-3.5" weight="fill" />} {w.kind === 'chat' ? 'Open in Analyst' : 'Run'}
                  </Button>
                )}
                {!w.available ? <span className="text-[12.5px] text-signal">needs {w.missing_keys.join(' + ')} key</span> : null}
                {w.last_run ? <span className="ml-auto text-[12.5px] text-faint">last run {formatDate(w.last_run.at, { dateStyle: 'medium', timeStyle: 'short' })}{w.last_run.rating ? ` · rating ${w.last_run.rating}` : ''}{w.last_run.claims ? ` · ${w.last_run.claims} claims` : ''}</span> : null}
              </div>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

