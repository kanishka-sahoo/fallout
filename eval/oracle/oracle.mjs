#!/usr/bin/env node
// Independent exposure oracle that uses npm's own resolver. It does not read FalkorDB.
//
// A target is exposed to affected version m of package P if its ideal tree, built by npm's
// arborist at S, has an installed edge to P whose spec admits m.
//
// Usage:
//   node oracle.mjs --before <ISO> --affected affected.json --project <dir>       [--tree-out f]
//   node oracle.mjs --before <ISO> --affected affected.json --package name@version [--tree-out f]
//   node oracle.mjs --before <ISO> --units units.json --package name@version [--tree-out f] [--lock-out f]
// affected.json: {"debug": ["4.4.2"], "chalk": ["5.6.1"], ...}
// Prints: {target, exposed, paths: [[{name, version, spec, type}, ...]], unknown_specs, nodes}
//
// --units (eval): builds one tree and labels it for many advisory groups at once.
// units.json: {"<unit>": {"mode": "admits" | "installed", "affected": {"pkg": ["v", ...]}}}
//   admits    (malicious, D10): an installed edge to P whose spec admits an affected version
//   installed (vulnerable, D1):  an installed node of P at an affected version
// Prints: {target, units: {"<unit>": {exposed, paths}}, nodes}. --lock-out writes the
// package-lock.json that arborist would write for this tree (the context for System B).

import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import Arborist from '@npmcli/arborist'
import semver from 'semver'

function args (argv) {
  const out = {}
  for (let i = 0; i < argv.length; i += 2) out[argv[i].replace(/^--/, '')] = argv[i + 1]
  for (const k of ['before', 'affected']) if (!out[k]) throw new Error(`--${k} is required`)
  if (!out.project === !out.package) throw new Error('give exactly one of --project or --package')
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

// Breadth-first search over installed edges from the root. The first path to each node is
// the shortest path, and the reference path must be the shortest.
export function findExposure (root, affected) {
  const paths = []
  const unknownSpecs = []
  const seen = new Set([root])
  const queue = [[root, []]]
  while (queue.length) {
    const [node, path] = queue.shift()
    for (const edge of node.edgesOut.values()) {
      if (!edge.to || (edge.type === 'dev' && !node.isProjectRoot && !node.isWorkspace)) continue
      // A workspace edge goes to a Link. Its dependencies are on the link target.
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

// `"strip-ansi-cjs": "npm:strip-ansi@^6"` -> {pkg: strip-ansi, spec: ^6}
function edgeTarget (edge) {
  const m = /^npm:((?:@[^/@]+\/)?[^@]+)(?:@(.*))?$/.exec(edge.spec ?? '')
  return m ? { pkg: m[1], spec: m[2] || '*' } : { pkg: edge.name, spec: edge.spec }
}

// The same BFS as findExposure. It runs once and labels every advisory group, with at most 3 reference paths each.
export function labelUnits (root, units) {
  const out = Object.fromEntries(Object.keys(units).map((u) => [u, { exposed: false, paths: [] }]))
  const seen = new Set([root])
  const queue = [[root, []]]
  while (queue.length) {
    const [node, path] = queue.shift()
    for (const edge of node.edgesOut.values()) {
      if (!edge.to || (edge.type === 'dev' && !node.isProjectRoot && !node.isWorkspace)) continue
      const to = edge.to.isLink ? edge.to.target : edge.to
      const { pkg, spec } = edgeTarget(edge)
      const hop = { name: to.packageName ?? pkg, version: to.version, spec: edge.spec, type: edge.type }
      for (const [u, cfg] of Object.entries(units)) {
        const bad = cfg.affected[pkg]
        if (!bad || out[u].paths.length >= 3) continue
        if (cfg.mode === 'installed') {
          if (bad.includes(to.version)) out[u].paths.push([...path, { ...hop, affected: to.version }])
        } else if (semver.validRange(spec) !== null) {
          const m = semver.maxSatisfying(bad, spec)
          if (m) out[u].paths.push([...path, { ...hop, admits: m }])
        }
      }
      if (!seen.has(to)) {
        seen.add(to)
        queue.push([to, [...path, hop]])
      }
    }
  }
  for (const u of Object.values(out)) u.exposed = u.paths.length > 0
  return out
}

function treeNodes (tree) {
  const edges = (n) => [...n.edgesOut.values()].map((e) => ({
    name: e.name,
    spec: e.spec,
    type: e.type,
    to: e.to?.version ?? null,
    toPackage: (e.to?.isLink ? e.to.target : e.to)?.packageName ?? null,
  }))
  return [...tree.inventory.values()].map((n) => ({
    location: n.location,
    name: n.name, // folder name: an alias (`strip-ansi-cjs`) or a workspace link name
    package: n.packageName, // the registry package that npm installs
    workspace: n.isLink || n.isWorkspace,
    root: n.isRoot || undefined,
    version: n.version,
    edgesOut: edges(n),
  }))
}

async function main () {
  const a = process.argv.includes('--units') ? unitArgs(process.argv.slice(2)) : args(process.argv.slice(2))
  if (a.units) return mainUnits(a)
  const affected = JSON.parse(readFileSync(a.affected, 'utf8'))
  const path = a.project ?? syntheticProject(a.package)
  const arb = new Arborist({ path, before: new Date(a.before) })
  const tree = await arb.buildIdealTree()
  const { paths, unknownSpecs } = findExposure(tree, affected)
  const nodes = [...tree.inventory.values()].filter((n) => !n.isRoot)
  if (a['tree-out']) writeFileSync(a['tree-out'], JSON.stringify(treeNodes(tree).filter((n) => !n.root)))
  process.stdout.write(JSON.stringify({
    target: a.project ?? a.package,
    exposed: paths.length > 0,
    paths,
    unknown_specs: unknownSpecs,
    nodes: nodes.length,
  }) + '\n')
}

function unitArgs (argv) {
  const out = {}
  for (let i = 0; i < argv.length; i += 2) out[argv[i].replace(/^--/, '')] = argv[i + 1]
  for (const k of ['before', 'units']) if (!out[k]) throw new Error(`--${k} is required`)
  if (!out.project === !out.package) throw new Error('give exactly one of --project or --package')
  return out
}

async function mainUnits (a) {
  const units = JSON.parse(readFileSync(a.units, 'utf8'))
  const path = a.project ?? syntheticProject(a.package)
  const arb = new Arborist({ path, before: new Date(a.before) })
  const tree = await arb.buildIdealTree()
  if (a['tree-out']) writeFileSync(a['tree-out'], JSON.stringify(treeNodes(tree)))
  if (a['lock-out']) writeFileSync(a['lock-out'], tree.meta.toString())
  process.stdout.write(JSON.stringify({
    target: a.project ?? a.package,
    units: labelUnits(tree, units),
    nodes: tree.inventory.size - 1,
  }) + '\n')
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    process.stderr.write(`oracle: ${err.stack}\n`)
    process.exit(1)
  })
}
