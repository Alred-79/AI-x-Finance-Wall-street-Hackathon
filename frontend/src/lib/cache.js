import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Stale-while-revalidate for API resources. The last result for a key is kept in memory and in sessionStorage,
 * so a view renders instantly with what it showed last time and refreshes in the background.
 */
const mem = new Map()
const PREFIX = 'sa-cache:'

export function readCache(key) {
  if (mem.has(key)) return mem.get(key)
  try {
    const raw = sessionStorage.getItem(PREFIX + key)
    if (raw) { const v = JSON.parse(raw); mem.set(key, v); return v }
  } catch { /* storage unavailable */ }
  return undefined
}

export function writeCache(key, value) {
  mem.set(key, value)
  try { sessionStorage.setItem(PREFIX + key, JSON.stringify(value)) } catch { /* quota or private mode */ }
}

export function clearCache() {
  mem.clear()
  try { Object.keys(sessionStorage).filter((k) => k.startsWith(PREFIX)).forEach((k) => sessionStorage.removeItem(k)) } catch { /* ignore */ }
}

/** Fetch `keys` one after another (the server serialises on one DB connection) so later views open instantly. */
export async function prefetch(entries) {
  for (const [key, fetcher] of entries) {
    if (readCache(key) !== undefined) continue
    try { writeCache(key, await fetcher()) } catch { /* best effort */ }
  }
}

/**
 * useResource(key, fetcher, deps) → { data, error, loading, refreshing, refresh }
 * - data: cached value immediately (may be stale), replaced when the fetch lands
 * - loading: true only when there is nothing cached yet
 * - refreshing: a background fetch is in flight
 */
export function useResource(key, fetcher, deps = []) {
  const [data, setData] = useState(() => readCache(key))
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const alive = useRef(true)
  useEffect(() => () => { alive.current = false }, [])

  const refresh = useCallback(async () => {
    setRefreshing(true)
    try {
      const v = await fetcher()
      if (!alive.current) return
      writeCache(key, v); setData(v); setError('')
    } catch (e) {
      if (alive.current) setError(e.message || String(e))
    } finally {
      if (alive.current) setRefreshing(false)
    }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { refresh() }, [refresh, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps

  return { data, error, loading: data === undefined && !error, refreshing, refresh }
}
