import { Check, ChevronRight, Clock, Crosshair, KeyRound, Loader2, Network, Play, Radio, Trash2, X } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import type { Incident, PackageInfo, ScenarioKind, ScenarioSpec } from '../api'
import { api, compact, parseScenario } from '../api'
import { PackageSearch } from '../components/PackageSearch'
import { PageBody, PageHeader } from '../components/Page'
import { Segmented } from '../components/Segmented'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { href } from '@/lib/route'
import { cn } from '@/lib/utils'

type Release = 'patch' | 'minor' | 'major' | 'custom'
type Row = { name: string; info?: PackageInfo; error?: string; release: Release; version: string; range: string }
export type SimRun = { step: string; started: number; error?: string }

// Steps of a run, in order. The API emits a `simulate` event as each one starts.
export const SIM_STEPS: [string, string][] = [
  ['prepare', 'Loading the packages as they were at snapshot time'],
  ['resolve', 'Resolving every requirement on the affected packages'],
  ['blast', 'Tracing the blast radius and classifying your repos'],
  ['done', 'Opening the result'],
]

type Props = {
  incidents: Incident[]
  snapshot: string
  run: SimRun | null
  onRun: (spec: ScenarioSpec) => void
  onDismiss: () => void
  onDelete: (id: string) => Promise<void>
}

const newRow = (name: string, release: Release = 'patch'): Row => ({ name, release, version: '', range: '' })

export function Simulate({ incidents, snapshot, run, onRun, onDismiss, onDelete }: Props) {
  const [kind, setKind] = useState<ScenarioKind>('release')
  const [rows, setRows] = useState<Row[]>([])
  const [when, setWhen] = useState<'now' | 'later'>('now')
  const [at, setAt] = useState('')
  const [title, setTitle] = useState('')
  const [osv, setOsv] = useState('')
  const [summary, setSummary] = useState<string | null>(null)

  // Load each package's versions at S once, when it is added.
  useEffect(() => {
    for (const r of rows) {
      if (r.info || r.error) continue
      api.packageInfo(r.name)
        .then((info) => setRows((xs) => xs.map((x) => (x.name === r.name ? { ...x, info } : x))))
        .catch((e) => setRows((xs) => xs.map((x) => (x.name === r.name ? { ...x, error: String(e.message).replace(/^\d+: /, '') } : x))))
    }
  }, [rows])

  const add = (name: string) => setRows((xs) => (xs.some((x) => x.name === name) ? xs : [...xs, newRow(name)]))
  const update = (name: string, patch: Partial<Row>) => setRows((xs) => xs.map((x) => (x.name === name ? { ...x, ...patch } : x)))
  const remove = (name: string) => setRows((xs) => xs.filter((x) => x.name !== name))

  const template = (t: Template) => {
    setKind(t.kind)
    setRows(t.packages?.map((n) => newRow(n)) ?? [])
    setOsv(t.advisories?.join('\n') ?? '')
    setTitle(t.title ?? '')
    setWhen('now')
    setSummary(t.note ?? null)
  }

  const ready =
    kind === 'osv'
      ? osv.trim().length > 0
      : rows.length > 0 &&
        rows.every((r) => r.info && (kind === 'release' ? r.release !== 'custom' || (r.version.trim() && !r.info.versions.includes(r.version.trim())) : r.range.trim())) &&
        (kind !== 'release' || when === 'now' || !!at)
  const submit = () => {
    if (!ready || run) return
    const spec: ScenarioSpec = { kind, title: title.trim() || undefined }
    if (kind === 'osv') spec.advisories = osv.split(/[\s,]+/).filter(Boolean)
    else spec.packages = rows.map((r) => (kind === 'release' ? { name: r.name, release: r.release, version: r.version.trim() || undefined } : { name: r.name, range: r.range.trim() }))
    if (kind === 'release' && when === 'later' && at) spec.published_at = new Date(at).toISOString()
    onRun(spec)
  }

  const sims = incidents.filter((i) => i.simulated).sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))

  return (
    <>
      <PageHeader
        title="Simulate an attack"
        description={`Model a compromise that has not happened yet, or one that is happening now. Fallout runs it against the dependency graph as it was on ${snapshot || 'the snapshot date'} and shows who gets hit and what each repo must change.`}
      />
      <PageBody className="@container">
        <div className="grid items-start gap-6 @4xl:grid-cols-[minmax(0,1fr)_340px] @6xl:grid-cols-[minmax(0,1fr)_380px]">
          <section className="overflow-hidden rounded-lg border bg-card" aria-label="Scenario">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
              <div>
                <h2 className="text-sm font-semibold">New scenario</h2>
                <p className="mt-1 text-[13px] text-muted-foreground">What does the attacker do?</p>
              </div>
              <Segmented
                className="max-sm:w-full"
                label="Attack type"
                value={kind}
                onChange={(k) => { setKind(k); setSummary(null) }}
                options={[
                  { value: 'release', label: <><Crosshair className="max-sm:hidden" />Malicious<span className="max-sm:hidden"> release</span></> },
                  { value: 'versions', label: <><KeyRound className="max-sm:hidden" />Compromised<span className="max-sm:hidden"> versions</span></> },
                  { value: 'osv', label: <><Radio className="max-sm:hidden" />Live<span className="max-sm:hidden"> advisory</span></> },
                ]}
              />
            </header>

            <form className="flex flex-col" onSubmit={(e) => { e.preventDefault(); submit() }}>
              <div className="flex flex-col gap-6 px-5 py-5">
                {summary ? <p className="rounded-md border bg-muted/50 px-3 py-2 text-[13px] text-pretty text-muted-foreground">{summary}</p> : null}
                {kind === 'osv' ? (
                  <Field label="OSV advisory ids" hint="One or more MAL- or GHSA- ids. Fallout fetches the affected versions from OSV and their publish times from the npm registry.">
                    <textarea
                      value={osv}
                      onChange={(e) => setOsv(e.target.value)}
                      rows={3}
                      placeholder="MAL-2025-46969"
                      className="w-full resize-y rounded-lg border border-input bg-card px-3 py-2 font-mono text-[13px] outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
                    />
                  </Field>
                ) : (
                  <Field
                    label="Packages"
                    hint={kind === 'release' ? 'The attacker publishes a new version of each package. npm picks it for every range that allows it.' : 'Releases that already existed at snapshot time are declared compromised. Repos that resolve to one of them are exposed.'}
                  >
                    <div className="flex flex-col gap-2">
                      {rows.length ? (
                        <ul className="flex flex-col divide-y rounded-lg border">
                          {rows.map((r) => <PackageRow key={r.name} row={r} kind={kind} onChange={(p) => update(r.name, p)} onRemove={() => remove(r.name)} />)}
                        </ul>
                      ) : null}
                      <PackageSearch onPick={add} exclude={rows.map((r) => r.name)} placeholder={rows.length ? 'Add another package' : 'Search packages, such as lodash'} />
                    </div>
                  </Field>
                )}

                {kind === 'release' ? (
                  <Field label="Published" hint="Any time after the snapshot. A future time shows what would happen once the release goes out.">
                    <div className="flex flex-wrap items-center gap-3">
                      <Segmented label="Published" value={when} onChange={setWhen} options={[{ value: 'now', label: 'Now' }, { value: 'later', label: 'At a set time' }]} />
                      {when === 'later' ? (
                        <Input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} className="h-8 w-auto" aria-label="Publish time" />
                      ) : null}
                    </div>
                  </Field>
                ) : null}

                <Field label="Name" hint="Optional. Fallout names the scenario after the versions if you leave it empty.">
                  <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Scenario name" className="h-9 bg-card" />
                </Field>
              </div>

              <footer className="flex flex-wrap items-center gap-3 border-t bg-muted/30 px-5 py-3">
                <p className="min-w-0 flex-1 text-[13px] text-muted-foreground">Running a scenario changes nothing outside Fallout. Pull requests open only when you select Create PR.</p>
                <Button type="submit" size="lg" disabled={!ready || !!run}>
                  <Play data-icon="inline-start" />
                  Run simulation
                </Button>
              </footer>
            </form>

            {run ? <Progress run={run} onDismiss={onDismiss} /> : null}
          </section>

          <aside className="flex flex-col gap-6">
            <Templates onPick={template} disabled={!!run} />
            <section className="overflow-hidden rounded-lg border bg-card" aria-label="Your scenarios">
              <header className="border-b px-5 py-4">
                <h2 className="text-sm font-semibold">Your scenarios</h2>
                <p className="mt-1 text-[13px] text-muted-foreground">Open one to see its blast radius and response plan. Each has its own link you can share or bookmark.</p>
              </header>
              {sims.length ? (
                <ul className="divide-y">
                  {sims.map((s) => <ScenarioItem key={s.id} incident={s} onDelete={() => onDelete(s.id)} />)}
                </ul>
              ) : (
                <p className="px-5 py-6 text-[13px] text-muted-foreground">No scenarios yet. Run one, or start from a template above.</p>
              )}
            </section>
          </aside>
        </div>
      </PageBody>
    </>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <div>
        <div className="text-[13px] font-medium">{label}</div>
        {hint ? <p className="mt-0.5 max-w-[68ch] text-xs text-pretty text-muted-foreground">{hint}</p> : null}
      </div>
      {children}
    </div>
  )
}

function PackageRow({ row, kind, onChange, onRemove }: { row: Row; kind: ScenarioKind; onChange: (p: Partial<Row>) => void; onRemove: () => void }) {
  const { info } = row
  const target = info ? (row.release === 'custom' ? row.version || '…' : info.next[row.release]) : null
  const [matches, setMatches] = useState<string[] | null>(null)
  const [rangeErr, setRangeErr] = useState<string | null>(null)

  useEffect(() => {
    if (kind !== 'versions' || !row.range.trim()) { setMatches(null); setRangeErr(null); return }
    const t = window.setTimeout(() => {
      api.matchingVersions(row.name, row.range.trim())
        .then((xs) => { setMatches(xs.map((x) => x.version)); setRangeErr(null) })
        .catch((e) => { setMatches(null); setRangeErr(String(e.message).replace(/^\d+: /, '')) })
    }, 250)
    return () => window.clearTimeout(t)
  }, [kind, row.name, row.range])

  return (
    <li className="flex flex-col gap-3 px-3 py-3 sm:px-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="truncate font-mono text-[13px] font-medium">{row.name}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {row.error ? <span className="text-hot">{row.error}</span> : info ? (
              <>Latest at snapshot <span className="font-mono text-foreground">{info.latest}</span>, {compact(info.downloads)} weekly downloads, {info.dependents.toLocaleString()} direct dependents</>
            ) : <span className="inline-block h-3 w-56 animate-pulse rounded bg-muted align-middle" />}
          </div>
        </div>
        <Button type="button" variant="ghost" size="icon-sm" onClick={onRemove} aria-label={`Remove ${row.name}`}><X /></Button>
      </div>
      {info && kind === 'release' ? (
        <div className="flex flex-wrap items-center gap-3">
          <Segmented
            label={`New version of ${row.name}`}
            value={row.release}
            onChange={(r) => onChange({ release: r })}
            options={[{ value: 'patch', label: 'Next patch' }, { value: 'minor', label: 'Next minor' }, { value: 'major', label: 'Next major' }, { value: 'custom', label: 'Custom' }]}
          />
          {row.release === 'custom' ? (
            <Input value={row.version} onChange={(e) => onChange({ version: e.target.value })} placeholder={info.next.patch} className="h-8 w-32 font-mono" aria-label={`Version of ${row.name}`} />
          ) : null}
          <span className="font-mono text-xs text-muted-foreground">
            {info.latest} <ChevronRight className="inline size-3" aria-label="becomes" /> <span className="font-medium text-hot">{target}</span>
          </span>
          {row.release === 'custom' && info.versions.includes(row.version.trim()) ? (
            <p className="w-full text-xs text-hot">{row.version.trim()} already existed at snapshot time. Choose a new version, or use Compromised versions.</p>
          ) : row.release === 'custom' && row.version.includes('-') ? (
            <p className="w-full text-xs text-warn">npm skips prerelease versions unless a range names one, so this release probably reaches no one.</p>
          ) : row.release === 'major' ? (
            <p className="w-full text-xs text-muted-foreground">A new major only reaches ranges such as * or &gt;=, because ^ and ~ stay within their major.</p>
          ) : null}
        </div>
      ) : null}
      {info && kind === 'versions' ? (
        <div className="flex flex-col gap-1.5">
          <Input value={row.range} onChange={(e) => onChange({ range: e.target.value })} placeholder={`>=${info.versions[Math.min(2, info.versions.length - 1)]} <=${info.latest}`} className="h-8 font-mono" aria-label={`Compromised range of ${row.name}`} />
          <p className={cn('text-xs', rangeErr ? 'text-hot' : 'text-muted-foreground')}>
            {rangeErr ?? (matches == null ? 'A semver range of releases that existed at snapshot time.' : matches.length ? `Matches ${matches.length} release${matches.length === 1 ? '' : 's'}: ${matches.slice(0, 6).join(', ')}${matches.length > 6 ? ', …' : ''}` : 'No release at snapshot time matches this range.')}
          </p>
        </div>
      ) : null}
    </li>
  )
}

type Template = { id: string; kind: ScenarioKind; title?: string; packages?: string[]; advisories?: string[]; note?: string }

function Templates({ onPick, disabled }: { onPick: (t: Template) => void; disabled: boolean }) {
  const [maint, setMaint] = useState<{ maintainer: string; reach: number; packages: string[] } | null>(null)
  const [central, setCentral] = useState<string | null>(null)
  useEffect(() => {
    api.maintainerTemplate().then(setMaint).catch(() => setMaint(null))
    api.tool<{ packages: { package: string }[] }>('critical_packages', { k: 1, algorithm: 'pagerank' }).then((e) => setCentral(e.result.packages?.[0]?.package ?? null)).catch(() => setCentral(null))
  }, [])

  const items: (Template & { icon: ReactNode; label: string; detail: string })[] = []
  if (maint)
    items.push({
      id: 'maint', kind: 'release', icon: <KeyRound />, label: 'Phished maintainer account',
      detail: `The account with the widest reach (${maint.reach.toLocaleString()} packages) publishes malicious patches of its ${maint.packages.length} most-downloaded packages.`,
      title: `Takeover of the ${maint.maintainer} account`, packages: maint.packages,
      note: `Same pattern as the September 2025 attack: one phished account, a malicious patch release of each package it publishes.`,
    })
  if (central)
    items.push({ id: 'central', kind: 'release', icon: <Network />, label: 'Most central package', detail: `A malicious patch of ${central}, the package with the highest PageRank in the graph.`, packages: [central] })
  items.push({ id: 'react', kind: 'release', icon: <Crosshair />, label: 'Malicious react release', detail: 'A malicious patch of react, published now.', packages: ['react'] })
  items.push({ id: 'osv', kind: 'osv', icon: <Radio />, label: 'Live OSV advisory', detail: 'Pull a real advisory from OSV by id and trace it through the graph.', advisories: ['MAL-2025-46969'] })

  return (
    <section className="overflow-hidden rounded-lg border bg-card" aria-label="Templates">
      <header className="border-b px-5 py-4">
        <h2 className="text-sm font-semibold">Start from a template</h2>
        <p className="mt-1 text-[13px] text-muted-foreground">Fills in the form. Nothing runs until you select Run simulation.</p>
      </header>
      <ul className="divide-y">
        {items.map((t) => (
          <li key={t.id}>
            <button type="button" disabled={disabled} onClick={() => onPick(t)} className="flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors hover:bg-muted/50 disabled:opacity-50 [&>svg]:mt-0.5 [&>svg]:size-4 [&>svg]:shrink-0 [&>svg]:text-muted-foreground">
              {t.icon}
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-medium">{t.label}</span>
                <span className="mt-0.5 block text-xs text-pretty text-muted-foreground">{t.detail}</span>
              </span>
              <ChevronRight className="text-muted-foreground/60" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

const ago = (ms: number | null) => {
  if (!ms) return ''
  const s = Math.max(0, (Date.now() - ms) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return new Date(ms).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

function ScenarioItem({ incident, onDelete }: { incident: Incident; onDelete: () => Promise<void> }) {
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const sc = parseScenario(incident)
  const label = sc?.kind === 'osv' ? 'Live advisory' : sc?.kind === 'versions' ? 'Compromised versions' : 'Malicious release'
  return (
    <li className="group relative flex items-start gap-3 px-5 py-3.5 transition-colors hover:bg-muted/50">
      <a href={href('overview', incident.id)} className="min-w-0 flex-1 text-left after:absolute after:inset-0 focus-visible:outline-none after:focus-visible:ring-2 after:focus-visible:ring-ring after:focus-visible:ring-inset">
        <span className="block truncate text-[13px] font-medium">{incident.title}</span>
        <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
          <span>{label}</span>
          <span className="tabular">{incident.exposed == null ? 'Not computed' : `${incident.exposed.toLocaleString()} exposed`}</span>
          <span className="flex items-center gap-1"><Clock className="size-3" aria-hidden />{ago(incident.created_at)}</span>
        </span>
      </a>
      <div className="relative z-10 flex items-center gap-1">
        {confirm ? (
          <>
            <Button size="xs" variant="destructive" disabled={busy} onClick={async () => { setBusy(true); await onDelete().finally(() => setBusy(false)); setConfirm(false) }}>
              {busy ? 'Deleting…' : 'Delete'}
            </Button>
            <Button size="xs" variant="ghost" onClick={() => setConfirm(false)}>Keep</Button>
          </>
        ) : (
          <Button size="icon-sm" variant="ghost" className="text-muted-foreground hover:text-hot" onClick={() => setConfirm(true)} aria-label={`Delete ${incident.title}`} title="Delete scenario"><Trash2 /></Button>
        )}
      </div>
    </li>
  )
}

function Progress({ run, onDismiss }: { run: SimRun; onDismiss: () => void }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (run.error) return
    const t = window.setInterval(() => setNow(Date.now()), 100)
    return () => window.clearInterval(t)
  }, [run.error])
  const at = SIM_STEPS.findIndex(([k]) => k === run.step)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-6 animate-in fade-in duration-200 dark:bg-black/60" role="dialog" aria-modal="true" aria-label="Simulation progress">
      <div className="w-full max-w-md rounded-xl border bg-popover p-5 shadow-xl animate-in zoom-in-95 duration-200" role="status" aria-live="polite">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-sm font-semibold">{run.error ? 'The simulation did not run' : 'Running the simulation'}</h3>
          <span className="font-mono text-xs text-muted-foreground tabular">{((now - run.started) / 1000).toFixed(1)}s</span>
        </div>
        <ol className="mt-4 flex flex-col gap-3">
          {SIM_STEPS.map(([key, label], i) => {
            const state = run.error ? (i < at ? 'done' : i === at ? 'error' : 'todo') : i < at ? 'done' : i === at ? 'active' : 'todo'
            return (
              <li key={key} className="flex items-center gap-3 text-[13px]">
                <span className={cn('flex size-5 shrink-0 items-center justify-center rounded-full border [&_svg]:size-3', state === 'done' && 'border-transparent bg-safe text-white dark:text-background', state === 'active' && 'border-foreground/30', state === 'error' && 'border-transparent bg-hot text-white dark:text-background')}>
                  {state === 'done' ? <Check /> : state === 'active' ? <Loader2 className="animate-spin" /> : state === 'error' ? <X /> : null}
                </span>
                <span className={cn(state === 'todo' && 'text-muted-foreground')}>{label}</span>
              </li>
            )
          })}
        </ol>
        {run.error ? (
          <div className="mt-4 flex flex-col gap-3">
            <p className="rounded-md border border-hot/30 bg-hot/5 px-3 py-2 text-[13px] text-pretty text-hot">{run.error}</p>
            <Button variant="outline" className="self-end" onClick={onDismiss}>Edit the scenario</Button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
