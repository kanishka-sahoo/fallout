# Decisions, deviations and limitations

This file records each place where the build differs from [BUILD.md](BUILD.md), and each
known approximation. The README's Limitations section is generated from this file.

The graph models the npm registry as it was at the snapshot time (S).

## Deviations from BUILD.md

| # | Spec | What we do instead | Why |
|---|---|---|---|
| D1 | §5.0, §7.2: a target is exposed when a requirement *admits* an affected version | A target is exposed only if the version that npm would pick is affected. For MAL advisories, we resolve with the malicious versions injected, as of just after their publish time. For VULN advisories, the version resolved at S must be in the affected set. The oracle uses the same rule. | Under the spec's rule, `^4.0.0` admits `lodash@4.17.20`, so almost every target is exposed to every VULN advisory. For the chalk/debug replay, both rules agree, because each malicious version was the newest release. |
| D2 | §7.4 `MATCH p = shortestPath(...)` | `WITH shortestPath(...) AS p` | FalkorDB allows `shortestPath` only in `WITH` and `RETURN` (checked 2026-10-15). |
| D3 | §7.4 `algo.SPpaths` as an alternative | Filter the returned paths on `CAN_RESOLVE_TO.incident` | `SPpaths` returns paths through the edges of all incidents. |
| D4 | §5.2 step 5: `npm:` aliases are optional | Follow each alias to the aliased package | `@isaacs/cliui` aliases `strip-ansi` and `wrap-ansi`. Both are incident packages. |
| D5 | §5.1 seeds: about 20k | 17,338 seeds: all of `npm-high-impact`. `npmHighImpact` is already the union of the top packages by downloads and by dependents. | No larger primary list is available without BigQuery. The transitive dependency tree has 33.5k versions and 115k dependency edges. |
| D6 | §6.1 any tool-calling LLM; §8 temperature 0 | OpenAI `gpt-6-luna`, at a fixed reasoning effort | The project owner chose this model. See the model notes below. Current reasoning models do not support temperature 0. |
| D7 | Local ports 6379 and 3000 | FalkorDB on `127.0.0.1:6380`, browser on `3001` (`FALKORDB_PORT`, `FALKORDB_BROWSER_PORT`) | Port 3000 is in use on the development machine. |
| D8 | §7.5: collect the affected packages that a repo reaches with `[:DIRECT_DEP\|DEPENDS_ON*0..12]` | Python walks the repo's resolved transitive dependency tree one hop at a time (`fallout/blast.py::Closure`). One query then reads the `CAN_RESOLVE_TO` edges of that tree. | A variable-length pattern enumerates paths, not nodes. On diamond-shaped trees, the number of paths grows very quickly. The walk is linear. Its adjacency list also supplies the override-coverage check and the path to each package. |
| D9 | §7.4: one path per repo, from `EXPOSES.via` | We keep the `via` path. Each repo also gets `paths_by_package`: the shortest path in the tree to each affected package that it reaches. A route that no nested override covers is preferred. | The `via` path can go through a package that an override already mitigates (for example `monorepo-tools` → `eslint` → `debug`). That path does not show why the repo is still exposed (`error-ex`). `plan_fix` needs every affected package in any case. |
| D10 | §5.0 oracle rule "admits" | No change in `oracle.mjs`. We checked that it gives the same result as D1. | Each malicious release had the `latest` tag and was the newest version. Thus "admits" and "would pick" are equivalent here. On the loaded graph, both rules give the same 790 `CAN_RESOLVE_TO` edges. |
| D11 | §8 targets: demo repos + 200 random seeds | Demo repos, 200 seeds sampled uniformly (seed 42), and 300 seeds sampled from the top 3,000 by weekly downloads (seed 43). `eval/dataset.json` records the `stratum` of each target. | Uniform seeds are mostly leaf packages. Only 40 of 2,613 pairs were positive, so the target share of about 40% positive pairs was not reachable. Download rank does not depend on any exposure label. Thus the second stratum adds positive pairs and does not favour the graph. |
| D12 | §6.3 step 1: global `overrides: {P: v}`, nested when ranges conflict | Version-specific overrides `{"P@<affected>": v}`. If P is a direct dependency, we pin it in the manifest instead. Nested overrides are the fallback. | Arborist applies a keyed rule only to edges whose spec intersects the key (`override-set.js` `getEdgeRule`). Thus the rule changes only the edges that admit the malicious version. A global override also forces unrelated edges (`debug@^3.2.7` → 4.x). With conflicting ranges, the spec's method gave nine nested entries for storefront-next. npm rejects an override that changes a root dependency (EOVERRIDE). A pin never intersects the version-specific key. |
| D13 | §4.1 schema | Adds `Plan {id, repo, incident, status, body}` and `(Plan)-[:FOR]->(Repo)` | Plans must persist after the MCP server process stops. The approval endpoint and the executor read plans from the graph. Status changes use compare-and-set. |
| D14 | §6.3 step 2: run `npm install --package-lock-only` on the checkout | The sandbox first removes the lockfile entries at affected versions | If a locked node still satisfies some edge, npm keeps it and does not apply the overrides again. In the LOCKED_MALICIOUS fixture, the hoisted `debug@4.4.2` stayed in place with `"debug@4.4.2": "4.4.1"`. The verification output and the PR body list the removed entries. |
| D15 | §6.1 any tool-calling LLM | `fallout/llm.py`: the OpenAI Responses API, plus `OfflineLLM`. `OfflineLLM` is a scripted planner that routes on keywords. It is used only when `OPENAI_API_KEY` is not set. | The demo and the plumbing can run headless before an API key is available. Every offline answer starts with `[offline mode: scripted planner, no LLM]`. The eval does not use the offline planner. |
| D16 | §5.3 malicious = `MAL-` | A GHSA record whose summary says "malware" or "malicious" counts as malicious. An advisory group can also set the kind. (GHSA-mh6f-8j2x-4483, event-stream, does not say so.) If an unpublished malicious version has no registry time, we use the OSV publish time of the advisory. | The 2018 and 2021 incidents were published as GHSA records, not as MAL records. |
| D17 | §5.3 affected versions from OSV | Most GHSA records give ranges only. We expand these ranges against the registry packument with npm semver (`semver-eval.mjs` `filter`). We drop vulnerable versions published after S. | Those versions did not exist at S. If we kept them, the graph would contain data newer than S. |
| D18 | §6.2 `exposure_path(repo, incident_id)` | `exposure_path(incident_id, repo=None, package=None)`. The target can also be `name` (its version at S) or `name@version`. | The package targets in the eval need the same tool as the repos. |
| D19 | §6.2 `blast_radius(max_hops=8)` | The default is 16 | The replay reaches hop 10. The `cross-spawn-redos` advisory group in the eval reaches hop 13. The result still reports `truncated`. |
| D20 | §3 frontend: React + Vite + TS, sigma.js + graphology, Tailwind | The same stack without Tailwind. One stylesheet based on design tokens (`web/src/styles.css`). The blast graph shows concentric rings by hop (`web/src/layout.ts`), not a force layout. | About a dozen design tokens did not need a framework. The hop count is the main information in the picture, and the rings make it easy to read. |
| D21 | `docker-compose.yml` `FALKORDB_ARGS` with `TIMEOUT 0` | We removed `TIMEOUT` and kept `TIMEOUT_MAX` and `TIMEOUT_DEFAULT`. Compose adds a `seed` service, an `api` service and a build-only `sandbox` service. | FalkorDB 4.22 stops the module load when the deprecated `TIMEOUT` is set together with `TIMEOUT_MAX`. `fallout/db.py` still removes every limit when it connects. |

## Eval protocol notes

After the first full run (2026-10-16), we changed one instruction. Then we added one grading
convention.

The first System C instructions said to copy the tool path "without the repo itself". The agent
then also removed package targets from their own paths. We reworded the instruction and ran all
four systems again. The results were A F1 0.655, B 0.935, C 1.000 and G 1.000. C path validity
was 87.7%, because the agent still removed the first hop in 6 answers. All 6 targets were
peer-dependency plugins.

We did not tune the prompt further against the test set. Instead, the grader now applies one path
convention to every system (`eval/run.py` `normalize_path`). For a repo target, hops start below
the repo. For a package target, hops start at the target itself, and the grader adds the target
if it is missing. We rescored the logged answers with `--regrade`, with no new model calls. The
original path of each answer is kept as `raw_path` in `eval/runs/`. We did not tune labels or
thresholds.

First run, before both changes: A F1 0.655, B 0.943, C 1.000 with path validity 91.8%, and G
1.000 with path validity 95.9%.

## Data-quality rules added during ingest

- Registry spam is pruned (`ingest/crawl.py::prune_spam`). 27 low-ranked seeds belong to a
  token-farming spam cluster. Their names are random words, such as `aloud-giant-draw@5.64.567`,
  and npm has since deleted them. A version is spam when at least 10 of its dependencies no longer
  exist or are spam, and these make up at least 20% of its dependencies. The rule repeats until
  nothing changes. Then we keep only what is reachable from non-spam roots. On the full crawl, the
  prune removed 213 spam versions (455 with orphans). We reviewed every flagged name by hand. The
  list is in `data/raw/crawl/spam.txt`. Without the prune, a spam clique whose members depend on
  each other would distort PageRank.
- The resolver ignores deprecation of a whole package (`workers/resolver.mjs`). deps.dev reports
  the deprecation flags of today, not those at S. If every version is deprecated, the flag cannot
  change the ranking. But it does stop npm-pick-manifest from using the default version (for
  example `@mui/base`).
- Maintainer data stores usernames only. It never stores email addresses.
- Lockfile versions that the crawl never resolved get stub `Version` nodes (`from_lockfile: true`,
  no `published_at`, no `DEPENDS_ON`). This lets `LOCKS` point at them. The demo org has exactly
  one such node: the synthetic `debug@4.4.2`. `ingest_advisory` then marks it malicious.
- Package maintainers and provenance come from the newest version of the package in the graph.
  That version stands in for `latest` at S.
- The graph has 21,006 `Package` nodes, but `summary.json` reports 21,741. The crawl summary
  counts every packument fetched. This includes packages whose candidate versions were all pruned
  as spam or failed with `ETARGET`.

## Operational notes

- The default settings of the FalkorDB image truncate results without a warning.
  `RESULTSET_SIZE 10000` limits result sets, and `TIMEOUT 1000` stops queries after 1 s. On this
  graph, both limits cut the blast radius short. `fallout/db.py` removes the limits on every
  connect, and `docker-compose.yml` sets them for new containers.

## Friday gate: demo repos vs the oracle

`uv run python -m eval.demo_check` writes `eval/demo_check.json`. All 6 demo repos match the
oracle on exposure and on the set of affected packages that they reach. Every hop of every graph
path exists in the oracle's tree. Every shortestPath cross-check has the same length as the path.
The graph's resolved transitive dependency tree and arborist's tree have a Jaccard similarity
between 0.84 and 1.0. Each difference is a peer dependency or the `monorepo-tools` override
(limitations 9 and 10).

## Limitations (to state in the README)

1. `dist-tags.latest` at S is an approximation. We use the highest stable, non-deprecated version
   published at or before S. If no such version exists, deprecated versions count, and then
   prereleases.
2. Deprecation flags are from today, not from S. A version deprecated after S can rank lower than
   npm would have ranked it at S.
3. Versions unpublished between S and today are missing, because deps.dev lists only current
   versions. Malicious versions are the exception. We inject them from OSV and from the registry
   `time` field.
4. The graph does not model npm dedupe or hoisting. Each `(dependent, range)` pair resolves
   independently to the highest matching version.
5. Non-registry specs (git, tarball, `file:`) are counted in `data/raw/crawl/summary.json`, but
   the crawl does not follow them. It does not follow `bundleDependencies` either (502 edges in
   the full crawl).
6. Weekly download counts are current, not as of S. We use them only for weighting and display.
7. The `LOCKED_MALICIOUS` repo is synthetic. The lockfile of `fallout-demo/storefront-next` was
   edited by hand to `debug@4.4.2`.
8. Packages that did not exist at S (283 ETARGET seeds, for example
   `@anthropic-ai/claude-agent-sdk`) are correctly absent from the graph.
9. Peer dependencies resolve independently. The graph resolves a peer range to its highest match
   at S. npm reuses the version that the root already installs. For example,
   `@vitejs/plugin-react` has the peer range `vite@^4||^5||^6||^7`. The graph picks `vite@7.1.5`,
   but npm reuses the root's `vite@5`. This can only add paths. It cannot remove them. It explains
   every node in the demo-repo check that the graph's tree has and the oracle's tree does not.
10. Overrides do not change resolution in the graph. `DEPENDS_ON` is the tree without overrides.
    Overrides are applied when the status is computed (`MITIGATED_BY_OVERRIDE`). For nested
    overrides (`{"a": {"b": {"c": "1"}}}`), only the nearest scope (`b`) is recorded as `parent`.
11. Maintainer reach includes the account's own packages. `reach_packages` counts every package
    that is, or transitively depends on, a package that the account maintains. It uses
    `PKG_DEPENDS_ON` at S. We score the top 300 accounts by summed PageRank (BUILD.md §7.7).
12. The approval session uses a shared console key. `POST /api/session` with
    `FALLOUT_CONSOLE_KEY` sets an HttpOnly cookie signed with HMAC. Used tokens are tracked in
    memory, so a restart forgets them. A restart also rotates the default HMAC secret, which makes
    those tokens invalid anyway.
13. Oracle targets that fail on this platform are excluded. On linux-x64, Arborist refuses
    platform-specific binaries (`@biomejs/cli-darwin-arm64`, `esbuild-linux-s390x`, and others)
    with EBADPLATFORM. `eval/dataset.json` lists them under `oracle_failed`.

## Model notes (researched 2026-10-15)

The requested model was "GPT 6.1 Luna". No such model exists. OpenAI lists GPT-6 Luna, GPT-6 Sol
and GPT-6.1 Sol, so we use `gpt-6-luna`. We compared it with `claude-haiku-5-5`. The details are
in the chat summary from the same day. Check the prices again before the README is written.
