import Graph from 'graphology'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'
import Sigma from 'sigma'
import type { IncidentGraph, Path } from '../api'
import { repoName, short } from '../api'
import { type Palette, hopColor } from '../hop'
import { radialLayout } from '../layout'
import { Button } from '@/components/ui/button'

type Props = {
  data: IncidentGraph
  reveal: number
  path: Path | null
  selected: string | null
  palette: Palette
  onSelect: (key: string, kind: 'Version' | 'Repo') => void
}

type NodeAttrs = { x: number; y: number; size: number; color: string; label: string; hop: number; kind: string }

const nodeSize = (downloads: number | null | undefined, kind: string, hop: number) => {
  if (kind === 'Repo') return 9
  const base = 1.4 + Math.log10((downloads ?? 0) + 1) * 0.55
  return hop === 0 ? base + 3 : base
}

export function BlastGraph({ data, reveal, path, selected, palette, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const sigma = useRef<Sigma<any> | null>(null)
  const state = useRef({ reveal, path: null as Path | null, onPath: new Set<string>(), selected })

  const maxHop = useMemo(() => Math.max(0, ...data.nodes.map((n) => n.hop)), [data])

  const graph = useMemo(() => {
    const g = new Graph<NodeAttrs>({ multi: false, type: 'directed' })
    const pos = radialLayout(data)
    for (const a of data.affected) {
      const p = pos.get(a.key)!
      g.addNode(a.key, { x: p.x, y: p.y, size: nodeSize(a.downloads, 'Version', 0), color: hopColor(0, maxHop), label: short(a.key), hop: 0, kind: 'Affected' })
    }
    for (const n of data.nodes) {
      const p = pos.get(n.key)
      if (!p || g.hasNode(n.key)) continue
      g.addNode(n.key, {
        x: p.x,
        y: p.y,
        size: nodeSize(n.downloads, n.kind, n.hop),
        color: n.kind === 'Repo' ? (n.status === 'MITIGATED_BY_OVERRIDE' ? palette.safe : palette.ink) : hopColor(n.hop, maxHop),
        label: n.kind === 'Repo' ? repoName(n.key) : short(n.key),
        hop: n.hop,
        kind: n.kind,
      })
    }
    for (const n of data.nodes) {
      if (n.via && g.hasNode(n.via) && g.hasNode(n.key) && !g.hasEdge(n.key, n.via)) {
        g.addEdge(n.key, n.via, { size: n.kind === 'Repo' ? 1.2 : 0.5, color: palette.edge, hop: n.hop })
      }
    }
    return g
  }, [data, maxHop, palette])

  useEffect(() => {
    if (!container.current) return
    const s = new Sigma(graph, container.current, {
      settings: {
        renderLabels: true,
        labelRenderedSizeThreshold: 999,
        hideEdgesOnMove: true,
        stagePadding: 24,
        itemSizesReference: 'screen',
        zoomToSizeRatioFunction: (r: number) => Math.sqrt(r),
        zIndex: true,
        allowInvalidContainer: true,
        labelColor: { color: palette.label },
        defaultDrawNodeHover: drawHover(palette),
      } as any,
      nodeReducer: (key, display, attrs) => {
        const st = state.current
        const a = attrs as unknown as NodeAttrs
        const out: Record<string, unknown> = {}
        if (a.hop > st.reveal) out.visibility = 'hidden'
        const onPath = st.onPath.has(key)
        const pinned = a.kind === 'Repo'
        out.labelVisibility = onPath || pinned || key === st.selected ? 'visible' : display.labelVisibility
        out.labelFont = 'Geist Mono Variable'
        out.labelSize = a.kind === 'Repo' ? 12 : 11
        out.labelColor = palette.label
        if (st.onPath.size) {
          if (onPath) {
            out.size = Math.max(display.size * 1.6, 5)
            out.zIndex = 2
          } else {
            out.opacity = 0.18
            out.labelVisibility = pinned && a.kind === 'Repo' ? 'visible' : 'hidden'
          }
        }
        if (key === st.selected) out.size = Math.max(display.size * 1.8, 7)
        return out
      },
      edgeReducer: (key, _display, attrs) => {
        const st = state.current
        const out: Record<string, unknown> = {}
        if ((attrs.hop ?? 0) > st.reveal) out.visibility = 'hidden'
        if (st.onPath.size) {
          const [a, b] = [graph.source(key), graph.target(key)]
          if (attrs.path || (st.onPath.has(a) && st.onPath.has(b) && attrs.path !== false)) {
            out.color = palette.ink
            out.size = 2.2
            out.zIndex = 2
            out.visibility = 'visible'
          } else {
            out.opacity = 0.12
          }
        }
        return out
      },
    })
    s.on('clickNode', ({ node }) => {
      const kind = graph.getNodeAttribute(node, 'kind')
      onSelect(node, kind === 'Repo' ? 'Repo' : 'Version')
    })
    sigma.current = s
    // Canvas labels do not wait for web fonts. Draw again once Geist Mono has loaded.
    document.fonts.load('11px "Geist Mono Variable"').then(() => sigma.current === s && s.refresh())
    // Sigma only listens to window resizes. The agent panel changes the width without one.
    const ro = new ResizeObserver(([e]) => { if (e.contentRect.height > 0) { s.resize(); s.refresh() } })
    ro.observe(container.current)
    return () => {
      ro.disconnect()
      s.kill()
      sigma.current = null
    }
    // onSelect does not change while the graph exists (App passes a useCallback).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph])

  // Update the reducer state for reveal, path highlight and selection, then refresh.
  useEffect(() => {
    const g = graph
    for (const e of g.filterEdges((_, attrs) => attrs.path === true)) g.dropEdge(e)
    const onPath = new Set<string>()
    if (path) {
      for (const n of path.nodes) if (g.hasNode(n)) onPath.add(n)
      for (let i = 0; i + 1 < path.nodes.length; i++) {
        const [a, b] = [path.nodes[i], path.nodes[i + 1]]
        if (g.hasNode(a) && g.hasNode(b) && !g.hasEdge(a, b) && !g.hasEdge(b, a)) {
          g.addEdge(a, b, { path: true, hop: 0, color: palette.ink, size: 2.2 })
        }
      }
    }
    state.current = { reveal, path, onPath, selected }
    sigma.current?.refresh()
  }, [graph, reveal, path, selected, palette])

  const camera = (f: (c: ReturnType<Sigma['getCamera']>) => void) => {
    const c = sigma.current?.getCamera()
    if (c) f(c)
  }
  return (
    <div className="relative size-full overflow-hidden">
      <div className="absolute inset-0" ref={container} aria-label="Blast radius graph. Malicious versions are at the centre. Each ring is one hop." />
      <div className="absolute right-3 bottom-3 flex flex-col overflow-hidden rounded-md border bg-background/90 shadow-xs backdrop-blur">
        <Button variant="ghost" size="icon-sm" className="rounded-none" aria-label="Zoom in" onClick={() => camera((c) => c.zoomIn({ duration: 200 }))}><Plus /></Button>
        <Button variant="ghost" size="icon-sm" className="rounded-none border-y" aria-label="Zoom out" onClick={() => camera((c) => c.zoomOut({ duration: 200 }))}><Minus /></Button>
        <Button variant="ghost" size="icon-sm" className="rounded-none" aria-label="Fit graph" onClick={() => camera((c) => c.reset({ duration: 250 }))}><Maximize2 /></Button>
      </div>
    </div>
  )
}

// Hover label that follows the theme. Sigma's default draws a white box, which is wrong on dark.
function drawHover(p: Palette) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (ctx: CanvasRenderingContext2D, d: any, settings: any) => {
    const size = settings.labelSize ?? 12
    ctx.font = `500 ${size}px "Geist Mono Variable", monospace`
    const w = ctx.measureText(d.label ?? '').width
    const x = d.x + d.size + 4
    ctx.fillStyle = p.tip
    ctx.strokeStyle = p.edge
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.roundRect(x - 4, d.y - size / 2 - 5, w + 8, size + 10, 4)
    ctx.fill()
    ctx.stroke()
    ctx.fillStyle = p.label
    ctx.fillText(d.label ?? '', x, d.y + size / 3)
  }
}
