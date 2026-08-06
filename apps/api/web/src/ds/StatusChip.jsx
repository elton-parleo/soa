/**
 * Tinted pill status chip. live pulses; tones map to the status
 * palette. Ported from the exported design-system bundle
 * (components/foundation/StatusChip.jsx) — same render tree, restored
 * to JSX.
 */
import { PulsingDot } from './PulsingDot.jsx'

const TONES = {
  live: { bg: 'var(--green-tint)', fg: 'var(--green)', dot: 'var(--green-bright)', pulse: true },
  success: { bg: 'var(--green-tint)', fg: 'var(--green)', dot: 'var(--green)' },
  warning: { bg: 'var(--amber-tint)', fg: 'var(--amber-deep)', dot: 'var(--amber)' },
  risk: { bg: 'var(--red-tint)', fg: 'var(--red-deep)', dot: 'var(--red)' },
  info: { bg: 'var(--blue-tint)', fg: 'var(--blue)', dot: 'var(--blue)' },
  neutral: { bg: 'var(--canvas-dim)', fg: 'var(--muted)', dot: 'var(--faint)' },
}

export function StatusChip({ tone = 'neutral', children, dot = true, size = 'md', style }) {
  const t = TONES[tone] || TONES.neutral
  const sm = size === 'sm'
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: sm ? '2px 8px' : '3px 10px',
        borderRadius: 999,
        background: t.bg,
        color: t.fg,
        fontSize: sm ? 11 : 11.5,
        fontWeight: 560,
        letterSpacing: '0.01em',
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {dot ? <PulsingDot color={t.dot} size={sm ? 5 : 6} pulse={!!t.pulse} /> : null}
      {children}
    </span>
  )
}
