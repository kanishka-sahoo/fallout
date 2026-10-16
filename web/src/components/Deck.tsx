import { useEffect, useRef, useState } from 'react'
import type { Answer, LogEvent } from '../api'

export type Msg = { role: 'user' | 'agent'; text: string; answer?: Answer }

type ChatProps = {
  messages: Msg[]
  pending: boolean
  onSend: (text: string) => void
  onCite: (answer: Answer, pathId: string) => void
}

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
    <div className="body">
      {parts.map((p, i) =>
        p.startsWith('`') ? <code key={i}>{p.slice(1, -1)}</code> : p.startsWith('**') ? <strong key={i}>{p.slice(2, -2)}</strong> : p,
      )}
    </div>
  )
}

export function Chat({ messages, pending, onSend, onCite }: ChatProps) {
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages, pending])
  return (
    <section className="chat" aria-label="Ask the agent">
      <div className="scroll">
        {messages.length === 0 ? (
          <p className="msg" style={{ color: 'var(--slate)' }}>
            Ask about exposure, dependency paths or fixes. Each answer uses graph tool results and cites the paths that the tools returned.
          </p>
        ) : null}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === 'user' ? m.text : <Body text={m.text} />}
            {m.answer ? (
              <>
                {m.answer.cited_path_ids.length ? (
                  <div className="cites" aria-label="Cited paths">
                    {m.answer.cited_path_ids.map((id) => (
                      <button
                        key={id}
                        className={m.answer!.unknown_path_ids.includes(id) ? 'unknown' : ''}
                        title={m.answer!.unknown_path_ids.includes(id) ? 'Unverified. No tool returned this path.' : 'Show this path on the graph'}
                        onClick={() => onCite(m.answer!, id)}
                      >
                        {id}
                      </button>
                    ))}
                  </div>
                ) : null}
                <div className="tools">
                  {m.answer.tool_calls.map((t) => t.name).join(', ') || 'No tools called'} in {(m.answer.took_ms / 1000).toFixed(1)}s
                  {m.answer.offline ? ' (offline planner)' : ''}
                </div>
              </>
            ) : null}
          </div>
        ))}
        {pending ? <div className="msg" style={{ color: 'var(--slate)' }}>Querying the graph…</div> : null}
        <div ref={end} />
      </div>
      <div>
        <div className="suggest">
          {SUGGESTIONS.map((s) => <button key={s} onClick={() => onSend(s)} disabled={pending}>{s}</button>)}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) { onSend(text.trim()); setText('') } }}>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about this incident" aria-label="Message" />
          <button className="btn" disabled={pending || !text.trim()}>Ask</button>
        </form>
      </div>
    </section>
  )
}

export function Log({ events }: { events: LogEvent[] }) {
  const box = useRef<HTMLDivElement>(null)
  const stuck = useRef(true) // Follow new events until the user scrolls up
  useEffect(() => {
    const el = box.current
    if (el && stuck.current) el.scrollTop = el.scrollHeight
  }, [events])
  return (
    <section
      className="log"
      ref={box}
      aria-label="Agent event log"
      aria-live="off"
      onScroll={(e) => {
        const el = e.currentTarget
        stuck.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
      }}
    >
      {events.length === 0 ? <div>Waiting for events…</div> : null}
      {events.map((e, i) => (
        <div key={i} className={`${e.level} ${e.source === 'fallout-api' ? 'src-api' : ''}`}>{e.line}</div>
      ))}
    </section>
  )
}
