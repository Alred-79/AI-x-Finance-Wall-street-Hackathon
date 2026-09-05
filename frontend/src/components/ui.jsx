import { CircleNotch } from '@phosphor-icons/react'
import { STATUS } from '../lib/format'

export { STATUS, STATUS_ORDER, AUTHORITY, formatDate } from '../lib/format'
export { toggleTheme } from '../lib/theme'

export const cx = (...parts) => parts.filter(Boolean).join(' ')

export function Button({ variant = 'primary', size = 'md', loading, className, children, disabled, ...rest }) {
  const styles = {
    primary: 'bg-text text-bg hover:bg-text/90',
    secondary: 'border border-border-strong bg-surface text-text hover:bg-surface-2',
    accent: 'bg-accent text-inverse hover:bg-accent-pressed',
    danger: 'border border-bad/40 text-bad hover:bg-bad-soft',
    ghost: 'text-muted hover:text-text hover:bg-text/7',
  }[variant]
  const sizing = size === 'sm' ? 'h-[34px] px-3 text-[13px]' : 'h-11 px-4 text-[14.5px]'
  return (
    <button
      className={cx('inline-flex items-center justify-center gap-2 rounded-[10px] font-medium tracking-[-0.01em] whitespace-nowrap transition-colors disabled:opacity-50 disabled:pointer-events-none active:translate-y-px', styles, sizing, className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <CircleNotch className="size-4 animate-spin" /> : null}
      {children}
    </button>
  )
}

export function Input({ className, ...rest }) {
  return <input className={cx('h-11 w-full rounded-[10px] border border-border bg-surface px-3.5 text-[14.5px] text-text placeholder:text-faint outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/20', className)} {...rest} />
}

export function Eyebrow({ children, className }) {
  return <p className={cx('mb-1.5 text-[13px] font-medium text-muted', className)}>{children}</p>
}

export function Tag({ children, tone = 'neutral', className }) {
  const styles = {
    neutral: 'border border-border text-muted',
    accent: 'bg-accent-soft text-accent',
    signal: 'bg-signal-soft text-signal',
    bad: 'bg-bad-soft text-bad',
    info: 'bg-info-soft text-info',
  }[tone]
  return <span className={cx('inline-flex items-center gap-1.5 rounded-full px-2 py-px text-[11.5px] font-medium whitespace-nowrap', styles, className)}>{children}</span>
}

export function Section({ title, children, aside, className }) {
  return (
    <section className={cx('mt-8 first:mt-0', className)}>
      {title ? (
        <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border pb-2">
          <h2 className="text-[12.5px] font-semibold uppercase tracking-[0.04em] text-faint">{title}</h2>
          {aside}
        </div>
      ) : null}
      {children}
    </section>
  )
}

export function Card({ children, className }) {
  return <div className={cx('rounded-xl border border-border bg-surface', className)}>{children}</div>
}

export function Panel({ title, detail, action }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-5 py-8 text-center sm:px-6">
      <h2 className="text-[17px] font-semibold tracking-[-0.015em]">{title}</h2>
      {detail ? <p className="mt-1.5 text-[14.5px] text-muted">{detail}</p> : null}
      {action ? <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  )
}

export function Spinner({ label }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-muted">
      <CircleNotch className="size-5 animate-spin" />
      {label ? <span className="text-[14.5px]">{label}</span> : null}
    </div>
  )
}

export function StatusDot({ status, className }) {
  const m = STATUS[status] || STATUS.UNKNOWN
  return <span title={m.label} className={cx('inline-block size-2 shrink-0 rounded-full bg-current', m.color, className)} />
}

export function StatusPill({ status }) {
  const m = STATUS[status] || STATUS.UNKNOWN
  return <Tag tone={m.tone}><span className="size-1.5 rounded-full bg-current" />{m.label}</Tag>
}

export function Confidence({ value, className }) {
  const pct = Math.round((value || 0) * 100)
  return (
    <span className={cx('inline-flex items-center gap-2 text-[12px] text-muted tabular-nums', className)} title="Confidence">
      <span className="h-1 w-14 overflow-hidden rounded-full bg-surface-2"><span className="block h-full rounded-full bg-accent" style={{ width: `${pct}%` }} /></span>
      {pct}%
    </span>
  )
}

export function Progress({ value, max, indeterminate, className }) {
  const pct = max ? Math.min(100, Math.round((value / max) * 100)) : 0
  return (
    <div className={cx('h-1.5 w-full overflow-hidden rounded-full bg-surface-2', indeterminate && 'shimmer', className)}>
      {!indeterminate && <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />}
    </div>
  )
}

/** Label/value rows that stack on small screens and align in two columns from `sm` up. */
export function Rows({ rows, labelWidth = 'sm:w-44' }) {
  return (
    <dl className="divide-y divide-border">
      {rows.map(({ label, value, tone }) => (
        <div key={label} className="flex flex-col gap-0.5 py-3 text-[14.5px] sm:flex-row sm:gap-4">
          <dt className={cx('shrink-0 text-muted', labelWidth)}>{label}</dt>
          <dd className={cx('min-w-0 flex-1 break-words', tone)}>{value ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}
