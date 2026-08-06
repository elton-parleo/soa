/**
 * The visibility language: SEEN / PARTIAL / INVISIBLE. chip = tinted
 * pill with eye glyph; value = figure that dims and strikes when agents
 * cannot see it; dot = compact matrix cell. Ported from the exported
 * design-system bundle (components/foundation/StateChip.jsx) — same
 * render tree, restored to JSX.
 *
 * 'unmeasured' is a new state this session adds (B-6): honest-state
 * rows whose inputs simply weren't sampled/available render this,
 * never 'invisible' — invisible asserts we looked and it wasn't there,
 * unmeasured says we don't know. Styled muted/neutral (faint on
 * canvas-dim), deliberately not sharing invisible's red or seen's
 * green/partial's amber, so it reads as a distinct third thing at a
 * glance.
 */
import { Glyph } from './Glyph.jsx'

const STATES = {
  seen: { label: 'Seen', glyph: 'eye', fg: 'var(--green)', bg: 'var(--green-tint)', dot: 'var(--green)' },
  partial: { label: 'Partial', glyph: 'eye', fg: 'var(--amber-deep)', bg: 'var(--amber-tint)', dot: 'var(--amber)' },
  invisible: { label: 'Invisible', glyph: 'eyeOff', fg: 'var(--red-deep)', bg: 'var(--red-tint)', dot: 'var(--red)' },
  unmeasured: { label: 'Unmeasured', glyph: 'eyeOff', fg: 'var(--faint)', bg: 'var(--canvas-dim)', dot: 'var(--faint)' },
}

export function StateChip({ state = 'seen', children, variant = 'chip', size = 'md', style }) {
  const s = STATES[state] || STATES.seen
  const text = children !== undefined ? children : s.label

  if (variant === 'value') {
    return (
      <span
        className="num"
        style={{
          position: 'relative',
          display: 'inline-block',
          color: state === 'seen' ? 'var(--text-strong)' : state === 'partial' ? 'var(--text)' : 'var(--faint)',
          ...style,
        }}
      >
        {text}
        {state === 'invisible' ? (
          <span aria-hidden="true" style={{ position: 'absolute', left: -1, right: -1, top: '52%', height: 1.5, background: 'var(--red)', opacity: 0.55, borderRadius: 1 }} />
        ) : null}
      </span>
    )
  }

  if (variant === 'dot') {
    return (
      <span
        title={s.label}
        style={{
          display: 'inline-block',
          width: 9,
          height: 9,
          borderRadius: '50%',
          background: state === 'invisible' ? 'transparent' : s.dot,
          border: state === 'invisible' ? `1.5px solid ${s.dot}` : 'none',
          opacity: state === 'partial' ? 0.9 : 1,
          ...style,
        }}
      />
    )
  }

  const sm = size === 'sm'
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: sm ? '2px 8px' : '3px 10px',
        borderRadius: 999,
        background: s.bg,
        color: s.fg,
        fontSize: sm ? 11 : 11.5,
        fontWeight: 560,
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      <Glyph name={s.glyph} size={sm ? 11 : 12} strokeWidth={1.6} />
      {text}
    </span>
  )
}
