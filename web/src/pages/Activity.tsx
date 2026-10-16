import { Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { LogEvent } from '../api'
import { PageBody, PageHeader } from '../components/Page'
import { Input } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { cn } from '@/lib/utils'

const LEVELS = ['all', 'info', 'warning', 'error'] as const
type Level = (typeof LEVELS)[number]
const levelOf = (e: LogEvent): Exclude<Level, 'all'> => {
  const l = e.level.toLowerCase()
  return l.startsWith('err') || l === 'critical' ? 'error' : l.startsWith('warn') ? 'warning' : 'info'
}

// The log line repeats the time, source and level. Strip them, they have their own columns.
const message = (e: LogEvent) => e.line.replace(/^\S+\s+\S+\s+(DEBUG|INFO|WARN(ING)?|ERROR|CRITICAL)\s+/, '')

function Message({ text }: { text: string }) {
  const parts = text.split(/(\b[a-z_]+=)/g)
  return (
    <>
      {parts.map((p, i) =>
        /^[a-z_]+=$/.test(p) ? (
          <span key={i} className="text-muted-foreground">
            {p}
          </span>
        ) : (
          p
        ),
      )}
    </>
  )
}

export function Activity({ events, connected }: { events: LogEvent[]; connected: boolean }) {
  const [q, setQ] = useState('')
  const [level, setLevel] = useState<Level>('all')
  const box = useRef<HTMLDivElement>(null)
  const stuck = useRef(true) // Follow new events until the user scrolls up
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return events.filter((e) => (level === 'all' || levelOf(e) === level) && (!needle || e.line.toLowerCase().includes(needle)))
  }, [events, q, level])
  useEffect(() => {
    const el = box.current
    if (el && stuck.current) el.scrollTop = el.scrollHeight
  }, [rows])

  return (
    <>
      <PageHeader title="Activity" description="Every graph tool call, agent step and approval, streamed live from the API." />
      <PageBody className="min-h-0 flex-1">
        <section className="flex min-h-[420px] flex-1 flex-col overflow-hidden rounded-lg border bg-card">
          <div className="flex flex-wrap items-center gap-3 border-b px-3 py-2.5">
            <div className="relative min-w-48 flex-1 sm:max-w-80">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter events" className="pl-8" aria-label="Filter events" />
            </div>
            <ToggleGroup value={[level]} onValueChange={(v) => v[0] && setLevel(v[0] as Level)} variant="outline" size="sm" spacing={0} aria-label="Level">
              {LEVELS.map((l) => (
                <ToggleGroupItem key={l} value={l} className="px-3 capitalize">
                  {l === 'warning' ? 'Warnings' : l === 'error' ? 'Errors' : l === 'info' ? 'Info' : 'All'}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <span className="ml-auto flex items-center gap-4 text-xs text-muted-foreground">
              <span className="tabular">{rows.length.toLocaleString()} events</span>
              <span className="flex items-center gap-1.5">
                <span className={cn('size-1.5 rounded-full', connected ? 'bg-safe' : 'bg-hot')} />
                {connected ? 'Live' : 'Reconnecting…'}
              </span>
            </span>
          </div>
          <div
            ref={box}
            className="log min-h-0 flex-1 overflow-auto font-mono text-xs leading-5"
            aria-label="Agent event log"
            aria-live="off"
            onScroll={(e) => {
              const el = e.currentTarget
              stuck.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
            }}
          >
            {rows.length === 0 ? (
              <p className="px-4 py-10 text-center font-sans text-sm text-muted-foreground">
                {events.length ? 'No events match this filter.' : 'Waiting for events. Replay the incident or ask the agent a question.'}
              </p>
            ) : null}
            <table className="w-full border-collapse">
              <tbody>
                {rows.map((e, i) => {
                  const lv = levelOf(e)
                  return (
                    <tr key={i} className={cn('align-top hover:bg-muted/50', lv === 'error' && 'bg-hot/5', lv === 'warning' && 'bg-warn/5')}>
                      <td className="w-0 py-0.5 pr-4 pl-4 whitespace-nowrap text-muted-foreground tabular">{e.ts.slice(11, 23)}</td>
                      <td className={cn('w-0 py-0.5 pr-4 whitespace-nowrap', lv === 'error' ? 'text-hot' : lv === 'warning' ? 'text-warn' : 'text-muted-foreground')}>
                        {lv === 'warning' ? 'warn' : lv}
                      </td>
                      <td className="hidden w-0 py-0.5 pr-4 whitespace-nowrap text-muted-foreground md:table-cell">{e.source}</td>
                      <td className="py-0.5 pr-4 break-all">
                        <Message text={message(e)} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      </PageBody>
    </>
  )
}
