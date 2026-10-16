import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import type { Plan } from '../api'
import { cn } from '@/lib/utils'

type Changes = Plan['body']['changes']

// Copies text and shows a check for a moment.
export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={() => navigator.clipboard.writeText(text).then(() => { setDone(true); window.setTimeout(() => setDone(false), 1400) })}
      className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 font-sans text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground [&_svg]:size-3.5"
      aria-label={done ? 'Copied' : label}
    >
      {done ? <Check className="text-safe" /> : <Copy />}
      {done ? 'Copied' : label}
    </button>
  )
}

// The JSON a user pastes into package.json: the pins as new values, plus the overrides block.
export const changesJson = ({ pin, overrides }: Changes) => {
  const out: Record<string, unknown> = {}
  for (const [pkg, c] of Object.entries(pin)) out[c.field] = { ...(out[c.field] as object), [pkg]: c.to }
  if (Object.keys(overrides).length) out.overrides = overrides
  return JSON.stringify(out, null, 2)
}

// package.json changes, shown as a diff.
export function Diff({ changes, className }: { changes: Changes; className?: string }) {
  const { pin, overrides } = changes
  const byField = new Map<string, [string, { from: string; to: string }][]>()
  for (const [pkg, c] of Object.entries(pin)) byField.set(c.field, [...(byField.get(c.field) ?? []), [pkg, c]])
  const lines: { t: ' ' | '-' | '+'; s: string }[] = []
  for (const [field, xs] of byField) {
    lines.push({ t: ' ', s: `"${field}": {` })
    for (const [pkg, c] of xs) {
      lines.push({ t: '-', s: `  "${pkg}": "${c.from}",` })
      lines.push({ t: '+', s: `  "${pkg}": "${c.to}",` })
    }
    lines.push({ t: ' ', s: '},' })
  }
  if (Object.keys(overrides).length) {
    const body = JSON.stringify(overrides, null, 2).split('\n')
    lines.push({ t: '+', s: `"overrides": ${body[0]}` })
    for (const l of body.slice(1)) lines.push({ t: '+', s: l })
  }
  return (
    <div className={cn('self-start overflow-hidden rounded-md border', className)}>
      <div className="flex items-center justify-between border-b bg-muted/50 py-1 pr-1 pl-3 font-mono text-xs text-muted-foreground">
        package.json
        <CopyButton text={changesJson(changes)} />
      </div>
      <pre className="overflow-x-auto py-2 font-mono text-xs leading-5">
        {lines.map((l, i) => (
          <div key={i} className={cn('px-3', l.t === '-' && 'bg-hot/8 text-hot', l.t === '+' && 'bg-safe/10 text-safe')}>
            <span className="inline-block w-4 select-none opacity-70">{l.t}</span>
            {l.s}
          </div>
        ))}
      </pre>
    </div>
  )
}
