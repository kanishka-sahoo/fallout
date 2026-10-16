import { cn } from '@/lib/utils'
import { statusLabel } from '../api'

// Severity order, worst first. The tone is the only colour a repo row carries.
export const STATUS_ORDER = ['LOCKED_MALICIOUS', 'EXPOSED_NO_LOCKFILE', 'RANGE_ADMITS_LOCK_SAFE', 'MITIGATED_BY_OVERRIDE', 'NOT_AFFECTED']

const TONE: Record<string, string> = {
  LOCKED_MALICIOUS: 'bg-hot text-white dark:text-background [&>i]:bg-current',
  EXPOSED_NO_LOCKFILE: 'bg-hot/10 text-hot [&>i]:bg-hot',
  RANGE_ADMITS_LOCK_SAFE: 'bg-warn/10 text-warn [&>i]:bg-warn',
  MITIGATED_BY_OVERRIDE: 'bg-safe/10 text-safe [&>i]:bg-safe',
  NOT_AFFECTED: 'bg-muted text-muted-foreground [&>i]:bg-muted-foreground/60',
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <span className={cn('inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium whitespace-nowrap', TONE[status] ?? TONE.NOT_AFFECTED, className)}>
      <i className="size-1.5 rounded-full" aria-hidden />
      {statusLabel(status)}
    </span>
  )
}

const DOT: Record<string, string> = {
  LOCKED_MALICIOUS: 'var(--hot)',
  EXPOSED_NO_LOCKFILE: 'var(--hot)',
  RANGE_ADMITS_LOCK_SAFE: 'var(--warn)',
  MITIGATED_BY_OVERRIDE: 'var(--safe)',
}

export function StatusDot({ status }: { status: string }) {
  return <span className="size-2 shrink-0 rounded-full" style={{ background: DOT[status] ?? 'var(--muted-foreground)' }} aria-hidden />
}
