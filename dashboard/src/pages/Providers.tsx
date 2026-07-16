import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import type { ProviderStat } from '../lib/types'
import { fmtNum, timeAgo } from '../lib/format'
import { Badge, Card, CardHeader, Empty, Td, Th, Toggle } from '../components/ui'

export default function Providers() {
  const [rows, setRows] = useState<ProviderStat[]>([])

  useEffect(() => {
    supabase.from('provider_stats').select('*').order('total_pips', { ascending: false })
      .then(({ data }) => setRows((data as ProviderStat[]) ?? []))
  }, [])

  const setEnabled = async (provider: string, enabled: boolean) => {
    setRows((r) => r.map((x) => (x.provider === provider ? { ...x, enabled } : x)))
    await supabase.from('provider_stats').update({ enabled, updated_at: new Date().toISOString() }).eq('provider', provider)
  }

  const setMultiplier = async (provider: string, risk_multiplier: number) => {
    setRows((r) => r.map((x) => (x.provider === provider ? { ...x, risk_multiplier } : x)))
    await supabase.from('provider_stats').update({ risk_multiplier, updated_at: new Date().toISOString() }).eq('provider', provider)
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-bold">Providers</h1>
        <p className="mt-0.5 text-sm text-muted">Performance by signal source — disable ones that drag PnL down</p>
      </header>

      <Card>
        <CardHeader title="Leaderboard" sub="Sorted by total pips" />
        {rows.length === 0 ? (
          <Empty title="Stats not calculated yet" hint="Run workers/backfill/provider_stats.py to compute performance from history." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-line">
                <tr>
                  <Th>Provider</Th><Th right>Signals</Th><Th right>Win rate</Th>
                  <Th right>Avg pips</Th><Th right>Total pips</Th><Th right>Last</Th>
                  <Th right>Risk ×</Th><Th right>Active</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((r, i) => (
                  <tr key={r.provider} className={`hover:bg-surface/60 ${!r.enabled ? 'opacity-50' : ''}`}>
                    <Td>
                      <div className="flex items-center gap-2">
                        {i === 0 && r.total_pips > 0 && <Badge tone="gold">#1</Badge>}
                        <span className="font-medium">{r.provider}</span>
                      </div>
                    </Td>
                    <Td right className="num">{r.signals_total}</Td>
                    <Td right className={`num ${r.win_rate != null && r.win_rate >= 50 ? 'text-win' : 'text-loss'}`}>
                      {r.win_rate == null ? '—' : `${fmtNum(r.win_rate, 1)}%`}
                    </Td>
                    <Td right className="num">{fmtNum(r.avg_pips, 1)}</Td>
                    <Td right className={`num font-semibold ${r.total_pips >= 0 ? 'text-win' : 'text-loss'}`}>{fmtNum(r.total_pips, 0)}</Td>
                    <Td right className="num text-muted">{timeAgo(r.last_signal_at)}</Td>
                    <Td right>
                      <select
                        className="input w-20 py-1 text-right"
                        value={String(r.risk_multiplier)}
                        onChange={(e) => setMultiplier(r.provider, Number(e.target.value))}
                      >
                        {[0.25, 0.5, 0.75, 1, 1.5, 2].map((v) => <option key={v} value={v}>{v}×</option>)}
                      </select>
                    </Td>
                    <Td right><Toggle checked={r.enabled} onChange={(v) => setEnabled(r.provider, v)} /></Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
