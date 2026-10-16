import { useEffect, useState } from 'react'
import { api } from '../api'
import { PageBody, PageHeader, Section } from '../components/Page'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { cn } from '@/lib/utils'

type Pkg = { package: string; pagerank: number; betweenness: number; downloads: number | null; maintainers: number | null; has_provenance: boolean | null }
type Maint = { maintainer: string; reach_packages: number; reach_downloads: number; packages_maintained: number; sole_maintainer_count: number }

const compact = (n: number | null | undefined) => (n == null ? '—' : Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n))

function Meter({ value, color = 'var(--foreground)' }: { value: number; color?: string }) {
  return (
    <span className="mt-1.5 block h-1 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
      <span className="block h-full rounded-full opacity-70" style={{ width: `${Math.max(2, value * 100)}%`, background: color }} />
    </span>
  )
}

function Loading({ rows = 8, cols }: { rows?: number; cols: number }) {
  return (
    <>
      {[...Array(rows).keys()].map((i) => (
        <TableRow key={i} className="hover:bg-transparent">
          {[...Array(cols).keys()].map((j) => (
            <TableCell key={j} className={j === 0 ? 'pl-5' : ''}>
              <div className="h-4 animate-pulse rounded bg-muted" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  )
}

const ErrorRow = ({ cols, text }: { cols: number; text: string }) => (
  <TableRow className="hover:bg-transparent">
    <TableCell colSpan={cols} className="py-8 text-center text-hot">
      {text}
    </TableCell>
  </TableRow>
)

export function Ecosystem() {
  const [algo, setAlgo] = useState<'pagerank' | 'betweenness'>('pagerank')
  const [pkgs, setPkgs] = useState<Pkg[] | null>(null)
  const [maint, setMaint] = useState<Maint[] | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    setPkgs(null)
    api
      .tool<{ packages: Pkg[] }>('critical_packages', { k: 15, algorithm: algo })
      .then((e) => setPkgs(e.result.packages ?? []))
      .catch((e) => setErr(String(e)))
  }, [algo])
  useEffect(() => {
    api
      .tool<{ maintainers: Maint[] }>('maintainer_reach', { k: 10 })
      .then((e) => setMaint(e.result.maintainers ?? []))
      .catch((e) => setErr(String(e)))
  }, [])

  const top = Math.max(...(pkgs ?? []).map((p) => p[algo] ?? 0), 1e-12)
  const topReach = Math.max(...(maint ?? []).map((m) => m.reach_packages), 1)
  return (
    <>
      <PageHeader title="Ecosystem" description="Where the npm dependency graph concentrates risk at snapshot time. These numbers do not depend on the incident you have selected." />
      <PageBody>
        <div className="grid items-start gap-6 2xl:grid-cols-2">
          <Section
            title="Critical packages"
            description={
              <>
                Centrality in the package dependency graph, computed in FalkorDB with <code>algo.pageRank</code> and <code>algo.betweenness</code>.
              </>
            }
            actions={
              <ToggleGroup value={[algo]} onValueChange={(v) => v[0] && setAlgo(v[0] as typeof algo)} variant="outline" size="sm" spacing={0} aria-label="Algorithm">
                <ToggleGroupItem value="pagerank" className="px-3">
                  PageRank
                </ToggleGroupItem>
                <ToggleGroupItem value="betweenness" className="px-3">
                  Betweenness
                </ToggleGroupItem>
              </ToggleGroup>
            }
          >
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-8 pl-5 text-right">#</TableHead>
                  <TableHead>Package</TableHead>
                  <TableHead className="text-right" title={algo === 'pagerank' ? 'PageRank × 1000' : undefined}>
                    {algo === 'pagerank' ? 'PageRank ×1000' : 'Betweenness'}
                  </TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Weekly downloads</TableHead>
                  <TableHead className="hidden pr-5 text-right md:table-cell">Maintainers</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {err && !pkgs ? (
                  <ErrorRow cols={5} text={err} />
                ) : !pkgs ? (
                  <Loading cols={5} />
                ) : (
                  pkgs.map((p, i) => (
                    <TableRow key={p.package}>
                      <TableCell className="pl-5 text-right text-muted-foreground tabular">{i + 1}</TableCell>
                      <TableCell className="w-1/2">
                        <code>{p.package}</code>
                        <Meter value={(p[algo] ?? 0) / top} />
                      </TableCell>
                      <TableCell className="text-right tabular">{algo === 'pagerank' ? (p.pagerank * 1000).toFixed(2) : compact(p.betweenness)}</TableCell>
                      <TableCell className="hidden text-right tabular sm:table-cell">{compact(p.downloads)}</TableCell>
                      <TableCell className="hidden pr-5 text-right tabular md:table-cell">{p.maintainers ?? '—'}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </Section>

          <Section
            title="Maintainer reach"
            description="How many packages one compromised maintainer account can reach through dependencies. This shows concentration risk. It does not rate any person."
          >
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-5">Account</TableHead>
                  <TableHead className="text-right">Packages reached</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Weekly downloads</TableHead>
                  <TableHead className="pr-5 text-right">Sole maintainer of</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {err && !maint ? (
                  <ErrorRow cols={4} text={err} />
                ) : !maint ? (
                  <Loading cols={4} />
                ) : (
                  maint.map((m) => (
                    <TableRow key={m.maintainer}>
                      <TableCell className="w-1/2 pl-5">
                        {m.maintainer}
                        <Meter value={m.reach_packages / topReach} color="var(--hot)" />
                      </TableCell>
                      <TableCell className="text-right tabular">{m.reach_packages.toLocaleString()}</TableCell>
                      <TableCell className="hidden text-right tabular sm:table-cell">{compact(m.reach_downloads)}</TableCell>
                      <TableCell className="pr-5 text-right tabular">{m.sole_maintainer_count}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </Section>
        </div>
      </PageBody>
    </>
  )
}

const SYS: Record<string, string> = { A: 'LLM only', B: 'LLM + lockfile', C: 'Fallout agent', G: 'Graph tools only' }
const pct = (v: number | null | undefined) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)
const f3 = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(3))

export function Evaluation() {
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api
      .results()
      .then(setRes)
      .catch((e) => setErr(String(e)))
  }, [])
  const s = (res?.summary ?? {}) as Record<string, any>
  const keys = Object.keys(SYS).filter((k) => s[k])
  return (
    <>
      <PageHeader
        title="Evaluation"
        description={
          res ? (
            <>
              {res.config.n_pairs} sampled questions across {res.config.n_units} advisory groups. Each asks whether a target is exposed at snapshot time, and through which path. Ground truth is the
              npm resolver (Arborist), which does not read FalkorDB. Model <code>{res.config.model}</code>.
            </>
          ) : (
            (err ?? 'Loading evaluation results…')
          )
        }
      />
      <PageBody>
        {s.C && s.A ? (
          <dl className="grid overflow-hidden rounded-lg border bg-card grid-cols-2 xl:grid-cols-4" aria-label="Fallout agent compared with an LLM alone">
            {(
              [
                ['Recall', f3(s.C.recall), f3(s.A.recall)],
                ['Hallucinated packages', pct(s.C.hallucinated_node_rate), pct(s.A.hallucinated_node_rate)],
                ['Path validity', pct(s.C.path_validity), pct(s.A.path_validity)],
                ['Median latency', `${(s.C.latency_p50_ms / 1000).toFixed(1)}s`, `${(s.A.latency_p50_ms / 1000).toFixed(1)}s`],
              ] as const
            ).map(([label, ours, base]) => (
              <div key={label} className="flex flex-col gap-1.5 px-5 py-4 nth-[-n+2]:border-b nth-[odd]:border-r xl:border-r xl:nth-[-n+2]:border-b-0 xl:last:border-r-0">
                <dt className="text-[13px] text-muted-foreground">{label}</dt>
                <dd className="figure text-[28px] leading-none font-semibold">{ours}</dd>
                <dd className="text-xs text-muted-foreground">{base} for LLM only</dd>
              </div>
            ))}
          </dl>
        ) : null}
        <Section title="Accuracy against the npm resolver" description="Higher is better, except hallucinated packages.">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">System</TableHead>
                <TableHead className="text-right">Recall</TableHead>
                <TableHead className="hidden text-right sm:table-cell">F1</TableHead>
                <TableHead className="text-right">Hallucinated packages</TableHead>
                <TableHead className="hidden pr-5 text-right sm:table-cell">Path validity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {err && !res ? (
                <ErrorRow cols={5} text={err} />
              ) : !res ? (
                <Loading rows={4} cols={5} />
              ) : (
                keys.map((k) => (
                  <TableRow key={k} className={cn(k === 'C' && 'bg-muted/50 font-semibold')}>
                    <TableCell className="pl-5">{SYS[k]}</TableCell>
                    <TableCell className="text-right tabular">{f3(s[k].recall)}</TableCell>
                    <TableCell className="hidden text-right tabular sm:table-cell">{f3(s[k].f1)}</TableCell>
                    <TableCell className={cn('text-right tabular', s[k].hallucinated_node_rate > 0 && 'text-hot')}>{pct(s[k].hallucinated_node_rate)}</TableCell>
                    <TableCell className="hidden pr-5 text-right tabular sm:table-cell">{pct(s[k].path_validity)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </Section>
        <Section title="Latency and cost per question">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">System</TableHead>
                <TableHead className="text-right">p50</TableHead>
                <TableHead className="hidden text-right sm:table-cell">p95</TableHead>
                <TableHead className="hidden text-right sm:table-cell">Tokens in</TableHead>
                <TableHead className="pr-5 text-right">Cost</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {err && !res ? (
                <ErrorRow cols={5} text={err} />
              ) : !res ? (
                <Loading rows={4} cols={5} />
              ) : (
                keys.map((k) => (
                  <TableRow key={k} className={cn(k === 'C' && 'bg-muted/50 font-semibold')}>
                    <TableCell className="pl-5">{SYS[k]}</TableCell>
                    <TableCell className="text-right tabular">{(s[k].latency_p50_ms / 1000).toFixed(1)}s</TableCell>
                    <TableCell className="hidden text-right tabular sm:table-cell">{(s[k].latency_p95_ms / 1000).toFixed(1)}s</TableCell>
                    <TableCell className="hidden text-right tabular sm:table-cell">{Math.round(s[k].tokens_in_per_q ?? 0).toLocaleString()}</TableCell>
                    <TableCell className="pr-5 text-right tabular">{s[k].cost_usd_per_q == null ? '—' : `$${s[k].cost_usd_per_q.toFixed(4)}`}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </Section>
        {res ? (
          <p className="text-xs text-muted-foreground">
            Run <code>{res.run_id}</code>. The full table, disagreements and every prompt are in <code>eval/results.md</code>.
          </p>
        ) : null}
      </PageBody>
    </>
  )
}
