import Graph from 'graphology'
import { useEffect, useMemo, useRef } from 'react'
import Sigma from 'sigma'
import type { IncidentGraph, Path } from '../api'
import { repoName, short } from '../api'
import { INK, SAFE, hopColor } from '../hop'
import { radialLayout } from '../layout'

type Props = {
  data: IncidentGraph
  reveal: number
  path: Path | null
  selected: string | null
  onSelect: (key: string, kind: 'Version' | 'Repo') => void
}

type NodeAttrs = { x: number; y: number; size: number; color: string; label: string; hop: number; kind: string }

const nodeSize = (downloads: number | null | undefined, kind: string, hop: number) => {
  if (kind === 'Repo') return 9
  const base = 1.4 + Math.log10((downloads ?? 0) + 1) * 0.55
  return hop === 0 ? base + 3 : base
}

export function BlastGraph({ data, reveal, path, selected, onSelect }: Props) {
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
        color: n.kind === 'Repo' ? (n.status === 'MITIGATED_BY_OVERRIDE' ? SAFE : INK) : hopColor(n.hop, maxHop),
        label: n.kind === 'Repo' ? repoName(n.key) : short(n.key),
        hop: n.hop,
        kind: n.kind,
      })
    }
    for (const n of data.nodes) {
      if (n.via && g.hasNode(n.via) && g.hasNode(n.key) && !g.hasEdge(n.key, n.via)) {
        g.addEdge(n.key, n.via, { size: n.kind === 'Repo' ? 1.2 : 0.5, color: '#c9d1d6', hop: n.hop })
      }
    }
    return g
  }, [data, maxHop])

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
      } as any,
      nodeReducer: (key, display, attrs) => {
        const st = state.current
        const a = attrs as unknown as NodeAttrs
        const out: Record<string, unknown> = {}
        if (a.hop > st.reveal) out.visibility = 'hidden'
        const onPath = st.onPath.has(key)
        const pinned = a.kind === 'Repo'
        out.labelVisibility = onPath || pinned || key === st.selected ? 'visible' : display.labelVisibility
        out.labelFont = 'IBM Plex Mono'
        out.labelSize = a.kind === 'Repo' ? 12 : 11
        out.labelColor = INK
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
            out.color = INK
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
    return () => {
      s.kill()
      sigma.current = null
    }
    // onSelect is stable for the lifetime of the graph (App passes a useCallback).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph])

  // Reveal, path highlight and selection: mutate the reducer state and refresh.
  useEffect(() => {
    const g = graph
    for (const e of g.filterEdges((_, attrs) => attrs.path === true)) g.dropEdge(e)
    const onPath = new Set<string>()
    if (path) {
      for (const n of path.nodes) if (g.hasNode(n)) onPath.add(n)
      for (let i = 0; i + 1 < path.nodes.length; i++) {
        const [a, b] = [path.nodes[i], path.nodes[i + 1]]
        if (g.hasNode(a) && g.hasNode(b) && !g.hasEdge(a, b) && !g.hasEdge(b, a)) {
          g.addEdge(a, b, { path: true, hop: 0, color: INK, size: 2.2 })
        }
      }
    }
    state.current = { reveal, path, onPath, selected }
    sigma.current?.refresh()
  }, [graph, reveal, path, selected])

  return <div className="graph" ref={container} aria-label="Blast radius graph: malicious versions at the centre, one ring per hop" />
}
