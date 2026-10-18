// Client for api/main.py. Tool calls use the same MCP server as the agent.

// Display labels for repo status values. The API values do not change.
const STATUS_LABEL: Record<string, string> = {
  LOCKED_MALICIOUS: 'Malicious version in lockfile',
  EXPOSED_NO_LOCKFILE: 'Exposed (no lockfile)',
  RANGE_ADMITS_LOCK_SAFE: 'Lockfile safe, range allows malicious version',
  MITIGATED_BY_OVERRIDE: 'Mitigated by override',
  NOT_AFFECTED: 'Not affected',
}
export const statusLabel = (s: string) => STATUS_LABEL[s] ?? s.replaceAll('_', ' ').toLowerCase()

export type Edge = { type: string | null; requirement?: string | null }
export type Path = { id: string; nodes: string[]; edges: Edge[] }
export type Envelope<T = any> = { result: T; paths: Path[]; cypher: string[]; timing_ms: number; summary: Record<string, unknown> }

export type GraphNode = { key: string; kind: 'Version' | 'Repo'; hop: number; via: string | null; status: string | null; downloads: number | null }
export type IncidentGraph = {
  incident: string
  anchor: string
  affected: { key: string; advisory: string; published_at: number | null; downloads: number | null }[]
  nodes: GraphNode[]
}

export type RepoStatus = {
  repo: string
  status: string
  status_meaning: string
  has_lockfile: boolean
  locked_affected: string[]
  affected_packages: string[]
  mitigated_packages: string[]
  path_ids: Record<string, string>
}

export type Plan = {
  id: string
  repo: string
  incident: string
  status: string
  created_at: number
  body: {
    status_before: string
    changes: { pin: Record<string, { field: string; from: string; to: string }>; overrides: Record<string, unknown> }
    packages: { package: string; strategy: string; version: string | null; reason: string; requirements?: { parent_name: string; requirement: string }[] }[]
    paths: (Path & { package: string })[]
  }
}

export type LogEvent = {
  ts: string
  kind: string
  source: string
  level: string
  fields: Record<string, unknown>
  line: string
  data?: any
}

export type Answer = {
  text: string
  tool_calls: { name: string; arguments: Record<string, unknown>; took_ms: number }[]
  cited_path_ids: string[]
  unknown_path_ids: string[]
  paths: Record<string, Path>
  offline: boolean
  took_ms: number
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body === undefined ? {} : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  })
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail ?? detail } catch { /* not JSON */ }
    throw new Error(`${r.status}: ${detail}`)
  }
  return r.json() as Promise<T>
}

export type Incident = { id: string; title: string; started_at: number | null; blast_at: number | null; exposed: number | null; simulated: boolean; scenario: string | null; created_at: number | null }

export type PackageInfo = { name: string; downloads: number | null; dependents: number; maintainers: string[]; latest: string; versions: string[]; next: Record<'patch' | 'minor' | 'major', string> }

export type ScenarioKind = 'release' | 'versions' | 'osv'
export type ScenarioSpec = {
  kind: ScenarioKind
  title?: string
  published_at?: string
  packages?: { name: string; release?: 'patch' | 'minor' | 'major' | 'custom'; version?: string; range?: string }[]
  advisories?: string[]
}
export type Scenario = { kind: ScenarioKind; versions: string[]; published_at: string | null; advisories: string[] | null }

export type PlanBody = Plan['body'] & { fixable: boolean }
export type ResponsePlan = {
  incident: string
  simulated: boolean
  anchor_S: string
  repos: { repo: string; status: string; plan: PlanBody | null; error?: string }[]
  needs_action: number
  by_status: Record<string, number>
  overrides: Record<string, unknown>
  safe_versions: Record<string, string>
}

export const api = {
  config: () => req<{ anchor: { S: string; incident: string }; incident: string; repos: string[]; llm: string }>('GET', '/api/config'),
  incidents: () => req<Incident[]>('GET', '/api/incidents'),
  graph: (incident: string) => req<IncidentGraph>('GET', `/api/graph/${encodeURIComponent(incident)}`),
  replay: (incident: string) => req<{ ingest: any; blast: any }>('POST', `/api/replay/${encodeURIComponent(incident)}`),
  tool: <T = any>(name: string, args: Record<string, unknown>) => req<Envelope<T>>('POST', `/api/tools/${name}`, args),
  plans: (status?: string) => req<Plan[]>('GET', `/api/plans${status ? `?status=${status}` : ''}`),
  session: (key: string, user: string) => req<{ ok: boolean; user: string }>('POST', '/api/session', { key, user }),
  approve: (planId: string) => req<any>('POST', `/api/plans/${planId}/approve`),
  results: () => req<any>('GET', '/api/results'),
  reset: () => req<{ ok: boolean }>('POST', '/api/reset'),
  searchPackages: (q: string) => req<{ name: string; downloads: number | null }[]>('GET', `/api/packages?q=${encodeURIComponent(q)}`),
  packageInfo: (name: string) => req<PackageInfo>('GET', `/api/packages/${name}`),
  matchingVersions: (name: string, range: string) => req<{ version: string; published_iso: string }[]>('GET', `/api/packages/${name}/versions?range=${encodeURIComponent(range)}`),
  maintainerTemplate: () => req<{ maintainer: string; reach: number; packages: string[] }>('GET', '/api/templates/maintainer'),
  simulate: (spec: ScenarioSpec) => req<{ incident: string; title: string; report: { edges: number; affected_versions: number }; blast: { exposed_versions: number } }>('POST', '/api/simulations', spec),
  deleteSimulation: (id: string) => req<{ ok: boolean; closed_prs: number }>('DELETE', `/api/simulations/${encodeURIComponent(id)}`),
  fix: (incident: string, repo: string) => req<FixResult>('POST', '/api/fix', { incident, repo }),
  prs: (incident?: string) => req<PullRequest[]>('GET', `/api/prs${incident ? `?incident=${encodeURIComponent(incident)}` : ''}`),
  closePr: (pr_url: string) => req<{ ok: boolean; repo: string; number: string; branch: string; plan_id: string | null }>('POST', '/api/prs/close', { pr_url }),
  response: (incident: string) => req<ResponsePlan>('GET', `/api/response/${encodeURIComponent(incident)}`),
}

export type PullRequest = { pr_url: string; number: number; repo: string; incident: string | null; plan_id: string | null; created_at: number; approved_by: string | null; state: 'open' | 'closed' | 'merged' | 'unknown' }
export type FixResult = {
  plan_id: string
  result: 'PR_OPENED' | 'VERIFICATION_FAILED'
  pr_url: string | null
  verification: { ok: boolean; affected_found: string[]; took_ms: number }
  recheck?: { result: { before?: { status: string }; after?: { status: string } } }
}
export const needsKey = (e: unknown) => String((e as Error)?.message ?? '').startsWith('401')

export const isSimulated = (incident: string) => incident.startsWith('sim-')
export const parseScenario = (i?: Incident): Scenario | null => {
  try { return i?.scenario ? (JSON.parse(i.scenario) as Scenario) : null } catch { return null }
}
export const compact = (n: number | null | undefined) =>
  n == null ? '—' : Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n)

export type Socket = { send: (message: string, incident?: string) => void; close: () => void }

export function connect(onEvent: (e: LogEvent) => void, onHistory: (e: LogEvent[]) => void, onAnswer: (a: Answer) => void, onState: (open: boolean) => void): Socket {
  let ws: WebSocket | null = null
  let closed = false
  let retry = 500
  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/ws`)
    ws.onopen = () => { retry = 500; onState(true) }
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      if (msg.type === 'history') onHistory(msg.events)
      else if (msg.type === 'event') onEvent(msg.event)
      else if (msg.type === 'answer') onAnswer(msg.answer)
    }
    ws.onclose = () => {
      onState(false)
      if (!closed) setTimeout(open, (retry = Math.min(retry * 2, 8000)))
    }
  }
  open()
  return {
    send: (message, incident) => ws?.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ type: 'chat', message, incident })),
    close: () => { closed = true; ws?.close() },
  }
}

export const short = (key: string) => key.replace(/^npm:/, '').replace(/^repo:/, '')
export const repoName = (key: string) => short(key).replace(/^[^/]+\//, '')
