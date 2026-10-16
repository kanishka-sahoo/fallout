import { useState } from 'react'
import type { Plan, RepoStatus } from '../api'
import { api, repoName, statusLabel } from '../api'

type Props = {
  repos: RepoStatus[]
  plans: Plan[]
  selected: string | null
  onSelect: (repo: string) => void
  onApplied: (plan: Plan) => void
}

const ORDER = ['LOCKED_MALICIOUS', 'EXPOSED_NO_LOCKFILE', 'RANGE_ADMITS_LOCK_SAFE', 'MITIGATED_BY_OVERRIDE', 'NOT_AFFECTED']
const label = statusLabel

export function Repos({ repos, plans, selected, onSelect, onApplied }: Props) {
  const sorted = [...repos].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || a.repo.localeCompare(b.repo))
  return (
    <>
      {plans.map((p) => <ApprovalCard key={p.id} plan={p} onApplied={onApplied} />)}
      <h3>Your repos</h3>
      <p className="note">Status is based on the lockfile and overrides of each repo. Select a repo to see the dependency path to the malicious version.</p>
      <ul className="repos">
        {sorted.map((r) => (
          <li key={r.repo} data-selected={selected === `repo:${r.repo}`}>
            <button className="row" onClick={() => onSelect(r.repo)}>
              <span className="name">{repoName(r.repo)}</span>
              <span className="status" data-s={r.status}>{label(r.status)}</span>
              <span className="pkgs">
                {r.locked_affected.length
                  ? `Lockfile pins ${r.locked_affected.map((k) => k.replace('npm:', '')).join(', ')}`
                  : r.affected_packages.length
                    ? `Reaches ${r.affected_packages.join(', ')}${r.mitigated_packages.length ? ` (overridden: ${r.mitigated_packages.join(', ')})` : ''}`
                    : 'No affected package reached'}
                {r.has_lockfile ? '' : '. No lockfile.'}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}

function ApprovalCard({ plan, onApplied }: { plan: Plan; onApplied: (plan: Plan) => void }) {
  const [key, setKey] = useState('')
  const [needKey, setNeedKey] = useState(false)
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<{ ok: boolean; text: string; pr?: string; before?: string; after?: string } | null>(null)

  const approve = async () => {
    setBusy(true)
    setOutcome(null)
    try {
      if (needKey) await api.session(key, 'console')
      const r = await api.approve(plan.id)
      const rc = r.recheck?.result
      setOutcome({ ok: r.result === 'PR_OPENED', text: r.result === 'PR_OPENED' ? 'Pull request opened. Verification passed.' : `Verification failed. Affected versions remain: ${r.verification?.affected_found?.join(', ')}`, pr: r.pr_url, before: rc?.before?.status, after: rc?.after?.status })
      onApplied(plan)
    } catch (e) {
      const msg = String((e as Error).message)
      if (msg.startsWith('401')) {
        setNeedKey(true)
        setOutcome({ ok: false, text: 'Enter the console key to approve this fix. Only a console user can approve fixes. The agent cannot approve.' })
      } else setOutcome({ ok: false, text: msg })
    } finally {
      setBusy(false)
    }
  }

  const changes = plan.body.changes
  return (
    <div className="card" role="region" aria-label={`Fix awaiting approval for ${repoName(plan.repo)}`}>
      <h4>Awaiting approval: fix for {repoName(plan.repo)}</h4>
      <p className="note">
        This fix pins the highest safe version published before snapshot time (S). When you approve, Fallout regenerates the lockfile in a sandbox with no secrets. It then verifies that no affected version remains and opens a pull request.
      </p>
      <pre>{JSON.stringify({ ...(Object.keys(changes.pin).length ? { dependencies: Object.fromEntries(Object.entries(changes.pin).map(([k, v]) => [k, v.to])) } : {}), overrides: changes.overrides }, null, 2)}</pre>
      <div className="actions">
        {needKey ? <input type="password" placeholder="Console key" value={key} onChange={(e) => setKey(e.target.value)} aria-label="Console key" /> : null}
        <button className="btn approve" disabled={busy || outcome?.ok === true} onClick={approve}>
          {busy ? 'Opening pull request…' : 'Approve fix'}
        </button>
        <span className="id" style={{ color: 'var(--slate)', fontSize: 12 }}>{plan.id}</span>
      </div>
      {outcome ? (
        <div className={`outcome ${outcome.ok ? '' : 'err'}`}>
          {outcome.text} {outcome.pr ? <a href={outcome.pr} target="_blank" rel="noreferrer">{outcome.pr.replace('https://github.com/', '')}</a> : null}
          {outcome.before && outcome.after ? (
            <div className="flip">
              <span className="status" data-s={outcome.before}>{label(outcome.before)}</span>
              <span aria-hidden>to</span>
              <span className="status" data-s={outcome.after}>{label(outcome.after)}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
