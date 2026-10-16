import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Answer, IncidentGraph, LogEvent, Path, Plan, RepoStatus, Socket } from './api'
import { api, connect, repoName, short } from './api'
import { BlastGraph } from './components/BlastGraph'
import { Chat, Log, type Msg } from './components/Deck'
import { Ecosystem, Metrics } from './components/Insights'
import { Inspector, type Selection } from './components/Inspector'
import { Repos } from './components/Repos'
import { Wave } from './components/Wave'
import { INK, SAFE, hopColor } from './hop'

type Tab = 'repos' | 'ecosystem' | 'metrics'
const HOP_MS = 650

// Show one approval card per repo. The newest pending plan replaces older plans.
const latestPerRepo = (plans: Plan[]) => {
  const seen = new Map<string, Plan>()
  for (const p of [...plans].sort((a, b) => b.created_at - a.created_at)) if (!seen.has(p.repo)) seen.set(p.repo, p)
  return [...seen.values()]
}

const fmtUtc = (iso: string) =>
  new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' }) + ' UTC'

export default function App() {
  const [incident, setIncident] = useState<string>('')
  const [incidents, setIncidents] = useState<{ id: string; title: string }[]>([])
  const [anchor, setAnchor] = useState('')
  const [data, setData] = useState<IncidentGraph | null>(null)
  const [reveal, setReveal] = useState(99)
  const [busy, setBusy] = useState<string | null>(null)
  const [repos, setRepos] = useState<RepoStatus[]>([])
  const [plans, setPlans] = useState<Plan[]>([])
  // Keep approved cards visible after the plan leaves AWAITING_APPROVAL, to show the result.
  const [kept, setKept] = useState<Plan[]>([])
  const [tab, setTab] = useState<Tab>('repos')
  const [sel, setSel] = useState<Selection | null>(null)
  const [pathId, setPathId] = useState<string | null>(null)
  const [cited, setCited] = useState<Path | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [pending, setPending] = useState(false)
  const [events, setEvents] = useState<LogEvent[]>([])
  const [open, setOpen] = useState(false)
  const socket = useRef<Socket | null>(null)
  const timer = useRef<number | null>(null)

  const loadRepos = useCallback(async (inc: string) => {
    try {
      const env = await api.tool<{ repos: RepoStatus[] }>('repo_status', { incident_id: inc })
      setRepos(env.result.repos ?? [])
    } catch { setRepos([]) }
  }, [])
  const loadPlans = useCallback(async () => setPlans(await api.plans('AWAITING_APPROVAL').catch(() => [])), [])

  const loadIncident = useCallback(async (inc: string) => {
    setSel(null)
    setCited(null)
    try {
      const g = await api.graph(inc)
      setData(g)
      setReveal(99)
    } catch { setData(null) }
    loadRepos(inc)
  }, [loadRepos])

  useEffect(() => {
    api.config().then((c) => {
      setAnchor(c.anchor.S)
      setIncident(c.incident)
      loadIncident(c.incident)
    })
    api.incidents().then((xs) => setIncidents(xs.filter((x) => !x.id.startsWith('eval-') || x.id === 'eval-chalk-debug')))
    loadPlans()
    socket.current = connect(
      (e) => {
        setEvents((xs) => [...xs.slice(-600), e])
        if (e.kind === 'approval_request' || e.kind === 'applied') loadPlans()
      },
      (hist) => setEvents(hist.slice(-600)),
      (a) => {
        setPending(false)
        setMessages((m) => [...m, { role: 'agent', text: a.text, answer: a }])
        const last = [...a.cited_path_ids].reverse().find((id) => a.paths[id])
        if (last) setCited(a.paths[last])
      },
      setOpen,
    )
    return () => socket.current?.close()
  }, [loadIncident, loadPlans])

  const maxHop = useMemo(() => Math.max(0, ...(data?.nodes ?? []).map((n) => n.hop)), [data])

  const replay = async () => {
    if (timer.current) window.clearInterval(timer.current)
    setSel(null)
    setCited(null)
    setReveal(0)
    setBusy('Loading advisories from OSV and computing the blast radius…')
    try {
      await api.replay(incident)
      const g = await api.graph(incident)
      setData(g)
      const top = Math.max(0, ...g.nodes.map((n) => n.hop))
      let h = 0
      timer.current = window.setInterval(() => {
        h += 1
        setReveal(h)
        if (h >= top && timer.current) {
          window.clearInterval(timer.current)
          timer.current = null
          loadRepos(incident)
        }
      }, HOP_MS)
    } catch (e) {
      setBusy(String(e))
      setReveal(99)
      return
    }
    setBusy(null)
  }

  const selectRepo = useCallback(async (repo: string) => {
    const key = repo.startsWith('repo:') ? repo : `repo:${repo}`
    setCited(null)
    setSel({ key, kind: 'Repo', title: repoName(key), paths: [] })
    try {
      const env = await api.tool('exposure_path', { incident_id: incident, repo: short(key) })
      const r = env.result
      if (r.error) return setSel({ key, kind: 'Repo', title: repoName(key), paths: [], error: r.error })
      const byId = new Map(env.paths.map((p) => [p.id, p]))
      const paths = (r.per_package as { package: string; path_id: string; mitigated: boolean }[])
        .map((pp) => ({ ...byId.get(pp.path_id)!, package: pp.package, mitigated: pp.mitigated }))
        .filter((p) => p.nodes)
        .sort((a, b) => Number(a.mitigated) - Number(b.mitigated))
      setSel({ key, kind: 'Repo', title: repoName(key), status: r.status, meaning: r.status_meaning, paths })
      setPathId(paths[0]?.id ?? null)
    } catch (e) {
      setSel({ key, kind: 'Repo', title: repoName(key), paths: [], error: String(e) })
    }
  }, [incident])

  const selectNode = useCallback(async (key: string, kind: 'Version' | 'Repo') => {
    if (kind === 'Repo') return selectRepo(key)
    setCited(null)
    setSel({ key, kind, title: short(key), paths: [] })
    try {
      const env = await api.tool('exposure_path', { incident_id: incident, package: short(key) })
      const r = env.result
      setSel({ key, kind, title: short(key), paths: env.paths, error: r.error, meaning: r.exposed ? `Exposed at hop ${r.hop}.` : undefined })
      setPathId(env.paths[0]?.id ?? null)
    } catch (e) {
      setSel({ key, kind, title: short(key), paths: [], error: String(e) })
    }
  }, [incident, selectRepo])

  const send = (text: string) => {
    setMessages((m) => [...m, { role: 'user', text }])
    setPending(true)
    socket.current?.send(text)
  }

  const onCite = (a: Answer, id: string) => {
    const p = a.paths[id]
    if (!p) return
    setSel({ key: p.nodes[0], kind: p.nodes[0].startsWith('repo:') ? 'Repo' : 'Version', title: `Cited path`, paths: [p] })
    setPathId(id)
    setCited(p)
  }

  const highlight = cited ?? (sel ? sel.paths.find((p) => p.id === pathId) ?? sel.paths[0] ?? null : null)

  return (
    <div className="app">
      <header className="masthead">
        <h1 className="wordmark">Fallout</h1>
        <div className="incident">
          <select value={incident} onChange={(e) => { setIncident(e.target.value); loadIncident(e.target.value) }} aria-label="Incident">
            {incidents.map((i) => <option key={i.id} value={i.id}>{i.title || i.id}</option>)}
          </select>
          <span className="anchor">Snapshot time (S): {anchor ? fmtUtc(anchor) : '…'}. This is 1 second before the first malicious release.</span>
        </div>
        <span className="spacer" />
        <span className="conn" data-open={open}>{open ? 'Connected' : 'Reconnecting…'}</span>
        <button className="btn" onClick={replay} disabled={!!busy || (reveal < maxHop && reveal > 0)}>
          {busy ? 'Replaying…' : 'Replay incident'}
        </button>
      </header>

      <Wave data={data} reveal={reveal} busy={busy} />

      <div className="main">
        <div className="stage">
          {data ? (
            <BlastGraph data={data} reveal={reveal} path={highlight} selected={sel?.key ?? null} onSelect={selectNode} />
          ) : (
            <div className="empty">No data for this incident. Select Replay incident to load the advisories and compute the blast radius.</div>
          )}
          <div />
          {sel ? <Inspector sel={sel} pathId={pathId} onPath={(id) => { setCited(null); setPathId(id) }} onClose={() => { setSel(null); setCited(null) }} /> : null}
          <div className="legend" aria-hidden>
            <span><i style={{ background: hopColor(0, maxHop) }} />Malicious version</span>
            <span><i style={{ background: hopColor(Math.ceil(maxHop / 3), maxHop) }} />Near</span>
            <span><i style={{ background: hopColor(maxHop, maxHop) }} />Far</span>
            <span><i style={{ background: INK }} />Your repo</span>
            <span><i style={{ background: SAFE }} />Mitigated repo</span>
          </div>
        </div>

        <aside className="side">
          <div className="tabs" role="tablist">
            {(['repos', 'ecosystem', 'metrics'] as Tab[]).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
                {t === 'repos' ? 'Repos' : t === 'ecosystem' ? 'Ecosystem' : 'Evaluation'}
              </button>
            ))}
          </div>
          <div className="pane" role="tabpanel">
            {tab === 'repos' ? (
              <Repos
                repos={repos}
                plans={[...kept.filter((k) => !plans.some((p) => p.id === k.id)), ...latestPerRepo(plans)].filter((p) => p.incident === incident)} selected={sel?.key ?? null} onSelect={selectRepo} onApplied={(p) => { setKept((xs) => [...xs.filter((x) => x.id !== p.id), p]); loadRepos(incident); loadPlans() }} />
            ) : tab === 'ecosystem' ? <Ecosystem /> : <Metrics />}
          </div>
        </aside>
      </div>

      <div className="deck">
        <Chat messages={messages} pending={pending} onSend={send} onCite={onCite} />
        <Log events={events} />
      </div>
    </div>
  )
}
