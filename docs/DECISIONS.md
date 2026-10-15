# Decisions, deviations and limitations

A running log of every place the build departs from [BUILD.md](BUILD.md), and of every
known approximation. The README's Limitations section is generated from this file.

## Deviations from BUILD.md

| # | Spec | What we do instead | Why |
|---|---|---|---|
| D1 | §5.0, §7.2: a target is exposed when a requirement *admits* an affected version | Exposed ⇔ the version npm **would pick** is affected. For MAL advisories: resolve with the malicious versions injected, as of just after their publish. For VULN advisories: the resolved-at-S version is in the affected set. The oracle uses the same rule. | Under the spec's rule, `^4.0.0` "admits" `lodash@4.17.20`, so nearly every target is exposed to every VULN advisory. For the chalk/debug replay both rules agree, because each malicious version was the newest release. |
| D2 | §7.4 `MATCH p = shortestPath(...)` | `WITH shortestPath(...) AS p` | FalkorDB only allows `shortestPath` in `WITH`/`RETURN` (checked 2026-10-15). |
| D3 | §7.4 `algo.SPpaths` as an alternative | Filter returned paths by `CAN_RESOLVE_TO.incident` | `SPpaths` returns paths through every incident's edges. |
| D4 | §5.2 step 5: `npm:` aliases optional | Followed to the aliased package | `@isaacs/cliui` aliases `strip-ansi`/`wrap-ansi`, both incident packages. |
| D5 | §5.1 seeds: ~20k | 17,338: all of `npm-high-impact` (`npmHighImpact` is already the union of top-by-downloads and top-by-dependents) | No larger primary list without BigQuery. The closure is 33.5k versions and 115k dependency edges. |
| D6 | §6.1 any tool-calling LLM; §8 temperature 0 | OpenAI `gpt-6-luna`, at a fixed reasoning effort | The user's choice. See the model notes below. Temperature 0 is not available on current reasoning models. |
| D7 | Local ports 6379/3000 | FalkorDB on `127.0.0.1:6380`, browser on `3001` (`FALKORDB_PORT`, `FALKORDB_BROWSER_PORT`) | Port 3000 is taken on the dev machine. |
| D8 | §7.5: gather a repo's reachable affected packages with `[:DIRECT_DEP\|DEPENDS_ON*0..12]` | Walk the repo's resolved closure hop by hop from Python (`fallout/blast.py::Closure`), then read its `CAN_RESOLVE_TO` edges in one query | A variable-length pattern enumerates paths, not nodes, so it blows up on diamond-shaped trees. The closure walk is linear and its adjacency also gives the override-coverage check and the per-package paths. |
| D9 | §7.4: one path per repo, from `EXPOSES.via` | The `via` path is kept, and each repo also gets `paths_by_package`: the shortest closure path to every affected package it reaches, preferring a route that no scoped override covers | The `via` path can run through a package an override already mitigates (e.g. `monorepo-tools` → `eslint` → `debug`), which hides why the repo is still exposed (`error-ex`). `plan_fix` needs every affected package anyway. |
| D10 | §5.0 oracle rule "admits" | Unchanged in `oracle.mjs`, checked equal to D1 | Each malicious release was tagged `latest` and was the newest version, so "admits" ⇔ "would pick". Measured on the loaded graph: both rules give the same 790 `CAN_RESOLVE_TO` edges. |

## Data-quality rules added during ingest

- **Registry spam prune** (`ingest/crawl.py::prune_spam`). 27 low-ranked seeds belong to a
  token-farming spam cluster, made of word-salad names like `aloud-giant-draw@5.64.567` that npm has since
  deleted. A version is spam when **at least 10** of its dependencies, making up at least **20%** of them,
  no longer exist or are spam themselves. The rule is iterated to a fixed point, and then only what
  is reachable from non-spam roots is kept. On the full crawl it removed 213 spam versions (455 with
  orphans), and every flagged name was reviewed by hand. The list is written to `data/raw/crawl/spam.txt`.
  Without the prune, a mutually-dependent spam clique would distort PageRank.
- **Whole-package deprecation is ignored when resolving** (`workers/resolver.mjs`). deps.dev reports
  today's deprecation flags, not the flags at S. When *every* version is deprecated, the flag cannot
  change the ranking, but it does stop npm-pick-manifest from using the default version (e.g. `@mui/base`).
- **Maintainer data stores usernames only, never emails.**
- **Lockfile versions the crawl never resolved get stub `Version` nodes** (`from_lockfile: true`, no
  `published_at`, no `DEPENDS_ON`), so `LOCKS` can point at them. In the demo org that is exactly one
  node: the synthetic `debug@4.4.2`, which `ingest_advisory` then marks malicious.
- **Package maintainers and provenance come from the package's newest version in the graph**, which
  stands in for the `latest` at S.
- **Graph `Package` count is 21,006; `summary.json` says 21,741.** The crawl summary counts every
  packument fetched, including packages whose only candidate versions were pruned as spam or hit
  `ETARGET`.

## Operational notes

- **FalkorDB's image defaults truncate silently**: `RESULTSET_SIZE 10000` caps result sets and
  `TIMEOUT 1000` kills queries after 1 s. Both cut the blast radius short on this graph.
  `fallout/db.py` lifts them on every connect, and `docker-compose.yml` sets them for new containers.

## Friday gate: demo repos vs the oracle

`uv run python -m eval.demo_check` writes `eval/demo_check.json`. All 6 demo repos match the
oracle on exposure and on the set of affected packages they reach. Every hop of every graph path
exists in the oracle's tree, and every shortestPath cross-check has the same length as the path.
The graph's resolved closure and arborist's tree agree with a Jaccard similarity between 0.84 and 1.0; every difference is a
peer dependency or the `monorepo-tools` override (limitations 4 and 9).

## Limitations (to state in the README)

1. **`dist-tags.latest` at S is approximated.** It is the highest stable, non-deprecated version
   published at or before S. If there is none, deprecated versions count, then prereleases.
2. **Deprecation flags are today's, not S's.** A version deprecated after S may rank lower than npm
   would have ranked it at S.
3. **Versions unpublished between S and today are missing**, because deps.dev lists only current
   versions. Malicious versions are the exception: they are injected from OSV and the registry
   `time` field.
4. **npm dedupe and hoisting are not modelled.** Each `(dependent, range)` resolves independently
   to the highest matching version.
5. **Non-registry specs** (git, tarball, `file:`) are counted in `data/raw/crawl/summary.json`
   but not followed. `bundleDependencies` are not followed either (502 edges in the full crawl).
6. **Weekly download counts are current, not as of S.** They are used only for weighting and display.
7. **The `LOCKED_MALICIOUS` repo is synthetic.** `fallout-demo/storefront-next`'s lockfile is
   hand-edited to `debug@4.4.2`.
8. **Packages that did not exist at S** (283 ETARGET seeds, e.g. `@anthropic-ai/claude-agent-sdk`)
   are correctly absent from the graph.
9. **Peer dependencies resolve independently.** The graph resolves a peer range to its highest
   match at S, while npm reuses the version the root already installs (e.g. `@vitejs/plugin-react`
   peers on `vite@^4||^5||^6||^7`: the graph picks `vite@7.1.5`, npm reuses the root's `vite@5`).
   This can only add paths, never remove them, and it explains every closure node in the
   demo-repo check that the oracle does not have.
10. **Overrides do not change resolution in the graph.** `DEPENDS_ON` is the un-overridden tree, and
    overrides are applied when computing status (`MITIGATED_BY_OVERRIDE`). In nested overrides
    (`{"a": {"b": {"c": "1"}}}`), only the nearest scope (`b`) is recorded as `parent`.

## Model notes (researched 2026-10-15)

Requested as "GPT 6.1 Luna". No such model exists: OpenAI lists GPT-6 Luna, GPT-6 Sol and
GPT-6.1 Sol, so we use **`gpt-6-luna`**. The comparison was with **`claude-haiku-5-5`**. Details are
in the chat summary from the same day; re-check prices before the README.
