import { Package, Search } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { api, compact } from '../api'
import { cn } from '@/lib/utils'

type Hit = { name: string; downloads: number | null }

// Package name combobox over the graph's Package nodes. Enter picks the highlighted match.
export function PackageSearch({ onPick, exclude, placeholder = 'Search packages in the graph' }: { onPick: (name: string) => void; exclude: string[]; placeholder?: string }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<Hit[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [loading, setLoading] = useState(false)
  const id = useId()
  const box = useRef<HTMLDivElement>(null)
  const skip = exclude.join('\n') // a string, so a new array with the same names does not refetch

  useEffect(() => {
    const needle = q.trim()
    if (!needle) { setHits([]); return }
    setLoading(true)
    const t = window.setTimeout(() => {
      api.searchPackages(needle)
        .then((xs) => { setHits(xs.filter((x) => !skip.split('\n').includes(x.name))); setActive(0) })
        .catch(() => setHits([]))
        .finally(() => setLoading(false))
    }, 120)
    return () => window.clearTimeout(t)
  }, [q, skip])

  useEffect(() => {
    const off = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', off)
    return () => document.removeEventListener('mousedown', off)
  }, [])

  const pick = (name: string) => {
    onPick(name)
    setQ('')
    setHits([])
    setOpen(false)
  }
  const show = open && q.trim().length > 0

  return (
    <div ref={box} className="relative">
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
      <input
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, hits.length - 1)) }
          if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
          if (e.key === 'Enter') { e.preventDefault(); if (hits[active]) pick(hits[active].name) }
          if (e.key === 'Escape') setOpen(false)
        }}
        role="combobox"
        aria-expanded={show}
        aria-controls={id}
        aria-activedescendant={show && hits[active] ? `${id}-${active}` : undefined}
        aria-autocomplete="list"
        placeholder={placeholder}
        className="h-9 w-full rounded-lg border border-input bg-card pr-3 pl-8 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
      />
      {show ? (
        <ul id={id} role="listbox" className="absolute inset-x-0 top-full z-20 mt-1 max-h-72 overflow-y-auto rounded-lg border bg-popover p-1 shadow-lg">
          {hits.map((h, i) => (
            <li
              key={h.name}
              id={`${id}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => { e.preventDefault(); pick(h.name) }}
              className={cn('flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm', i === active && 'bg-accent')}
            >
              <Package className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{h.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground tabular">{compact(h.downloads)}/wk</span>
            </li>
          ))}
          {!hits.length ? <li className="px-2.5 py-2 text-sm text-muted-foreground">{loading ? 'Searching…' : `No package starting with “${q.trim()}” in the graph.`}</li> : null}
        </ul>
      ) : null}
    </div>
  )
}
