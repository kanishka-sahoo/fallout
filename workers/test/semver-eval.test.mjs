import { test } from 'node:test'
import assert from 'node:assert/strict'
import { evaluate } from '../semver-eval.mjs'

const sat = (range, version) => evaluate({ op: 'satisfies', range, version }).result
const max = (range, versions) => evaluate({ op: 'maxSatisfying', range, versions }).result

test('caret and tilde ranges', () => {
  assert.equal(sat('^4.3.4', '4.4.2'), true)
  assert.equal(sat('~4.3.0', '4.4.2'), false)
})

test('*, >= and x-ranges', () => {
  assert.equal(sat('*', '4.4.2'), true)
  assert.equal(sat('>=4.0.0', '4.4.2'), true)
  assert.equal(sat('4.x', '4.4.2'), true)
  assert.equal(sat('4.3.x', '4.4.2'), false)
})

test('prereleases are excluded by default', () => {
  assert.equal(sat('^1.3.0', '1.3.3-alpha.1'), false)
  assert.equal(max('*', ['1.3.3-alpha.1']), null)
})

test('non-registry specs return unknown', () => {
  for (const spec of ['npm:chalk@^5', 'git+https://github.com/a/b.git', 'https://x.test/a.tgz',
    'file:../a', 'github:a/b', 'a/b', 'latest']) {
    assert.equal(evaluate({ op: 'satisfies', range: spec, version: '1.0.0' }).result, 'unknown', spec)
  }
})

test('maxSatisfying picks the highest affected version the range admits', () => {
  assert.equal(max('~1.3.0', ['1.3.3', '1.29.2']), '1.3.3')
  assert.equal(max('>=1', ['1.3.3', '1.29.2']), '1.29.2')
  assert.equal(max('^2', ['1.3.3']), null)
})
