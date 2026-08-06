/**
 * Final CTA — V4 design. ink-photo panel (no lifestyle photo asset
 * ported — out of scope for this stage's D/L work, which covers tokens,
 * components, and the crawled product image only; the panel still reads
 * correctly as a plain ink surface with the grain/wash overlay).
 * Reuses the same LiteForm compact+inv widget as the hero.
 */
import { LiteForm } from '../LiteForm.jsx'
import { SAMPLE_REPORT_URL } from './landingSampleContent.js'

export function FinalCta({ onSubmitted }) {
  return (
    <section style={{ padding: '8px 24px 40px' }}>
      <div className="ink-photo" style={{ maxWidth: 1120, margin: '0 auto', borderRadius: 20, padding: '74px 40px 78px', textAlign: 'center' }}>
        <h2 className="section-heading sm on-dark" style={{ margin: 0 }}>Find out what agents are missing.</h2>
        <div style={{ maxWidth: 480, margin: '26px auto 0', textAlign: 'left' }}>
          <LiteForm onSubmitted={onSubmitted} compact inv submitLabel="Run my free audit" placeholder="yourstore.com" />
        </div>
        <div style={{ fontSize: 13, color: 'var(--dark-muted)', marginTop: 16 }}>
          Free, no email to start, ready in 10–20 minutes, <a href={SAMPLE_REPORT_URL} style={{ color: 'var(--blue-lite)', fontWeight: 530 }}>see a sample first</a>
        </div>
      </div>
    </section>
  )
}
