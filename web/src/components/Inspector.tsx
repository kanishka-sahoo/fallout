import { cn } from '@/lib/utils'
import type { Path } from '../api'
import { short } from '../api'
import { Chain } from './Chain'

export type Selection = {
  key: string
  kind: 'Version' | 'Repo'
  title: string
  status?: string
  meaning?: string
  paths: (Path & { package?: string; mitigated?: boolean })[]
  error?: string
  loading?: boolean
}

// Status meaning, a package picker when several affected packages are reached, and the path.
export function PathDetail({ sel, pathId, onPath }: { sel: Selection; pathId: string | null; onPath: (id: string) => void }) {
  const path = sel.paths.find((p) => p.id === pathId) ?? sel.paths[0]
  return (
    <div className="flex flex-col gap-4">
      {sel.meaning ? <p className="text-[13px] text-pretty text-muted-foreground first-letter:uppercase">{sel.meaning}</p> : null}
      {sel.error ? <p className="rounded-md border border-hot/30 bg-hot/5 px-3 py-2 text-[13px] text-hot">{sel.error}</p> : null}
      {sel.paths.length > 1 ? (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-muted-foreground">Affected package</span>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Affected package">
            {sel.paths.map((p) => (
              <button
                key={p.id}
                aria-pressed={p.id === path?.id}
                onClick={() => onPath(p.id)}
                className={cn(
                  'h-7 rounded-md border px-2.5 font-mono text-xs transition-colors hover:bg-accent',
                  p.id === path?.id && 'border-foreground bg-foreground text-background hover:bg-foreground',
                  p.mitigated && 'text-muted-foreground line-through decoration-muted-foreground/60',
                  p.mitigated && p.id === path?.id && 'text-background/70',
                )}
                title={p.mitigated ? 'Mitigated by an override' : undefined}
              >
                {p.package ?? short(p.nodes[p.nodes.length - 1])}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {path ? (
        <>
          <div className="rounded-lg border bg-muted/40 p-4">
            <Chain path={path} />
          </div>
          <p className="text-xs text-muted-foreground">
            Path <code className="text-foreground">{path.id}</code>, {path.edges.length} hop{path.edges.length === 1 ? '' : 's'}. Requirements as declared at snapshot time.
          </p>
        </>
      ) : sel.loading ? (
        <div className="flex flex-col gap-2" aria-label="Loading">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-9 animate-pulse rounded-md bg-muted" />)}
        </div>
      ) : !sel.error ? (
        <p className="text-[13px] text-muted-foreground">Not reached. No requirement in this dependency tree resolves to an affected version.</p>
      ) : null}
    </div>
  )
}
