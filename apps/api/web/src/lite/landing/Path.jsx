/** THE PATH — section [6]. */
import { SectionHeader } from '../liteTheme.jsx'
import { Pill } from '../liteTheme.jsx'
import { PathColumn } from './landingTheme.jsx'

const COLUMNS = [
  { dotColor: 'var(--accent-ink)', kicker: 'FREE', title: 'The Parleo Scan', description: 'The diagnostic on this page.' },
  { dotColor: 'var(--warn-ink)', kicker: 'DIAGNOSTIC', title: 'Share of Algorithm measurement', description: 'Live agent answers across your category, run for you.' },
  { dotColor: 'var(--ink)', kicker: 'PLATFORM', title: 'Command Center', description: 'Your offers, encoded, monitored, and attributed.' },
  { dotColor: 'var(--good-ink)', kicker: 'LIVE', title: 'Deals API + protocols', description: 'MCP and UCP endpoints agents query directly.' },
]

export function Path() {
  const ctaUrl = import.meta.env.VITE_LITE_CTA_URL

  return (
    <section className="lite-landing-section">
      <SectionHeader label="THE PATH" />
      <h2 className="lite-display-headline" style={{ fontSize: 'clamp(28px, 4.5vw, 48px)' }}>
        Start with the score. Keep the <span className="lite-serif-italic">system</span>.
      </h2>

      <div className="lite-cols-4" style={{ marginTop: 40, marginBottom: 32 }}>
        {COLUMNS.map((c) => <PathColumn key={c.kicker} {...c} />)}
      </div>

      <div className="lite-divider" />

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20, flexWrap: 'wrap', marginTop: 24 }}>
        <p className="lite-body lite-muted" style={{ fontSize: 14, maxWidth: 620, margin: 0 }}>
          What a crawl cannot see, live incentive citation, the real price
          gap, and your competitive position, is measured in a Parleo
          diagnostic.
        </p>
        {ctaUrl ? (
          <Pill as="a" href={ctaUrl} target="_blank" rel="noreferrer" solid>
            Request a working session
          </Pill>
        ) : (
          <Pill solid>Request a working session</Pill>
        )}
      </div>
    </section>
  )
}
