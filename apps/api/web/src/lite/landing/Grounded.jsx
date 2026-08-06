/**
 * Grounded — V4 design. Two cards: "every number is measured" +
 * provenance, and the Profound/Bluelight comparison. Ported verbatim.
 */
import { Glyph, ProvenanceLine } from '../../ds/index.js'
import { GROUNDED_PROVENANCE } from './landingSampleContent.js'

export function Grounded() {
  return (
    <section style={{ padding: '34px 24px 30px' }}>
      <div className="lite-landing-grounded-grid" style={{ maxWidth: 1120, margin: '0 auto', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, alignItems: 'stretch' }}>
        <div style={{ background: 'var(--surface)', border: '1px solid var(--hairline)', borderRadius: 16, padding: '24px 26px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
            <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 36, height: 36, flexShrink: 0, borderRadius: 11, background: 'var(--canvas-dim)' }}>
              <Glyph name="check" size={17} color="var(--text-strong)" />
            </span>
            <b style={{ fontSize: 16.5, color: 'var(--text-strong)', letterSpacing: '-0.014em' }}>Every number above is measured</b>
          </div>
          <div style={{ fontSize: 14, color: 'var(--muted)', lineHeight: 1.68, marginTop: 14, textWrap: 'pretty' }}>
            The audit reads the open standards agents actually read (schema.org, UCP, ACP) and scores them deterministically, so you can inspect every point. One run is a sample of agent behavior. The Full Analysis runs the category study.
          </div>
          <div style={{ marginTop: 'auto', paddingTop: 18 }}>
            <ProvenanceLine parts={GROUNDED_PROVENANCE} confidence="observed" />
          </div>
        </div>
        <div style={{ background: 'var(--surface)', border: '1px solid rgba(1,102,255,.28)', borderRadius: 16, padding: '24px 26px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
            <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 36, height: 36, flexShrink: 0, borderRadius: 11, background: 'rgba(1,102,255,.09)' }}>
              <Glyph name="layers" size={17} color="var(--blue)" />
            </span>
            <b style={{ fontSize: 16.5, color: 'var(--text-strong)', letterSpacing: '-0.014em' }}>Already running Profound or Bluelight? Keep them</b>
          </div>
          <div style={{ fontSize: 14, color: 'var(--muted)', lineHeight: 1.68, marginTop: 14, textWrap: 'pretty' }}>
            They track whether agents mention you. This audit measures whether your real price and value survive when they do.
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 18 }}>
            <div style={{ flex: 1, background: 'var(--canvas-dim)', borderRadius: 10, padding: '12px 13px' }}>
              <div className="mono-label" style={{ fontSize: 9, color: 'var(--muted)' }}>THEY MEASURE</div>
              <div style={{ fontSize: 13, color: 'var(--text)', marginTop: 6 }}>Whether you are mentioned</div>
            </div>
            <div style={{ flex: 1, background: 'var(--blue-tint)', borderRadius: 10, padding: '12px 13px' }}>
              <div className="mono-label" style={{ fontSize: 9, color: 'var(--blue)' }}>WE MEASURE</div>
              <div style={{ fontSize: 13, color: 'var(--text-strong)', fontWeight: 540, marginTop: 6 }}>Whether your value survives</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
