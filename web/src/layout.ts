// Radial layout. Affected versions are at the centre. Hop k is on ring k. Each ring is sorted
// by the angle of the parent node, so a branch stays near its parent.
import type { IncidentGraph } from './api'

export type Placed = { x: number; y: number; hop: number; angle: number }

export function radialLayout(data: IncidentGraph): Map<string, Placed> {
  const out = new Map<string, Placed>()
  const center = data.affected.map((a) => a.key).sort()
  center.forEach((k, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, center.length)
    const r = center.length > 1 ? 0.55 : 0
    out.set(k, { x: r * Math.cos(angle), y: r * Math.sin(angle), hop: 0, angle })
  })
  const byHop = new Map<number, typeof data.nodes>()
  for (const n of data.nodes) {
    if (!byHop.has(n.hop)) byHop.set(n.hop, [])
    byHop.get(n.hop)!.push(n)
  }
  for (const hop of [...byHop.keys()].sort((a, b) => a - b)) {
    const ring = byHop.get(hop)!
    const parentAngle = (n: (typeof ring)[number]) => (n.via ? (out.get(n.via)?.angle ?? 0) : 0)
    ring.sort((a, b) => parentAngle(a) - parentAngle(b) || a.key.localeCompare(b.key))
    // A ring with more nodes gets a larger radius, so it does not overlap the next ring.
    const r = 0.55 + hop * (1 + Math.min(1.2, ring.length / 1500))
    ring.forEach((n, i) => {
      const angle = (2 * Math.PI * (i + 0.5)) / ring.length
      out.set(n.key, { x: r * Math.cos(angle), y: r * Math.sin(angle), hop, angle })
    })
  }
  return out
}
