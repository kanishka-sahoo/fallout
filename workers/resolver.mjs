#!/usr/bin/env node
// Time-anchored version resolution with npm's own picker (BUILD.md §5.2).
//
// Usage: node resolver.mjs --before <ISO 8601>  < requests.jsonl  > results.jsonl
//
// Input, one JSON object per line, grouped by package so a packument is sent once:
//   {"packument": {name, versions: {v: {deprecated?}}, time: {v: iso}, "dist-tags": {...}},
//    "requests": [{"id": "...", "range": "^4.3.4"}, ...]}
// Output, one line per request:
//   {"id": "...", "version": "4.4.1"}            resolved
//   {"id": "...", "error": "ETARGET", "message"}  no version satisfies at S; never invented

import { createInterface } from 'node:readline'
import pickManifest from 'npm-pick-manifest'
import semver from 'semver'

// The historical dist-tag is not available, so when the packument has none, `latest` is
// approximated as the highest stable, non-deprecated version published at or before S,
// falling back to deprecated ones, then to prereleases for packages that had no stable
// release yet. Recorded under Limitations in the README.
export function synthesizeLatest (packument, before) {
  const cutoff = Date.parse(before)
  const atS = Object.keys(packument.versions).filter((v) => {
    const t = packument.time?.[v]
    return semver.valid(v) && (!t || Date.parse(t) <= cutoff)
  })
  const stable = atS.filter((v) => !semver.prerelease(v))
  const live = stable.filter((v) => !packument.versions[v].deprecated)
  const pool = [live, stable, atS].find((p) => p.length) ?? []
  return pool.length ? semver.rsort(pool)[0] : undefined
}

export function resolve (packument, range, before) {
  // deps.dev reports today's deprecation status, not the status at S. A package deprecated in
  // full was almost always deprecated after its active life, and the flag cannot change the
  // relative ranking, so drop it rather than let it block the default version.
  const manifests = Object.values(packument.versions)
  if (manifests.length && manifests.every((m) => m.deprecated)) {
    for (const m of manifests) delete m.deprecated
  }
  if (!packument['dist-tags']?.latest) {
    const latest = synthesizeLatest(packument, before)
    packument['dist-tags'] = latest ? { latest } : {}
  }
  try {
    const m = pickManifest(packument, range || '*', { before })
    return { version: m.version }
  } catch (err) {
    return { error: err.code || 'EUNKNOWN', message: err.message }
  }
}

function parseArgs (argv) {
  const i = argv.indexOf('--before')
  if (i === -1 || !argv[i + 1]) throw new Error('--before <ISO 8601> is required')
  const before = argv[i + 1]
  if (Number.isNaN(Date.parse(before))) throw new Error(`invalid --before: ${before}`)
  return { before }
}

async function main () {
  const { before } = parseArgs(process.argv.slice(2))
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity })
  for await (const line of rl) {
    if (!line.trim()) continue
    const { packument, requests } = JSON.parse(line)
    for (const { id, range } of requests) {
      process.stdout.write(JSON.stringify({ id, ...resolve(packument, range, before) }) + '\n')
    }
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    process.stderr.write(`resolver: ${err.message}\n`)
    process.exit(1)
  })
}
