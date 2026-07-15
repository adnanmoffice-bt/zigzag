import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import type { ActivityRow } from '../lib/types'
import { fmtTime } from '../lib/format'
import { Badge, Card, Empty } from '../components/ui'

const LEVELS = ['sve', 'trade', 'warn', 'error'] as const

export default function ActivityPage() {
  const [rows, setRows] = useState<ActivityRow[]>([])
  const [filter, setFilter] = useState<(typeof LEVELS)[number]>('sve')

  useEffect(() => {
    supabase.from('activity_log').select('*').order('created_at', { ascending: false }).limit(400)
      .then(({ data }) => setRows((data as ActivityRow[]) ?? []))
    const ch = supabase
      .channel('activity-page')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'activity_log' },
        (p) => setRows((r) => [p.new as ActivityRow, ...r].slice(0, 400)))
      .subscribe()
    return () => { supabase.removeChannel(ch) }
  }, [])

  const filtered = filter === 'sve' ? rows : rows.filter((r) => r.level === filter)

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-bold">Aktivnost</h1>
          <p className="mt-0.5 text-sm text-muted">Kompletan dnevnik — svaka odluka i razlog</p>
        </div>
        <div className="flex gap-1 rounded-lg border border-line bg-white p-1">
          {LEVELS.map((f) => (
            <button key={f} onClick={() => setFilter(f)}
              className={`rounded-md px-3 py-1 text-xs font-medium transition ${filter === f ? 'bg-accent-soft text-accent-dark' : 'text-muted hover:text-ink'}`}>
              {f === 'sve' ? 'Sve' : f === 'trade' ? 'Trejdovi' : f === 'warn' ? 'Upozorenja' : 'Greške'}
            </button>
          ))}
        </div>
      </header>

      <Card>
        {filtered.length === 0 ? (
          <Empty title="Log je prazan" hint="Workeri upisuju svaki događaj ovdje." />
        ) : (
          <ul className="divide-y divide-line">
            {filtered.map((a) => (
              <li key={a.id} className="flex items-start gap-3 px-5 py-3">
                <Badge tone={a.level === 'error' ? 'loss' : a.level === 'warn' ? 'warn' : a.level === 'trade' ? 'accent' : 'neutral'}>
                  {a.level}
                </Badge>
                <div className="min-w-0 flex-1">
                  <p className="text-sm">{a.message}</p>
                  {Object.keys(a.meta ?? {}).length > 0 && (
                    <pre className="num mt-1 overflow-x-auto rounded bg-surface px-2 py-1 text-[11px] text-muted">{JSON.stringify(a.meta)}</pre>
                  )}
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-[11px] font-medium text-muted">{a.category}</div>
                  <div className="num text-[11px] text-muted/70">{fmtTime(a.created_at)}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
