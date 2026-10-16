import { ArrowUp, Route, SquarePen, Wrench, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Answer, Path } from '../api'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { cn } from '@/lib/utils'

export type Msg = { role: 'user' | 'agent'; text: string; answer?: Answer }

type Props = {
  messages: Msg[]
  pending: boolean
  model: string
  known: Record<string, Path>
  simulated: boolean
  onSend: (text: string) => void
  onCite: (answer: Answer, pathId: string) => void
  onClear: () => void
  onClose: () => void
}

const SIM_SUGGESTIONS = [
  'Which of my repos does this scenario hit, and how?',
  'Which repo should we fix first, and why?',
  'Which packages spread it the furthest?',
]

const SUGGESTIONS = [
  'Why is billing-api affected?',
  'Which repos need action first, and why?',
  'Fix billing-api',
  'Which packages are the most critical?',
]

// Render inline code and bold text only. Agent answers use short Markdown.
function Body({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g)
  return (
    <div className="text-sm leading-relaxed whitespace-pre-wrap text-pretty">
      {parts.map((p, i) =>
        p.startsWith('`') ? <code key={i} className="rounded bg-muted px-1 py-px">{p.slice(1, -1)}</code> : p.startsWith('**') ? <strong key={i} className="font-semibold">{p.slice(2, -2)}</strong> : p,
      )}
    </div>
  )
}

export function Agent({ messages, pending, model, known, simulated, onSend, onCite, onClear, onClose }: Props) {
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages, pending])
  useEffect(() => input.current?.focus(), [])

  const submit = () => {
    if (!text.trim() || pending) return
    onSend(text.trim())
    setText('')
  }

  return (
    <section className="flex h-full min-h-0 flex-col bg-background" aria-label="Ask the agent">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b px-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">Agent</h2>
          <p className="truncate text-xs text-muted-foreground">{model === 'offline' ? 'Offline planner. Add an LLM key for full answers.' : model === 'openai' ? 'Answers from graph tools, using OpenAI' : 'Answers from graph tools'}</p>
        </div>
        {messages.length ? (
          <Button variant="ghost" size="sm" onClick={onClear} disabled={pending} title="Clear the conversation and start again">
            <SquarePen data-icon="inline-start" />New chat
          </Button>
        ) : null}
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close agent"><X /></Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
        {messages.length === 0 ? (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-pretty text-muted-foreground">
              Ask about exposure, dependency paths or fixes. Every answer comes from graph tool results and cites the paths those tools returned. Select a cited path to see it on the graph.
            </p>
            <ul className="flex flex-col gap-1.5">
              {(simulated ? SIM_SUGGESTIONS : SUGGESTIONS).map((s) => (
                <li key={s}>
                  <button className="w-full rounded-md border px-3 py-2 text-left text-sm transition-colors hover:bg-accent disabled:opacity-50" onClick={() => onSend(s)} disabled={pending}>{s}</button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <div className="flex flex-col gap-5">
          {messages.map((m, i) =>
            m.role === 'user' ? (
              <div key={i} className="msg user ml-8 self-end rounded-lg rounded-br-sm bg-secondary px-3 py-2 text-sm">{m.text}</div>
            ) : (
              <div key={i} className="msg agent flex flex-col gap-2.5">
                <Body text={m.text} />
                {m.answer?.cited_path_ids.length ? (
                  <div className="cites flex flex-wrap gap-1.5" aria-label="Cited paths">
                    {m.answer.cited_path_ids.map((id) => {
                      const unknown = !m.answer!.paths[id] && !known[id]
                      return (
                        <button
                          key={id}
                          disabled={unknown}
                          className={cn(
                            'inline-flex h-6 items-center gap-1 rounded-md border px-2 font-mono text-[11px] transition-colors hover:bg-accent',
                            unknown && 'cursor-not-allowed border-dashed border-hot/50 text-hot hover:bg-transparent',
                          )}
                          title={unknown ? 'Unverified. No tool returned this path in this session.' : 'Show this path on the graph'}
                          onClick={() => onCite(m.answer!, id)}
                        >
                          <Route className="size-3" aria-hidden />
                          {id}
                        </button>
                      )
                    })}
                  </div>
                ) : null}
                {m.answer ? (
                  <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                    <Wrench className="mt-0.5 size-3 shrink-0" aria-hidden />
                    <span>
                      {m.answer.tool_calls.map((t) => t.name).join(', ') || 'No tools called'} in {(m.answer.took_ms / 1000).toFixed(1)}s
                      {m.answer.offline ? ' (offline planner)' : ''}
                    </span>
                  </p>
                ) : null}
              </div>
            ),
          )}
          {pending ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="flex gap-1" aria-hidden>
                {[0, 1, 2].map((i) => <span key={i} className="size-1.5 animate-pulse rounded-full bg-muted-foreground" style={{ animationDelay: `${i * 150}ms` }} />)}
              </span>
              Querying the graph
            </div>
          ) : null}
        </div>
        <div ref={end} />
      </div>

      <form
        className="shrink-0 border-t p-3"
        onSubmit={(e) => { e.preventDefault(); submit() }}
      >
        <div className="rounded-lg border bg-card focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30">
          <textarea
            ref={input}
            value={text}
            rows={2}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
            placeholder={simulated ? 'Ask about this scenario' : 'Ask about this incident'}
            aria-label="Message"
            className="block w-full resize-none bg-transparent px-3 pt-2.5 text-sm outline-none placeholder:text-muted-foreground"
          />
          <div className="flex items-center justify-between px-2 pb-2">
            <span className="pl-1 text-xs text-muted-foreground"><Kbd>Enter</Kbd> to send</span>
            <Button type="submit" size="icon-sm" disabled={pending || !text.trim()} aria-label="Ask"><ArrowUp /></Button>
          </div>
        </div>
      </form>
    </section>
  )
}
