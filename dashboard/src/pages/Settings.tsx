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
    title: 'Način rada',
    sub: 'Demo dok validacija ne prođe — minimum 4 sedmice i 50+ signala',
    fields: [{ name: 'mode', label: 'Mod', options: ['demo', 'live'], hint: 'live tek nakon demo validacije' }],
  },
  {
    key: 'telegram',
    title: 'Telegram',
    sub: 'Listener čita kanal; bot šalje notifikacije tebi',
    fields: [
      { name: 'api_id', label: 'API ID', hint: 'my.telegram.org → API development tools' },
      { name: 'api_hash', label: 'API Hash', type: 'password' },
      { name: 'channel_id', label: 'ID kanala', hint: 'npr. -1003910126970' },
      { name: 'bot_token', label: 'Bot token (BotFather)', type: 'password' },
      { name: 'notify_chat_id', label: 'Tvoj chat ID', hint: 'iz /getUpdates nakon što botu pošalješ /start' },
    ],
  },
  {
    key: 'anthropic',
    title: 'Claude (Anthropic)',
    sub: 'Parser signala — API ključ ide u .env na serveru, ne ovdje',
    fields: [
      { name: 'model', label: 'Model', hint: 'npr. claude-sonnet-4-6' },
      { name: 'max_tokens', label: 'Max tokena po pozivu', type: 'number' },
    ],
  },
  {
    key: 'mt5',
    title: 'MetaTrader 5 (IG)',
    sub: 'Lozinka NIKAD ovdje — samo u .env na Windows VPS-u',
    fields: [
      { name: 'login', label: 'MT5 login (broj naloga)' },
      { name: 'server', label: 'Server', hint: 'IG-Live2 ili IG-Demo' },
      { name: 'symbol', label: 'Simbol', hint: 'XAUUSD' },
      { name: 'symbol_suffix', label: 'Suffix simbola', hint: 'ostavi prazno ako je čisti XAUUSD' },
    ],
  },
  {
    key: 'risk',
    title: 'Rizik',
    sub: 'Pravila koja executor primjenjuje na svaki signal',
    fields: [
      { name: 'risk_percent', label: 'Rizik po trejdu (%)', type: 'number', hint: 'preporuka 0.5 za start' },
      { name: 'daily_max_loss_percent', label: 'Dnevni max gubitak (%)', type: 'number', hint: 'bot staje kad se dosegne' },
      { name: 'max_open_positions', label: 'Max otvorenih pozicija', type: 'number' },
      { name: 'min_confidence', label: 'Min. confidence parsera (0–1)', type: 'number', hint: 'ispod ovoga → skip' },
      { name: 'slippage_max_usd', label: 'Max udaljenost od entry raspona ($)', type: 'number', hint: 'zaštita od "chasing" ulaza' },
      { name: 'entry_mode', label: 'Entry mod', options: ['smart', 'market', 'limit'], hint: 'smart: market ako je cijena u rasponu, inače limit' },
      { name: 'lot_floor', label: 'Min. lot', type: 'number' },
      { name: 'lot_cap', label: 'Max. lot (safety cap)', type: 'number' },
    ],
  },
  {
    key: 'external_signals',
    title: 'Ingestija (napredna)',
    sub: 'Mapiranje kolona postojeće external_signals tabele',
    fields: [
      { name: 'text_column', label: 'Kolona sa tekstom poruke', hint: 'raw_text' },
      { name: 'provider_column', label: 'Kolona sa provajderom', hint: 'sender' },
      { name: 'status_column', label: 'Kolona za status obrade', hint: 'parse_status — parser upisuje zz_parsed' },
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
    if (error) setError(`Snimanje nije uspjelo: ${error.message}`)
    else setSavedAt(new Date().toLocaleTimeString())
    setSaving(false)
  }

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-bold">Postavke</h1>
          <p className="mt-0.5 text-sm text-muted">Konekcije i pravila — workeri čitaju ove vrijednosti iz baze</p>
        </div>
        <div className="flex items-center gap-3">
          {savedAt && <span className="text-xs text-win">Snimljeno {savedAt}</span>}
          <button className="btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Snimanje…' : 'Snimi promjene'}
          </button>
        </div>
      </header>

      {error && <p className="rounded-lg bg-loss/5 px-4 py-2 text-sm text-loss">{error}</p>}

      <div className="rounded-xl border border-warn/30 bg-warn/5 px-4 py-3 text-xs text-warn">
        <strong>Tajne (MT5 lozinka, Anthropic API ključ, Supabase service key) se NE unose ovdje</strong> — one žive
        isključivo u <code>.env</code> fajlovima na serverima (vidi <code>docs/SETUP.md</code>). Ova stranica čuva samo
        konfiguraciju i ID-jeve.
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
