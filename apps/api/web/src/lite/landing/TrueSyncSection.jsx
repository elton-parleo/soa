/**
 * TrueSync — V4 design. MonoTag + SectionHeading inside a Container,
 * three fix cards (encode/declare/stay-in-sync), CTA row. Ported
 * verbatim except the CTA itself: leadgen session replaced the
 * WALKTHROUGH_URL link-out to parleo.io with RequestFormModal
 * (source: landing_truesync — same TrueSync copy as the report's
 * TrueSync CTAs, distinguishable by where the lead came from).
 */
import { Glyph, MonoTag, SectionHeading, Container, Button, RequestFormModal } from '../../ds/index.js'
import { useDemoRequestModal } from '../useDemoRequestModal.js'

function FixCard({ tag, glyph, title, body }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--hairline)', borderRadius: 14, padding: '20px 20px 18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 36, height: 36, flexShrink: 0, borderRadius: 11, background: 'rgba(1,102,255,.09)' }}>
          <Glyph name={glyph} size={17} color="var(--blue)" />
        </span>
        <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--blue)' }}>{tag}</span>
      </div>
      <b style={{ display: 'block', fontSize: 16, color: 'var(--text-strong)', marginTop: 14, letterSpacing: '-0.014em' }}>{title}</b>
      <span style={{ display: 'block', fontSize: 13.5, color: 'var(--muted)', lineHeight: 1.6, marginTop: 5 }}>{body}</span>
    </div>
  )
}

export function TrueSyncSection() {
  const demoModal = useDemoRequestModal()
  return (
    <section id="truesync" style={{ padding: '56px 24px 16px', scrollMarginTop: 90 }}>
      <Container pad={0}>
        <div style={{ padding: '34px 40px 36px' }}>
          <MonoTag tone="blue">TRUESYNC</MonoTag>
          <div style={{ marginTop: 16 }}>
            <SectionHeading size="sm" accent="TrueSync closes them.">The audit finds the gaps.</SectionHeading>
          </div>
          <p className="section-copy" style={{ margin: '14px 0 0', maxWidth: 640, fontSize: 15 }}>
            The audit measures four gap areas. Parleo fixes two of them directly: <b style={{ color: 'var(--text-strong)', fontWeight: 620 }}>incentive sync</b> (your member value and deals, encoded and current) and <b style={{ color: 'var(--text-strong)', fontWeight: 620 }}>protocol declarations</b> (your value wired into UCP and ACP agent checkout).
          </p>
          <div className="lite-truesync-landing-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 14, marginTop: 26 }}>
            <FixCard tag="01 ENCODE" glyph="doc" title="Member value and deals" body="In markup agents can read." />
            <FixCard tag="02 DECLARE" glyph="card" title="Value at agent checkout" body="UCP and ACP declarations." />
            <FixCard tag="03 STAY IN SYNC" glyph="refresh" title="No drift back to zero" body="Updated as offers change." />
          </div>
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', marginTop: 26 }}>
            <Button variant="blue" arrow onClick={() => demoModal.open('landing_truesync')}>Talk to us about TrueSync</Button>
            <span style={{ fontSize: 13, color: 'var(--muted)' }}>or start with the free audit above. Same road.</span>
          </div>
        </div>
      </Container>
      {demoModal.cta && (
        <RequestFormModal
          open={demoModal.isOpen}
          onClose={demoModal.close}
          eyebrow={demoModal.cta.eyebrow}
          title={demoModal.cta.title}
          messagePlaceholder={demoModal.cta.messagePlaceholder}
          onSubmit={demoModal.onSubmit}
        />
      )}
    </section>
  )
}
