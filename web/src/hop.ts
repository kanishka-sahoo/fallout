// Colour scale for hop distance from a malicious version. Red is near. Grey-blue is far.
const STOPS: [number, [number, number, number]][] = [
  [0, [0xc2, 0x1e, 0x3a]],
  [0.3, [0xe3, 0x9b, 0x2d]],
  [1, [0x9d, 0xb3, 0xc1]],
]

export function hopColor(hop: number, maxHop: number): string {
  const t = maxHop <= 0 ? 0 : Math.min(1, hop / maxHop)
  for (let i = 1; i < STOPS.length; i++) {
    const [t1, c1] = STOPS[i]
    const [t0, c0] = STOPS[i - 1]
    if (t <= t1) {
      const k = (t - t0) / (t1 - t0)
      const c = c0.map((v, j) => Math.round(v + (c1[j] - v) * k))
      return `rgb(${c[0]}, ${c[1]}, ${c[2]})`
    }
  }
  return 'rgb(157, 179, 193)'
}

export const INK = '#17222d'
export const SAFE = '#2f7d6b'
