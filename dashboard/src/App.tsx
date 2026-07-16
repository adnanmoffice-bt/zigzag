import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import type { Session } from '@supabase/supabase-js'
import {
  Activity as ActivityIcon, CandlestickChart, LayoutDashboard, ListTree,
  LogOut, Radio, Settings as SettingsIcon, Users,
} from 'lucide-react'
import { supabase } from './lib/supabase'
import type { Heartbeat } from './lib/types'
import { timeAgo } from './lib/format'
import { StatusDot, Toggle } from './components/ui'
import Login from './pages/Login'
import Overview from './pages/Overview'
import Signals from './pages/Signals'
import Positions from './pages/Positions'
import Providers from './pages/Providers'
import ActivityPage from './pages/Activity'
import SettingsPage from './pages/Settings'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/signals', label: 'Signals', icon: Radio },
  { to: '/positions', label: 'Positions', icon: CandlestickChart },
  { to: '/providers', label: 'Providers', icon: Users },
  { to: '/activity', label: 'Activity', icon: ListTree },
  { to: '/settings', label: 'Settings', icon: SettingsIcon },
]

function KillSwitch() {
  const [enabled, setEnabled] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    supabase.from('bot_settings').select('value').eq('key', 'kill_switch').single()
      .then(({ data }) => setEnabled(Boolean((data?.value as any)?.enabled)))
  }, [])

  const flip = async (v: boolean) => {
    setSaving(true)
    setEnabled(v)
    await supabase.from('bot_settings').upsert({ key: 'kill_switch', value: { enabled: v }, updated_at: new Date().toISOString() })
    setSaving(false)
  }

  return (
    <div className={`flex items-center justify-between rounded-xl border px-3 py-2.5 ${enabled ? 'border-loss/40 bg-loss/5' : 'border-line bg-white'}`}>
      <div>
        <div className="text-xs font-semibold">{enabled ? 'Bot stopped' : 'Bot active'}</div>
        <div className="text-[11px] text-muted">Kill switch</div>
      </div>
      <Toggle checked={enabled} onChange={flip} disabled={saving} />
    </div>
  )
}

function Heartbeats() {
  const [beats, setBeats] = useState<Heartbeat[]>([])
  useEffect(() => {
    const load = () => supabase.from('bot_heartbeat').select('*').then(({ data }) => setBeats((data as Heartbeat[]) ?? []))
    load()
    const t = setInterval(load, 20000)
    return () => clearInterval(t)
  }, [])
  const items = ['listener', 'parser', 'executor'].map((c) => beats.find((b) => b.component === c) ?? { component: c, status: 'down', last_seen: null as any, meta: {} })
  return (
    <div className="space-y-1.5">
      {items.map((b) => {
        const stale = b.last_seen && Date.now() - new Date(b.last_seen).getTime() > 120000
        const status = !b.last_seen || stale ? 'down' : b.status
        return (
          <div key={b.component} className="flex items-center justify-between px-1 text-xs">
            <span className="flex items-center gap-2 capitalize text-muted"><StatusDot status={status} />{b.component}</span>
            <span className="num text-muted/70">{b.last_seen ? timeAgo(b.last_seen) : 'off'}</span>
          </div>
        )
      })}
    </div>
  )
}

function Shell({ children, email }: { children: React.ReactNode; email: string }) {
  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 hidden w-60 flex-col border-r border-line bg-white px-4 py-5 md:flex">
        <div className="flex items-center gap-2.5 px-1">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-white font-bold">Z</div>
          <div>
            <div className="text-sm font-bold leading-none">ZigZag</div>
            <div className="mt-1 text-[11px] font-medium text-gold">XAUUSD autotrader</div>
          </div>
        </div>

        <nav className="mt-7 flex-1 space-y-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive ? 'bg-accent-soft text-accent-dark' : 'text-muted hover:bg-surface hover:text-ink'
                }`
              }
            >
              <Icon size={16} strokeWidth={2} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="space-y-3">
          <Heartbeats />
          <KillSwitch />
          <button
            onClick={() => supabase.auth.signOut()}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-muted hover:bg-surface"
          >
            <LogOut size={14} /> {email}
          </button>
        </div>
      </aside>

      <main className="flex-1 md:pl-60">
        <div className="mx-auto max-w-6xl px-5 py-7">{children}</div>
      </main>
    </div>
  )
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => { setSession(data.session); setReady(true) })
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s))
    return () => sub.subscription.unsubscribe()
  }, [])

  if (!ready) return null
  if (!session) return <Login />

  return (
    <Shell email={session.user.email ?? ''}>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/signals" element={<Signals />} />
        <Route path="/positions" element={<Positions />} />
        <Route path="/providers" element={<Providers />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}
