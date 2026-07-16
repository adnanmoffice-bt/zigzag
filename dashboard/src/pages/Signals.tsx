import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import type { ParsedSignal } from '../lib/types'
import { fmtNum, fmtTime } from '../lib/format'
import { Badge, Card, DirectionBadge, Empty } from '../components/ui'

const TYPE_LABEL: Record<string, string> = {
  new_signal: 'New signal',
  update_sl: 'Update SL',
  tp_hit: 'TP hit',
  move_to_be: 'Breakeven',
  close: 'Close',
  partial_close: 'Partial close',
  noise: 'Noise',
}

const FILTERS = ['all', 'new_signal', 'execute', 'skip'] as const

export default function Signals() {
  const [rows, setRows] = useState<ParsedSignal[]>([])
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    supabase.from('parsed_signals').select('*').order('created_at', { ascending: false }).limit(200)
      .then(({ data }) => { setRows((data as ParsedSignal[]) ?? []); setLoading(false) })
    const ch = supabase
      .channel('signals-feed')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'parsed_signals' },
        (p) => setRows((r) => [p.new as ParsedSignal, ...r].slice(0, 200)))
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'parsed_signals' },
        (p) => setRows((r) => r.map((x) => (x.id === (p.new as ParsedSignal).id ? (p.new as ParsedSignal) : x))))
      .subscribe()
    return () => { supabase.removeChannel(ch) }
  }, [])

  const filtered = rows.filter((r) => {
    if (filter === 'all') return true
    if (filter === 'new_signal') return r.message_type === 'new_signal'
    return r.decision === filter
  })

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-bold">Signals</h1>
          <p className="mt-0.5 text-sm text-muted">Live feed from the Telegram channel, parsed by Claude</p>
        </div>
        <div className="flex gap-1 rounded-lg border border-line bg-white p-1">
          {FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-md px-3 py-1 text-xs font-medium transition ${
                filter === f ? 'bg-accent-soft text-accent-dark' : 'text-muted hover:text-ink'
              }`}
            >
              {f === 'all' ? 'All' : f === 'new_signal' ? 'New signals' : f === 'execute' ? 'Executed' : 'Skipped'}
            </button>
          ))}
        </div>
      </header>

      {loading ? null : filtered.length === 0 ? (
        <Card><Empty title="No signals for this filter" hint="Signals appear as soon as the parser processes them." /></Card>
      ) : (
        <div className="space-y-3">
          {filtered.map((s) => (
            <Card key={s.id} className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={s.message_type === 'new_signal' ? 'accent' : 'neutral'}>{TYPE_LABEL[s.message_type] ?? s.message_type}</Badge>
                  {s.symbol && <Badge tone="gold">{s.symbol}</Badge>}
                  {s.direction && <DirectionBadge direction={s.direction} />}
                  {s.provider && <span className="text-xs text-muted">{s.provider}</span>}
                </div>
                <div className="flex items-center gap-2">
                  {s.confidence != null && (
                    <span className="num text-xs text-muted">conf {Math.round(s.confidence * 100)}%</span>
                  )}
                  <Badge tone={s.decision === 'execute' ? 'win' : s.decision === 'skip' ? 'warn' : 'neutral'}>
                    {s.decision.toUpperCase()}
                  </Badge>
                  <span className="num text-xs text-muted">{fmtTime(s.created_at)}</span>
                </div>
              </div>

              {s.message_type === 'new_signal' && (
                <div className="mt-3 grid grid-cols-3 gap-3 rounded-lg bg-surface px-4 py-3 text-sm sm:max-w-md">
                  <div><div className="label">Entry</div><div className="num mt-0.5">{fmtNum(s.entry_low)}–{fmtNum(s.entry_high)}</div></div>
                  <div><div className="label">SL</div><div className="num mt-0.5 text-loss">{fmtNum(s.sl)}</div></div>
                  <div><div className="label">TPs</div><div className="num mt-0.5 text-win">{(s.tps ?? []).map((t) => fmtNum(t, 0)).join(' · ') || '—'}</div></div>
                </div>
              )}

              {s.decision_reason && (
                <p className="mt-2 text-xs text-muted"><span className="font-semibold">Reason:</span> {s.decision_reason}</p>
              )}
              {s.raw_text && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-[11px] font-medium text-muted/70 hover:text-muted">Original message</summary>
                  <pre className="mt-1.5 whitespace-pre-wrap rounded-lg bg-surface px-3 py-2 font-sans text-xs text-muted">{s.raw_text}</pre>
                </details>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
