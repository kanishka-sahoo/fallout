#!/usr/bin/env node
// Authoritative npm semver evaluation (BUILD.md §7.2).
//
// Usage: node semver-eval.mjs < requests.jsonl > results.jsonl
//
// Input lines:
//   {"id", "op": "maxSatisfying", "range", "versions": [...]}  -> {"id", "result": "4.4.2" | null}
//   {"id", "op": "satisfies", "range", "version"}              -> {"id", "result": true | false}
//   {"id", "op": "filter", "range", "versions": [...]}         -> {"id", "result": [...matching]}
// A spec that is not a registry semver range (npm: alias, git, tarball, file:, dist-tag)
// yields {"id", "result": "unknown", "reason"}. It is reported, never silently dropped.

import { createInterface } from 'node:readline'
import semver from 'semver'

const NON_REGISTRY = /^(npm:|git\+|git:|github:|gitlab:|bitbucket:|https?:|file:|link:|workspace:)|^[^@\s]+\/[^@\s]+$/

export function classifySpec (range) {
  const spec = (range ?? '').trim()
  if (NON_REGISTRY.test(spec)) return { ok: false, reason: 'non-registry spec' }
  if (semver.validRange(spec) === null) return { ok: false, reason: 'not a semver range' }
  return { ok: true, spec }
}

export function evaluate (req) {
  const c = classifySpec(req.range)
  if (!c.ok) return { result: 'unknown', reason: c.reason }
  switch (req.op) {
    case 'maxSatisfying':
      return { result: semver.maxSatisfying(req.versions, c.spec) }
    case 'satisfies':
      return { result: semver.satisfies(req.version, c.spec) }
    case 'filter':
      return { result: req.versions.filter((v) => semver.valid(v) && semver.satisfies(v, c.spec)) }
    default:
      throw new Error(`unknown op: ${req.op}`)
  }
}

async function main () {
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity })
  for await (const line of rl) {
    if (!line.trim()) continue
    const req = JSON.parse(line)
    process.stdout.write(JSON.stringify({ id: req.id, ...evaluate(req) }) + '\n')
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    process.stderr.write(`semver-eval: ${err.message}\n`)
    process.exit(1)
  })
}
