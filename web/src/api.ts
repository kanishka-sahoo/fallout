// Client for api/main.py. Tool calls use the same MCP server as the agent.

// Display labels for repo status values. The API values do not change.
export const STATUS_LABEL: Record<string, string> = {
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
    packages: { package: string; strategy: string; version: string | null; reason: string }[]
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

export const api = {
  config: () => req<{ anchor: { S: string; incident: string }; incident: string; repos: string[]; llm: string }>('GET', '/api/config'),
  incidents: () => req<{ id: string; title: string; started_at: number | null; blast_at: number | null; exposed: number | null }[]>('GET', '/api/incidents'),
  graph: (incident: string) => req<IncidentGraph>('GET', `/api/graph/${encodeURIComponent(incident)}`),
  replay: (incident: string) => req<{ ingest: any; blast: any }>('POST', `/api/replay/${encodeURIComponent(incident)}`),
  tool: <T = any>(name: string, args: Record<string, unknown>) => req<Envelope<T>>('POST', `/api/tools/${name}`, args),
  plans: (status?: string) => req<Plan[]>('GET', `/api/plans${status ? `?status=${status}` : ''}`),
  session: (key: string, user: string) => req<{ ok: boolean; user: string }>('POST', '/api/session', { key, user }),
  approve: (planId: string) => req<any>('POST', `/api/plans/${planId}/approve`),
  results: () => req<any>('GET', '/api/results'),
  reset: () => req<{ ok: boolean }>('POST', '/api/reset'),
}

export type Socket = { send: (message: string) => void; close: () => void }

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
    send: (message) => ws?.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ type: 'chat', message })),
    close: () => { closed = true; ws?.close() },
  }
}

export const short = (key: string) => key.replace(/^npm:/, '').replace(/^repo:/, '')
export const repoName = (key: string) => short(key).replace(/^[^/]+\//, '')
