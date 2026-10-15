#!/usr/bin/env node
// Independent, npm-authoritative exposure oracle (BUILD.md §8). Never reads FalkorDB.
//
// A target is exposed to affected version m of package P when its ideal tree, built by npm's
// own arborist at S, contains an installed edge into P whose spec admits m (§5.0).
//
// Usage:
//   node oracle.mjs --before <ISO> --affected affected.json --project <dir>       [--tree-out f]
//   node oracle.mjs --before <ISO> --affected affected.json --package name@version [--tree-out f]
// affected.json: {"debug": ["4.4.2"], "chalk": ["5.6.1"], ...}
// Prints: {target, exposed, paths: [[{name, version, spec, type}, ...]], unknown_specs, nodes}

import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import Arborist from '@npmcli/arborist'
import semver from 'semver'

function args (argv) {
  const out = {}
  for (let i = 0; i < argv.length; i += 2) out[argv[i].replace(/^--/, '')] = argv[i + 1]
  for (const k of ['before', 'affected']) if (!out[k]) throw new Error(`--${k} is required`)
  if (!out.project === !out.package) throw new Error('exactly one of --project / --package')
  return out
}

function syntheticProject (spec) {
  const at = spec.lastIndexOf('@')
  const [name, version] = [spec.slice(0, at), spec.slice(at + 1)]
  const dir = mkdtempSync(join(tmpdir(), 'fallout-oracle-'))
  writeFileSync(join(dir, 'package.json'),
    JSON.stringify({ name: 'oracle-root', version: '0.0.0', dependencies: { [name]: version } }))
  return dir
}

// Breadth-first over installed edges from the root; the first path found to each node is
// the shortest, which is what the reference path should be.
export function findExposure (root, affected) {
  const paths = []
  const unknownSpecs = []
  const seen = new Set([root])
  const queue = [[root, []]]
  while (queue.length) {
    const [node, path] = queue.shift()
    for (const edge of node.edgesOut.values()) {
      if (!edge.to || (edge.type === 'dev' && !node.isProjectRoot && !node.isWorkspace)) continue
      // Workspace edges land on a Link; its dependencies live on the link target.
      const to = edge.to.isLink ? edge.to.target : edge.to
      const hop = { name: edge.name, version: to.version, spec: edge.spec, type: edge.type }
      const bad = affected[edge.name]
      if (bad) {
        if (semver.validRange(edge.spec) === null) {
          unknownSpecs.push([...path, hop])
        } else {
          const m = semver.maxSatisfying(bad, edge.spec)
          if (m) paths.push([...path, { ...hop, admits: m }])
        }
      }
      if (!seen.has(to)) {
        seen.add(to)
        queue.push([to, [...path, hop]])
      }
    }
  }
  return { paths, unknownSpecs }
}

async function main () {
  const a = args(process.argv.slice(2))
  const affected = JSON.parse(readFileSync(a.affected, 'utf8'))
  const path = a.project ?? syntheticProject(a.package)
  const arb = new Arborist({ path, before: new Date(a.before) })
  const tree = await arb.buildIdealTree()
  const { paths, unknownSpecs } = findExposure(tree, affected)
  const nodes = [...tree.inventory.values()].filter((n) => !n.isRoot)
  if (a['tree-out']) {
    writeFileSync(a['tree-out'], JSON.stringify(nodes.map((n) => ({
      location: n.location,
      name: n.name,
      version: n.version,
      edgesOut: [...n.edgesOut.values()].map((e) => ({ name: e.name, spec: e.spec, type: e.type, to: e.to?.version ?? null })),
    }))))
  }
  process.stdout.write(JSON.stringify({
    target: a.project ?? a.package,
    exposed: paths.length > 0,
    paths,
    unknown_specs: unknownSpecs,
    nodes: nodes.length,
  }) + '\n')
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    process.stderr.write(`oracle: ${err.stack}\n`)
    process.exit(1)
  })
}
