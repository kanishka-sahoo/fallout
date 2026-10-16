import { Activity, ChevronsUpDown, Crosshair, FlaskConical, FolderGit2, Monitor, Moon, Network, Plus, Radar, ShieldCheck, Sun } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Page } from '@/lib/route'
import type { ThemePref } from '@/lib/theme'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuItem,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

type Incident = { id: string; title: string; simulated?: boolean }

type Props = {
  page: Page
  onNavigate: (p: Page) => void
  incident: string
  incidents: Incident[]
  onIncident: (id: string) => void
  snapshot: string
  connected: boolean
  pendingFixes: number
  toFix: number
  theme: ThemePref
  onTheme: (t: ThemePref) => void
}

// The mark is the blast radius itself: the malicious core, a near ring and a far ring.
export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <circle cx="16" cy="16" r="5" fill="#C21E3A" />
      <circle cx="16" cy="16" r="10" fill="none" stroke="#E39B2D" strokeWidth="2.25" />
      <circle cx="16" cy="16" r="14.5" fill="none" stroke="#9DB3C1" strokeWidth="2" />
    </svg>
  )
}

export function Sidebar(p: Props) {
  const current = p.incidents.find((i) => i.id === p.incident)
  const real = p.incidents.filter((i) => !i.simulated)
  const sims = p.incidents.filter((i) => i.simulated)
  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex h-14 shrink-0 items-center gap-2.5 px-4">
        <Mark className="size-6" />
        <span className="text-[17px] leading-none font-semibold tracking-[-0.03em]">Fallout</span>
      </div>

      <div className="px-3 pb-3">
        <DropdownMenu>
          <DropdownMenuTrigger
            className="flex w-full items-center gap-2 rounded-lg border bg-card px-3 py-2 text-left shadow-xs transition-colors outline-none hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/40 aria-expanded:bg-accent"
            aria-label="Incident"
          >
            <span className="min-w-0 flex-1">
              {current?.simulated ? <span className="mb-1 inline-flex h-4 items-center rounded-sm bg-warn/15 px-1 text-[10px] font-medium text-warn">Simulation</span> : null}
              <span className="line-clamp-2 text-[13px] leading-snug font-medium">{current?.title || p.incident || 'Loading incident…'}</span>
              {p.snapshot ? <span className="mt-0.5 block text-xs text-muted-foreground">Snapshot {p.snapshot}</span> : null}
            </span>
            <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
          </DropdownMenuTrigger>
          <DropdownMenuContent className="max-h-[70vh] w-80" align="start">
            {([['Incidents', real], ['Simulations', sims]] as const).map(([label, xs]) =>
              xs.length ? (
                <DropdownMenuGroup key={label}>
                  <DropdownMenuLabel>{label}</DropdownMenuLabel>
                  <DropdownMenuRadioGroup value={p.incident} onValueChange={(v) => p.onIncident(String(v))}>
                    {xs.map((i) => (
                      <DropdownMenuRadioItem key={i.id} value={i.id} className="py-2" closeOnClick>
                        <span className="line-clamp-2 text-[13px]">{i.title || i.id}</span>
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuGroup>
              ) : null,
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => p.onNavigate('simulate')}><Plus />Simulate an attack</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <nav className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-3 py-2" aria-label="Main">
        <ul className="flex flex-col gap-0.5">
          <Item icon={<Radar />} active={p.page === 'overview'} onClick={() => p.onNavigate('overview')}>Overview</Item>
          <Item icon={<ShieldCheck />} active={p.page === 'response'} onClick={() => p.onNavigate('response')} count={p.toFix} countTone="hot" countLabel="repos to fix">Response plan</Item>
          <Item icon={<FolderGit2 />} active={p.page === 'repos'} onClick={() => p.onNavigate('repos')} count={p.pendingFixes} countTone="safe" countLabel="fixes awaiting approval">
            Repositories
          </Item>
          <Item icon={<Activity />} active={p.page === 'activity'} onClick={() => p.onNavigate('activity')}>Activity</Item>
        </ul>
        <div>
          <p className="px-2.5 pb-1.5 text-xs text-muted-foreground">What if</p>
          <ul className="flex flex-col gap-0.5">
            <Item icon={<Crosshair />} active={p.page === 'simulate'} onClick={() => p.onNavigate('simulate')}>Simulate an attack</Item>
          </ul>
        </div>
        <div>
          <p className="px-2.5 pb-1.5 text-xs text-muted-foreground">Insights</p>
          <ul className="flex flex-col gap-0.5">
            <Item icon={<Network />} active={p.page === 'ecosystem'} onClick={() => p.onNavigate('ecosystem')}>Ecosystem</Item>
            <Item icon={<FlaskConical />} active={p.page === 'evaluation'} onClick={() => p.onNavigate('evaluation')}>Evaluation</Item>
          </ul>
        </div>
      </nav>

      <div className="flex shrink-0 items-center gap-2 border-t px-4 py-3">
        <span className="flex min-w-0 flex-1 items-center gap-2 text-xs text-muted-foreground" role="status">
          <span className={cn('relative flex size-2', !p.connected && 'animate-pulse')}>
            <span className={cn('size-2 rounded-full', p.connected ? 'bg-safe' : 'bg-hot')} />
          </span>
          {p.connected ? 'Connected' : 'Reconnecting…'}
        </span>
        <ThemeSwitch value={p.theme} onChange={p.onTheme} />
      </div>
    </div>
  )
}

function Item({ icon, active, onClick, children, count, countTone, countLabel }: { icon: ReactNode; active: boolean; onClick: () => void; children: string; count?: number; countTone?: 'hot' | 'safe'; countLabel?: string }) {
  return (
    <li>
      <a
        href="#"
        onClick={(e) => { e.preventDefault(); onClick() }}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground [&_svg]:size-4',
          active && 'bg-sidebar-accent font-medium text-sidebar-foreground',
        )}
      >
        {icon}
        <span className="flex-1">{children}</span>
        {count ? (
          <span
            className={cn('tabular min-w-5 rounded-full px-1.5 text-center text-[11px] leading-5 font-medium', countTone === 'safe' ? 'bg-safe/15 text-safe' : 'bg-hot/10 text-hot')}
            aria-label={`${count} ${countLabel}`}
            title={`${count} ${countLabel}`}
          >
            {count}
          </span>
        ) : null}
      </a>
    </li>
  )
}

function ThemeSwitch({ value, onChange }: { value: ThemePref; onChange: (t: ThemePref) => void }) {
  const opts: [ThemePref, ReactNode, string][] = [['light', <Sun />, 'Light'], ['dark', <Moon />, 'Dark'], ['system', <Monitor />, 'System']]
  return (
    <div className="flex rounded-full border bg-card p-0.5" role="radiogroup" aria-label="Theme">
      {opts.map(([v, icon, label]) => (
        <button
          key={v}
          role="radio"
          aria-checked={value === v}
          aria-label={label}
          title={label}
          onClick={() => onChange(v)}
          className={cn('flex size-6 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground [&_svg]:size-3.5', value === v && 'bg-accent text-foreground')}
        >
          {icon}
        </button>
      ))}
    </div>
  )
}
