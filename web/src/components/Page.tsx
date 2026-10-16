import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

const WIDTH = 'mx-auto w-full max-w-[1400px] px-4 lg:px-8'

// Title band across the top of a page, on the card colour, above the grey content area.
export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="shrink-0 border-b bg-card">
      <div className={cn(WIDTH, 'flex flex-wrap items-end justify-between gap-x-6 gap-y-3 py-6 lg:py-8')}>
        <div className="min-w-0">
          <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.03em] text-balance">{title}</h1>
          {description ? <p className="mt-1.5 max-w-[78ch] text-sm leading-normal text-pretty text-muted-foreground">{description}</p> : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  )
}

export function PageBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn(WIDTH, 'flex flex-col gap-6 py-6 lg:py-8', className)}>{children}</div>
}

export function Section({ title, description, actions, children, className }: { title: string; description?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn('overflow-hidden rounded-lg border bg-card', className)}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4">
        <div className="min-w-0 max-w-[72ch]">
          <h2 className="text-sm font-semibold">{title}</h2>
          {description ? <p className="mt-1 text-[13px] text-pretty text-muted-foreground">{description}</p> : null}
        </div>
        {actions}
      </header>
      {children}
    </section>
  )
}
