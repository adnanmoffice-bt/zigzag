import { useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { supabase } from '../lib/supabase'
import type { ActivityRow, EquityPoint, ParsedSignal, TradeExecution } from '../lib/types'
import { fmtMoney, fmtNum, fmtTime, timeAgo } from '../lib/format'
import { Badge, Card, CardHeader, DirectionBadge, Empty, Stat } from '../components/ui'

export default function Overview() {
  const [equity, setEquity] = useState<EquityPoint[]>([])
  const [execs, setExecs] = useState<TradeExecution[]>([])
  const [signals, setSignals] = useState<ParsedSignal[]>([])
  const [activity, setActivity] = useState<ActivityRow[]>([])

  useEffect(() => {
    supabase.from('equity_snapshots').select('*').order('created_at', { ascending: true }).limit(500)
      .then(({ data }) => setEquity((data as EquityPoint[]) ?? []))
    supabase.from('trade_executions').select('*').order('created_at', { ascending: false }).limit(300)
      .then(({ data }) => setExecs((data as TradeExecution[]) ?? []))
    supabase.from('parsed_signals').select('*').order('created_at', { ascending: false }).limit(20)
      .then(({ data }) => setSignals((data as ParsedSignal[]) ?? []))
    supabase.from('activity_log').select('*').order('created_at', { ascending: false }).limit(8)
      .then(({ data }) => setActivity((data as ActivityRow[]) ?? []))

    const ch = supabase
      .channel('overview')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'parsed_signals' },
        (p) => setSignals((s) => [p.new as ParsedSignal, ...s].slice(0, 20)))
      .on('postgres_changes', { event: '*', schema: 'public', table: 'trade_executions' },
        () => supabase.from('trade_executions').select('*').order('created_at', { ascending: false }).limit(300)
          .then(({ data }) => setExecs((data as TradeExecution[]) ?? [])))
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'activity_log' },
        (p) => setActivity((a) => [p.new as ActivityRow, ...a].slice(0, 8)))
      .subscribe()
    return () => { supabase.removeChannel(ch) }
  }, [])

  const kpi = useMemo(() => {
    const closed = execs.filter((e) => e.status === 'closed')
    const open = execs.filter((e) => e.status === 'open')
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const todayPnl = closed
      .filter((e) => e.closed_at && new Date(e.closed_at) >= today)
      .reduce((s, e) => s + (e.profit ?? 0), 0)
    const wins = closed.filter((e) => (e.profit ?? 0) > 0).length
    const winRate = closed.length ? (wins / closed.length) * 100 : null
    const totalPnl = closed.reduce((s, e) => s + (e.profit ?? 0), 0)
    return { openCount: open.length, todayPnl, winRate, totalPnl, closedCount: closed.length }
  }, [execs])

  const chartData = equity.map((e) => ({ t: fmtTime(e.created_at), equity: e.equity ?? e.balance ?? 0 }))
  const lastSignal = signals.find((s) => s.message_type === 'new_signal') ?? signals[0]

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-bold">Pregled</h1>
          <p className="mt-0.5 text-sm text-muted">Šta bot radi upravo sada</p>
        </div>
        {lastSignal && (
          <div className="text-right text-xs text-muted">
            Zadnji signal <span className="num font-semibold text-ink">{timeAgo(lastSignal.created_at)}</span>
          </div>
        )}
      </header>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="PnL danas" value={fmtMoney(kpi.todayPnl)} tone={kpi.todayPnl > 0 ? 'win' : kpi.todayPnl < 0 ? 'loss' : 'neutral'} />
        <Stat label="Otvorene pozicije" value={kpi.openCount} sub="XAUUSD" />
        <Stat label="Win rate" value={kpi.winRate == null ? '—' : `${fmtNum(kpi.winRate, 1)}%`} sub={`${kpi.closedCount} zatvorenih`} />
        <Stat label="Ukupan PnL" value={fmtMoney(kpi.totalPnl)} tone={kpi.totalPnl > 0 ? 'win' : kpi.totalPnl < 0 ? 'loss' : 'neutral'} />
      </div>

      <Card>
        <CardHeader title="Equity kriva" sub="Snapshoti sa MT5 naloga" />
        <div className="h-64 px-2 py-3">
          {chartData.length < 2 ? (
            <Empty title="Još nema equity podataka" hint="Executor upisuje snapshot svakih 5 minuta kad je pokrenut." />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#635BFF" stopOpacity={0.18} />
                    <stop offset="100%" stopColor="#635BFF" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="t" tick={{ fontSize: 11, fill: '#6B7280' }} tickLine={false} axisLine={false} minTickGap={48} />
                <YAxis tick={{ fontSize: 11, fill: '#6B7280' }} tickLine={false} axisLine={false} width={64}
                  domain={['auto', 'auto']} tickFormatter={(v) => `$${Number(v).toLocaleString()}`} />
                <Tooltip
                  contentStyle={{ borderRadius: 10, border: '1px solid #E6E8EC', boxShadow: '0 4px 12px rgba(16,24,40,.08)', fontSize: 12 }}
                  formatter={(v: number) => [fmtMoney(v), 'Equity']}
                />
                <Area type="monotone" dataKey="equity" stroke="#635BFF" strokeWidth={2} fill="url(#eq)" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Zadnji signal" sub="Kako ga je Claude pročitao" />
          {!lastSignal ? (
            <Empty title="Još nema signala" hint="Kad listener uhvati poruku sa kanala, pojavit će se ovdje." />
          ) : (
            <div className="space-y-3 p-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="gold">{lastSignal.symbol ?? 'XAUUSD'}</Badge>
                <DirectionBadge direction={lastSignal.direction} />
                <Badge tone={lastSignal.decision === 'execute' ? 'win' : lastSignal.decision === 'skip' ? 'warn' : 'neutral'}>
                  {lastSignal.decision.toUpperCase()}
                </Badge>
                {lastSignal.confidence != null && <Badge tone="accent">conf {Math.round(lastSignal.confidence * 100)}%</Badge>}
              </div>
              <div className="grid grid-cols-3 gap-3 text-sm">
                <div><div className="label">Entry</div><div className="num mt-0.5">{fmtNum(lastSignal.entry_low)}–{fmtNum(lastSignal.entry_high)}</div></div>
                <div><div className="label">SL</div><div className="num mt-0.5 text-loss">{fmtNum(lastSignal.sl)}</div></div>
                <div><div className="label">TP</div><div className="num mt-0.5 text-win">{(lastSignal.tps ?? []).map((t) => fmtNum(t, 0)).join(' · ') || '—'}</div></div>
              </div>
              {lastSignal.decision_reason && <p className="rounded-lg bg-surface px-3 py-2 text-xs text-muted">{lastSignal.decision_reason}</p>}
              {lastSignal.raw_text && <p className="text-xs text-muted/70 line-clamp-3 whitespace-pre-wrap">{lastSignal.raw_text}</p>}
            </div>
          )}
        </Card>

        <Card>
          <CardHeader title="Aktivnost" sub="Zadnjih 8 događaja" />
          {activity.length === 0 ? (
            <Empty title="Log je prazan" />
          ) : (
            <ul className="divide-y divide-line">
              {activity.map((a) => (
                <li key={a.id} className="flex items-start gap-3 px-5 py-2.5">
                  <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                    a.level === 'error' ? 'bg-loss' : a.level === 'warn' ? 'bg-warn' : a.level === 'trade' ? 'bg-accent' : 'bg-line'
                  }`} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm">{a.message}</p>
                    <p className="text-[11px] text-muted">{a.category} · {timeAgo(a.created_at)}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
