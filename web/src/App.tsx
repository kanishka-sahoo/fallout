import { Menu, MessageSquare, Play } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Answer, Incident, IncidentGraph, LogEvent, Path, Plan, PullRequest, RepoStatus, ScenarioSpec, Socket } from './api'
import { api, connect, isSimulated, needsKey, parseScenario, repoName, short } from './api'
import { KeyDialog } from './components/KeyDialog'
import { Agent, type Msg } from './components/Agent'
import type { Selection } from './components/Inspector'
import { Sidebar } from './components/Sidebar'
import { PALETTE } from './hop'
import { Activity } from './pages/Activity'
import { Ecosystem, Evaluation } from './pages/Insights'
import { Overview, fmtUtc } from './pages/Overview'
import { Repositories } from './pages/Repositories'
import { Response } from './pages/Response'
import { SIM_STEPS, type SimRun, Simulate } from './pages/Simulate'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { type Page, useRoute } from '@/lib/route'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'

const HOP_MS = 650
const TITLES: Record<Page, string> = { overview: 'Overview', response: 'Response plan', repos: 'Repositories', activity: 'Activity', simulate: 'Simulate an attack', ecosystem: 'Ecosystem', evaluation: 'Evaluation' }
const STEP_ORDER = SIM_STEPS.map(([k]) => k)
// Progress of a one-click fix, from the events the fix executor emits for the repo.
const FIX_STEPS: Record<string, string> = {
  plan: 'Planning the fix…',
  sandbox: 'Regenerating the lockfile in a sandbox…',
  verify: 'Checking the new lockfile…',
  pr: 'Opening the pull request…',
  recheck: 'Rechecking the repo…',
}
const CANCELLED = 'cancelled'
const errText = (e: unknown) => String((e as Error).message ?? e).replace(/^\d+: /, '')
const EXPOSED = ['LOCKED_MALICIOUS', 'EXPOSED_NO_LOCKFILE', 'RANGE_ADMITS_LOCK_SAFE']

// Show one approval card per repo. The newest pending plan replaces older plans.
const latestPerRepo = (plans: Plan[]) => {
  const seen = new Map<string, Plan>()
  for (const p of [...plans].sort((a, b) => b.created_at - a.created_at)) if (!seen.has(p.repo)) seen.set(p.repo, p)
  return [...seen.values()]
}

const MOD = /Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌘' : 'Ctrl '
const wide = () => window.matchMedia('(min-width: 1280px)').matches

export default function App() {
  const [route, go] = useRoute()
  const page = route.page
  const setPage = useCallback((p: Page) => go(p), [go])
  const firstRoute = useRef(route)
  const [ready, setReady] = useState(false)
  const [themePref, setTheme, theme] = useTheme()
  const [incident, setIncident] = useState<string>('')
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [defaultIncident, setDefaultIncident] = useState('')
  const [simRun, setSimRun] = useState<SimRun | null>(null)
  const [planVersion, setPlanVersion] = useState(0)
  const [toast, setToast] = useState<{ text: string; tone: 'hot' | 'muted' | 'safe'; href?: string } | null>(null)
  const [prs, setPrs] = useState<PullRequest[]>([])
  const [creating, setCreating] = useState<Record<string, number>>({}) // repo key -> start time
  const [closing, setClosing] = useState<Record<string, boolean>>({}) // PR URL -> busy
  const [keyAsk, setKeyAsk] = useState<((ok: boolean) => void) | null>(null)
  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 5000)
    return () => window.clearTimeout(t)
  }, [toast])
  const [anchor, setAnchor] = useState('')
  const [model, setModel] = useState('')
  const [data, setData] = useState<IncidentGraph | null>(null)
  const [reveal, setReveal] = useState(99)
  const [busy, setBusy] = useState<string | null>(null)
  const [repos, setRepos] = useState<RepoStatus[]>([])
  const [plans, setPlans] = useState<Plan[]>([])
  // Keep approved cards visible after the plan leaves AWAITING_APPROVAL, to show the result.
  const [kept, setKept] = useState<Plan[]>([])
  const [sel, setSel] = useState<Selection | null>(null)
  const [pathId, setPathId] = useState<string | null>(null)
  const [cited, setCited] = useState<Path | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [pending, setPending] = useState(false)
  const [events, setEvents] = useState<LogEvent[]>([])
  const [open, setOpen] = useState(false)
  const [agentOpen, setAgentOpen] = useState(() => (localStorage.getItem('fallout-agent') ?? (window.innerWidth >= 1600 ? '1' : '0')) === '1')
  const [isWide, setWide] = useState(wide)
  const [navOpen, setNavOpen] = useState(false)
  const socket = useRef<Socket | null>(null)
  const timer = useRef<number | null>(null)
  const main = useRef<HTMLElement>(null)
  // A page change clears the selection, unless it came from "Show on graph" or a citation.
  const keepSel = useRef(false)
  useEffect(() => {
    if (!keepSel.current) { setSel(null); setCited(null) }
    keepSel.current = false
    main.current?.scrollTo({ top: 0 })
  }, [page])
  const showOnGraph = () => { keepSel.current = true; setPage('overview') }

  const toggleAgent = useCallback((v?: boolean) => {
    setAgentOpen((o) => {
      const next = v ?? !o
      localStorage.setItem('fallout-agent', next ? '1' : '0')
      return next
    })
  }, [])

  useEffect(() => {
    const m = window.matchMedia('(min-width: 1280px)')
    const on = () => setWide(m.matches)
    m.addEventListener('change', on)
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') { e.preventDefault(); toggleAgent() }
    }
    window.addEventListener('keydown', key)
    return () => { m.removeEventListener('change', on); window.removeEventListener('keydown', key) }
  }, [toggleAgent])

  const loadRepos = useCallback(async (inc: string) => {
    try {
      const env = await api.tool<{ repos: RepoStatus[] }>('repo_status', { incident_id: inc })
      setRepos(env.result.repos ?? [])
    } catch { setRepos([]) }
  }, [])
  const loadPlans = useCallback(async () => setPlans(await api.plans('AWAITING_APPROVAL').catch(() => [])), [])
  const loadPrs = useCallback(async () => setPrs(await api.prs().catch(() => [])), [])

  // Runs a call that needs a console session. On 401 it asks for the key once, then retries.
  const authed = useCallback(async <T,>(fn: () => Promise<T>): Promise<T> => {
    try {
      return await fn()
    } catch (e) {
      if (!needsKey(e)) throw e
      const ok = await new Promise<boolean>((resolve) => setKeyAsk(() => resolve))
      if (!ok) throw new Error(CANCELLED)
      return await fn()
    }
  }, [])

  const loadIncidents = useCallback(async () => {
    const xs = await api.incidents().catch(() => [] as Incident[])
    const shown = xs.filter((x) => !x.id.startsWith('eval-') || x.id === 'eval-chalk-debug')
    setIncidents(shown)
    return shown
  }, [])

  const loadIncident = useCallback(async (inc: string) => {
    localStorage.setItem('fallout-incident', inc)
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
    Promise.all([api.config(), loadIncidents()]).then(([c, xs]) => {
      setAnchor(c.anchor.S)
      setModel(c.llm)
      setDefaultIncident(c.incident)
      // The URL wins, then the incident or scenario that was selected last, then the default.
      const known = (id: string | null) => !!id && xs.some((x) => x.id === id)
      const want = firstRoute.current.incident
      const saved = localStorage.getItem('fallout-incident')
      const inc = known(want) ? want! : known(saved) ? saved! : c.incident
      if (want && !known(want)) setToast({ text: `No incident or scenario called ${want}. It may have been deleted.`, tone: 'hot' })
      setIncident(inc)
      loadIncident(inc)
      go(firstRoute.current.page, inc, true)
      setReady(true)
    })
    loadPlans()
    loadPrs()
    socket.current = connect(
      (e) => {
        setEvents((xs) => [...xs.slice(-600), e])
        if (e.kind === 'approval_request' || e.kind === 'applied') loadPlans()
        if (e.kind === 'applied') setPlanVersion((v) => v + 1)
        if (e.kind === 'applied' || e.kind === 'pr_closed') loadPrs()
        const step = e.kind === 'simulate' ? String(e.fields.step) : ''
        if (STEP_ORDER.includes(step))
          setSimRun((r) => (r && !r.error && STEP_ORDER.indexOf(step) > STEP_ORDER.indexOf(r.step) ? { ...r, step } : r))
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
  }, [loadIncident, loadIncidents, loadPlans, loadPrs])

  const maxHop = useMemo(() => Math.max(0, ...(data?.nodes ?? []).map((n) => n.hop)), [data])

  // Reveals the graph one hop at a time, then reloads repo status and the response plan.
  const animate = useCallback((g: IncidentGraph, inc: string) => {
    if (timer.current) window.clearInterval(timer.current)
    const top = Math.max(0, ...g.nodes.map((n) => n.hop))
    let h = 0
    setReveal(0)
    timer.current = window.setInterval(() => {
      h += 1
      setReveal(h)
      if (h >= top && timer.current) {
        window.clearInterval(timer.current)
        timer.current = null
        loadRepos(inc)
        setPlanVersion((v) => v + 1)
      }
    }, HOP_MS)
  }, [loadRepos])

  const replay = async () => {
    setSel(null)
    setCited(null)
    if (page !== 'overview') setPage('overview')
    // A simulation has no advisory config to ingest again. Its stored blast radius replays as is.
    if (isSimulated(incident)) {
      if (data) animate(data, incident)
      return
    }
    if (timer.current) window.clearInterval(timer.current)
    setReveal(0)
    setBusy('Loading advisories from OSV and computing the blast radius…')
    try {
      await api.replay(incident)
      const g = await api.graph(incident)
      setData(g)
      animate(g, incident)
      loadIncidents()
    } catch (e) {
      setReveal(99)
      setToast({ text: `Replay failed: ${errText(e)}`, tone: 'hot' })
    } finally {
      setBusy(null)
    }
  }

  const switchIncident = (id: string, to?: Page) => {
    if (timer.current) window.clearInterval(timer.current)
    setIncident(id)
    loadIncident(id)
    go(to ?? page, id)
  }

  // Back, forward, or a pasted link can change the incident in the URL.
  useEffect(() => {
    const want = route.incident
    if (!ready || !want || want === incident) return
    if (incidents.some((i) => i.id === want)) {
      if (timer.current) window.clearInterval(timer.current)
      setIncident(want)
      loadIncident(want)
    } else {
      setToast({ text: `No incident or scenario called ${want}. It may have been deleted.`, tone: 'hot' })
      go(route.page, incident, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.incident, ready])

  const runSimulation = async (spec: ScenarioSpec) => {
    setSimRun({ step: 'prepare', started: Date.now() })
    try {
      const r = await api.simulate(spec)
      setSimRun((s) => (s ? { ...s, step: 'done' } : s))
      const [g] = await Promise.all([api.graph(r.incident), loadIncidents()])
      localStorage.setItem('fallout-incident', r.incident)
      setIncident(r.incident)
      go('overview', r.incident)
      setSel(null)
      setCited(null)
      setRepos([])
      setData(g)
      animate(g, r.incident)
      setSimRun(null)
    } catch (e) {
      setSimRun((s) => ({ step: s?.step ?? 'prepare', started: s?.started ?? Date.now(), error: errText(e) }))
    }
  }

  const deleteSimulation = async (id: string) => {
    try {
      const r = await authed(() => api.deleteSimulation(id))
      await Promise.all([loadIncidents(), loadPrs()])
      if (id === incident) switchIncident(defaultIncident, page === 'simulate' ? 'simulate' : 'overview')
      setToast({ text: r.closed_prs ? `Scenario deleted, with its ${r.closed_prs} pull request${r.closed_prs === 1 ? '' : 's'}.` : 'Scenario deleted.', tone: 'muted' })
    } catch (e) {
      if (errText(e) !== CANCELLED) setToast({ text: `Could not delete the scenario: ${errText(e)}`, tone: 'hot' })
    }
  }

  // Reloads everything a pull request changes: repo status, the graph and the response plan.
  const refreshAfterPr = async () => {
    const g = await api.graph(incident).catch(() => null)
    if (g) setData(g)
    await Promise.all([loadRepos(incident), loadPrs(), loadIncidents(), loadPlans()])
    setPlanVersion((v) => v + 1)
  }

  const createPr = async (repo: string) => {
    setCreating((c) => ({ ...c, [repo]: Date.now() }))
    try {
      const r = await authed(() => api.fix(incident, repo))
      if (r.result === 'PR_OPENED' && r.pr_url) setToast({ text: `Opened ${r.pr_url.replace('https://github.com/', '')}. The sandbox found no affected version.`, tone: 'safe', href: r.pr_url })
      else setToast({ text: `No pull request: affected versions remain after the install (${r.verification.affected_found.join(', ')}).`, tone: 'hot' })
      await refreshAfterPr()
    } catch (e) {
      if (errText(e) !== CANCELLED) setToast({ text: `Could not open a pull request for ${repoName(repo)}: ${errText(e)}`, tone: 'hot' })
    } finally {
      setCreating(({ [repo]: _, ...rest }) => rest)
    }
  }

  const closePr = async (url: string) => {
    setClosing((c) => ({ ...c, [url]: true }))
    try {
      const r = await authed(() => api.closePr(url))
      // The API erased the PR's records and log lines. Drop them from this tab too.
      const marks = [url, r.plan_id, r.branch].filter(Boolean) as string[]
      setPrs((xs) => xs.filter((p) => p.pr_url !== url))
      setEvents((xs) => xs.filter((e) => !marks.some((m) => JSON.stringify(e).includes(m))))
      setToast({ text: `Deleted ${r.repo}#${r.number}: closed on GitHub, branch deleted, and no record left in Fallout.`, tone: 'muted' })
      await refreshAfterPr()
    } catch (e) {
      if (errText(e) !== CANCELLED) setToast({ text: `Could not delete the pull request: ${errText(e)}`, tone: 'hot' })
    } finally {
      setClosing(({ [url]: _, ...rest }) => rest)
    }
  }

  const fixProgress = useMemo(() => {
    const out: Record<string, string> = {}
    for (const [repo, start] of Object.entries(creating)) {
      const full = short(repo)
      const last = [...events].reverse().find((e) => e.fields.repo === full && FIX_STEPS[e.kind] && Date.parse(e.ts) >= start - 2000)
      out[repo] = last ? FIX_STEPS[last.kind] : FIX_STEPS.plan
    }
    return out
  }, [creating, events])
  const incidentPrs = prs.filter((p) => p.incident === incident)

  const selectRepo = useCallback(async (repo: string) => {
    const key = repo.startsWith('repo:') ? repo : `repo:${repo}`
    setCited(null)
    setSel({ key, kind: 'Repo', title: repoName(key), paths: [], loading: true })
    try {
      const env = await api.tool('exposure_path', { incident_id: incident, repo: short(key) })
      const r = env.result
      if (r.error) return setSel({ key, kind: 'Repo', title: repoName(key), paths: [], error: r.error })
      const byId = new Map(env.paths.map((p) => [p.id, p]))
      const pins = repos.find((x) => x.repo === short(key))?.locked_affected ?? []
      const locked = (pkg: string) => pins.some((k) => short(k).replace(/@[^@]+$/, '') === pkg)
      const paths = (r.per_package as { package: string; path_id: string; mitigated: boolean }[])
        .map((pp) => ({ ...byId.get(pp.path_id)!, package: pp.package, mitigated: pp.mitigated }))
        .filter((p) => p.nodes)
        // Unmitigated first, then packages the lockfile actually pins at an affected version.
        .sort((a, b) => Number(a.mitigated) - Number(b.mitigated) || Number(locked(b.package)) - Number(locked(a.package)))
      setSel({ key, kind: 'Repo', title: repoName(key), status: r.status, meaning: r.status_meaning, paths })
      setPathId(paths[0]?.id ?? null)
    } catch (e) {
      setSel({ key, kind: 'Repo', title: repoName(key), paths: [], error: String(e) })
    }
  }, [incident, repos])

  const selectNode = useCallback(async (key: string, kind: 'Version' | 'Repo') => {
    if (kind === 'Repo') return selectRepo(key)
    setCited(null)
    setSel({ key, kind, title: short(key), paths: [], loading: true })
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
    socket.current?.send(text, incident)
  }

  const clearChat = async () => {
    try {
      await api.reset()
      setMessages([])
      setPending(false)
      setCited(null)
    } catch (e) {
      setToast({ text: `Could not clear the chat: ${errText(e)}`, tone: 'hot' })
    }
  }

  const askFix = (repo: string) => {
    toggleAgent(true)
    send(`Fix ${repoName(repo)}`)
  }
  const showPath = async (repo: string) => {
    await selectRepo(repo)
    showOnGraph()
  }

  // Paths from every answer so far. An answer can cite a path that a tool returned in an earlier turn.
  const knownPaths = useMemo(() => Object.assign({}, ...messages.map((m) => m.answer?.paths ?? {})) as Record<string, Path>, [messages])
  const onCite = (a: Answer, id: string) => {
    const p = a.paths[id] ?? knownPaths[id]
    if (!p) return
    setSel({ key: p.nodes[0], kind: p.nodes[0].startsWith('repo:') ? 'Repo' : 'Version', title: 'Cited path', paths: [p] })
    setPathId(id)
    setCited(p)
    if (page !== 'overview') showOnGraph()
    if (!isWide) toggleAgent(false)
  }

  const navigate = (p: Page) => {
    setNavOpen(false)
    setPage(p)
  }
  const closeSel = () => { setSel(null); setCited(null) }
  const choosePath = (id: string) => { setCited(null); setPathId(id) }

  const highlight = cited ?? (sel ? sel.paths.find((p) => p.id === pathId) ?? sel.paths[0] ?? null : null)
  const shownPlans = [...kept.filter((k) => !plans.some((p) => p.id === k.id)), ...latestPerRepo(plans)].filter((p) => p.incident === incident)
  const pendingFixes = latestPerRepo(plans).filter((p) => p.incident === incident).length
  const exposedRepos = repos.filter((r) => EXPOSED.includes(r.status)).length
  const current = incidents.find((i) => i.id === incident)
  const replaying = !!busy || (reveal < maxHop && reveal > 0)

  const sidebar = (
    <Sidebar
      page={page}
      onNavigate={navigate}
      incident={incident}
      incidents={incidents}
      onIncident={switchIncident}
      snapshot={anchor ? fmtUtc(anchor).replace(/, \d\d:\d\d:\d\d UTC$/, '') : ''}
      connected={open}
      pendingFixes={pendingFixes}
      toFix={exposedRepos}
      theme={themePref}
      onTheme={setTheme}
    />
  )
  const agent = <Agent messages={messages} pending={pending} model={model} known={knownPaths} simulated={isSimulated(incident)} onSend={send} onCite={onCite} onClear={clearChat} onClose={() => toggleAgent(false)} />

  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className="hidden w-64 shrink-0 border-r lg:block">{sidebar}</aside>
      <Sheet open={navOpen} onOpenChange={setNavOpen}>
        <SheetContent side="left" className="w-72 p-0" showCloseButton={false}>
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          {sidebar}
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-card px-4 lg:px-6">
          <Button variant="ghost" size="icon-sm" className="-ml-1 lg:hidden" onClick={() => setNavOpen(true)} aria-label="Open menu"><Menu /></Button>
          <nav className="flex min-w-0 flex-1 items-center gap-2 text-sm" aria-label="Breadcrumb">
            <span className="hidden truncate text-muted-foreground sm:inline">{current?.title.split(':')[0] || 'Incident'}</span>
            <span className="hidden text-muted-foreground/50 sm:inline" aria-hidden>/</span>
            <span className="shrink-0 font-medium">{TITLES[page]}</span>
          </nav>
          <Button variant="outline" onClick={() => toggleAgent()} aria-pressed={agentOpen} className={cn(agentOpen && 'bg-accent')}>
            <MessageSquare data-icon="inline-start" />
            <span className="hidden sm:inline">Ask agent</span>
            <Kbd className="ml-1 hidden md:inline-flex">{MOD}J</Kbd>
          </Button>
          <Button onClick={replay} disabled={replaying}>
            <Play data-icon="inline-start" className={cn(replaying && 'animate-pulse')} />
            {busy ? 'Replaying…' : <>Replay<span className="hidden sm:inline"> {isSimulated(incident) ? 'scenario' : 'incident'}</span></>}
          </Button>
        </header>

        <main ref={main} className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {page === 'overview' ? (
            <Overview
              title={current?.title ?? ''}
              scenario={isSimulated(incident) ? parseScenario(current) ?? { kind: 'release', versions: [], published_at: null, advisories: null } : null}
              onResponse={() => setPage('response')}
              onDelete={() => deleteSimulation(incident)}
              anchor={anchor}
              data={data}
              reveal={reveal}
              busy={busy}
              palette={PALETTE[theme]}
              repos={repos}
              sel={sel}
              pathId={pathId}
              highlight={highlight}
              onSelectNode={selectNode}
              onSelectRepo={selectRepo}
              onPath={choosePath}
              onClose={closeSel}
              onReplay={replay}
            />
          ) : page === 'repos' ? (
            <Repositories
              repos={repos}
              plans={shownPlans}
              sel={sel}
              pathId={pathId}
              onSelect={selectRepo}
              onPath={choosePath}
              onClose={closeSel}
              onShowGraph={showOnGraph}
              onApplied={(p) => { setKept((xs) => [...xs.filter((x) => x.id !== p.id), p]); refreshAfterPr() }}
              prs={incidentPrs}
              closing={closing}
              onClosePr={closePr}
              authed={authed}
            />
          ) : page === 'response' ? (
            <Response
              incident={incident}
              simulated={isSimulated(incident)}
              version={planVersion}
              prs={incidentPrs}
              progress={fixProgress}
              closing={closing}
              onCreatePr={createPr}
              onClosePr={closePr}
              onAskFix={askFix}
              onShowPath={showPath}
            />
          ) : page === 'simulate' ? (
            <Simulate
              incidents={incidents}
              snapshot={anchor ? fmtUtc(anchor).replace(/, \d\d:\d\d:\d\d UTC$/, '') : ''}
              run={simRun}
              onRun={runSimulation}
              onDismiss={() => setSimRun(null)}
              onDelete={deleteSimulation}
            />
          ) : page === 'activity' ? (
            <Activity events={events} connected={open} />
          ) : page === 'ecosystem' ? (
            <Ecosystem />
          ) : (
            <Evaluation />
          )}
        </main>
      </div>

      {isWide ? (
        agentOpen ? <aside className="w-[400px] shrink-0 border-l">{agent}</aside> : null
      ) : (
        <Sheet open={agentOpen} onOpenChange={(o) => toggleAgent(o)}>
          <SheetContent className="w-full p-0 sm:max-w-md" showCloseButton={false}>
            <SheetTitle className="sr-only">Agent</SheetTitle>
            {agent}
          </SheetContent>
        </Sheet>
      )}

      {toast ? (
        <div role="status" className={cn('fixed right-4 bottom-4 z-50 flex max-w-sm items-start gap-3 rounded-lg border bg-popover px-4 py-3 text-[13px] shadow-lg animate-in fade-in slide-in-from-bottom-2', toast.tone === 'hot' && 'border-hot/40 text-hot', toast.tone === 'safe' && 'border-safe/40')}>
          <span className="min-w-0 flex-1 text-pretty">{toast.text}</span>
          {toast.href ? <a href={toast.href} target="_blank" rel="noreferrer" className="shrink-0 font-medium underline underline-offset-2">View</a> : null}
        </div>
      ) : null}
      {keyAsk ? <KeyDialog onDone={(ok) => { keyAsk(ok); setKeyAsk(null) }} /> : null}
    </div>
  )
}
