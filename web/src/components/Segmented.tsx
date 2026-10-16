import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

// A row of mutually exclusive options. Arrow keys move the selection, as in a native radio group.
export function Segmented<T extends string>({ value, onChange, options, label, className }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[]; label: string; className?: string }) {
  const move = (dir: number) => {
    const i = options.findIndex((o) => o.value === value)
    onChange(options[(i + dir + options.length) % options.length].value)
  }
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn('inline-flex max-w-full overflow-x-auto rounded-lg border bg-muted/60 p-0.5', className)}
      onKeyDown={(e) => {
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); move(1) }
        if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); move(-1) }
      }}
    >
      {options.map((o) => {
        const on = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.value)}
            className={cn(
              'flex h-7 flex-1 items-center justify-center gap-1.5 rounded-md px-3 text-[13px] whitespace-nowrap text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 [&_svg]:size-3.5',
              on && 'bg-card font-medium text-foreground shadow-xs ring-1 ring-border',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
