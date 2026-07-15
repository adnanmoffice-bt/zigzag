import { ReactNode } from 'react'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`card ${className}`}>{children}</div>
}

export function CardHeader({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between px-5 pt-4 pb-3 border-b border-line">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        {sub && <p className="text-xs text-muted mt-0.5">{sub}</p>}
      </div>
      {right}
    </div>
  )
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'win' | 'loss' | 'neutral' }) {
  const toneCls = tone === 'win' ? 'text-win' : tone === 'loss' ? 'text-loss' : 'text-ink'
  return (
    <div className="card px-5 py-4">
      <div className="label">{label}</div>
      <div className={`num text-2xl font-semibold mt-1.5 ${toneCls}`}>{value}</div>
      {sub && <div className="text-xs text-muted mt-1">{sub}</div>}
    </div>
  )
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'win' | 'loss' | 'warn' | 'accent' | 'gold' | 'neutral' }) {
  const map: Record<string, string> = {
    win: 'bg-win/10 text-win',
    loss: 'bg-loss/10 text-loss',
    warn: 'bg-warn/10 text-warn',
    accent: 'bg-accent-soft text-accent-dark',
    gold: 'bg-gold-soft text-gold',
    neutral: 'bg-surface text-muted border border-line',
  }
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${map[tone]}`}>
      {children}
    </span>
  )
}

export function DirectionBadge({ direction }: { direction: string | null }) {
  if (!direction) return <Badge>—</Badge>
  return direction === 'buy'
    ? <Badge tone="win">▲ BUY</Badge>
    : <Badge tone="loss">▼ SELL</Badge>
}

export function StatusDot({ status }: { status: 'ok' | 'degraded' | 'down' | string }) {
  const color = status === 'ok' ? 'bg-win' : status === 'degraded' ? 'bg-warn' : 'bg-loss'
  return <span className={`inline-block h-2 w-2 rounded-full ${color} ${status === 'ok' ? 'live-dot' : ''}`} />
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="py-14 text-center">
      <p className="text-sm font-medium text-muted">{title}</p>
      {hint && <p className="text-xs text-muted/70 mt-1">{hint}</p>}
    </div>
  )
}

export function Th({ children, right }: { children: ReactNode; right?: boolean }) {
  return <th className={`label px-4 py-2.5 ${right ? 'text-right' : 'text-left'}`}>{children}</th>
}

export function Td({ children, right, className = '' }: { children: ReactNode; right?: boolean; className?: string }) {
  return <td className={`px-4 py-3 text-sm ${right ? 'text-right' : 'text-left'} ${className}`}>{children}</td>
}

export function Spinner() {
  return <div className="h-5 w-5 animate-spin rounded-full border-2 border-line border-t-accent" />
}

export function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-10 items-center rounded-full transition
        ${checked ? 'bg-accent' : 'bg-line'} ${disabled ? 'opacity-50' : ''}`}
      aria-pressed={checked}
    >
      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition ${checked ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
    </button>
  )
}
