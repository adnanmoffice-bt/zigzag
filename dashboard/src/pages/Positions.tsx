import { useEffect, useMemo, useState } from 'react'
import { supabase } from '../lib/supabase'
import type { TradeExecution } from '../lib/types'
import { fmtMoney, fmtNum, fmtTime } from '../lib/format'
import { Badge, Card, CardHeader, DirectionBadge, Empty, Td, Th } from '../components/ui'

export default function Positions() {
  const [rows, setRows] = useState<TradeExecution[]>([])

  useEffect(() => {
    const load = () =>
      supabase.from('trade_executions').select('*').order('created_at', { ascending: false }).limit(300)
        .then(({ data }) => setRows((data as TradeExecution[]) ?? []))
    load()
    const ch = supabase
      .channel('positions')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'trade_executions' }, load)
      .subscribe()
    return () => { supabase.removeChannel(ch) }
  }, [])

  const open = useMemo(() => rows.filter((r) => r.status === 'open' || r.status === 'pending'), [rows])
  const closed = useMemo(() => rows.filter((r) => r.status === 'closed'), [rows])

  const Table = ({ data, showClose }: { data: TradeExecution[]; showClose?: boolean }) => (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="border-b border-line">
          <tr>
            <Th>Smjer</Th><Th>Lot</Th><Th>Entry</Th><Th>SL</Th><Th>TP</Th>
            {showClose && <Th>Close</Th>}
            <Th right>Pips</Th><Th right>Profit</Th><Th right>Vrijeme</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {data.map((r) => (
            <tr key={r.id} className="hover:bg-surface/60">
              <Td><div className="flex items-center gap-2"><DirectionBadge direction={r.direction} />{r.tp_index ? <Badge>TP{r.tp_index}</Badge> : null}{r.status === 'pending' && <Badge tone="warn">pending</Badge>}{r.status === 'error' && <Badge tone="loss">error</Badge>}</div></Td>
              <Td className="num">{fmtNum(r.lot)}</Td>
              <Td className="num">{fmtNum(r.entry_price)}</Td>
              <Td className="num text-loss">{fmtNum(r.sl)}</Td>
              <Td className="num text-win">{fmtNum(r.tp)}</Td>
              {showClose && <Td className="num">{fmtNum(r.close_price)}</Td>}
              <Td right className={`num ${r.pips == null ? '' : r.pips >= 0 ? 'text-win' : 'text-loss'}`}>{r.pips == null ? '—' : fmtNum(r.pips, 0)}</Td>
              <Td right className={`num font-semibold ${r.profit == null ? '' : r.profit >= 0 ? 'text-win' : 'text-loss'}`}>{fmtMoney(r.profit)}</Td>
              <Td right className="num text-muted">{fmtTime(showClose ? r.closed_at : (r.opened_at ?? r.created_at))}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-bold">Pozicije</h1>
        <p className="mt-0.5 text-sm text-muted">Sve što je executor otvorio na MT5</p>
      </header>

      <Card>
        <CardHeader title="Otvorene" sub={`${open.length} pozicija`} />
        {open.length === 0 ? <Empty title="Nema otvorenih pozicija" /> : <Table data={open} />}
      </Card>

      <Card>
        <CardHeader title="Zatvorene" sub={`Zadnjih ${closed.length}`} />
        {closed.length === 0 ? <Empty title="Još nema zatvorenih trejdova" /> : <Table data={closed} showClose />}
      </Card>
    </div>
  )
}
