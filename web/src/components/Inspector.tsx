import type { Path } from '../api'
import { short } from '../api'

export type Selection = {
  key: string
  kind: 'Version' | 'Repo'
  title: string
  status?: string
  meaning?: string
  paths: (Path & { package?: string; mitigated?: boolean })[]
  error?: string
}

type Props = { sel: Selection; pathId: string | null; onPath: (id: string) => void; onClose: () => void }

export function Chain({ path }: { path: Path }) {
  const last = path.nodes.length - 1
  return (
    <ol className="chain">
      {path.nodes.map((n, i) => {
        const next = path.edges[i]
        const cls = n.startsWith('repo:') ? 'root' : i === last && last > 0 ? 'bad' : ''
        return (
          <li key={`${n}-${i}`} className={cls}>
            <span className="rail" aria-hidden />
            <span className="node">{short(n)}</span>
            {next ? (
              <span className={`req ${next.type === 'CAN_RESOLVE_TO' ? 'crt' : ''}`}>
                {next.type === 'CAN_RESOLVE_TO'
                  ? `requires ${next.requirement}, npm would pick the malicious release`
                  : `requires ${next.requirement ?? '?'}${next.type === 'DIRECT_DEP' ? ' (direct dependency)' : ''}`}
              </span>
            ) : <span />}
          </li>
        )
      })}
    </ol>
  )
}

export function Inspector({ sel, pathId, onPath, onClose }: Props) {
  const path = sel.paths.find((p) => p.id === pathId) ?? sel.paths[0]
  return (
    <section className="inspector" aria-label="Exposure path">
      <header>
        <h2>{sel.title}</h2>
        {sel.status ? <span className="status" data-s={sel.status}>{sel.status.replaceAll('_', ' ').toLowerCase()}</span> : null}
        <button className="btn quiet close" onClick={onClose}>Close</button>
      </header>
      {sel.meaning ? <p className="meaning">{sel.meaning}</p> : null}
      {sel.error ? <p className="meaning">{sel.error}</p> : null}
      {sel.paths.length > 1 ? (
        <div className="pathsel" role="group" aria-label="Affected package">
          {sel.paths.map((p) => (
            <button key={p.id} aria-pressed={p.id === path?.id} onClick={() => onPath(p.id)}>
              {p.package ?? short(p.nodes[p.nodes.length - 1])}
              {p.mitigated ? <span className="m">, mitigated</span> : null}
            </button>
          ))}
        </div>
      ) : null}
      {path ? (
        <>
          <Chain path={path} />
          <div className="pid">path <span className="id">{path.id}</span>, {path.edges.length} hops, every requirement as declared at S</div>
        </>
      ) : !sel.error ? (
        <p className="meaning">Not reached: no requirement on this tree would pick an affected version.</p>
      ) : null}
    </section>
  )
}
