import { useEffect, useState } from 'react'
import { api } from '../api'

type Pkg = { package: string; pagerank: number; betweenness: number; downloads: number | null; maintainers: number | null; has_provenance: boolean | null }
type Maint = { maintainer: string; reach_packages: number; reach_downloads: number; packages_maintained: number; sole_maintainer_count: number }

const compact = (n: number | null | undefined) =>
  n == null ? '—' : Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n)

export function Ecosystem() {
  const [algo, setAlgo] = useState<'pagerank' | 'betweenness'>('pagerank')
  const [pkgs, setPkgs] = useState<Pkg[]>([])
  const [maint, setMaint] = useState<Maint[]>([])
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.tool<{ packages: Pkg[] }>('critical_packages', { k: 15, algorithm: algo }).then((e) => setPkgs(e.result.packages ?? [])).catch((e) => setErr(String(e)))
  }, [algo])
  useEffect(() => {
    api.tool<{ maintainers: Maint[] }>('maintainer_reach', { k: 10 }).then((e) => setMaint(e.result.maintainers ?? [])).catch((e) => setErr(String(e)))
  }, [])

  const top = Math.max(...pkgs.map((p) => p[algo] ?? 0), 1e-12)
  const topReach = Math.max(...maint.map((m) => m.reach_packages), 1)
  return (
    <>
      <h3>Chokepoint packages</h3>
      <p className="note">
        Centrality over the package dependency graph as it stood at S, computed in FalkorDB with <code>algo.pageRank</code> and <code>algo.betweenness</code>.
      </p>
      <div className="seg" role="group" aria-label="Algorithm">
        <button aria-pressed={algo === 'pagerank'} onClick={() => setAlgo('pagerank')}>PageRank</button>
        <button aria-pressed={algo === 'betweenness'} onClick={() => setAlgo('betweenness')}>Betweenness</button>
      </div>
      {err ? <p className="note">{err}</p> : null}
      <table className="data">
        <thead><tr><th>Package</th><th className="num">Score</th><th className="num">Weekly</th><th className="num">Maint.</th></tr></thead>
        <tbody>
          {pkgs.map((p) => (
            <tr key={p.package}>
              <td><code>{p.package}</code><span className="meter" style={{ width: `${(100 * (p[algo] ?? 0)) / top}%` }} /></td>
              <td className="num">{algo === 'pagerank' ? (p.pagerank * 1000).toFixed(2) : compact(p.betweenness)}</td>
              <td className="num">{compact(p.downloads)}</td>
              <td className="num">{p.maintainers ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {algo === 'pagerank' ? <p className="note">PageRank shown ×1000.</p> : null}

      <h3>Maintainer reach</h3>
      <p className="note">
        How many packages a single account takeover would reach through dependencies, and their weekly downloads. A measure of concentration risk in the ecosystem, not of any person.
      </p>
      <table className="data">
        <thead><tr><th>Account</th><th className="num">Reach</th><th className="num">Weekly</th><th className="num">Sole maint.</th></tr></thead>
        <tbody>
          {maint.map((m) => (
            <tr key={m.maintainer}>
              <td>{m.maintainer}<span className="meter" style={{ width: `${(100 * m.reach_packages) / topReach}%`, background: 'var(--hot)' }} /></td>
              <td className="num">{m.reach_packages.toLocaleString()}</td>
              <td className="num">{compact(m.reach_downloads)}</td>
              <td className="num">{m.sole_maintainer_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

const SYS: Record<string, string> = { A: 'LLM only', B: 'LLM + lockfile', C: 'Fallout agent', G: 'Graph tools only' }
const pct = (v: number | null | undefined) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)
const f3 = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(3))

export function Metrics() {
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { api.results().then(setRes).catch((e) => setErr(String(e))) }, [])
  if (err) return <p className="note">{err}</p>
  if (!res) return <p className="note">Loading eval results…</p>
  const s = res.summary as Record<string, any>
  return (
    <>
      <h3>Measured against npm itself</h3>
      <p className="note">
        {res.config.n_pairs} sampled questions of the form “as of S, is this target exposed, and through which path?”, over {res.config.n_units} advisory sets.
        Ground truth is npm's own resolver (arborist) at S, which never reads FalkorDB. Model <code>{res.config.model}</code>.
      </p>
      <table className="data">
        <thead><tr><th>System</th><th className="num">Recall</th><th className="num">F1</th><th className="num">Made-up nodes</th><th className="num">Valid paths</th></tr></thead>
        <tbody>
          {Object.keys(SYS).filter((k) => s[k]).map((k) => (
            <tr key={k} className={k === 'C' ? 'ours' : ''}>
              <td>{SYS[k]}</td>
              <td className="num">{f3(s[k].recall)}</td>
              <td className="num">{f3(s[k].f1)}</td>
              <td className="num">{pct(s[k].hallucinated_node_rate)}</td>
              <td className="num">{pct(s[k].path_validity)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Latency and cost per question</h3>
      <table className="data">
        <thead><tr><th>System</th><th className="num">p50</th><th className="num">p95</th><th className="num">Tokens in</th><th className="num">Cost</th></tr></thead>
        <tbody>
          {Object.keys(SYS).filter((k) => s[k]).map((k) => (
            <tr key={k}>
              <td>{SYS[k]}</td>
              <td className="num">{(s[k].latency_p50_ms / 1000).toFixed(1)}s</td>
              <td className="num">{(s[k].latency_p95_ms / 1000).toFixed(1)}s</td>
              <td className="num">{Math.round(s[k].tokens_in_per_q ?? 0).toLocaleString()}</td>
              <td className="num">{s[k].cost_usd_per_q == null ? '—' : `$${s[k].cost_usd_per_q.toFixed(4)}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">Run <code>{res.run_id}</code>. Full table, disagreements and every prompt: <code>eval/results.md</code>.</p>
    </>
  )
}
