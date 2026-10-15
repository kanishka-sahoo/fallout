import { test } from 'node:test'
import assert from 'node:assert/strict'
import { resolve } from '../resolver.mjs'

const S = '2025-09-08T13:12:09.343Z'

// Synthetic packument shaped like the ones crawl.py builds from deps.dev data.
function packument ({ latest, versions }) {
  return {
    name: 'pkg',
    'dist-tags': { latest },
    versions: Object.fromEntries(versions.map(([v, , deprecated]) =>
      [v, { name: 'pkg', version: v, ...(deprecated ? { deprecated: 'old' } : {}) }])),
    time: Object.fromEntries(versions.map(([v, t]) => [v, t])),
  }
}

const base = packument({
  latest: '4.4.1',
  versions: [
    ['4.3.4', '2022-03-17T00:00:00Z'],
    ['4.4.0', '2024-12-06T00:00:00Z'],
    ['4.4.1', '2025-05-13T00:00:00Z'],
    ['4.5.0', '2025-06-01T00:00:00Z', true], // deprecated, higher than latest
    ['4.6.0', '2025-10-01T00:00:00Z'], // published after S
    ['5.0.0', '2025-07-01T00:00:00Z'],
  ],
})

test('dist-tag latest is preferred when it satisfies the range', () => {
  assert.deepEqual(resolve(base, '^4.3.4', S), { version: '4.4.1' })
})

test('versions published after S are excluded', () => {
  assert.deepEqual(resolve(base, '>=4.5.0 <5', S), { version: '4.5.0' })
  assert.equal(resolve(base, '4.6.0', S).error, 'ETARGET')
})

test('deprecated versions rank below non-deprecated ones', () => {
  const p = packument({
    latest: '1.0.0',
    versions: [['1.0.0', '2020-01-01T00:00:00Z'], ['2.0.0', '2021-01-01T00:00:00Z'], ['2.1.0', '2022-01-01T00:00:00Z', true]],
  })
  assert.deepEqual(resolve(p, '>=2', S), { version: '2.0.0' })
})

test('ETARGET is surfaced, not swallowed', () => {
  const r = resolve(base, '^9.0.0', S)
  assert.equal(r.error, 'ETARGET')
  assert.ok(r.message)
})

test('latest is synthesized at S when the packument has no dist-tags', () => {
  const p = packument({
    latest: undefined,
    versions: [
      ['1.0.0', '2020-01-01T00:00:00Z'],
      ['1.1.0', '2021-01-01T00:00:00Z'],
      ['1.2.0', '2022-01-01T00:00:00Z', true], // deprecated
      ['2.0.0-beta.1', '2023-01-01T00:00:00Z'], // prerelease
      ['2.0.0', '2025-12-01T00:00:00Z'], // after S
    ],
  })
  delete p['dist-tags']
  assert.deepEqual(resolve(p, '*', S), { version: '1.1.0' })
  assert.equal(p['dist-tags'].latest, '1.1.0')
})

test('latest falls back to the highest prerelease when nothing stable exists at S', () => {
  const p = packument({
    latest: undefined,
    versions: [['1.3.2-alpha.24', '2025-08-01T00:00:00Z'], ['1.3.2-alpha.25', '2025-08-20T00:00:00Z']],
  })
  delete p['dist-tags']
  assert.deepEqual(resolve(p, '*', S), { version: '1.3.2-alpha.25' })
})

test('a fully deprecated, prerelease-only package still resolves (today\'s deprecation is ignored)', () => {
  const p = packument({
    latest: undefined,
    versions: [['5.0.0-beta.69', '2025-01-01T00:00:00Z', true], ['5.0.0-beta.70', '2025-03-01T00:00:00Z', true]],
  })
  delete p['dist-tags']
  assert.deepEqual(resolve(p, '*', S), { version: '5.0.0-beta.70' })
})

test('empty range behaves like *', () => {
  assert.deepEqual(resolve(base, '', S), { version: '4.4.1' })
})
