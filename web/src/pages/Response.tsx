import { CircleCheck, ExternalLink, GitPullRequest, GitPullRequestClosed, Loader2, Network } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { PullRequest, ResponsePlan } from '../api'
import { api, repoName } from '../api'
import { CopyButton, Diff } from '../components/Diff'
import { PageBody, PageHeader } from '../components/Page'
import { StatusBadge } from '../components/Status'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const WHY: Record<string, string> = {
  LOCKED_MALICIOUS: 'The lockfile pins an affected version. The next install from the lockfile gets it.',
  EXPOSED_NO_LOCKFILE: 'There is no lockfile, so every install resolves the ranges again and picks the affected version.',
  RANGE_ADMITS_LOCK_SAFE: 'The lockfile is safe today, but a fresh resolve (npm update, a new lockfile, a bot PR) picks the affected version.',
}

type Props = {
  incident: string
  simulated: boolean
  version: number // changes when the incident is recomputed, so the plan reloads
  prs: PullRequest[] // this incident's pull requests
  progress: Record<string, string> // repo key -> step of a running Create PR
  closing: Record<string, boolean> // PR URL -> closing
  onCreatePr: (repo: string) => Promise<void>
  onClosePr: (url: string) => Promise<void>
  onAskFix: (repo: string) => void
  onShowPath: (repo: string) => void
}

export function Response({ incident, simulated, version, prs, progress, closing, onCreatePr, onClosePr, onShowPath }: Props) {
  const [plan, setPlan] = useState<ResponsePlan | null>(null)
  const [err, setErr] = useState<string | null>(null)
  // A new incident clears the page. A recompute of the same incident keeps the old plan on screen until the new one arrives.
  useEffect(() => {
    if (!incident) return
    let live = true
    setPlan((p) => (p?.incident === incident ? p : null))
    setErr(null)
    api.response(incident)
      .then((x) => live && setPlan(x))
      .catch((e) => live && setErr(String(e.message).replace(/^\d+: /, '')))
    return () => { live = false }
  }, [incident, version])

  const todo = plan?.repos.filter((r) => r.plan) ?? []
  const failed = plan?.repos.filter((r) => !r.plan && r.error) ?? []
  const fine = plan?.repos.filter((r) => !r.plan && !r.error) ?? []
  const overrides = plan && Object.keys(plan.overrides).length ? JSON.stringify({ overrides: plan.overrides }, null, 2) : null
  const openPr = (repo: string) => prs.find((p) => p.repo === repo && p.state === 'open')
  const creatable = todo.filter((r) => r.plan?.fixable && !openPr(r.repo) && !progress[r.repo])
  const busy = Object.keys(progress).length > 0
  const createAll = async () => {
    for (const r of creatable) await onCreatePr(r.repo)
  }

  return (
    <>
      <PageHeader
        title="Response plan"
        description={
          simulated
            ? 'What each repo would have to change if this scenario happened. Create PR blocks the versions before anyone publishes them. Each fix is verified in a sandbox first.'
            : 'What each repo must change to remove the affected versions, in priority order. Create PR verifies the fix in a sandbox, then opens a pull request in the repo.'
        }
      />
      <PageBody>
        {err ? <p className="rounded-lg border border-hot/30 bg-hot/5 px-4 py-3 text-sm text-hot">{err}</p> : null}
        {!plan && !err ? <Loading /> : null}
        {plan ? (
          <>
            <dl className="grid grid-cols-3 overflow-hidden rounded-lg border bg-card" aria-label="Summary">
              {([
                ['Repos to fix', plan.needs_action, plan.needs_action ? 'var(--hot)' : undefined],
                ['Packages to replace', Object.keys(plan.safe_versions).length],
                ['Repos not affected', fine.length, 'var(--safe)'],
              ] as [string, number, string?][]).map(([label, value, dot]) => (
                <div key={label} className="flex flex-col gap-1.5 px-5 py-4 not-last:border-r">
                  <dt className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
                    {dot ? <span className="size-1.5 rounded-full" style={{ background: dot }} aria-hidden /> : null}
                    {label}
                  </dt>
                  <dd className="figure text-[28px] leading-none font-semibold">{value}</dd>
                </div>
              ))}
            </dl>

            {!todo.length && !failed.length ? (
              <section className="flex flex-col items-center gap-2 rounded-lg border bg-card px-6 py-12 text-center">
                <CircleCheck className="size-6 text-safe" aria-hidden />
                <h2 className="font-medium">No repo needs action</h2>
                <p className="max-w-md text-sm text-muted-foreground">None of your repos can install an affected version, or an existing override already covers every path.</p>
              </section>
            ) : null}

            {overrides ? (
              <section className="overflow-hidden rounded-lg border bg-card" aria-label="Block the affected versions everywhere">
                <header className="flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4">
                  <div className="max-w-[72ch]">
                    <h2 className="text-sm font-semibold">Block the affected versions everywhere</h2>
                    <p className="mt-1 text-[13px] text-pretty text-muted-foreground">
                      One overrides block that covers every repo below. Add it to each package.json and run <code>npm install</code>. It replaces only the affected versions, so other ranges on the same packages do not change.
                    </p>
                  </div>
                  <CopyButton text={overrides} label="Copy block" />
                </header>
                <pre className="overflow-x-auto bg-muted/30 px-5 py-4 font-mono text-xs leading-5">{overrides}</pre>
              </section>
            ) : null}

            {todo.length ? (
              <section className="flex flex-col gap-3" aria-label="Fix each repo">
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold">Fix each repo</h2>
                    <p className="mt-1 text-[13px] text-muted-foreground">Worst first: a malicious version in a lockfile, then repos with no lockfile, then repos that a fresh resolve would expose.</p>
                  </div>
                  {creatable.length > 1 ? (
                    <Button variant="outline" onClick={createAll} disabled={busy}>
                      <GitPullRequest data-icon="inline-start" />Create {creatable.length} PRs
                    </Button>
                  ) : null}
                </div>
                <ol className="flex flex-col gap-3">
                  {todo.map((r, i) => (
                    <li key={r.repo} className="overflow-hidden rounded-lg border bg-card">
                      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-5 py-3">
                        <span className="flex size-6 items-center justify-center rounded-full bg-muted text-xs font-medium tabular" aria-label={`Priority ${i + 1}`}>{i + 1}</span>
                        <h3 className="text-sm font-semibold">{repoName(r.repo)}</h3>
                        <StatusBadge status={r.status} />
                        <span className="ml-auto flex flex-wrap items-center gap-2">
                          <Button variant="ghost" onClick={() => onShowPath(r.repo)}><Network data-icon="inline-start" />Show path</Button>
                          <PrActions repo={r.repo} pr={openPr(r.repo)} progress={progress[r.repo]} closing={closing} fixable={!!r.plan?.fixable} onCreate={onCreatePr} onClose={onClosePr} />
                        </span>
                      </header>
                      <div className="grid gap-4 p-5 lg:grid-cols-2">
                        <div className="flex flex-col gap-3">
                          <p className="text-[13px] text-pretty text-muted-foreground">{WHY[r.status]}</p>
                          <ul className="flex flex-col divide-y rounded-md border text-[13px]">
                            {r.plan!.packages.map((x) => (
                              <li key={x.package} className="flex flex-col gap-0.5 px-3 py-2">
                                <span className="flex items-baseline gap-2">
                                  <code className={cn('font-medium', !x.version && 'text-hot')}>{x.package}{x.version ? `@${x.version}` : ''}</code>
                                  <span className="text-xs text-muted-foreground">{x.strategy === 'pin' ? 'pin' : x.strategy === 'scoped' ? 'nested override' : x.strategy === 'unresolved' ? 'no safe version' : 'override'}</span>
                                </span>
                                {x.reason ? <span className="text-xs text-pretty text-hot">{x.reason}</span> : x.requirements?.length ? (
                                  <span className="text-xs text-pretty text-muted-foreground">
                                    Required as {x.requirements.slice(0, 2).map((q) => `${q.requirement} by ${q.parent_name}`).join(', ')}
                                    {x.requirements.length > 2 ? ` and ${x.requirements.length - 2} more` : ''}
                                  </span>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        </div>
                        <Diff changes={r.plan!.changes} />
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}

            {failed.map((r) => (
              <p key={r.repo} className="rounded-lg border border-hot/30 bg-hot/5 px-4 py-3 text-[13px] text-hot">
                Could not plan a fix for {repoName(r.repo)}: {r.error}
              </p>
            ))}

            {fine.length ? (
              <section className="overflow-hidden rounded-lg border bg-card" aria-label="Not affected">
                <header className="border-b px-5 py-4">
                  <h2 className="text-sm font-semibold">No action needed</h2>
                </header>
                <ul className="divide-y">
                  {fine.map((r) => (
                    <li key={r.repo} className="flex flex-wrap items-center gap-3 px-5 py-2.5 text-sm">
                      <span className="min-w-0 flex-1 font-medium">{repoName(r.repo)}</span>
                      {openPr(r.repo) ? <PrActions repo={r.repo} pr={openPr(r.repo)} progress={undefined} closing={closing} fixable={false} onCreate={onCreatePr} onClose={onClosePr} /> : null}
                      <StatusBadge status={r.status} />
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        ) : null}
      </PageBody>
    </>
  )
}

function PrActions({ repo, pr, progress, closing, fixable, onCreate, onClose }: { repo: string; pr?: PullRequest; progress?: string; closing: Record<string, boolean>; fixable: boolean; onCreate: (repo: string) => Promise<void>; onClose: (url: string) => Promise<void> }) {
  if (progress)
    return (
      <span className="flex h-8 items-center gap-2 rounded-lg border bg-muted/50 px-3 text-[13px] text-muted-foreground" role="status">
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
        {progress}
      </span>
    )
  if (pr)
    return (
      <span className="flex items-center gap-1">
        <a href={pr.pr_url} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] font-medium text-safe transition-colors hover:bg-safe/10">
          <GitPullRequest className="size-3.5" aria-hidden />PR #{pr.number}<ExternalLink className="size-3 opacity-70" aria-hidden />
        </a>
        <Button variant="ghost" onClick={() => onClose(pr.pr_url)} disabled={closing[pr.pr_url]} title="Close it on GitHub, delete its branch and remove every record of it from Fallout">
          {closing[pr.pr_url] ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <GitPullRequestClosed data-icon="inline-start" />}
          {closing[pr.pr_url] ? 'Deleting…' : 'Delete PR'}
        </Button>
      </span>
    )
  return (
    <Button onClick={() => onCreate(repo)} disabled={!fixable} title={fixable ? 'Verify the fix in a sandbox, then open a pull request' : 'No safe version satisfies every range'}>
      <GitPullRequest data-icon="inline-start" />Create PR
    </Button>
  )
}

function Loading() {
  return (
    <div className="flex flex-col gap-4" aria-label="Loading">
      <div className="h-[86px] animate-pulse rounded-lg border bg-card" />
      <div className="h-40 animate-pulse rounded-lg border bg-card" />
      <div className="h-64 animate-pulse rounded-lg border bg-card" />
    </div>
  )
}
