import type { IncidentGraph } from '../api'
import { hopColor } from '../hop'

type Props = { data: IncidentGraph | null; reveal: number; busy: string | null }

export function Wave({ data, reveal, busy }: Props) {
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
  const packages = new Set(
    (data?.nodes ?? []).filter((n) => n.kind === 'Version' && n.hop <= reveal).map((n) => n.key.replace(/^npm:/, '').replace(/@[^@]+$/, '')),
  ).size

  return (
    <section className="wave" aria-label="Blast radius by hop">
      <div className="tally" aria-live="polite">
        <div><b>{data?.affected.length ?? 0}</b><span>Malicious versions</span></div>
        <div><b>{versions.toLocaleString()}</b><span>Exposed versions</span></div>
        <div><b>{packages.toLocaleString()}</b><span>Exposed packages</span></div>
        <div><b>{repos}</b><span>Your repos exposed</span></div>
      </div>
      <div className="bands">
        {busy && !data?.nodes.length ? <span className="lbl">{busy}</span> : null}
        {[...Array(maxHop).keys()].map((i) => {
          const hop = i + 1
          const h = hops.get(hop) ?? { versions: 0, repos: 0 }
          const height = 8 + 44 * Math.sqrt(h.versions / peak)
          return (
            <div className="band" key={hop} data-on={hop <= reveal}>
              <b className="count">{h.versions.toLocaleString()}</b>
              <div className="bar" style={{ height, background: hopColor(hop, maxHop) }} />
              <div className="lbl">
                <span>Hop {hop}</span>
                {h.repos ? <span className="repos">+{h.repos} repo{h.repos > 1 ? 's' : ''}</span> : null}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
