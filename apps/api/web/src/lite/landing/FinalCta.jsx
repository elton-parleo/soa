/** FINAL CTA — section [7]. Second instance of the same LiteForm compact
 * variant used in the hero — one component, rendered twice. */
import { LiteForm } from '../LiteForm.jsx'

export function FinalCta({ onSubmitted }) {
  return (
    <section className="lite-landing-section" style={{ background: 'var(--ink)', maxWidth: 'none', padding: 0, textAlign: 'center' }}>
      <div style={{ maxWidth: 560, margin: '0 auto', padding: '80px 20px' }}>
        <h2 className="lite-display-headline lite-display-headline--inv" style={{ fontSize: 'clamp(28px, 5vw, 48px)', marginBottom: 32 }}>
          Get your <span className="lite-serif-italic">visibility report</span>.
        </h2>

        <div style={{ textAlign: 'left', marginBottom: 16 }}>
          <LiteForm onSubmitted={onSubmitted} compact inv submitLabel="Get your visibility report" placeholder="yourstore.com" />
        </div>

        <p className="lite-body--inv" style={{ fontSize: 13 }}>
          Your score streams live in a few minutes. The full report, with
          every fix, unlocks with your email.
        </p>
      </div>
    </section>
  )
}
