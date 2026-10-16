import { cn } from '@/lib/utils'
import type { Path } from '../api'
import { short } from '../api'

// One dependency path, from the repo (top) down to the affected version (bottom).
export function Chain({ path }: { path: Path }) {
  const last = path.nodes.length - 1
  return (
    <ol className="relative">
      {path.nodes.map((n, i) => {
        const next = path.edges[i]
        const root = n.startsWith('repo:')
        const bad = i === last && last > 0
        return (
          <li key={`${n}-${i}`} className="relative grid grid-cols-[16px_minmax(0,1fr)] gap-x-3">
            <span className="relative flex justify-center" aria-hidden>
              {i < last ? <span className="absolute top-3 bottom-0 w-px bg-border" /> : null}
              <span className={cn('relative mt-1.5 size-2.5 rounded-full border-2 border-background ring-1', root ? 'rounded-[3px] bg-foreground ring-foreground' : bad ? 'bg-hot ring-hot' : 'bg-steel ring-steel')} />
            </span>
            <div className={cn('min-w-0 pb-3', i === last && 'pb-0')}>
              <div className={cn('truncate font-mono text-[13px] leading-6', bad && 'font-medium text-hot', root && 'font-medium')}>{short(n)}</div>
              {next ? (
                <div className={cn('font-mono text-xs leading-5 text-muted-foreground', next.type === 'CAN_RESOLVE_TO' && 'text-hot')}>
                  {next.type === 'CAN_RESOLVE_TO'
                    ? `requires ${next.requirement}, which npm resolves to the malicious version`
                    : `requires ${next.requirement ?? '?'}${next.type === 'DIRECT_DEP' ? ' (direct dependency)' : ''}`}
                </div>
              ) : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
