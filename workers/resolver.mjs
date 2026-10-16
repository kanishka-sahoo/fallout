#!/usr/bin/env node
// Resolves versions as of snapshot time S with npm's own version picker.
//
// Usage: node resolver.mjs --before <ISO 8601>  < requests.jsonl  > results.jsonl
//
// Input is one JSON object per line. Requests are grouped by package, so each packument is sent once:
//   {"packument": {name, versions: {v: {deprecated?}}, time: {v: iso}, "dist-tags": {...}},
//    "requests": [{"id": "...", "range": "^4.3.4"}, ...]}
// Output is one line per request:
//   {"id": "...", "version": "4.4.1"}            resolved
//   {"id": "...", "error": "ETARGET", "message"}  no version satisfies the range at S

import { createInterface } from 'node:readline'
import pickManifest from 'npm-pick-manifest'
import semver from 'semver'

// The historical dist-tag is not available. If the packument has no `latest` tag, `latest` is
// set to the highest stable, non-deprecated version published at or before S. If there is no
// such version, deprecated versions are used, and then prereleases (for packages that had no
// stable release yet). The README lists this under Limitations.
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
  // deps.dev reports the current deprecation status, not the status at S. If all versions of a
  // package are deprecated, the package was almost always deprecated after its active life.
  // The flag cannot change the relative order of the versions, so remove it. Otherwise it
  // would stop npm from picking the default version.
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
