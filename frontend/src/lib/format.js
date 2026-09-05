export function formatDate(value, options = { dateStyle: 'medium' }) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? String(value).slice(0, 10) : new Intl.DateTimeFormat(undefined, options).format(d)
}

export const AUTHORITY = { 5: 'employee', 4: 'record', 3: 'attestation', 2: 'policy', 1: 'template', 0: 'public web' }

export const STATUS = {
  VERIFIED: { label: 'Verified from documents', short: 'Verified', tone: 'accent', color: 'text-accent' },
  CONFIRMED_BY_USER: { label: 'Confirmed by employee', short: 'Confirmed', tone: 'info', color: 'text-info' },
  PARTIAL: { label: 'Partially supported', short: 'Partial', tone: 'signal', color: 'text-signal' },
  CONFLICT: { label: 'Sources conflict', short: 'Conflict', tone: 'bad', color: 'text-bad' },
  UNKNOWN: { label: 'Unknown', short: 'Unknown', tone: 'neutral', color: 'text-faint' },
}
export const STATUS_ORDER = ['VERIFIED', 'CONFIRMED_BY_USER', 'PARTIAL', 'CONFLICT', 'UNKNOWN']
