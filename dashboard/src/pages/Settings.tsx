import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'
import { Card, CardHeader } from '../components/ui'

type SettingsMap = Record<string, Record<string, any>>

const SECTIONS: {
  key: string
  title: string
  sub: string
  fields: { name: string; label: string; type?: string; hint?: string; options?: string[] }[]
}[] = [
  {
    key: 'mode',
    title: 'Operating mode',
    sub: 'Demo until validation passes — minimum 4 weeks and 50+ signals',
    fields: [{ name: 'mode', label: 'Mode', options: ['demo', 'live'], hint: 'live only after demo validation' }],
  },
  {
    key: 'telegram',
    title: 'Telegram',
    sub: 'Listener reads the channel; bot sends notifications to you',
    fields: [
      { name: 'api_id', label: 'API ID', hint: 'my.telegram.org → API development tools' },
      { name: 'api_hash', label: 'API Hash', type: 'password' },
      { name: 'channel_id', label: 'Channel ID', hint: 'e.g. -1003910126970' },
      { name: 'bot_token', label: 'Bot token (BotFather)', type: 'password' },
      { name: 'notify_chat_id', label: 'Your chat ID', hint: 'from /getUpdates after you send the bot /start' },
    ],
  },
  {
    key: 'anthropic',
    title: 'Claude (Anthropic)',
    sub: 'Signal parser — API key goes in .env on the server, not here',
    fields: [
      { name: 'model', label: 'Model', hint: 'e.g. claude-sonnet-4-6' },
      { name: 'max_tokens', label: 'Max tokens per call', type: 'number' },
    ],
  },
  {
    key: 'mt5',
    title: 'MetaTrader 5 (IG)',
    sub: 'Password NEVER here — only in .env on the worker host',
    fields: [
      { name: 'login', label: 'MT5 login (account number)' },
      { name: 'server', label: 'Server', hint: 'IG-LIVE or IG-Demo' },
      { name: 'symbol', label: 'Symbol', hint: 'XAUUSD' },
      { name: 'symbol_suffix', label: 'Symbol suffix', hint: 'leave blank for plain XAUUSD' },
      { name: 'metaapi_account_id', label: 'MetaApi account ID', hint: 'from metaapi_provision.py' },
    ],
  },
  {
    key: 'risk',
    title: 'Risk',
    sub: 'Rules the executor applies to every signal',
    fields: [
      { name: 'risk_percent', label: 'Risk per trade (%)', type: 'number', hint: 'recommend 0.5 to start' },
      { name: 'max_risk_usd', label: 'Max risk per signal ($)', type: 'number', hint: 'hard loss cap if SL hits — e.g. 80; 0 = off' },
      { name: 'daily_max_loss_percent', label: 'Daily max loss (%)', type: 'number', hint: 'bot stops when reached' },
      { name: 'max_open_positions', label: 'Max open positions', type: 'number' },
      { name: 'min_confidence', label: 'Min. parser confidence (0–1)', type: 'number', hint: 'below this → skip' },
      { name: 'slippage_max_usd', label: 'Max distance from entry range ($)', type: 'number', hint: 'anti-chasing protection' },
      { name: 'entry_mode', label: 'Entry mode', options: ['smart', 'market', 'limit'], hint: 'smart: market if price in range, else limit' },
      { name: 'lot_floor', label: 'Min. lot', type: 'number' },
      { name: 'lot_cap', label: 'Max. lot (safety cap)', type: 'number' },
    ],
  },
  {
    key: 'external_signals',
    title: 'Ingestion (advanced)',
    sub: 'Column mapping for the existing external_signals table',
    fields: [
      { name: 'text_column', label: 'Message text column', hint: 'raw_text' },
      { name: 'provider_column', label: 'Provider column', hint: 'sender' },
      { name: 'status_column', label: 'Parse status column', hint: 'parse_status — parser writes zz_parsed' },
    ],
  },
]

export default function SettingsPage() {
  const [values, setValues] = useState<SettingsMap>({})
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    supabase.from('bot_settings').select('key,value').then(({ data }) => {
      const map: SettingsMap = {}
      for (const row of data ?? []) map[row.key] = (row.value as Record<string, any>) ?? {}
      setValues(map)
    })
  }, [])

  const set = (section: string, field: string, v: string) =>
    setValues((prev) => ({ ...prev, [section]: { ...(prev[section] ?? {}), [field]: v } }))

  const save = async () => {
    setSaving(true)
    setError(null)
    const rows = SECTIONS.map((s) => {
      const raw = values[s.key] ?? {}
      const clean: Record<string, any> = { ...raw }
      for (const f of s.fields) {
        if (f.type === 'number' && clean[f.name] !== '' && clean[f.name] != null) clean[f.name] = Number(clean[f.name])
      }
      return { key: s.key, value: clean, updated_at: new Date().toISOString() }
    })
    const { error } = await supabase.from('bot_settings').upsert(rows)
    if (error) setError(`Save failed: ${error.message}`)
    else setSavedAt(new Date().toLocaleTimeString())
    setSaving(false)
  }

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-bold">Settings</h1>
          <p className="mt-0.5 text-sm text-muted">Connections and rules — workers read these values from the database</p>
        </div>
        <div className="flex items-center gap-3">
          {savedAt && <span className="text-xs text-win">Saved {savedAt}</span>}
          <button className="btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </header>

      {error && <p className="rounded-lg bg-loss/5 px-4 py-2 text-sm text-loss">{error}</p>}

      <div className="rounded-xl border border-warn/30 bg-warn/5 px-4 py-3 text-xs text-warn">
        <strong>Secrets (MT5 password, Anthropic API key, Supabase service key) are NOT entered here</strong> — they live
        only in <code>.env</code> files on the servers (see <code>docs/SETUP.md</code>). This page stores configuration
        and IDs only.
      </div>

      {SECTIONS.map((s) => (
        <Card key={s.key}>
          <CardHeader title={s.title} sub={s.sub} />
          <div className="grid gap-4 p-5 sm:grid-cols-2">
            {s.fields.map((f) => (
              <div key={f.name}>
                <label className="label mb-1.5 block">{f.label}</label>
                {f.options ? (
                  <select
                    className="input"
                    value={String(values[s.key]?.[f.name] ?? f.options[0])}
                    onChange={(e) => set(s.key, f.name, e.target.value)}
                  >
                    {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <input
                    className="input"
                    type={f.type === 'password' ? 'password' : 'text'}
                    inputMode={f.type === 'number' ? 'decimal' : undefined}
                    value={String(values[s.key]?.[f.name] ?? '')}
                    onChange={(e) => set(s.key, f.name, e.target.value)}
                    autoComplete="off"
                  />
                )}
                {f.hint && <p className="mt-1 text-[11px] text-muted">{f.hint}</p>}
              </div>
            ))}
          </div>
        </Card>
      ))}
    </div>
  )
}
