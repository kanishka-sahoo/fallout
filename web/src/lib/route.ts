import { useCallback, useEffect, useState } from 'react'

// Hash routes, so a page can be linked to and reloaded without a server-side router.
// The selected incident or scenario is part of the route: #/overview?incident=sim-...
export type Page = 'overview' | 'response' | 'repos' | 'activity' | 'simulate' | 'ecosystem' | 'evaluation'
const PAGES: Page[] = ['overview', 'response', 'repos', 'activity', 'simulate', 'ecosystem', 'evaluation']

export type Route = { page: Page; incident: string | null }

const read = (): Route => {
  const [path, qs] = location.hash.replace(/^#\/?/, '').split('?')
  const page = PAGES.includes(path as Page) ? (path as Page) : 'overview'
  return { page, incident: new URLSearchParams(qs ?? '').get('incident') }
}

export const href = (page: Page, incident: string | null) => `#/${page}${incident ? `?incident=${encodeURIComponent(incident)}` : ''}`

// go(page) keeps the current incident. go(page, id) switches it. replace avoids a history entry.
export function useRoute(): [Route, (page: Page, incident?: string | null, replace?: boolean) => void] {
  const [route, setRoute] = useState<Route>(read)
  useEffect(() => {
    const on = () => setRoute(read())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const go = useCallback((page: Page, incident?: string | null, replace = false) => {
    const next = href(page, incident === undefined ? read().incident : incident)
    if (next === location.hash) return
    if (replace) {
      history.replaceState(null, '', next)
      setRoute(read())
    } else location.hash = next
  }, [])
  return [route, go]
}
