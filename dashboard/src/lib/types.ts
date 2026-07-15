export type ParsedSignal = {
  id: string
  external_signal_id: string | null
  provider: string | null
  message_type: 'new_signal' | 'update_sl' | 'tp_hit' | 'move_to_be' | 'close' | 'partial_close' | 'noise'
  symbol: string | null
  direction: 'buy' | 'sell' | null
  entry_low: number | null
  entry_high: number | null
  sl: number | null
  tps: number[]
  confidence: number | null
  decision: 'pending' | 'execute' | 'skip' | 'manual'
  decision_reason: string | null
  raw_text: string | null
  processed_at: string | null
  created_at: string
}

export type TradeExecution = {
  id: string
  parsed_signal_id: string | null
  mt5_ticket: number | null
  symbol: string | null
  direction: string | null
  lot: number | null
  entry_price: number | null
  sl: number | null
  tp: number | null
  tp_index: number | null
  status: 'pending' | 'open' | 'closed' | 'cancelled' | 'error'
  opened_at: string | null
  closed_at: string | null
  close_price: number | null
  profit: number | null
  pips: number | null
  notes: string | null
  created_at: string
}

export type ProviderStat = {
  provider: string
  signals_total: number
  wins: number
  losses: number
  win_rate: number | null
  avg_pips: number | null
  total_pips: number
  last_signal_at: string | null
  enabled: boolean
  risk_multiplier: number
}

export type ActivityRow = {
  id: string
  level: 'info' | 'warn' | 'error' | 'trade'
  category: string
  message: string
  meta: Record<string, unknown>
  created_at: string
}

export type Heartbeat = {
  component: string
  status: 'ok' | 'degraded' | 'down'
  last_seen: string
  meta: Record<string, unknown>
}

export type EquityPoint = {
  id: string
  balance: number | null
  equity: number | null
  created_at: string
}
