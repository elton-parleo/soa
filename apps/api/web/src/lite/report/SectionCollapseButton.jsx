import { Glyph } from '../../ds/index.js'
import { track } from '../analytics.js'
import { EVENTS } from '../analyticsEvents.js'

// Analytics session: the one place section_expanded fires for a
// top-level section (Visibility/Accessibility/True Value/FixesTable/
// FunnelGate/DiscoveryFinding/ExposureSection all render through this
// one button — ReportSection.jsx and TrueValueSection.jsx's own direct
// call both pass their section id through). Fires only on the closed
// -> open transition, never on collapse.
export function SectionCollapseButton({ open, onClick, dark = false, section }) {
  const label = open ? 'Collapse' : 'Expand'
  function handleClick() {
    if (!open && section) {
      track(EVENTS.SECTION_EXPANDED, { section, control: 'section' })
    }
    onClick()
  }
  return (
    <button
      type="button"
      onClick={handleClick}
      aria-expanded={open}
      title={`${label} this section`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 9, flexShrink: 0,
        background: dark ? 'rgba(242,240,239,.08)' : 'var(--surface)',
        border: dark ? '1px solid rgba(242,240,239,.20)' : '1px solid var(--border-strong)',
        borderRadius: 10, padding: '7px 14px 7px 8px', cursor: 'pointer',
        fontFamily: 'inherit', fontSize: 12, fontWeight: 580, letterSpacing: '-0.004em',
        color: dark ? 'var(--dark-text)' : 'var(--text-strong)',
      }}
    >
      <span
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', width: 21, height: 21,
          borderRadius: 7, background: dark ? 'rgba(242,240,239,.12)' : 'var(--canvas-dim)',
          transition: 'transform .26s var(--ease)', transform: open ? 'rotate(0deg)' : 'rotate(-90deg)',
        }}
      >
        <Glyph name="chevronDown" size={12} color={dark ? 'var(--dark-text)' : 'var(--text-strong)'} />
      </span>
      {label}
    </button>
  )
}
