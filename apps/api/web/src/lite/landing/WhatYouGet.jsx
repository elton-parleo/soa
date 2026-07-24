/** WHAT YOU GET — section [3]. Card names/order from the copy deck; each
 * mini-visual is a generic illustration of the real report section it
 * maps to (ExecutiveTiles+VisibilityByStage / WhySectionCard / FixList
 * in LiteFullReport.jsx) — no invented brand data. */
import { SectionHeader } from '../liteTheme.jsx'

function AnswersVisual() {
  const stages = [
    { label: 'Awareness', pct: 62 },
    { label: 'Research', pct: 48 },
    { label: 'Comparison', pct: 35 },
    { label: 'Ready to buy', pct: 21 },
  ]
  return (
    <div style={{ marginBottom: 18 }}>
      {stages.map((s) => (
        <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
          <span className="lite-mono lite-muted" style={{ fontSize: 10, width: 90, flexShrink: 0 }}>{s.label}</span>
          <div className="lite-bar-track" style={{ flex: 1 }}>
            <div className="lite-bar-fill" style={{ width: `${s.pct}%`, background: 'var(--accent)' }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function WhyVisual() {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', height: 64, marginBottom: 18 }}>
      {[
        { label: 'List', value: 100, color: 'var(--foundation)' },
        { label: 'Member', value: 68, color: 'var(--accent-tint)' },
        { label: 'Pays', value: 85, color: 'var(--accent)' },
      ].map((b) => (
        <div key={b.label} style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ height: `${b.value * 0.5}px`, background: b.color, borderRadius: '4px 4px 0 0' }} />
          <div className="lite-mono lite-muted" style={{ fontSize: 9, marginTop: 4 }}>{b.label}</div>
        </div>
      ))}
    </div>
  )
}

function FixesVisual() {
  const fixes = [
    { text: 'Encode the co-op as MemberProgram', impact: 6 },
    { text: 'Attach member prices to offers', impact: 6 },
    { text: 'Declare discounts in UCP', impact: 4 },
  ]
  return (
    <div style={{ marginBottom: 18 }}>
      {fixes.map((f) => (
        <div key={f.text} className="lite-mono" style={{
          fontSize: 11, color: 'var(--text-2)', border: '1px solid var(--line)', borderRadius: 8,
          padding: '7px 10px', marginBottom: 6,
        }}>
          {f.text} <span style={{ color: 'var(--good-ink)' }}>+{f.impact}</span>
        </div>
      ))}
    </div>
  )
}

const CARDS = [
  { icon: '📈', label: 'THE SCORE', Visual: AnswersVisual, text: 'A 0-100 score you can re-run monthly and hand to your team.' },
  { icon: '📄', label: 'THE WHY', Visual: WhyVisual, text: 'Every finding with the evidence, including what a member really pays versus what agents quote.' },
  { icon: '#', label: 'THE FIXES', Visual: FixesVisual, text: 'Ranked by score impact, with the exact markup to ship. Copy, paste, re-scan.' },
]

export function WhatYouGet() {
  return (
    <section className="lite-landing-section">
      <SectionHeader label="WHAT YOU GET" />
      <h2 className="lite-display-headline" style={{ fontSize: 'clamp(28px, 4.5vw, 48px)' }}>
        The report leaves you with <span className="lite-serif-italic">three</span> things.
      </h2>

      <div className="lite-cols-3" style={{ marginTop: 32 }}>
        {CARDS.map(({ icon, label, Visual, text }) => (
          <div key={label} className="lite-card">
            <Visual />
            <div className="lite-mono" style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent-ink)', marginBottom: 8 }}>
              <span aria-hidden="true">{icon}</span> {label}
            </div>
            <div className="lite-body" style={{ fontSize: 14 }}>{text}</div>
          </div>
        ))}
      </div>
    </section>
  )
}
