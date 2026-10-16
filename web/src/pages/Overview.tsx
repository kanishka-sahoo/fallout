import { Play, ShieldCheck, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import type { IncidentGraph, Path, RepoStatus, Scenario } from '../api'
import { repoName, short, statusLabel } from '../api'
import { BlastGraph } from '../components/BlastGraph'
import { PathDetail, type Selection } from '../components/Inspector'
import { PageBody, PageHeader } from '../components/Page'
import { STATUS_ORDER, StatusBadge, StatusDot } from '../components/Status'
import { type Palette, hopColor } from '../hop'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type Props = {
  title: string
  scenario: Scenario | null
  onResponse: () => void
  onDelete: () => Promise<void>
  anchor: string
  data: IncidentGraph | null
  reveal: number
  busy: string | null
  palette: Palette
  repos: RepoStatus[]
  sel: Selection | null
  pathId: string | null
  highlight: Path | null
  onSelectNode: (key: string, kind: 'Version' | 'Repo') => void
  onSelectRepo: (repo: string) => void
  onPath: (id: string) => void
  onClose: () => void
  onReplay: () => void
}

export const fmtUtc = (iso: string) =>
  new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' }) + ' UTC'

export function Overview(p: Props) {
  const maxHop = Math.max(0, ...(p.data?.nodes ?? []).map((n) => n.hop))
  return (
    <>
      <PageHeader
        title={
          <>
            {p.scenario ? <span className="mb-2 flex w-fit items-center rounded-md bg-warn/12 px-2 py-0.5 text-xs font-medium tracking-normal text-warn">Simulation</span> : null}
            {p.title || 'Incident'}
          </>
        }
        description={p.anchor ? describe(p.scenario, p.anchor) : 'Loading snapshot time…'}
        actions={
          <>
            {p.scenario ? <DeleteScenario onDelete={p.onDelete} /> : null}
            <Button variant="outline" size="lg" onClick={p.onResponse}><ShieldCheck data-icon="inline-start" />Response plan</Button>
          </>
        }
      />
      <PageBody className="@container gap-5">
        <BlastSummary data={p.data} reveal={p.reveal} busy={p.busy} />

        <section className="grid overflow-hidden rounded-lg border bg-card @2xl:h-[clamp(480px,calc(100dvh-390px),900px)] @2xl:grid-cols-[minmax(0,1fr)_280px] @4xl:grid-cols-[minmax(0,1fr)_320px] @5xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="flex min-h-0 flex-col">
            <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b px-5 py-3">
              <h2 className="text-sm font-semibold">Dependency graph</h2>
              <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Legend">
                <Key color={hopColor(0, maxHop)}>{p.scenario?.kind === 'versions' ? 'Compromised version' : 'Malicious version'}</Key>
                <Key color={hopColor(Math.ceil(maxHop / 3), maxHop)}>Near</Key>
                <Key color={hopColor(maxHop, maxHop)}>Far</Key>
                <Key color={p.palette.ink}>Your repo</Key>
                <Key color={p.palette.safe}>Mitigated repo</Key>
              </ul>
            </header>
            <div className="relative h-[460px] min-h-0 @2xl:h-auto @2xl:flex-1">
              {p.data ? (
                <>
                  <BlastGraph data={p.data} reveal={p.reveal} path={p.highlight} selected={p.sel?.key ?? null} palette={p.palette} onSelect={p.onSelectNode} />
                  {p.data.nodes.length === 0 && !p.busy ? (
                    <div className="pointer-events-none absolute inset-x-0 top-6 flex justify-center px-6">
                      <div className="max-w-md rounded-lg border bg-card/95 px-4 py-3 text-center shadow-xs">
                        <p className="text-sm font-medium">Nothing would install {p.data.affected.length === 1 ? 'this version' : 'these versions'}</p>
                        <p className="mt-1 text-[13px] text-pretty text-muted-foreground">
                          npm picks a version only for a range that allows it. Ranges skip prerelease versions and versions outside their major, so no dependent in the graph resolves to it.
                        </p>
                      </div>
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="flex size-full flex-col items-center justify-center gap-4 px-6 text-center">
                  <div className="max-w-sm">
                    <p className="font-medium">No blast radius for this incident yet</p>
                    <p className="mt-1 text-sm text-muted-foreground">Replay the incident to load its advisories from OSV and compute which versions and repos are exposed.</p>
                  </div>
                  <Button onClick={p.onReplay} disabled={!!p.busy}>
                    <Play data-icon="inline-start" />
                    Replay incident
                  </Button>
                </div>
              )}
            </div>
          </div>
          <aside className="flex max-h-[520px] min-h-0 flex-col border-t @2xl:max-h-none @2xl:border-t-0 @2xl:border-l" aria-label={p.sel ? 'Exposure path' : 'Your repositories'}>
            {p.sel ? <Inspector sel={p.sel} pathId={p.pathId} onPath={p.onPath} onClose={p.onClose} /> : <RepoRail repos={p.repos} onSelect={p.onSelectRepo} />}
          </aside>
        </section>
      </PageBody>
    </>
  )
}

const when = (iso: string | null) => {
  if (!iso) return 'now'
  const t = new Date(iso).getTime()
  return Math.abs(t - Date.now()) < 5 * 60_000 ? 'now' : `on ${fmtUtc(iso)}`
}

function describe(sc: Scenario | null, anchor: string) {
  const ring = 'Each ring is one hop from an affected version.'
  if (!sc) return `The dependency graph as it was at ${fmtUtc(anchor)}, one second before the first malicious release. ${ring}`
  const list = (xs: string[]) => (xs.length > 4 ? `${xs.slice(0, 4).join(', ')} and ${xs.length - 4} more` : xs.join(', '))
  const base = `against the dependency graph as it was at ${fmtUtc(anchor)}.`
  if (sc.kind === 'osv') return `Advisory ${list(sc.advisories ?? [])}, traced ${base} ${ring}`
  if (sc.kind === 'versions') return `What happens if ${list(sc.versions)} turn out to be compromised, ${base} ${ring}`
  return `What happens if ${list(sc.versions)} ${sc.versions.length === 1 ? 'is' : 'are'} published ${when(sc.published_at)} with malicious code, ${base} ${ring}`
}

function DeleteScenario({ onDelete }: { onDelete: () => Promise<void> }) {
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  if (!confirm)
    return (
      <Button variant="ghost" size="lg" onClick={() => setConfirm(true)}>
        <Trash2 data-icon="inline-start" />Delete scenario
      </Button>
    )
  return (
    <span className="flex items-center gap-2 rounded-lg border border-hot/30 bg-hot/5 py-1 pr-1 pl-3 text-[13px]" role="alert">
      Delete this scenario and its pull requests?
      <Button size="sm" variant="destructive" disabled={busy} onClick={async () => { setBusy(true); await onDelete().finally(() => setBusy(false)); setConfirm(false) }}>
        {busy ? 'Deleting…' : 'Delete'}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Keep</Button>
    </span>
  )
}

function Key({ color, children }: { color: string; children: string }) {
  return (
    <li className="flex items-center gap-1.5">
      <span className="size-2 rounded-full" style={{ background: color }} aria-hidden />
      {children}
    </li>
  )
}

function Inspector({ sel, pathId, onPath, onClose }: { sel: Selection; pathId: string | null; onPath: (id: string) => void; onClose: () => void }) {
  return (
    <section className="inspector flex min-h-0 flex-1 flex-col" aria-label="Exposure path">
      <header className="flex items-start gap-3 border-b px-5 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-muted-foreground">{sel.title === 'Cited path' ? 'Cited by the agent' : sel.kind === 'Repo' ? 'Repository' : 'Package version'}</p>
          <h2 className={cn('truncate text-sm font-semibold', sel.kind === 'Version' && 'font-mono text-sm')}>{sel.title === 'Cited path' ? short(sel.key) : sel.title}</h2>
        </div>
        <Button variant="ghost" size="icon-sm" className="close -mr-1.5" onClick={onClose} aria-label="Close">
          <X />
        </Button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {sel.status ? <StatusBadge status={sel.status} className="mb-3" /> : null}
        <PathDetail sel={sel} pathId={pathId} onPath={onPath} />
      </div>
    </section>
  )
}

function RepoRail({ repos, onSelect }: { repos: RepoStatus[]; onSelect: (repo: string) => void }) {
  const sorted = [...repos].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || a.repo.localeCompare(b.repo))
  return (
    <>
      <header className="border-b px-5 py-3">
        <h2 className="text-sm font-semibold">Your repositories</h2>
        <p className="text-xs text-muted-foreground">Select a repo or a node to trace its path to the malicious version.</p>
      </header>
      <ul className="min-h-0 flex-1 overflow-y-auto p-2">
        {sorted.length === 0 ? <li className="px-3 py-2 text-sm text-muted-foreground">No repo status yet.</li> : null}
        {sorted.map((r) => (
          <li key={r.repo}>
            <button className="row flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors hover:bg-accent" onClick={() => onSelect(r.repo)}>
              <StatusDot status={r.status} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{repoName(r.repo)}</span>
                <span className="block truncate text-xs text-muted-foreground">{statusLabel(r.status)}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}

function BlastSummary({ data, reveal, busy }: { data: IncidentGraph | null; reveal: number; busy: string | null }) {
  const hops = new Map<number, { versions: number; repos: number }>()
  for (const n of data?.nodes ?? []) {
    const h = hops.get(n.hop) ?? { versions: 0, repos: 0 }
    if (n.kind === 'Repo') h.repos += 1
    else h.versions += 1
    hops.set(n.hop, h)
  }
  const maxHop = Math.max(0, ...hops.keys())
  const peak = Math.max(1, ...[...hops.values()].map((h) => h.versions))
  const shown = [...hops.entries()].filter(([h]) => h <= reveal)
  const versions = shown.reduce((s, [, h]) => s + h.versions, 0)
  const repos = shown.reduce((s, [, h]) => s + h.repos, 0)
  const packages = new Set((data?.nodes ?? []).filter((n) => n.kind === 'Version' && n.hop <= reveal).map((n) => n.key.replace(/^npm:/, '').replace(/@[^@]+$/, ''))).size

  const stats: [string, number, string?][] = [
    ['Malicious versions', data?.affected.length ?? 0, 'var(--hot)'],
    ['Exposed versions', versions],
    ['Exposed packages', packages],
    ['Your repos exposed', repos],
  ]
  return (
    <section className="grid overflow-hidden rounded-lg border bg-card @5xl:grid-cols-[auto_minmax(0,1fr)]" aria-label="Blast radius by hop">
      <dl className="grid grid-cols-2 border-b @xl:grid-cols-4 @5xl:border-r @5xl:border-b-0" aria-live="polite">
        {stats.map(([label, value, dot]) => (
          <div key={label} className="flex min-w-32 flex-col justify-center gap-1.5 px-5 py-4 not-last:border-r max-@xl:nth-[2]:border-r-0 max-@xl:nth-[-n+2]:border-b">
            <dt className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
              {dot ? <span className="size-1.5 rounded-full" style={{ background: dot }} aria-hidden /> : null}
              {label}
            </dt>
            <dd className="figure text-[28px] leading-none font-semibold">{value.toLocaleString()}</dd>
          </div>
        ))}
      </dl>
      <div className="flex min-w-0 flex-col gap-2 px-5 py-4">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-[13px] text-muted-foreground">Exposed versions by hop</h2>
          {busy ? <span className="animate-pulse text-xs text-muted-foreground">{busy}</span> : null}
        </div>
        <div className="flex h-[84px] items-end gap-1">
          {maxHop === 0 ? (
            <div className="flex h-full flex-1 items-end">
              <div className="w-full border-t pt-2 text-xs text-muted-foreground">{data && !busy ? 'No version is exposed.' : null}</div>
            </div>
          ) : null}
          {[...Array(maxHop).keys()].map((i) => {
            const hop = i + 1
            const h = hops.get(hop) ?? { versions: 0, repos: 0 }
            const on = hop <= reveal
            return (
              <div
                key={hop}
                className="group flex min-w-0 flex-1 flex-col justify-end gap-1"
                title={`Hop ${hop}: ${h.versions.toLocaleString()} versions${h.repos ? `, ${h.repos} of your repos` : ''}`}
              >
                <span className={cn('tabular truncate text-[11px] font-medium transition-opacity duration-300', on ? 'opacity-100' : 'opacity-0')}>
                  <span className="@2xl:hidden">{Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(h.versions)}</span>
                  <span className="hidden @2xl:inline">{h.versions.toLocaleString()}</span>
                </span>
                <div
                  className="rounded-[3px] transition-[opacity,transform] duration-500 ease-out motion-reduce:transition-none"
                  style={{
                    height: 6 + 46 * Math.sqrt(h.versions / peak),
                    background: hopColor(hop, maxHop),
                    opacity: on ? 1 : 0.14,
                    transformOrigin: 'bottom',
                    transform: on ? 'scaleY(1)' : 'scaleY(0.35)',
                  }}
                />
                <span className="flex items-center gap-1 truncate text-[11px] text-muted-foreground">
                  {hop}
                  {h.repos ? <span className="size-1.5 rounded-full bg-foreground" aria-label={`${h.repos} repos`} /> : null}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
