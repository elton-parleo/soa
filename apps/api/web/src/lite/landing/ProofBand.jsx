/**
 * Proof band — V4 design, new section between Hero and The Stakes.
 * Ported from the mock's "Proof band" section verbatim.
 */
import { LogoMarquee } from '../../ds/index.js'
import { PROOF_MERCHANTS, PROOF_RAILS } from './landingSampleContent.js'

export function ProofBand() {
  return (
    <section style={{ padding: '22px 0 26px', borderTop: '1px solid var(--hairline)', borderBottom: '1px solid var(--hairline)', background: 'rgba(255,255,255,.4)' }}>
      <div style={{ maxWidth: 1180, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 11 }}>
        <div className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', padding: '0 24px' }}>STORES WE AUDIT</div>
        <LogoMarquee items={PROOF_MERCHANTS} speed={40} />
        <div className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', padding: '0 24px', marginTop: 4 }}>PROTOCOL RAILS WE READ · THE CHECKOUT AND FEED STANDARDS AGENTS USE</div>
        <LogoMarquee items={PROOF_RAILS} speed={52} />
      </div>
    </section>
  )
}
