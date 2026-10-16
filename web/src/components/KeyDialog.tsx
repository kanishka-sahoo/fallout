import { KeyRound } from 'lucide-react'
import { useRef, useState } from 'react'
import { api } from '../api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

// Asks for the console key once. The API then sets an 8-hour session cookie, so later
// pull request actions are one click.
export function KeyDialog({ onDone }: { onDone: (ok: boolean) => void }) {
  const [key, setKey] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const submit = async () => {
    if (!key) return
    setBusy(true)
    try {
      await api.session(key, 'console')
      onDone(true)
    } catch {
      setErr('That key is not right. It is FALLOUT_CONSOLE_KEY in .env, or the key the API printed at startup.')
      input.current?.select()
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-6 animate-in fade-in duration-150 dark:bg-black/60" role="dialog" aria-modal="true" aria-labelledby="key-title" onKeyDown={(e) => e.key === 'Escape' && onDone(false)}>
      <form className="w-full max-w-sm rounded-xl border bg-popover p-5 shadow-xl animate-in zoom-in-95 duration-150" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <div className="flex items-center gap-2">
          <KeyRound className="size-4 text-muted-foreground" aria-hidden />
          <h2 id="key-title" className="text-sm font-semibold">Console key</h2>
        </div>
        <p className="mt-2 text-[13px] text-pretty text-muted-foreground">Pull requests change real repos, so only a console user can open or close them. Enter the key once. It lasts 8 hours.</p>
        <Input ref={input} autoFocus type="password" value={key} onChange={(e) => { setKey(e.target.value); setErr(null) }} placeholder="FALLOUT_CONSOLE_KEY" className="mt-4 h-9" aria-label="Console key" aria-invalid={!!err} />
        {err ? <p className="mt-2 text-xs text-hot">{err}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => onDone(false)}>Cancel</Button>
          <Button type="submit" disabled={!key || busy}>{busy ? 'Checking…' : 'Continue'}</Button>
        </div>
      </form>
    </div>
  )
}
