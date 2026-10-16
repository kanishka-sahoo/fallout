import { Check, ChevronRight, ExternalLink, GitPullRequest, GitPullRequestClosed, Loader2, Network } from 'lucide-react'
import { useState } from 'react'
import type { Plan, RepoStatus } from '../api'
import type { PullRequest } from '../api'
import { api, repoName } from '../api'
import { Diff } from '../components/Diff'
import { PathDetail, type Selection } from '../components/Inspector'
import { PageBody, PageHeader, Section } from '../components/Page'
import { STATUS_ORDER, StatusBadge } from '../components/Status'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

type Props = {
  repos: RepoStatus[]
  plans: Plan[]
  sel: Selection | null
  pathId: string | null
  onSelect: (repo: string) => void
  onPath: (id: string) => void
  onClose: () => void
  onShowGraph: () => void
  onApplied: (plan: Plan) => void
  prs: PullRequest[]
  closing: Record<string, boolean>
  onClosePr: (url: string) => Promise<void>
  authed: Authed
}

export type Authed = <T>(fn: () => Promise<T>) => Promise<T>

export function Repositories({ repos, plans, sel, pathId, onSelect, onPath, onClose, onShowGraph, onApplied, prs, closing, onClosePr, authed }: Props) {
  const sorted = [...repos].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || a.repo.localeCompare(b.repo))
  const exposed = repos.filter((r) => r.status !== 'NOT_AFFECTED' && r.status !== 'MITIGATED_BY_OVERRIDE').length
  const open = sel?.kind === 'Repo'
  return (
    <>
      <PageHeader
        title="Repositories"
        description={
          repos.length
            ? `${exposed} of ${repos.length} repos can install a malicious version. Status comes from each repo's lockfile and overrides.`
            : "Status comes from each repo's lockfile and overrides."
        }
      />
      <PageBody>
        {plans.length ? (
          <section className="flex flex-col gap-3" aria-label="Fixes awaiting approval">
            <div>
              <h2 className="text-sm font-semibold">Fixes awaiting approval</h2>
              <p className="mt-1 max-w-[80ch] text-[13px] text-pretty text-muted-foreground">
                Each fix pins the highest safe version published before snapshot time. When you approve, Fallout regenerates the lockfile in a sandbox with no secrets, checks that no affected version
                remains, and opens a pull request. Only a console user can approve. The agent cannot.
              </p>
            </div>
            {plans.map((p) => (
              <ApprovalCard key={p.id} plan={p} onApplied={onApplied} authed={authed} />
            ))}
          </section>
        ) : null}

        {prs.length ? <PullRequests prs={prs} closing={closing} onClose={onClosePr} /> : null}

        <Section title="All repositories" description="Select a repo to see the dependency path to the malicious version.">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">Repository</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden md:table-cell">Affected packages</TableHead>
                <TableHead className="hidden sm:table-cell">Lockfile</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((r) => (
                <TableRow key={r.repo} className="relative cursor-pointer" data-state={sel?.key === `repo:${r.repo}` ? 'selected' : undefined}>
                  <TableCell className="pl-5">
                    <button
                      className="row text-left font-medium after:absolute after:inset-0 focus-visible:outline-none after:focus-visible:ring-2 after:focus-visible:ring-ring after:focus-visible:ring-inset"
                      onClick={() => onSelect(r.repo)}
                    >
                      {repoName(r.repo)}
                    </button>
                    <div className="text-xs text-muted-foreground">{r.repo.replace(/\/[^/]+$/, '')}</div>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={r.status} />
                  </TableCell>
                  <TableCell className="hidden max-w-[360px] md:table-cell">
                    <Packages r={r} />
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground sm:table-cell">{r.has_lockfile ? 'Present' : <span className="text-hot">Missing</span>}</TableCell>
                  <TableCell className="pr-4 text-muted-foreground">
                    <ChevronRight className="size-4" />
                  </TableCell>
                </TableRow>
              ))}
              {sorted.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="py-10 text-center text-muted-foreground">
                    No repo status yet. Replay the incident to compute it.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </Section>

        <Sheet
          open={open}
          onOpenChange={(o) => {
            if (!o) onClose()
          }}
        >
          <SheetContent className="w-full gap-0 sm:max-w-md">
            {sel ? (
              <>
                <SheetHeader className="border-b px-5 py-4">
                  <SheetTitle className="text-base font-semibold">{sel.title}</SheetTitle>
                  <SheetDescription>Path from this repo to the malicious version</SheetDescription>
                  {sel.status ? <StatusBadge status={sel.status} className="mt-2 self-start" /> : null}
                </SheetHeader>
                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                  <PathDetail sel={sel} pathId={pathId} onPath={onPath} />
                </div>
                <SheetFooter className="border-t px-5 py-3">
                  <Button variant="outline" onClick={onShowGraph} disabled={!sel.paths.length}>
                    <Network data-icon="inline-start" />
                    Show on graph
                  </Button>
                </SheetFooter>
              </>
            ) : null}
          </SheetContent>
        </Sheet>
      </PageBody>
    </>
  )
}

function Packages({ r }: { r: RepoStatus }) {
  const locked = new Set(r.locked_affected.map((k) => k.replace(/^npm:/, '').replace(/@[^@]+$/, '')))
  if (!r.affected_packages.length && !r.locked_affected.length) return <span className="text-muted-foreground">None reached</span>
  const names = r.locked_affected.length ? r.locked_affected.map((k) => k.replace(/^npm:/, '')) : r.affected_packages
  return (
    <div className="flex flex-wrap gap-1">
      {names.map((n) => {
        const mitigated = r.mitigated_packages.includes(n)
        return (
          <code
            key={n}
            className={cn('rounded border px-1.5 py-px text-xs', locked.has(n.replace(/@[^@]+$/, '')) && 'border-hot/30 bg-hot/5 text-hot', mitigated && 'text-muted-foreground line-through')}
            title={mitigated ? 'Mitigated by an override' : undefined}
          >
            {n}
          </code>
        )
      })}
    </div>
  )
}

function ApprovalCard({ plan, onApplied, authed }: { plan: Plan; onApplied: (plan: Plan) => void; authed: Authed }) {
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<{ ok: boolean; text: string; pr?: string; before?: string; after?: string } | null>(null)

  const approve = async () => {
    setBusy(true)
    setOutcome(null)
    try {
      const r = await authed(() => api.approve(plan.id))
      const rc = r.recheck?.result
      setOutcome({
        ok: r.result === 'PR_OPENED',
        text: r.result === 'PR_OPENED' ? 'Pull request opened. Verification passed.' : `Verification failed. Affected versions remain: ${r.verification?.affected_found?.join(', ')}`,
        pr: r.pr_url,
        before: rc?.before?.status,
        after: rc?.after?.status,
      })
      onApplied(plan)
    } catch (e) {
      const msg = String((e as Error).message)
      if (msg !== 'cancelled') setOutcome({ ok: false, text: msg.replace(/^\d+: /, '') })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card overflow-hidden rounded-lg border bg-card" role="region" aria-label={`Fix awaiting approval for ${repoName(plan.repo)}`}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-5 py-3">
        <GitPullRequest className="size-4 text-muted-foreground" aria-hidden />
        <h3 className="text-sm font-semibold">Fix for {repoName(plan.repo)}</h3>
        {plan.body.status_before ? <StatusBadge status={plan.body.status_before} /> : null}
        <span className="ml-auto flex items-center gap-2">
          <code className="hidden text-xs text-muted-foreground sm:inline">{plan.id}</code>
          <Button className="approve" disabled={busy || outcome?.ok === true} onClick={approve}>
            {outcome?.ok ? <Check data-icon="inline-start" /> : null}
            {busy ? 'Opening pull request…' : outcome?.ok ? 'Approved' : 'Approve fix'}
          </Button>
        </span>
      </header>
      {outcome ? (
        <div className={cn('outcome border-b px-5 py-3 text-[13px]', outcome.ok ? 'bg-safe/8 text-safe' : 'bg-hot/6 text-hot')} role="status">
          {outcome.text}{' '}
          {outcome.pr ? (
            <a className="inline-flex items-center gap-1 font-medium text-foreground underline underline-offset-2" href={outcome.pr} target="_blank" rel="noreferrer">
              {outcome.pr.replace('https://github.com/', '')}
              <ExternalLink className="size-3" />
            </a>
          ) : null}
          {outcome.before && outcome.after ? (
            <div className="flip mt-2 flex flex-wrap items-center gap-2 text-muted-foreground">
              <StatusBadge status={outcome.before} />
              <ChevronRight className="size-4" aria-label="changed to" />
              <StatusBadge status={outcome.after} />
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="grid gap-4 p-5 lg:grid-cols-2">
        {plan.body.packages.length ? (
          <ul className="flex flex-col divide-y self-start rounded-md border text-[13px]">
            {plan.body.packages.map((x) => (
              <li key={x.package} className="flex flex-col gap-0.5 px-3 py-2">
                <code className="font-medium">
                  {x.package}
                  {x.version ? `@${x.version}` : ''}
                </code>
                <span className="text-xs text-pretty text-muted-foreground">
                  {x.reason || (x.requirements?.length ? `Required as ${x.requirements.slice(0, 2).map((r) => `${r.requirement} by ${r.parent_name}`).join(', ')}${x.requirements.length > 2 ? ` and ${x.requirements.length - 2} more` : ''}` : x.strategy)}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        <Diff changes={plan.body.changes} />
      </div>
    </section>
  )
}

const PR_TONE: Record<PullRequest['state'], string> = {
  open: 'bg-safe/10 text-safe',
  merged: 'bg-violet-500/10 text-violet-600 dark:text-violet-400',
  closed: 'bg-muted text-muted-foreground',
  unknown: 'bg-muted text-muted-foreground',
}

function PullRequests({ prs, closing, onClose }: { prs: PullRequest[]; closing: Record<string, boolean>; onClose: (url: string) => Promise<void> }) {
  const open = prs.filter((p) => p.state === 'open').length
  return (
    <Section title="Pull requests" description={`${open} open. Delete PR closes it on GitHub, deletes its branch, puts the repo back on its default branch and removes every record of it from Fallout. GitHub keeps the closed PR, because its API cannot delete one.`}>
      <ul className="divide-y">
        {prs.map((p) => (
          <li key={p.pr_url} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-5 py-3">
            {p.state === 'open' ? <GitPullRequest className="size-4 text-safe" aria-hidden /> : <GitPullRequestClosed className="size-4 text-muted-foreground" aria-hidden />}
            <a href={p.pr_url} target="_blank" rel="noreferrer" className="min-w-0 text-sm font-medium hover:underline">
              {repoName(p.repo)} <span className="text-muted-foreground">#{p.number}</span>
            </a>
            <span className={cn('inline-flex h-5 items-center rounded-full px-2 text-xs font-medium capitalize', PR_TONE[p.state])}>{p.state}</span>
            <span className="text-xs text-muted-foreground">
              {new Date(p.created_at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
              {p.approved_by ? `, approved by ${p.approved_by}` : ''}
            </span>
            <span className="ml-auto flex items-center gap-1">
              <a href={p.pr_url} target="_blank" rel="noreferrer" className="inline-flex h-7 items-center gap-1 rounded-md px-2.5 text-[0.8rem] font-medium transition-colors hover:bg-muted [&_svg]:size-3.5">
                <ExternalLink />View
              </a>
              {p.state !== 'merged' ? (
                <Button variant="outline" size="sm" onClick={() => onClose(p.pr_url)} disabled={closing[p.pr_url]} title="Close it on GitHub, delete its branch and remove every record of it from Fallout">
                  {closing[p.pr_url] ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <GitPullRequestClosed data-icon="inline-start" />}
                  {closing[p.pr_url] ? 'Deleting…' : 'Delete PR'}
                </Button>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  )
}
