/**
 * Field evidence — V4 design, section [4]. Case 01 (Brooklinen member
 * price) and Case 02 (razor-category deal-citation rate), ported
 * verbatim from the mock. Copy lives in landingSampleContent.js.
 */
import { Glyph, BrandLogo, ProvenanceLine } from '../../ds/index.js'
import { SectionHeading } from '../../ds/index.js'
import { CASE_01, CASE_02, FIELD_EVIDENCE_PROVENANCE } from './landingSampleContent.js'

function TrueSyncLink({ label }) {
  return (
    <a href="#truesync" style={{ display: 'flex', alignItems: 'center', gap: 9, marginTop: 'auto', padding: '14px 24px', borderTop: '1px solid var(--hairline)', background: 'var(--blue-tint)', textDecoration: 'none' }}>
      <Glyph name="refresh" size={13} color="var(--blue)" />
      <span className="mono-label" style={{ flex: 1, fontSize: 9.5, color: 'var(--blue)', lineHeight: 1.5 }}>{label}</span>
      <Glyph name="arrowRight" size={13} color="var(--blue)" />
    </a>
  )
}

function Case01Card() {
  return (
    <div style={{ position: 'relative', background: 'var(--surface)', borderRadius: 18, boxShadow: 'var(--shadow-card)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '15px 24px 14px' }}>
        <span className="mono-label" style={{ fontSize: 8, color: '#fff', background: 'var(--ink)', borderRadius: 999, padding: '3.5px 9px', flexShrink: 0 }}>CASE 01</span>
        <BrandLogo name={CASE_01.brand} domain={CASE_01.domain} size={18} />
        <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--muted)' }}>{CASE_01.eyebrow}</span>
      </div>
      <div style={{ padding: '4px 24px 0' }}>
        <div style={{ fontFamily: "'Newsreader',Georgia,serif", fontSize: 25, fontWeight: 400, lineHeight: 1.42, letterSpacing: '-0.014em', color: 'var(--text-strong)' }}>
          "{CASE_01.quote}"
        </div>
      </div>
      <div style={{ margin: '22px 24px 0', border: '1px solid var(--border)', borderRadius: 14, overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '14px 17px', background: 'var(--surface-warm)' }}>
          <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 30, height: 30, flexShrink: 0, borderRadius: 9, background: 'var(--surface)', boxShadow: 'var(--shadow-sm)' }}>
            <BrandLogo name="ChatGPT" domain="openai.com" size={15} />
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="mono-label" style={{ fontSize: 9, color: 'var(--muted)' }}>WHAT THE AGENT QUOTED</div>
            <div style={{ fontSize: 11, color: 'var(--faint)', marginTop: 2 }}>{CASE_01.quoted.productLabel}</div>
          </div>
          <span className="num" style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.026em', color: 'var(--faint)', textDecoration: 'line-through', flexShrink: 0 }}>{CASE_01.quoted.stickerPrice}</span>
        </div>
        <div className="atmos-cool-dark" style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '15px 17px', background: 'var(--ink)' }}>
          <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 30, height: 30, flexShrink: 0, borderRadius: 9, background: 'rgba(127,176,255,.16)' }}>
            <Glyph name="card" size={15} color="#7FB0FF" />
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="mono-label" style={{ fontSize: 9, color: '#7FB0FF' }}>WHAT MEMBERS ACTUALLY PAY</div>
            <div style={{ fontSize: 11, color: 'var(--dark-faint)', marginTop: 2 }}>{CASE_01.memberPrice.label}</div>
          </div>
          <div style={{ textAlign: 'right', flexShrink: 0 }}>
            <div className="num" style={{ fontSize: 26, fontWeight: 730, letterSpacing: '-0.026em', color: 'var(--dark-text)', lineHeight: 1 }}>{CASE_01.memberPrice.price}</div>
            <div className="mono-label" style={{ fontSize: 8.5, color: '#7FB0FF', marginTop: 4 }}>{CASE_01.memberPrice.delta}</div>
          </div>
        </div>
      </div>
      <div style={{ padding: '18px 24px 0', fontSize: 14, color: 'var(--muted)', lineHeight: 1.65 }}>
        <b style={{ color: 'var(--text-strong)', fontWeight: 640 }}>{CASE_01.finding}</b> {CASE_01.findingBody}
      </div>
      <TrueSyncLink label={CASE_01.linkLabel} />
    </div>
  )
}

function Case02Card() {
  const bars = Array.from({ length: CASE_02.surfacedTotal }, (_, i) => i < CASE_02.surfacedFilled)
  return (
    <div style={{ position: 'relative', background: 'var(--surface)', borderRadius: 18, boxShadow: 'var(--shadow-card)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '15px 24px 14px' }}>
        <span className="mono-label" style={{ fontSize: 8, color: '#fff', background: 'var(--ink)', borderRadius: 999, padding: '3.5px 9px', flexShrink: 0 }}>CASE 02</span>
        <Glyph name="search" size={14} color="var(--faint)" />
        <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--muted)' }}>{CASE_02.eyebrow}</span>
      </div>
      <div style={{ padding: '6px 24px 0', display: 'flex', alignItems: 'baseline', gap: 14 }}>
        <span className="num" style={{ fontSize: 66, fontWeight: 750, letterSpacing: '-0.045em', lineHeight: 0.92, color: 'var(--blue)' }}>{CASE_02.statValue}</span>
        <span className="mono-label" style={{ fontSize: 9, color: 'var(--muted)', lineHeight: 1.65, maxWidth: 140 }}>{CASE_02.statCaption}</span>
      </div>
      <div style={{ padding: '20px 24px 0', fontSize: 15, color: 'var(--text-strong)', lineHeight: 1.58, letterSpacing: '-0.008em' }}>{CASE_02.headline}</div>
      <div style={{ margin: '22px 24px 0', border: '1px solid var(--border)', borderRadius: 14, padding: '16px 17px', background: 'var(--surface-warm)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, marginBottom: 11 }}>
          <span className="mono-label" style={{ fontSize: 9, color: 'var(--muted)' }}>{CASE_02.surfacedLabel}</span>
          <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, fontWeight: 700, color: 'var(--blue)' }}>{CASE_02.surfacedValue}</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${CASE_02.surfacedTotal},1fr)`, gap: 3 }}>
          {bars.map((filled, i) => (
            <i key={i} style={{ height: 22, borderRadius: 3, background: filled ? 'var(--blue)' : 'var(--canvas-dim)', boxShadow: filled ? '0 0 10px rgba(1,102,255,.45)' : 'inset 0 0 0 1px var(--hairline)' }} />
          ))}
        </div>
        <div className="mono-label" style={{ fontSize: 8.5, color: 'var(--faint)', marginTop: 11, lineHeight: 1.6 }}>{CASE_02.bandCaption}</div>
      </div>
      <div style={{ padding: '18px 24px 0', fontSize: 14, color: 'var(--muted)', lineHeight: 1.65 }}>
        <b style={{ color: 'var(--text-strong)', fontWeight: 640 }}>{CASE_02.finding}</b> {CASE_02.findingBody}
      </div>
      <TrueSyncLink label={CASE_02.linkLabel} />
    </div>
  )
}

export function FieldEvidence() {
  return (
    <section style={{ position: 'relative', isolation: 'isolate', padding: '70px 24px 12px', overflow: 'hidden' }}>
      <div aria-hidden="true" className="texture-dots-faint" style={{ position: 'absolute', inset: 0, zIndex: 0 }} />
      <div style={{ position: 'relative', zIndex: 1, maxWidth: 1120, margin: '0 auto' }}>
        <SectionHeading
          size="sm"
          accent="We measured it."
          body="Two findings from our own scans. Both are the same failure: value that exists, funded and live, that no agent could read."
        >
          Trade &amp; Retail Media Spend that never reaches the agent.
        </SectionHeading>
        <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 0.9fr', gap: 20, marginTop: 34, alignItems: 'stretch' }}>
          <Case01Card />
          <Case02Card />
        </div>
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 20 }}>
          <ProvenanceLine parts={FIELD_EVIDENCE_PROVENANCE} confidence="observed" />
        </div>
      </div>
    </section>
  )
}
